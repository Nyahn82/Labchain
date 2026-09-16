"""Result history and completion, serialized with the Phase 4A order lock."""

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (
    LabOrder, LabOrderItem, LabResultItem, OrderPanel, Patient, ReferenceRange,
    Specimen, SpecimenOrderItem, TestCatalog, UserAccount,
)
from app.schemas import results as s
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import related, resolve_reference_range, retry_deadlocks
from app.services.result_calculations import age_at_date, calculate_result_flag, parse_numeric_value
from app.services.workflow_service import current, fields, start_processing


def result_views(db, records, *, lock=False):
    """Batch allowlisted summaries; never fetch credential columns for actors."""
    if not records:
        return []
    item_ids = {record.order_item_id for record in records}
    items = {item.order_item_id: (item, test) for item, test in db.execute(current(
        select(LabOrderItem, TestCatalog).join(TestCatalog, TestCatalog.test_id == LabOrderItem.test_id)
        .where(LabOrderItem.order_item_id.in_(item_ids)), lock))}
    specimen_ids = {record.specimen_id for record in records if record.specimen_id is not None}
    specimens = {row.specimen_id: s.ResultSpecimenSummary.model_validate(row) for row in db.scalars(current(
        select(Specimen).where(Specimen.specimen_id.in_(specimen_ids)), lock))} if specimen_ids else {}
    range_ids = {record.reference_range_id for record in records if record.reference_range_id is not None}
    ranges = {row.range_id: s.ResultRangeSummary.model_validate(row) for row in db.scalars(current(
        select(ReferenceRange).where(ReferenceRange.range_id.in_(range_ids)), lock))} if range_ids else {}
    actor_ids = {getattr(record, field) for record in records for field in (
        'encoded_by_user_id', 'reviewed_by_user_id', 'verified_by_user_id') if getattr(record, field) is not None}
    actors = {row.user_id: s.ActorSummary(user_id=row.user_id, username=row.username) for row in db.execute(current(
        select(UserAccount.user_id, UserAccount.username).where(UserAccount.user_id.in_(actor_ids)), lock))}
    return [s.ResultResponse(
        **fields(record), order_id=items[record.order_item_id][0].order_id,
        test=s.ResultTestSummary.model_validate(items[record.order_item_id][1]),
        specimen=specimens.get(record.specimen_id), reference_range=ranges.get(record.reference_range_id),
        encoded_by=actors[record.encoded_by_user_id], reviewed_by=actors.get(record.reviewed_by_user_id),
        verified_by=actors.get(record.verified_by_user_id),
    ) for record in records]


def result_detail(db, result_item_id, *, lock=False):
    return result_views(db, [get_record(db, LabResultItem, result_item_id, lock=lock)], lock=lock)[0]


def list_results(db, order_id, *, page, page_size):
    get_record(db, LabOrder, order_id)
    statement = (select(LabResultItem).join(LabOrderItem, LabOrderItem.order_item_id == LabResultItem.order_item_id)
                 .where(LabOrderItem.order_id == order_id))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    records = list(db.scalars(statement.order_by(LabResultItem.order_item_id, LabResultItem.result_item_id)
                              .offset((page - 1) * page_size).limit(page_size)))
    return dict(items=result_views(db, records), page=page, page_size=page_size, total=total)


def lock_item_order(db, order_item_id):
    # Only discover the immutable parent from the snapshot. All decisions below
    # use current reads after the same order lock as cancellation/registration.
    parent_id = get_record(db, LabOrderItem, order_item_id).order_id
    order = get_record(db, LabOrder, parent_id, lock=True)
    item = get_record(db, LabOrderItem, order_item_id, lock=True)
    if order.status == 'CANCELLED' or item.status == 'CANCELLED':
        raise HTTPException(409, 'Cancelled orders or items cannot accept result mutations.')
    return order, item


def current_results(db, item_id):
    # The order/item locks serialize even the empty set, without adding UNIQUE.
    return list(db.scalars(select(LabResultItem).where(LabResultItem.order_item_id == item_id)
                          .order_by(LabResultItem.result_item_id).limit(2).with_for_update()
                          .execution_options(populate_existing=True)))


def lock_result_context(db, result_item_id):
    item_id = get_record(db, LabResultItem, result_item_id).order_item_id
    order, item = lock_item_order(db, item_id)
    records = current_results(db, item_id)
    if len(records) != 1 or records[0].result_item_id != result_item_id:
        raise HTTPException(409, 'Phase 4B requires one current result per order item.')
    return order, item, records[0], related(db, TestCatalog, item.test_id)


def validate_specimen(db, order, item, specimen_id):
    if specimen_id is None:
        return None
    specimen = db.scalar(select(Specimen).where(Specimen.specimen_id == specimen_id)
                         .with_for_update().execution_options(populate_existing=True))
    if specimen is None:
        raise HTTPException(422, 'Specimen does not exist.')
    if specimen.order_id != order.order_id:
        raise HTTPException(422, 'Specimen must belong to the same laboratory order.')
    mapping = db.scalar(current(select(SpecimenOrderItem.specimen_order_item_id).where(
        SpecimenOrderItem.specimen_id == specimen_id, SpecimenOrderItem.order_item_id == item.order_item_id), True))
    if mapping is None:
        raise HTTPException(422, 'Specimen must be mapped to this order item.')
    if specimen.specimen_status not in {'RECEIVED', 'PROCESSED'}:
        raise HTTPException(409, 'Result specimens must be RECEIVED or PROCESSED.')
    return specimen


def derive_result(db, order, test, result_value):
    numeric_value = parse_numeric_value(test.result_type, result_value)
    patient = related(db, Patient, order.patient_id)
    order_day = order.order_date.date()
    selected = resolve_reference_range(db, test.test_id, patient.sex,
                                       age_at_date(patient.birth_date, order_day), order_day, lock=True)
    return dict(numeric_value=numeric_value, reference_range_id=selected.range_id if selected else None,
                flag=calculate_result_flag(test.result_type, result_value, numeric_value, selected))


def validate_stored_result(db, item, result, test):
    """Check structural integrity without rewriting previously derived flags.

    A range ID is a pointer to mutable master data, not a frozen range snapshot.
    Review/verification preserve encoded derivations; only a changed draft value
    selects ranges/flags again. Reports/snapshots are outside this phase.
    """
    if result.status == 'REVIEWED' and (result.reviewed_by_user_id is None or result.reviewed_at is None):
        raise HTTPException(409, 'Reviewed result has incomplete review provenance.')
    if result.status == 'DRAFT' and (result.reviewed_by_user_id is not None or result.reviewed_at is not None):
        raise HTTPException(409, 'Draft result has inconsistent review provenance.')
    if result.verified_by_user_id is not None or result.verified_at is not None:
        raise HTTPException(409, 'Unverified result has inconsistent verification provenance.')
    try:
        numeric_value = parse_numeric_value(test.result_type, result.result_value)
    except HTTPException:
        raise HTTPException(409, 'Stored result is inconsistent with the test configuration.') from None
    if numeric_value != result.numeric_value:
        raise HTTPException(409, 'Stored numeric value is inconsistent with the display value or test type.')
    if result.reference_range_id is not None:
        reference = related(db, ReferenceRange, result.reference_range_id)
        if reference.test_id != item.test_id:
            raise HTTPException(409, 'Stored reference range belongs to another test.')
    elif result.flag is not None:
        raise HTTPException(409, 'A flagged result must have a reference range.')


def process_specimen(specimen):
    if specimen is not None and specimen.specimen_status == 'RECEIVED':
        specimen.specimen_status = 'PROCESSED'


@retry_deadlocks
def create_result(db, order_item_id, payload, actor_id, ip_address):
    with mutation(db):
        order, item = lock_item_order(db, order_item_id)
        if current_results(db, order_item_id):
            raise HTTPException(409, 'A result already exists for this order item.')
        test = related(db, TestCatalog, item.test_id)
        specimen = validate_specimen(db, order, item, payload.specimen_id)
        derived = derive_result(db, order, test, payload.result_value)
        result = LabResultItem(order_item_id=order_item_id, **payload.model_dump(), **derived,
                               status='DRAFT', encoded_by_user_id=actor_id, encoded_at=utc_now())
        db.add(result)
        process_specimen(specimen)
        start_processing(db, order, [item])
        db.flush()
        audit(db, actor_id, 'LAB_RESULT_CREATE', 'lab_result_item', result.result_item_id, ip_address,
              new={'order_item_id': order_item_id, 'status': 'DRAFT', 'flag': result.flag})
        response = result_detail(db, result.result_item_id, lock=True)
    return response


@retry_deadlocks
def update_result(db, result_item_id, payload, actor_id, ip_address):
    with mutation(db):
        order, item, result, test = lock_result_context(db, result_item_id)
        if result.status != 'DRAFT':
            raise HTTPException(409, 'Only DRAFT results may be edited.')
        values = payload.model_dump(exclude_unset=True)
        changed = sorted(field for field, value in values.items() if getattr(result, field) != value)
        specimen = validate_specimen(db, order, item, values.get('specimen_id', result.specimen_id))
        old_flag = result.flag
        if 'result_value' in changed:
            derived = derive_result(db, order, test, values['result_value'])
            for field, value in derived.items():
                setattr(result, field, value)
        else:
            validate_stored_result(db, item, result, test)
        for field in changed:
            setattr(result, field, values[field])
        process_specimen(specimen)
        db.flush()
        audit(db, actor_id, 'LAB_RESULT_UPDATE', 'lab_result_item', result_item_id, ip_address,
              old={'flag': old_flag}, new={'order_item_id': item.order_item_id, 'status': 'DRAFT',
                                          'flag': result.flag, 'changed_fields': changed})
        response = result_detail(db, result_item_id, lock=True)
    return response


def progress_status(items):
    active = [item for item in items if item.status != 'CANCELLED']
    if active and all(item.status == 'COMPLETED' for item in active):
        return 'COMPLETED'
    if any(item.status in {'IN_PROGRESS', 'COMPLETED'} for item in active):
        return 'IN_PROGRESS'
    return 'REQUESTED'


def recalculate_panel(db, order_panel_id):
    panel = get_record(db, OrderPanel, order_panel_id, lock=True)
    if panel.status == 'CANCELLED':
        return
    items = list(db.scalars(select(LabOrderItem).where(LabOrderItem.order_panel_id == order_panel_id)
                           .with_for_update().execution_options(populate_existing=True)))
    panel.status = progress_status(items)


def recalculate_order(db, order):
    if order.status == 'CANCELLED':
        return
    items = list(db.scalars(select(LabOrderItem).where(LabOrderItem.order_id == order.order_id)
                           .with_for_update().execution_options(populate_existing=True)))
    status = progress_status(items)
    if status == 'REQUESTED' and order.status in {'IN_PROGRESS', 'COMPLETED'}:
        status = 'IN_PROGRESS'  # Processing history does not disappear if all items are cancelled.
    if order.status != status:
        order.status, order.updated_at = status, utc_now()


@retry_deadlocks
def transition_result(db, result_item_id, action, actor_id, ip_address):
    with mutation(db):
        order, item, result, test = lock_result_context(db, result_item_id)
        expected, target = {'REVIEW': ('DRAFT', 'REVIEWED'), 'VERIFY': ('REVIEWED', 'VERIFIED')}[action]
        if result.status != expected:
            raise HTTPException(409, f'Result must be {expected} for this transition.')
        validate_specimen(db, order, item, result.specimen_id)
        validate_stored_result(db, item, result, test)
        result.status = target
        if action == 'REVIEW':
            result.reviewed_by_user_id, result.reviewed_at = actor_id, utc_now()
        else:
            result.verified_by_user_id, result.verified_at = actor_id, utc_now()
            item.status = 'COMPLETED'
        # Flush before current-read completion queries can refresh these objects.
        db.flush()
        if action == 'VERIFY':
            if item.order_panel_id is not None:
                recalculate_panel(db, item.order_panel_id)
            recalculate_order(db, order)
            db.flush()
        audit(db, actor_id, 'LAB_RESULT_' + action, 'lab_result_item', result_item_id, ip_address,
              old={'status': expected}, new={'order_item_id': item.order_item_id, 'status': target})
        response = result_detail(db, result_item_id, lock=True)
    return response
