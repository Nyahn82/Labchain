"""Atomic laboratory workflow; all specimen mutations lock the order first."""

from datetime import datetime, time
from functools import wraps
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    LabOrder, LabOrderItem, LabPayment, OrderPanel, PanelTest, Patient,
    RejectionReason, RequestingPhysician, SampleType, Specimen, SpecimenOrderItem,
    SpecimenRejection, TestCatalog, TestPanel, TestSampleType,
)
from app.schemas import workflow as s
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import related, retry_deadlocks


class CodeCollision(Exception):
    """Only a confirmed generated-code unique violation is retryable."""


def generated_code(prefix):
    # 72 random bits, uppercase to preserve entropy under MySQL's CI collation.
    # LAB + separator + 6-digit UTC date + separator + 18 hex digits = 29.
    return f'{prefix}-{utc_now():%y%m%d}-{secrets.token_hex(9).upper()}'


def insert_coded(db, model, field, prefix, **values):
    record = model(**values, **{field: generated_code(prefix)})
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        args = getattr(exc.orig, 'args', ())
        message = str(args[1]) if len(args) > 1 else str(exc.orig)
        key = re.search(r"for key ['`]([^'`]+)['`]", message)
        mysql_collision = (db.get_bind().dialect.name == 'mysql' and args and args[0] == 1062
                           and key and key[1].split('.')[-1] == f'uq_{model.__tablename__}_{field}')
        sqlite_collision = (db.get_bind().dialect.name == 'sqlite'
                            and message == f'UNIQUE constraint failed: {model.__tablename__}.{field}')
        if mysql_collision or sqlite_collision:
            raise CodeCollision from None
        raise
    return record


def retry_codes(operation):
    @wraps(operation)
    def wrapped(db, *args, **kwargs):
        for attempt in range(3):
            try:
                return operation(db, *args, **kwargs)
            except CodeCollision:
                # The entire mutation, including all children/audits, rolled back.
                if attempt == 2:
                    raise HTTPException(409, 'Unable to allocate a unique workflow code; retry the request.') from None
    return wrapped


def current(statement, lock):
    return (statement.with_for_update(read=True).execution_options(populate_existing=True)
            if lock else statement)


def fields(record):
    return {column.key: getattr(record, column.key) for column in inspect(type(record)).columns}


def active_related(db, model, identifier, label):
    row = related(db, model, identifier)
    if not row.is_active:
        raise HTTPException(409, f'{label} is inactive.')
    return row


def order_items(db, order_id, *, lock=False):
    statement = (select(LabOrderItem, TestCatalog).join(TestCatalog, TestCatalog.test_id == LabOrderItem.test_id)
                 .where(LabOrderItem.order_id == order_id).order_by(LabOrderItem.order_item_id))
    return [s.OrderItemResponse(**fields(item), test=s.TestSummary.model_validate(test))
            for item, test in db.execute(current(statement, lock))]


def specimen_views(db, specimens, *, lock=False):
    """Batch nested reads: query count does not grow with the specimen count."""
    if not specimens:
        return []
    ids = [row.specimen_id for row in specimens]
    samples = {row.sample_type_id: s.SampleSummary.model_validate(row) for row in db.scalars(current(
        select(SampleType).where(SampleType.sample_type_id.in_({row.sample_type_id for row in specimens})), lock))}
    mappings = {identifier: [] for identifier in ids}
    statement = (select(SpecimenOrderItem, LabOrderItem, TestCatalog)
                 .join(LabOrderItem, LabOrderItem.order_item_id == SpecimenOrderItem.order_item_id)
                 .join(TestCatalog, TestCatalog.test_id == LabOrderItem.test_id)
                 .where(SpecimenOrderItem.specimen_id.in_(ids)).order_by(SpecimenOrderItem.specimen_order_item_id))
    for link, item, test in db.execute(current(statement, lock)):
        mappings[link.specimen_id].append(s.MappingResponse(**fields(link), order_item=s.OrderItemResponse(
            **fields(item), test=s.TestSummary.model_validate(test))))
    rejections = {identifier: [] for identifier in ids}
    statement = (select(SpecimenRejection, RejectionReason)
                 .join(RejectionReason, RejectionReason.rejection_reason_id == SpecimenRejection.rejection_reason_id)
                 .where(SpecimenRejection.specimen_id.in_(ids))
                 .order_by(SpecimenRejection.rejected_at, SpecimenRejection.specimen_rejection_id))
    for rejection, reason in db.execute(current(statement, lock)):
        rejections[rejection.specimen_id].append(s.RejectionResponse(
            **fields(rejection), reason=s.ReasonResponse.model_validate(reason)))
    return [s.SpecimenResponse(**fields(row), sample_type=samples[row.sample_type_id],
                              mappings=mappings[row.specimen_id], rejections=rejections[row.specimen_id])
            for row in specimens]


def specimen_detail(db, specimen_id, *, lock=False):
    specimen = get_record(db, Specimen, specimen_id, lock=lock)
    return specimen_views(db, [specimen], lock=lock)[0]


def order_detail(db, order_id, *, lock=False):
    order = get_record(db, LabOrder, order_id, lock=lock)
    patient = db.scalar(current(select(Patient).where(Patient.patient_id == order.patient_id), lock))
    physician = (db.scalar(current(select(RequestingPhysician).where(
        RequestingPhysician.physician_id == order.physician_id), lock)) if order.physician_id else None)
    panels = [s.OrderPanelResponse(**fields(op), panel=s.PanelSummary.model_validate(panel))
              for op, panel in db.execute(current(select(OrderPanel, TestPanel)
                  .join(TestPanel, TestPanel.panel_id == OrderPanel.panel_id)
                  .where(OrderPanel.order_id == order_id).order_by(OrderPanel.order_panel_id), lock))]
    payments = [s.PaymentResponse.model_validate(row) for row in db.scalars(current(
        select(LabPayment).where(LabPayment.order_id == order_id)
        .order_by(LabPayment.recorded_at, LabPayment.payment_id), lock))]
    specimens = list(db.scalars(current(select(Specimen).where(Specimen.order_id == order_id)
                                       .order_by(Specimen.created_at, Specimen.specimen_id), lock)))
    return s.OrderDetail(**fields(order), patient=s.PatientSummary.model_validate(patient),
                         physician=s.PhysicianSummary.model_validate(physician) if physician else None,
                         panels=panels, items=order_items(db, order_id, lock=lock), payments=payments,
                         specimens=specimen_views(db, specimens, lock=lock))


def list_orders(db, *, page, page_size, search=None, date_from=None, date_to=None, **filters):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'date_from must not be later than date_to.')
    conditions = [getattr(LabOrder, field) == value for field, value in filters.items() if value is not None]
    if search and search.strip():
        conditions.append(or_(*(column.icontains(search.strip(), autoescape=True) for column in (
            LabOrder.order_code, Patient.patient_code, Patient.first_name, Patient.last_name))))
    if date_from:
        conditions.append(LabOrder.order_date >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(LabOrder.order_date <= datetime.combine(date_to, time.max))
    base = select(LabOrder, Patient, RequestingPhysician).join(Patient, Patient.patient_id == LabOrder.patient_id).outerjoin(
        RequestingPhysician, RequestingPhysician.physician_id == LabOrder.physician_id).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(base.order_by(LabOrder.order_date.desc(), LabOrder.order_id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return dict(items=[s.OrderListItem(**{key: getattr(order, key) for key in (
        'order_id', 'order_code', 'order_date', 'priority', 'status')}, patient=s.PatientSummary.model_validate(patient),
        physician=s.PhysicianSummary.model_validate(physician) if physician else None)
        for order, patient, physician in rows], page=page, page_size=page_size, total=total)


@retry_deadlocks
@retry_codes
def create_order(db, payload, actor_id, ip_address):
    with mutation(db):
        related(db, Patient, payload.patient_id)
        if payload.physician_id is not None:
            active_related(db, RequestingPhysician, payload.physician_id, 'Physician')
        # Match master-data lock order: panel parents before composition/tests.
        for panel_id in sorted(payload.panel_ids):
            active_related(db, TestPanel, panel_id, 'Panel')
        composition = {}
        for panel_id in sorted(payload.panel_ids):
            members = list(db.scalars(current(select(PanelTest).where(PanelTest.panel_id == panel_id)
                           .order_by(PanelTest.sort_order, PanelTest.panel_test_id), True)))
            if not members:
                raise HTTPException(409, f'Panel {panel_id} configuration is invalid: no tests.')
            composition[panel_id] = [member.test_id for member in members]
        panel_tests = {test_id for ids in composition.values() for test_id in ids}
        for test_id in sorted(panel_tests | set(payload.test_ids)):
            test = related(db, TestCatalog, test_id)
            if not test.is_active:
                if test_id in panel_tests:
                    raise HTTPException(409, 'Panel configuration is invalid: contains an inactive test.')
                raise HTTPException(409, 'Requested test is inactive.')
        now = utc_now()
        order = insert_coded(db, LabOrder, 'order_code', 'LAB',
                             **payload.model_dump(exclude={'panel_ids', 'test_ids'}),
                             ordered_by_user_id=actor_id, order_date=now, created_at=now, status='REQUESTED')
        for panel_id in payload.panel_ids:
            panel = OrderPanel(order_id=order.order_id, panel_id=panel_id, status='REQUESTED')
            db.add(panel)
            db.flush()
            db.add_all(LabOrderItem(order_id=order.order_id, test_id=test_id, order_panel_id=panel.order_panel_id,
                                    status='REQUESTED', created_at=now) for test_id in composition[panel_id])
        db.add_all(LabOrderItem(order_id=order.order_id, test_id=test_id, status='REQUESTED', created_at=now)
                   for test_id in payload.test_ids)
        db.flush()
        audit(db, actor_id, 'LAB_ORDER_CREATE', 'lab_order', order.order_id, ip_address,
              new={'status': 'REQUESTED', 'panel_ids': payload.panel_ids, 'test_ids': payload.test_ids})
        result = order_detail(db, order.order_id, lock=True)
    return result


@retry_deadlocks
def cancel_order(db, order_id, payload, actor_id, ip_address):
    with mutation(db):
        order = get_record(db, LabOrder, order_id, lock=True)
        if order.status in {'COMPLETED', 'CANCELLED'}:
            raise HTTPException(409, 'Completed or cancelled orders cannot be cancelled.')
        previous = order.status
        order.status, order.updated_at = 'CANCELLED', utc_now()
        for model in (OrderPanel, LabOrderItem):
            for row in db.scalars(select(model).where(model.order_id == order_id)
                                  .order_by(*inspect(model).primary_key).with_for_update()
                                  .execution_options(populate_existing=True)):
                if row.status != 'COMPLETED':
                    row.status = 'CANCELLED'
        db.flush()
        # JSON encoding preserves a bounded reason as data, never as a log format.
        audit(db, actor_id, 'LAB_ORDER_CANCEL', 'lab_order', order_id, ip_address,
              old={'status': previous}, new={'status': 'CANCELLED', 'reason': payload.reason})
        result = s.OrderResponse.model_validate(order)
    return result


@retry_deadlocks
def record_payment(db, order_id, payload, actor_id, ip_address):
    with mutation(db):
        get_record(db, LabOrder, order_id, lock=True)
        payment = LabPayment(order_id=order_id, **payload.model_dump(), recorded_by_user_id=actor_id, recorded_at=utc_now())
        db.add(payment)
        db.flush()
        audit(db, actor_id, 'PAYMENT_RECORD', 'lab_payment', payment.payment_id, ip_address,
              new={'order_id': order_id, 'payment_status': payment.payment_status})
        result = s.PaymentResponse.model_validate(payment)
    return result


def start_processing(db, order, items):
    """Registration starts only REQUESTED entities; completion belongs to 4B."""
    if order.status == 'REQUESTED':
        order.status, order.updated_at = 'IN_PROGRESS', utc_now()
    panel_ids = set()
    for item in items:
        if item.status == 'REQUESTED':
            item.status = 'IN_PROGRESS'
            if item.order_panel_id is not None:
                panel_ids.add(item.order_panel_id)
    for panel_id in sorted(panel_ids):
        panel = get_record(db, OrderPanel, panel_id, lock=True)
        if panel.status == 'REQUESTED':
            panel.status = 'IN_PROGRESS'


def ensure_processing_allowed(order):
    if order.status in {'CANCELLED', 'COMPLETED'}:
        raise HTTPException(409, 'Cancelled or completed orders cannot enter specimen processing.')


@retry_deadlocks
@retry_codes
def register_specimen(db, order_id, payload, actor_id, ip_address):
    with mutation(db):
        order = get_record(db, LabOrder, order_id, lock=True)
        ensure_processing_allowed(order)
        active_related(db, SampleType, payload.sample_type_id, 'Sample type')
        items = []
        for identifier in sorted(payload.order_item_ids):
            item = related(db, LabOrderItem, identifier)
            if item.order_id != order_id:
                raise HTTPException(422, 'Every item must belong to this order.')
            if item.status in {'CANCELLED', 'COMPLETED'}:
                raise HTTPException(409, 'Cancelled or completed items cannot enter specimen processing.')
            items.append(item)
        # Shared test locks serialize compatibility checks with configuration PUT.
        for test_id in sorted({item.test_id for item in items}):
            related(db, TestCatalog, test_id)
            compatible = db.scalar(current(select(TestSampleType.test_sample_type_id).where(
                TestSampleType.test_id == test_id, TestSampleType.sample_type_id == payload.sample_type_id), True))
            if compatible is None:
                raise HTTPException(409, 'Selected sample type is not allowed for every requested test.')
        specimen = insert_coded(db, Specimen, 'specimen_code', 'SP', order_id=order_id,
                                sample_type_id=payload.sample_type_id, remarks=payload.remarks,
                                specimen_status='PENDING', created_at=utc_now())
        db.add_all(SpecimenOrderItem(specimen_id=specimen.specimen_id, order_item_id=item.order_item_id) for item in items)
        start_processing(db, order, items)
        db.flush()
        audit(db, actor_id, 'SPECIMEN_REGISTER', 'specimen', specimen.specimen_id, ip_address,
              new={'order_id': order_id, 'order_item_ids': payload.order_item_ids, 'specimen_status': 'PENDING'})
        result = specimen_detail(db, specimen.specimen_id, lock=True)
    return result


def lock_specimen_order(db, specimen_id):
    # Parent ID is immutable. This initial snapshot read only discovers that ID;
    # lifecycle decisions use fresh locking reads after acquiring the order lock.
    parent_id = get_record(db, Specimen, specimen_id).order_id
    order = get_record(db, LabOrder, parent_id, lock=True)
    specimen = get_record(db, Specimen, specimen_id, lock=True)
    return order, specimen


@retry_deadlocks
def transition_specimen(db, specimen_id, action, actor_id, ip_address, payload=None):
    with mutation(db):
        order, specimen = lock_specimen_order(db, specimen_id)
        previous = specimen.specimen_status
        allowed = {'COLLECT': {'PENDING'}, 'RECEIVE': {'COLLECTED'}, 'REJECT': {'COLLECTED', 'RECEIVED'}}
        if previous not in allowed[action]:
            raise HTTPException(409, 'Invalid specimen status transition.')
        now = utc_now()
        if action == 'REJECT':
            active_related(db, RejectionReason, payload.rejection_reason_id, 'Rejection reason')
            db.add(SpecimenRejection(specimen_id=specimen_id, **payload.model_dump(),
                                     rejected_by_user_id=actor_id, rejected_at=now))
            specimen.specimen_status = 'REJECTED'
        else:
            ensure_processing_allowed(order)
            if action == 'COLLECT':
                specimen.collected_by_user_id, specimen.collected_at = actor_id, now
                specimen.specimen_status = 'COLLECTED'
            else:
                specimen.received_by_user_id, specimen.received_at = actor_id, now
                specimen.specimen_status = 'RECEIVED'
        db.flush()
        new = {'order_id': order.order_id, 'specimen_status': specimen.specimen_status}
        if payload is not None:
            new.update(rejection_reason_id=payload.rejection_reason_id, recollection_required=payload.recollection_required)
        audit(db, actor_id, 'SPECIMEN_' + action, 'specimen', specimen_id, ip_address,
              old={'specimen_status': previous}, new=new)
        result = specimen_detail(db, specimen_id, lock=True)
    return result
