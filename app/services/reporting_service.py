"""Official report snapshots and approval; release is deliberately separate."""
from datetime import datetime, time
import secrets

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_, select

from app.models import (
    FacilityProfile, LabOrder, LabOrderItem, LabReport, LabResultItem, OrderPanel,
    PanelSection, PanelTest, Patient, ReferenceRange, ReportPatientSnapshot,
    ReportResultItem, ReportSignatory, ReportTemplate, RequestingPhysician,
    Signatory, Staff, StaffAccountLink, TestCatalog, TestPanel,
)
from app.schemas import reporting as s
from app.services.auth_service import utc_now
from app.services.identity_service import audit, get_record, mutation
from app.services.laboratory_service import related, retry_deadlocks
from app.services.report_formatting import full_years, printable_name, printable_range


def current(statement, lock=True):
    return statement.with_for_update().execution_options(populate_existing=True) if lock else statement


def fields(row):
    return {column.key: getattr(row, column.key) for column in inspect(type(row)).columns}


def facility(db, *, lock=False):
    rows = list(db.scalars(current(select(FacilityProfile).order_by(FacilityProfile.facility_id).limit(2), lock)))
    if not rows:
        raise HTTPException(404, 'Issuing facility is not configured.')
    if len(rows) != 1:
        raise HTTPException(409, 'Multiple issuing facilities require administrator configuration correction.')
    return rows[0]


@retry_deadlocks
def save_facility(db, payload, actor_id, ip_address, *, create=False):
    with mutation(db):
        if create:
            if db.scalar(current(select(FacilityProfile.facility_id).limit(1))) is not None:
                raise HTTPException(409, 'The issuing facility already exists; use PATCH.')
            # Fixed server-owned PK serializes competing empty-table creation.
            record = FacilityProfile(facility_id=1, **payload.model_dump())
            db.add(record)
        else:
            record = facility(db, lock=True)
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(record, key, value)
            record.updated_at = utc_now()
        db.flush()
        audit(db, actor_id, 'FACILITY_PROFILE_CREATE' if create else 'FACILITY_PROFILE_UPDATE',
              'facility_profile', record.facility_id, ip_address,
              new={'changed_fields': sorted(payload.model_fields_set)})
        response = s.FacilityResponse.model_validate(record)
    return response


def approved_reference(db, model, identifier):
    statement = select(LabReport.report_id).where(LabReport.report_status.in_(['APPROVED', 'RELEASED', 'REVOKED']))
    if model is ReportTemplate:
        statement = statement.where(LabReport.template_id == identifier)
    else:
        statement = statement.join(ReportSignatory, ReportSignatory.report_id == LabReport.report_id).where(
            ReportSignatory.signatory_id == identifier)
    return db.scalar(current(statement.limit(1))) is not None


@retry_deadlocks
def save_configuration(db, model, payload, actor_id, ip_address, *, record_id=None):
    with mutation(db):
        record = get_record(db, model, record_id, lock=True) if record_id is not None else None
        values = payload.model_dump(exclude_unset=record is not None)
        changed = {key for key, value in values.items() if record is None or getattr(record, key) != value}
        merged = (fields(record) if record is not None else {}) | values
        if model is ReportTemplate:
            schema, action = s.TemplateResponse, 'REPORT_TEMPLATE'
            if record and changed - {'is_active'} and approved_reference(db, model, record_id):
                raise HTTPException(409, 'Approved report templates are immutable; create a new template code.')
            if merged['panel_id'] is not None:
                related(db, TestPanel, merged['panel_id'])
        else:
            schema, action = s.SignatoryResponse, 'SIGNATORY'
            if record and changed - {'is_active'}:
                signed = db.scalar(current(select(ReportSignatory.report_signatory_id).where(
                    ReportSignatory.signatory_id == record_id, ReportSignatory.signed_at.is_not(None)).limit(1)))
                if signed is not None or approved_reference(db, model, record_id):
                    raise HTTPException(409, 'Signed or approved signatory display fields are immutable; create a new profile.')
            staff = related(db, Staff, merged['staff_id'])
            if merged['is_active'] and not staff.is_active:
                raise HTTPException(409, 'An active signatory requires active staff.')
        if record is None:
            record = model(**values)
            db.add(record)
        else:
            for key in changed:
                setattr(record, key, values[key])
        db.flush()
        audit(db, actor_id, action + ('_CREATE' if record_id is None else '_UPDATE'), model.__tablename__,
              inspect(record).identity[0], ip_address, new={'changed_fields': sorted(changed)})
        response = schema.model_validate(record)
    return response


def report_signatories(db, report_id, *, lock=False):
    rows = db.execute(current(select(ReportSignatory, Signatory, Staff)
        .join(Signatory, Signatory.signatory_id == ReportSignatory.signatory_id)
        .join(Staff, Staff.staff_id == Signatory.staff_id)
        .where(ReportSignatory.report_id == report_id)
        .order_by(ReportSignatory.sort_order, ReportSignatory.report_signatory_id), lock))
    return [s.ReportSignatoryResponse(**fields(link), profile=s.SignatoryResponse.model_validate(profile),
                                     staff_name=printable_name(staff)) for link, profile, staff in rows]


def report_detail(db, report_id, *, lock=False):
    report = get_record(db, LabReport, report_id, lock=lock)
    patient = db.scalar(current(select(ReportPatientSnapshot).where(ReportPatientSnapshot.report_id == report_id), lock))
    lines = list(db.scalars(current(select(ReportResultItem).where(ReportResultItem.report_id == report_id)
                                   .order_by(ReportResultItem.sort_order, ReportResultItem.report_result_item_id), lock)))
    return s.ReportDetail(**fields(report),
        facility=s.FacilityResponse.model_validate(get_record(db, FacilityProfile, report.facility_id, lock=lock)),
        template=s.TemplateResponse.model_validate(get_record(db, ReportTemplate, report.template_id, lock=lock))
                 if report.template_id is not None else None,
        patient_snapshot=patient, result_snapshots=lines, signatories=report_signatories(db, report_id, lock=lock))


def list_reports(db, *, page, page_size, search=None, order_id=None, status=None, date_from=None, date_to=None):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'date_from must not exceed date_to.')
    statement = select(LabReport).join(LabOrder, LabOrder.order_id == LabReport.order_id).outerjoin(
        ReportPatientSnapshot, ReportPatientSnapshot.report_id == LabReport.report_id)
    if order_id is not None:
        statement = statement.where(LabReport.order_id == order_id)
    if status is not None:
        statement = statement.where(LabReport.report_status == status)
    if date_from:
        statement = statement.where(LabReport.generated_at >= datetime.combine(date_from, time.min))
    if date_to:
        statement = statement.where(LabReport.generated_at <= datetime.combine(date_to, time.max))
    if search and search.strip():
        statement = statement.where(or_(*(field.icontains(search.strip(), autoescape=True) for field in (
            LabReport.report_code, LabOrder.order_code, ReportPatientSnapshot.patient_code, ReportPatientSnapshot.patient_name))))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = list(db.scalars(statement.order_by(LabReport.report_id.desc()).offset((page - 1) * page_size).limit(page_size)))
    return dict(items=rows, page=page, page_size=page_size, total=total)


def verified_sources(db, order):
    if order.status != 'COMPLETED':
        raise HTTPException(409, 'Official reporting requires a COMPLETED, non-cancelled order.')
    items = list(db.scalars(current(select(LabOrderItem).where(
        LabOrderItem.order_id == order.order_id, LabOrderItem.status != 'CANCELLED').order_by(LabOrderItem.order_item_id))))
    if not items or any(item.status != 'COMPLETED' for item in items):
        raise HTTPException(409, 'Order completion and requested items disagree.')
    sources = []
    for item in items:
        rows = list(db.scalars(current(select(LabResultItem).where(LabResultItem.order_item_id == item.order_item_id))))
        if len(rows) != 1 or rows[0].status != 'VERIFIED':
            raise HTTPException(409, 'Every reportable item must have exactly one VERIFIED result.')
        result = rows[0]
        if any(getattr(result, key) is None for key in ('reviewed_by_user_id', 'reviewed_at', 'verified_by_user_id', 'verified_at')):
            raise HTTPException(409, 'Verified result provenance is incomplete.')
        sources.append((item, result))
    return sources


def snapshot_lines(db, sources):
    ordered = []
    for item, result in sources:
        test = related(db, TestCatalog, item.test_id)
        reference = related(db, ReferenceRange, result.reference_range_id) if result.reference_range_id is not None else None
        if reference and reference.test_id != item.test_id:
            raise HTTPException(409, 'Result reference range belongs to another test.')
        panel_id, section_name, member = None, None, None
        if item.order_panel_id is not None:
            panel = related(db, OrderPanel, item.order_panel_id)
            if panel.order_id != item.order_id or panel.status != 'COMPLETED':
                raise HTTPException(409, 'Order panel completion is inconsistent.')
            panel_id = panel.panel_id
            related(db, TestPanel, panel_id)  # Coordinate with panel membership replacement.
            member = db.scalar(current(select(PanelTest).where(PanelTest.panel_id == panel_id, PanelTest.test_id == item.test_id)))
            if member and member.section_id is not None:
                section = db.scalar(current(select(PanelSection).where(
                    PanelSection.section_id == member.section_id, PanelSection.panel_id == panel_id)))
                section_name = section.section_name if section else None
        default_order = test.default_sort_order
        sort_key = (item.order_panel_id is None, item.order_panel_id or 0,
                    member.sort_order if member else (default_order if default_order is not None else item.order_item_id),
                    default_order if default_order is not None else item.order_item_id, item.order_item_id)
        ordered.append((sort_key, dict(result_item_id=result.result_item_id, panel_id_snapshot=panel_id,
            section_name_snapshot=section_name, test_name_snapshot=test.test_name,
            result_value_snapshot=result.result_value,
            unit_snapshot=reference.unit if reference and reference.unit is not None else test.default_unit,
            reference_range_snapshot=printable_range(reference, test.result_type), flag_snapshot=result.flag)))
    return [dict(values, sort_order=index) for index, (_, values) in enumerate(sorted(ordered, key=lambda pair: pair[0]), 1)]


@retry_deadlocks
def generate_report(db, order_id, payload, actor_id, ip_address):
    with mutation(db):
        order = get_record(db, LabOrder, order_id, lock=True)
        if db.scalar(current(select(LabReport.report_id).where(LabReport.order_id == order_id).limit(1))) is not None:
            raise HTTPException(409, 'A report already exists; use the future report-revision workflow.')
        sources = verified_sources(db, order)
        issuing = facility(db, lock=True)
        if payload.template_id is not None:
            template = related(db, ReportTemplate, payload.template_id)
            if not template.is_active:
                raise HTTPException(409, 'The selected report template is inactive.')
        patient = related(db, Patient, order.patient_id)
        physician = related(db, RequestingPhysician, order.physician_id) if order.physician_id is not None else None
        now = utc_now()
        report = LabReport(report_code=f'RPT-{now:%Y%m%d}-{secrets.token_hex(8).upper()}',
            order_id=order_id, facility_id=issuing.facility_id, **payload.model_dump(), version_no=1,
            supersedes_report_id=None, report_status='GENERATED', generated_by_user_id=actor_id, generated_at=now)
        db.add(report)
        db.flush()
        db.add(ReportPatientSnapshot(report_id=report.report_id, patient_code=patient.patient_code,
            patient_name=printable_name(patient), birth_date=patient.birth_date,
            age_at_report=full_years(patient.birth_date, now.date()), sex=patient.sex,
            physician_name=printable_name(physician) if physician else None))
        db.add_all(ReportResultItem(report_id=report.report_id, **line) for line in snapshot_lines(db, sources))
        db.flush()
        audit(db, actor_id, 'REPORT_GENERATE', 'lab_report', report.report_id, ip_address,
              new={'order_id': order_id, 'version_no': 1, 'status': 'GENERATED', 'result_count': len(sources)})
        response = report_detail(db, report.report_id, lock=True)
    return response


def generated_report(db, report_id):
    report = get_record(db, LabReport, report_id, lock=True)
    if report.report_status != 'GENERATED':
        raise HTTPException(409, 'Only GENERATED reports accept this operation.')
    return report


def active_signatory(db, signatory_id):
    profile = related(db, Signatory, signatory_id)
    staff = related(db, Staff, profile.staff_id)
    if not profile.is_active or not staff.is_active:
        raise HTTPException(409, 'Signing requires an active signatory and active staff.')
    return profile


@retry_deadlocks
def assign_signatory(db, report_id, payload, actor_id, ip_address):
    with mutation(db):
        generated_report(db, report_id)
        active_signatory(db, payload.signatory_id)
        if db.scalar(current(select(ReportSignatory.report_signatory_id).where(
            ReportSignatory.report_id == report_id, ReportSignatory.signatory_id == payload.signatory_id,
            ReportSignatory.signatory_type == payload.signatory_type).limit(1))) is not None:
            raise HTTPException(409, 'This signatory/type is already assigned.')
        link = ReportSignatory(report_id=report_id, **payload.model_dump(), signed_at=None)
        db.add(link)
        db.flush()
        audit(db, actor_id, 'REPORT_SIGNATORY_ASSIGN', 'report_signatory', link.report_signatory_id, ip_address,
              new={'report_id': report_id, 'signatory_id': link.signatory_id, 'signatory_type': link.signatory_type})
        response = next(row for row in report_signatories(db, report_id, lock=True) if row.report_signatory_id == link.report_signatory_id)
    return response


@retry_deadlocks
def sign_report(db, report_id, payload, actor_id, ip_address):
    with mutation(db):
        generated_report(db, report_id)
        link = get_record(db, ReportSignatory, payload.report_signatory_id, lock=True)
        if link.report_id != report_id:
            raise HTTPException(404, 'Signatory assignment not found in this report.')
        profile = active_signatory(db, link.signatory_id)
        identity = db.scalar(current(select(StaffAccountLink).where(
            StaffAccountLink.staff_id == profile.staff_id, StaffAccountLink.user_id == actor_id)))
        if identity is None:
            raise HTTPException(403, 'Only the user linked to this signatory staff identity may sign.')
        if link.signed_at is not None:
            raise HTTPException(409, 'This assignment is already signed.')
        link.signed_at = utc_now()
        db.flush()
        audit(db, actor_id, 'REPORT_SIGN', 'report_signatory', link.report_signatory_id, ip_address,
              new={'report_id': report_id, 'signatory_id': link.signatory_id})
        response = next(row for row in report_signatories(db, report_id, lock=True) if row.report_signatory_id == link.report_signatory_id)
    return response


@retry_deadlocks
def approve_report(db, report_id, actor_id, ip_address):
    with mutation(db):
        parent_id = get_record(db, LabReport, report_id).order_id
        order = get_record(db, LabOrder, parent_id, lock=True)
        report = generated_report(db, report_id)
        sources = verified_sources(db, order)
        if any(getattr(report, field) is not None for field in (
            'approved_at', 'approved_by_user_id', 'released_at', 'released_by_user_id',
            'revoked_at', 'revoked_by_user_id', 'revocation_reason', 'pdf_path')):
            raise HTTPException(409, 'Generated report has inconsistent lifecycle metadata.')
        patient = db.scalar(current(select(ReportPatientSnapshot).where(ReportPatientSnapshot.report_id == report_id)))
        lines = list(db.scalars(current(select(ReportResultItem).where(ReportResultItem.report_id == report_id))))
        expected = {result.result_item_id: result for _, result in sources}
        if (patient is None or not patient.patient_code.strip() or not patient.patient_name.strip()
                or patient.age_at_report != full_years(patient.birth_date, report.generated_at.date())
                or not lines or len(lines) != len(expected)
                or {line.result_item_id for line in lines} != set(expected)
                or sorted(line.sort_order for line in lines) != list(range(1, len(lines) + 1))):
            raise HTTPException(409, 'Report snapshot integrity is invalid.')
        source_items = {result.result_item_id: item for item, result in sources}
        for line in lines:
            source = expected[line.result_item_id]
            item = source_items[line.result_item_id]
            panel_id = (related(db, OrderPanel, item.order_panel_id).panel_id
                        if item.order_panel_id is not None else None)
            if line.panel_id_snapshot != panel_id:
                raise HTTPException(409, 'Report snapshot panel disagrees with its requested item.')
            if (not line.test_name_snapshot.strip() or not line.result_value_snapshot.strip()
                    or line.result_value_snapshot != source.result_value or line.flag_snapshot != source.flag):
                raise HTTPException(409, 'Report snapshot disagrees with its verified source.')
        # Shared configuration locks serialize approval against display-field updates.
        if report.template_id is not None:
            related(db, ReportTemplate, report.template_id)
        assignments = report_signatories(db, report_id, lock=True)
        if not assignments or any(row.signed_at is None for row in assignments):
            raise HTTPException(409, 'At least one signatory is required and all assignments must be signed.')
        report.report_status = 'APPROVED'
        report.approved_by_user_id, report.approved_at = actor_id, utc_now()
        db.flush()
        audit(db, actor_id, 'REPORT_APPROVE', 'lab_report', report_id, ip_address,
              old={'status': 'GENERATED'}, new={'status': 'APPROVED'})
        response = report_detail(db, report_id, lock=True)
    return response
