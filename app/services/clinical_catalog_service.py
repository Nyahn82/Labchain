"""Facility approval and frozen order definitions layered on existing master data."""
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from app.config import settings
from app.models import LabDepartment, PanelSection, TestSampleType, SampleType
from app.schemas.laboratory import TestResponse


def orderable(record):
    metadata = record.catalog_metadata or {}
    development_available = (settings.environment.lower() == 'development'
                             and settings.development_catalog_ordering_enabled
                             and record.facility_status == 'UNREVIEWED')
    return bool(record.is_active
                and (record.facility_status in (None, 'APPROVED') or development_available)
                and not metadata.get('restricted_workflow'))


def require_orderable(record):
    if not orderable(record):
        raise HTTPException(409, 'Examination or panel is not approved and available for clinical ordering.')


def test_definition(item, test):
    snapshot = item.definition_snapshot
    return SimpleNamespace(**snapshot['test']) if snapshot and 'test' in snapshot else test


def capture_test(db, test, memberships):
    specimens = [dict(sample_type_id=s.sample_type_id, sample_name=s.sample_name,
                      specimen_code=s.specimen_code, collection_guidance=s.collection_guidance)
                 for s in db.scalars(select(SampleType).join(TestSampleType,
                    SampleType.sample_type_id == TestSampleType.sample_type_id).where(
                    TestSampleType.test_id == test.test_id).order_by(SampleType.sample_type_id))]
    department = db.get(LabDepartment, test.department_id)
    return {'test': TestResponse.model_validate(test).model_dump(mode='json'),
            'department': department.department_name, 'specimens': specimens,
            'panels': memberships}


def panel_membership(db, panel, member):
    section = db.get(PanelSection, member.section_id) if member.section_id else None
    return dict(panel_id=panel.panel_id, panel_name=panel.panel_name, panel_code=panel.panel_code,
                section_name=section.section_name if section else None, sort_order=member.sort_order)


def load_catalog():
    from pathlib import Path
    from app.services.starter_catalog_service import Catalog
    return Catalog.model_validate_json((Path(__file__).resolve().parents[1] / 'data' / 'philippine_clinical_catalog.json').read_text())


def catalog_view(db):
    from app.models import TestCatalog, TestPanel, PanelTest
    from app.schemas.laboratory import DepartmentResponse, SampleTypeResponse, PanelResponse
    departments = list(db.scalars(select(LabDepartment).order_by(LabDepartment.department_id)))
    samples = list(db.scalars(select(SampleType).order_by(SampleType.sample_type_id)))
    active_departments = {r.department_id for r in departments if r.is_active}
    active_samples = {r.sample_type_id for r in samples if r.is_active}
    mappings = {}
    for row in db.scalars(select(TestSampleType)):
        mappings.setdefault(row.test_id, []).append(row.sample_type_id)
    tests = []
    for row in db.scalars(select(TestCatalog).order_by(TestCatalog.test_name)):
        test = TestResponse.model_validate(row).model_dump(mode='json')
        test['sample_type_ids'] = mappings.get(row.test_id, [])
        test['orderable'] = orderable(row) and row.department_id in active_departments and bool(set(test['sample_type_ids']) & active_samples)
        tests.append(test)
    allowed = {r['test_id'] for r in tests if r['orderable']}
    members = {}
    for row in db.scalars(select(PanelTest).order_by(PanelTest.sort_order, PanelTest.panel_test_id)):
        members.setdefault(row.panel_id, []).append(row.test_id)
    panels = []
    for row in db.scalars(select(TestPanel).order_by(TestPanel.panel_name)):
        panel = PanelResponse.model_validate(row).model_dump(mode='json')
        panel['test_ids'] = members.get(row.panel_id, [])
        panel['orderable'] = orderable(row) and bool(panel['test_ids']) and set(panel['test_ids']) <= allowed
        panels.append(panel)
    return dict(tests=tests, panels=panels,
                departments=[DepartmentResponse.model_validate(r) for r in departments],
                specimens=[SampleTypeResponse.model_validate(r) for r in samples])
