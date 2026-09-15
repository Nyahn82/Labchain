"""Identity mutations and their minimal audit events share one transaction."""

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, ReferringFacility, RequestingPhysician
from app.services.auth_service import utc_now


@contextmanager
def mutation(db: Session):
    # Authentication's SELECTs have already begun the request transaction.
    # This service owns its single commit, including every audit write.
    try:
        yield
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Record conflicts with existing data.') from None
    except Exception:
        db.rollback()
        raise


def audit(db, actor_id, action, entity, record_id, ip_address, *, old=None, new=None):
    db.add(AuditLog(
        user_id=actor_id, action=action, entity_type=entity, record_id=record_id,
        ip_address=ip_address, created_at=utc_now(), old_value=old, new_value=new,
    ))


def get_record(db, model, record_id, *, lock=False):
    key = inspect(model).primary_key[0]
    statement = select(model).where(key == record_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(404, 'Record not found.')
    return record


def list_records(db, model, *, page, page_size, search=None, search_fields=(), filters=None, options=()):
    conditions = [getattr(model, field) == value for field, value in (filters or {}).items() if value is not None]
    if search and search.strip():
        conditions.append(or_(*(getattr(model, field).icontains(search.strip(), autoescape=True) for field in search_fields)))
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    statement = select(model).where(*conditions).order_by(*inspect(model).primary_key)
    items = db.scalars(statement.options(*options).offset((page - 1) * page_size).limit(page_size)).all()
    return dict(items=items, page=page, page_size=page_size, total=total)


def validate_facility(db, model, values):
    if model is RequestingPhysician and values.get('referring_facility_id') is not None:
        if db.get(ReferringFacility, values['referring_facility_id']) is None:
            raise HTTPException(422, 'Referring facility does not exist.')


def create_record(db, model, payload, response_schema, actor_id, ip_address, action):
    with mutation(db):
        values = payload.model_dump()
        validate_facility(db, model, values)
        record = model(**values)
        db.add(record)
        db.flush()
        audit(db, actor_id, action, model.__tablename__, inspect(record).identity[0], ip_address,
              new={'changed_fields': sorted(payload.model_fields_set)})
        result = response_schema.model_validate(record)
    return result


def patch_record(db, model, record_id, payload, response_schema, actor_id, ip_address, action):
    with mutation(db):
        record = get_record(db, model, record_id, lock=True)
        values = payload.model_dump(exclude_unset=True)
        validate_facility(db, model, values)
        changed = [field for field, value in values.items() if getattr(record, field) != value]
        for field in changed:
            setattr(record, field, values[field])
        if changed and hasattr(record, 'updated_at'):
            record.updated_at = utc_now()
        db.flush()
        audit(db, actor_id, action, model.__tablename__, record_id, ip_address,
              new={'changed_fields': sorted(changed)})
        result = response_schema.model_validate(record)
    return result
