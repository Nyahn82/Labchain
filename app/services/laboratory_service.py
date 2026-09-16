"""Laboratory configuration transactions. No patient results or clinical inference."""

import logging
from datetime import date
from decimal import Decimal
from functools import wraps

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, inspect, or_, select
from sqlalchemy.exc import OperationalError

from app.models import (
    LabDepartment, PanelSection, PanelTest, ReferenceRange, SampleType,
    TestCatalog, TestPanel, TestSampleType,
)
from app.schemas import laboratory as s
from app.services.identity_service import audit, get_record, mutation

logger = logging.getLogger(__name__)


def retry_deadlocks(operation):
    """Replay the whole rolled-back mutation on MySQL's deadlock victim error.

    InnoDB next-key locks can deadlock even for distinct parents when an empty
    association index gap is shared. Authentication is checked once per request,
    as in the existing APIs; each retry remains inside that authorized request.
    """
    @wraps(operation)
    def wrapped(db, *args, **kwargs):
        for attempt in range(3):
            try:
                return operation(db, *args, **kwargs)
            except OperationalError as exc:
                # mutation() already rolled back the complete attempt, including
                # audit writes. Never retry arbitrary errors or uncertain commits.
                error_args = getattr(exc.orig, 'args', ())
                code = error_args[0] if error_args else None
                if db.get_bind().dialect.name != 'mysql' or code != 1213 or attempt == 2:
                    raise
                logger.warning('Retrying laboratory mutation after database deadlock (attempt %s).', attempt + 1)
    return wrapped


def related(db, model, record_id):
    """Current read: authentication may already have opened an older MySQL snapshot."""
    row = db.scalar(select(model).where(inspect(model).primary_key[0] == record_id)
                    .with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(422, 'Related record does not exist.')
    return row


def validate_department(db, model, values, changed=None):
    if model not in {TestCatalog, TestPanel} or values.get('department_id') is None:
        return
    # Existing tests can still be edited/deactivated after their department retires.
    if changed is not None and not {'department_id', 'is_active'} & changed:
        return
    department = related(db, LabDepartment, values['department_id'])
    if model is TestCatalog and values['is_active'] and not department.is_active:
        raise HTTPException(409, 'An active test requires an active department when created, moved or activated.')


@retry_deadlocks
def save_record(db, model, payload, response_schema, actor_id, ip_address, action,
                *, record_id=None, parent_id=None):
    with mutation(db):
        # Parent keys cannot be changed by this API. Lock parent before child so
        # ranges and panel sections use the same order as replacement operations.
        if model is ReferenceRange and record_id is not None:
            parent_id = get_record(db, model, record_id).test_id
        if model is PanelSection:
            get_record(db, TestPanel, parent_id, lock=True)
        elif parent_id is not None:
            get_record(db, TestCatalog, parent_id, lock=True)
        record = get_record(db, model, record_id, lock=True) if record_id is not None else None
        if model is PanelSection and record is not None and record.panel_id != parent_id:
            raise HTTPException(404, 'Section not found in this panel.')
        values = payload.model_dump(exclude_unset=record is not None)
        changed = {key for key, value in values.items() if record is None or getattr(record, key) != value}
        merged = ({column.key: getattr(record, column.key) for column in inspect(model).columns}
                  if record is not None else {}) | values
        validate_department(db, model, merged, changed if record is not None else None)
        if model is ReferenceRange:
            try:
                validated = s.RangeCreate.model_validate({key: merged[key] for key in s.RangeCreate.model_fields})
            except ValidationError:
                raise HTTPException(422, 'Invalid reference range bounds.') from None
            ensure_no_overlap(db, parent_id, validated, exclude_id=record_id)
        if record is None:
            if parent_id is not None:
                values['panel_id' if model is PanelSection else 'test_id'] = parent_id
            record = model(**values)
            db.add(record)
        else:
            for key in changed:
                setattr(record, key, values[key])
        db.flush()
        audit(db, actor_id, action, model.__tablename__, inspect(record).identity[0], ip_address,
              new={'changed_fields': sorted(changed)})
        result = response_schema.model_validate(record)
    return result


def sample_assignments(db, test_id, *, lock=False):
    statement = (select(TestSampleType, SampleType)
                 .join(SampleType, SampleType.sample_type_id == TestSampleType.sample_type_id)
                 .where(TestSampleType.test_id == test_id)
                 .order_by(TestSampleType.sample_type_id, TestSampleType.test_sample_type_id))
    if lock:
        statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
    return [s.SampleAssignmentResponse(
        test_sample_type_id=link.test_sample_type_id, test_id=link.test_id,
        sample_type_id=link.sample_type_id, is_default=link.is_default,
        sample_type=s.SampleTypeResponse.model_validate(sample),
    ) for link, sample in db.execute(statement)]


def test_detail(db, test_id):
    test = get_record(db, TestCatalog, test_id)
    return s.TestDetail(**s.TestResponse.model_validate(test).model_dump(),
                        department=s.DepartmentResponse.model_validate(get_record(db, LabDepartment, test.department_id)),
                        sample_types=sample_assignments(db, test_id))


def sections(db, panel_id):
    return list(db.scalars(select(PanelSection).where(PanelSection.panel_id == panel_id)
                           .order_by(PanelSection.sort_order, PanelSection.section_id)))


def panel_assignments(db, panel_id, *, lock=False):
    # Unsectioned tests first; then section order/ID; then member order/ID.
    statement = (select(PanelTest, TestCatalog)
                 .join(TestCatalog, TestCatalog.test_id == PanelTest.test_id)
                 .outerjoin(PanelSection, PanelSection.section_id == PanelTest.section_id)
                 .where(PanelTest.panel_id == panel_id)
                 .order_by(PanelTest.section_id.is_not(None), PanelSection.sort_order,
                           PanelSection.section_id, PanelTest.sort_order, PanelTest.panel_test_id))
    if lock:
        statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
    return [s.PanelAssignmentResponse(
        panel_test_id=link.panel_test_id, panel_id=link.panel_id, test_id=link.test_id,
        section_id=link.section_id, sort_order=link.sort_order, is_required=link.is_required,
        test=s.TestResponse.model_validate(test),
    ) for link, test in db.execute(statement)]


def panel_detail(db, panel_id):
    panel = get_record(db, TestPanel, panel_id)
    return s.PanelDetail(**s.PanelResponse.model_validate(panel).model_dump(),
                         sections=sections(db, panel_id), tests=panel_assignments(db, panel_id))


@retry_deadlocks
def replace_sample_types(db, test_id, payload, actor_id, ip_address):
    with mutation(db):
        get_record(db, TestCatalog, test_id, lock=True)
        ids = [item.sample_type_id for item in payload.sample_types]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, 'Duplicate sample type IDs.')
        if sum(item.is_default for item in payload.sample_types) > 1:
            raise HTTPException(422, 'At most one default sample type is allowed.')
        for sample_id in sorted(ids):
            related(db, SampleType, sample_id)
        db.execute(delete(TestSampleType).where(TestSampleType.test_id == test_id))
        db.add_all(TestSampleType(test_id=test_id, **item.model_dump()) for item in payload.sample_types)
        db.flush()
        audit(db, actor_id, 'TEST_SAMPLE_TYPES_UPDATE', 'test_catalog', test_id, ip_address,
              new={'sample_type_ids': sorted(ids),
                   'default_sample_type_id': next((item.sample_type_id for item in payload.sample_types if item.is_default), None)})
        result = sample_assignments(db, test_id, lock=True)
    return result


@retry_deadlocks
def replace_panel_tests(db, panel_id, payload, actor_id, ip_address):
    with mutation(db):
        get_record(db, TestPanel, panel_id, lock=True)
        ids = [item.test_id for item in payload.tests]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, 'Duplicate test IDs.')
        for test_id in sorted(ids):
            related(db, TestCatalog, test_id)
        for section_id in sorted({item.section_id for item in payload.tests if item.section_id is not None}):
            if related(db, PanelSection, section_id).panel_id != panel_id:
                raise HTTPException(422, 'Section must belong to this panel.')
        db.execute(delete(PanelTest).where(PanelTest.panel_id == panel_id))
        db.add_all(PanelTest(panel_id=panel_id, **item.model_dump()) for item in payload.tests)
        db.flush()
        audit(db, actor_id, 'PANEL_TESTS_UPDATE', 'test_panel', panel_id, ip_address,
              new={'test_ids': sorted(ids), 'section_ids': sorted({item.section_id for item in payload.tests if item.section_id is not None})})
        result = panel_assignments(db, panel_id, lock=True)
    return result


def ensure_no_overlap(db, test_id, values, *, exclude_id=None):
    """Parent test must be locked. Inclusive windows, NULL unbounded, same sex only."""
    if not values.is_active:
        return
    conditions = [ReferenceRange.test_id == test_id, ReferenceRange.sex == values.sex,
                  ReferenceRange.is_active.is_(True)]
    if exclude_id is not None:
        conditions.append(ReferenceRange.range_id != exclude_id)
    for lower, upper in [('age_min', 'age_max'), ('effective_from', 'effective_to')]:
        low, high = getattr(values, lower), getattr(values, upper)
        if low is not None:
            conditions.append(or_(getattr(ReferenceRange, upper).is_(None), getattr(ReferenceRange, upper) >= low))
        if high is not None:
            conditions.append(or_(getattr(ReferenceRange, lower).is_(None), getattr(ReferenceRange, lower) <= high))
    # Locking read observes committed contenders even under REPEATABLE READ.
    if db.scalar(select(ReferenceRange.range_id).where(*conditions).with_for_update().limit(1)) is not None:
        raise HTTPException(409, 'Active reference range overlaps another range of the same sex.')


class ReferenceRangeAmbiguityError(HTTPException):
    def __init__(self):
        super().__init__(409, 'Multiple reference ranges have equal applicability; review configuration.')


def resolve_reference_range(db, test_id: int, patient_sex: str | None, age_years: Decimal | None,
                            as_of_date: date, *, lock: bool = False) -> ReferenceRange | None:
    """Select configuration by test/sex/age/date; never evaluate a result.

    Callers derive age from PATIENT.birth_date as of the desired date. This
    service receives no patient ID and stores no age. Unknown age only matches
    age-unbounded ranges; unknown sex only matches ANY. None means no match.
    Mutation callers request current shared reads with lock=True.
    """
    try:
        inputs = s.RangeSelection(sex=patient_sex, age_years=age_years, as_of_date=as_of_date)
    except ValidationError:
        raise HTTPException(422, 'Invalid reference range selection parameters.') from None
    (related if lock else get_record)(db, TestCatalog, test_id)
    allowed = ['ANY'] if inputs.sex in {'Other', None} else [inputs.sex, 'ANY']
    age_conditions = ([ReferenceRange.age_min.is_(None), ReferenceRange.age_max.is_(None)]
                      if inputs.age_years is None else [
                          or_(ReferenceRange.age_min.is_(None), ReferenceRange.age_min <= inputs.age_years),
                          or_(ReferenceRange.age_max.is_(None), ReferenceRange.age_max >= inputs.age_years)])
    statement = select(ReferenceRange).where(
        ReferenceRange.test_id == test_id, ReferenceRange.is_active.is_(True),
        ReferenceRange.sex.in_(allowed),
        *age_conditions,
        or_(ReferenceRange.effective_from.is_(None), ReferenceRange.effective_from <= inputs.as_of_date),
        or_(ReferenceRange.effective_to.is_(None), ReferenceRange.effective_to >= inputs.as_of_date),
    )
    if lock:
        statement = statement.with_for_update(read=True).execution_options(populate_existing=True)
    candidates = list(db.scalars(statement))
    preferred = [row for row in candidates if row.sex == inputs.sex]
    selected = preferred or candidates
    if len(selected) > 1:
        # Log configuration IDs only, never patient data or selection inputs.
        logger.error('Ambiguous reference range configuration: test_id=%s range_ids=%s',
                     test_id, sorted(row.range_id for row in selected))
        raise ReferenceRangeAmbiguityError()
    return selected[0] if selected else None
