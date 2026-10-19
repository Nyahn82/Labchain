"""Offline synthetic import, permissions, atomicity and catalog-to-PDF coverage."""
from copy import deepcopy
from io import BytesIO
import re

from fastapi import HTTPException
from pydantic import ValidationError
from pypdf import PdfReader
import pytest
from sqlalchemy import func, select

from app.models import (AuditLog, CodeSequence, LabDepartment, PanelTest, Permission,
                        ReferenceRange, Role, RolePermission, SampleType,
                        TestCatalog as Catalog, TestPanel as Panel, TestSampleType as SampleLink, UserRole)
from app.services import starter_catalog_service as service
from app.services.auth_service import utc_now
from test_phase_3a_authentication_rbac import env, password_hash, login, csrf
from test_phase_3c_laboratory import lab_api, lab_admin
from test_phase_4a_workflow import workflow_api, call, create, order, specimen, transition
from test_phase_4b_results import results_api, advance
from test_phase_5a_reports import reports_api, admin, assigned, sign, approve
from test_phase_5b_release import api, release

PATH = '/lab/starter-catalog'
PERMISSIONS = ['LAB_MASTER_READ', 'LAB_DEPARTMENT_MANAGE', 'SAMPLE_TYPE_MANAGE', 'TEST_CATALOG_MANAGE', 'TEST_PANEL_MANAGE']


def preview(api):
    response = call(api, 'GET', PATH)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def apply(api, plan=None):
    plan = plan or preview(api)
    return call(api, 'POST', PATH, {'fingerprint': plan['fingerprint'], 'acknowledge_inactive_review': True})


def counters(db):
    return dict(db.execute(select(CodeSequence.sequence_key, CodeSequence.current_value)).all())


def totals(db):
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (LabDepartment, SampleType, Catalog, Panel, SampleLink, PanelTest, AuditLog)}


def test_catalog_integrity_and_no_clinical_defaults():
    catalog = service.load_catalog()
    assert {k: len(getattr(catalog, k)) for k in service.KINDS} == dict(departments=5, samples=5, tests=39, panels=5)
    data = catalog.model_dump(mode='json')
    assert all(t['sources'] and t['review_note'] and t['reference_policy'] for t in data['tests'])
    assert all(not {'default_unit', 'methodology', 'normal_low', 'normal_high', 'is_active'} & t.keys() for t in data['tests'])
    cbc, differential = data['panels'][:2]
    assert len(cbc['tests']) == 14 and set(differential['tests']) <= set(cbc['tests'])
    assert 'single IgG' in next(t['review_note'] for t in data['tests'] if t['key'] == 'igg')
    assert not any('plasma' in t['samples'] for t in data['tests'])
    assert not any(t['department'] == 'microbiology' for t in data['tests'])


@pytest.mark.parametrize('defect', ['alias', 'member', 'sample', 'source', 'clinical_override'])
def test_manifest_rejects_invalid_or_duplicate_definitions(defect):
    data = service.load_catalog().model_dump(mode='json')
    if defect == 'alias': data['tests'][1]['aliases'].append(' HEMOGLOBIN ')
    if defect == 'member': data['panels'][0]['tests'].append(data['panels'][0]['tests'][0])
    if defect == 'sample': data['tests'][0]['samples'] = ['not-a-specimen']
    if defect == 'source': data['tests'][0]['sources'] = ['unverified']
    if defect == 'clinical_override': data['tests'][0]['default_unit'] = 'invented'
    with pytest.raises(ValidationError): service.Catalog.model_validate(data)


def test_preview_is_read_only_and_import_is_inactive_atomic_and_idempotent(lab_admin):
    with lab_admin.factory() as db: before, seq = totals(db), counters(db)
    plan = preview(lab_admin)
    assert plan['create_count'] == 54 and not plan['conflicts']
    assert preview(lab_admin)['fingerprint'] == plan['fingerprint']
    with lab_admin.factory() as db: assert (totals(db), counters(db)) == (before, seq)
    response = apply(lab_admin, plan)
    assert response.status_code == 200, response.text
    assert len(response.json()['created']) == 54
    with lab_admin.factory() as db:
        for kind, (model, _, code, _) in service.KINDS.items():
            for item in response.json()['created']:
                if item['kind'] == kind:
                    row = db.get(model, item['record_id'])
                    assert row.is_active is False
                    if code: assert re.fullmatch(r'(DEP|TST|PNL)-\d+', getattr(row, code))
                    if model is Catalog: assert row.default_unit is row.methodology is None
        assert db.scalar(select(func.count()).select_from(SampleLink)) == 39
        assert db.scalar(select(func.count()).select_from(PanelTest)) == 32
        assert db.scalar(select(func.count()).select_from(ReferenceRange)) == 0
        assert counters(db) == {**seq, 'DEPARTMENT': 5, 'TEST': 39, 'PANEL': 5}
        after, final_seq = totals(db), counters(db)
        assert after['audit_log'] - before['audit_log'] == 54
    assert apply(lab_admin, plan).status_code == 409  # stale replay consumes nothing
    fresh = preview(lab_admin)
    assert fresh['create_count'] == 0 and fresh['preserved_count'] == 54
    assert apply(lab_admin, fresh).json()['created'] == []
    with lab_admin.factory() as db: assert (totals(db), counters(db)) == (after, final_seq)


def test_existing_custom_metadata_and_relationships_are_preserved(lab_admin):
    with lab_admin.factory.begin() as db:
        db.get(LabDepartment, 1).department_name = 'Hematology'
        row = db.get(Catalog, 1)
        row.test_name, row.default_unit, row.methodology = 'HGB', 'local-unit', 'Local approved method'
        db.add(SampleLink(test_id=1, sample_type_id=1, is_default=True))
        db.add(ReferenceRange(test_id=1, sex='ANY', unit='approved-unit', qualitative_normal='local'))
        db.get(Panel, 1).panel_name = 'CBC'
        db.get(Panel, 1).department_id = 1
        db.add(PanelTest(panel_id=1, test_id=2, sort_order=10, is_required=False))
    plan = preview(lab_admin)
    assert not plan['conflicts']
    assert apply(lab_admin, plan).status_code == 200
    with lab_admin.factory() as db:
        row = db.get(Catalog, 1)
        assert (row.test_code, row.test_name, row.default_unit, row.methodology, row.is_active) == ('SEED1', 'HGB', 'local-unit', 'Local approved method', True)
        links = list(db.scalars(select(SampleLink).where(SampleLink.test_id == 1)))
        assert len(links) == 1 and links[0].sample_type_id == 1 and links[0].is_default
        assert db.scalar(select(ReferenceRange.unit)) == 'approved-unit'
        assert list(db.scalars(select(PanelTest.test_id).where(PanelTest.panel_id == 1))) == [2]
        assert db.get(Panel, 1).panel_code == 'SEED1'
        assert db.get(Catalog, 2).test_name == 'Seed test 2'


@pytest.mark.parametrize('defect', ['ambiguous', 'department', 'result_type', 'aggregate'])
def test_conflicting_existing_mappings_block_entire_import(lab_admin, defect):
    with lab_admin.factory.begin() as db:
        db.get(LabDepartment, 1).department_name = 'Hematology'
        db.get(Catalog, 1).test_name = 'Hémoglobin  '
        if defect == 'ambiguous': db.get(Catalog, 2).test_name = 'HGB'
        if defect == 'department': db.get(LabDepartment, 1).department_name = 'Different department'
        if defect == 'result_type': db.get(Catalog, 1).result_type = 'TEXT'
        if defect == 'aggregate': db.get(Catalog, 1).test_name = 'CBC'
    with lab_admin.factory() as db: before, seq = totals(db), counters(db)
    plan = preview(lab_admin)
    assert plan['conflicts']
    assert apply(lab_admin, plan).status_code == 409
    with lab_admin.factory() as db: assert (totals(db), counters(db)) == (before, seq)


def test_stale_preview_and_missing_sequence_fail_without_writes(lab_admin):
    plan = preview(lab_admin)
    with lab_admin.factory.begin() as db: db.get(Catalog, 1).methodology = 'New local configuration'
    assert apply(lab_admin, plan).status_code == 409
    with lab_admin.factory.begin() as db: db.delete(db.get(CodeSequence, 'TEST'))
    with lab_admin.factory() as db: before = totals(db)
    assert apply(lab_admin).status_code == 409
    with lab_admin.factory() as db: assert totals(db) == before


def test_failure_rolls_back_records_links_audit_and_counters(lab_admin, monkeypatch):
    original = service.audit
    def fail(*args, **kwargs):
        if kwargs['new']['catalog_key'] == 'renal':
            raise RuntimeError('synthetic audit failure')
        return original(*args, **kwargs)
    with lab_admin.factory() as db:
        plan = service.preview(db)
        before, seq = totals(db), counters(db)
        monkeypatch.setattr(service, 'audit', fail)
        with pytest.raises(RuntimeError, match='synthetic audit'):
            service.import_catalog(db, service.ImportRequest(fingerprint=plan['fingerprint'], acknowledge_inactive_review=True), 1, None)
        assert (totals(db), counters(db)) == (before, seq)


@pytest.mark.parametrize('missing', PERMISSIONS)
def test_import_requires_every_management_permission(lab_api, missing):
    with lab_api.factory.begin() as db:
        for permission in PERMISSIONS:
            if permission != missing:
                pid = db.scalar(select(Permission.permission_id).where(Permission.permission_code == permission))
                db.add(RolePermission(role_id=1, permission_id=pid))
    assert login(lab_api).status_code == 200
    assert call(lab_api, 'POST', PATH, {'fingerprint': '0' * 64, 'acknowledge_inactive_review': True}).status_code == 403


def test_auth_csrf_and_patient_separation(lab_api):
    assert lab_api.client.get('/api/v1'+PATH).status_code == 401
    with lab_api.factory.begin() as db: db.add(UserRole(user_id=1, role_id=2, assigned_at=utc_now()))
    assert login(lab_api).status_code == 200
    plan = preview(lab_api)
    body = dict(fingerprint=plan['fingerprint'], acknowledge_inactive_review=True)
    assert lab_api.client.post('/api/v1'+PATH, json=body).status_code == 403
    assert lab_api.client.post('/api/v1'+PATH, json=body, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    with lab_api.factory.begin() as db:
        role = Role(role_code='PATIENT', role_name='Patient', is_active=True)
        db.add(role); db.flush()
        db.add(UserRole(user_id=1, role_id=role.role_id, assigned_at=utc_now()))
    assert call(lab_api, 'GET', PATH).status_code == 403
    assert call(lab_api, 'POST', PATH, body).status_code == 403


@pytest.mark.parametrize('change', [{'acknowledge_inactive_review': False}, {'fingerprint': 'invalid'}, {'test_code': 'MANUAL'}, {'is_active': True}])
def test_request_rejects_unreviewed_or_client_configuration(lab_admin, change):
    assert call(lab_admin, 'POST', PATH, {'fingerprint': preview(lab_admin)['fingerprint'], 'acknowledge_inactive_review': True, **change}).status_code == 422


def test_catalog_order_specimen_results_and_pdf_history(api):
    plan = preview(api)
    assert apply(api, plan).status_code == 200
    mapping = {(i['kind'], i['key']): i['record_id'] for i in preview(api)['items']}
    tid = lambda key: mapping['tests', key]
    panel = mapping['panels', 'renal']
    payload = dict(patient_id=1, priority='ROUTINE', panel_ids=[panel], test_ids=[tid('upt'), tid('abo')])
    assert call(api, 'POST', '/lab-orders', payload).status_code == 409
    # Explicit synthetic approvals through existing authorized APIs, never an import side effect.
    for kind, keys, endpoint in [('departments', ['chemistry', 'microscopy', 'hematology'], 'departments'),
                                 ('samples', ['serum', 'urine', 'blood'], 'sample-types'),
                                 ('tests', ['creat', 'bun', 'upt', 'abo'], 'tests'), ('panels', ['renal'], 'panels')]:
        for key in keys:
            body = {'is_active': True}
            if kind == 'tests' and key in {'creat', 'bun'}:
                body.update(default_unit='synthetic-unit', methodology='Synthetic approved method')
            assert call(api, 'PATCH', f'/lab/{endpoint}/{mapping[kind, key]}', body).status_code == 200
    create(api, f'/lab/tests/{tid("creat")}/reference-ranges', {'sex': 'ANY', 'normal_low': '1', 'normal_high': '10', 'unit': 'REFU'})
    requested = create(api, '/lab-orders', payload)
    assert {i['test_id'] for i in requested['items']} == {tid(k) for k in ['creat', 'bun', 'upt', 'abo']}
    for sample, keys in [('serum', ['creat', 'bun']), ('urine', ['upt']), ('blood', ['abo'])]:
        selected = [i for i in requested['items'] if i['test_id'] in {tid(k) for k in keys}]
        registered = specimen(api, requested, sample_type_id=mapping['samples', sample], order_item_ids=[i['order_item_id'] for i in selected])
        sid = registered['specimen_id']
        assert transition(api, 'collect', sid).status_code == 200
        assert transition(api, 'receive', sid).status_code == 200
        for item in selected:
            value = 'Negative' if item['test_id'] == tid('upt') else 'O positive' if item['test_id'] == tid('abo') else '5'
            result = create(api, f'/lab-order-items/{item["order_item_id"]}/result', {'result_value': value, 'specimen_id': sid})
            assert advance(api, 'review', result['result_item_id']).status_code == 200
            assert advance(api, 'verify', result['result_item_id']).status_code == 200
    generated = create(api, f'/lab-orders/{requested["order_id"]}/reports', {})
    snapshots = deepcopy(generated['result_snapshots'])
    assigned(api)
    assert sign(api).status_code == 200 and approve(api).status_code == 200
    released = release(api)
    pdf = call(api, 'GET', f'/reports/{released["report_id"]}/pdf').content
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    for expected in ['Creatinine', 'Blood Urea Nitrogen', 'Negative', 'O positive', 'REFU', 'Synthetic approved method', 'PDF v2']:
        assert expected in text
    # Catalog retirement cannot rewrite any previously released report or its snapshots.
    assert call(api, 'PATCH', f'/lab/tests/{tid("creat")}', {'is_active': False, 'test_name': 'Retired synthetic name'}).status_code == 200
    assert call(api, 'GET', '/reports/1/pdf').content == pdf
    assert call(api, 'GET', '/reports/1').json()['result_snapshots'] == snapshots
    assert call(api, 'POST', '/lab-orders', payload).status_code == 409


@pytest.mark.parametrize('kind,key,model,column', [('tests', 'hb', Catalog, 'test_name'), ('panels', 'cbc', Panel, 'panel_name')])
def test_renaming_imported_configuration_cannot_silently_duplicate_it(lab_admin, kind, key, model, column):
    assert apply(lab_admin).status_code == 200
    plan = preview(lab_admin)
    record_id = next(i['record_id'] for i in plan['items'] if i['kind'] == kind and i['key'] == key)
    with lab_admin.factory.begin() as db: setattr(db.get(model, record_id), column, 'Locally renamed approved record')
    with lab_admin.factory() as db: before, seq = totals(db), counters(db)
    plan = preview(lab_admin)
    assert any('previous import was renamed' in message for message in plan['conflicts'])
    assert apply(lab_admin, plan).status_code == 409
    with lab_admin.factory() as db: assert (totals(db), counters(db)) == (before, seq)


def test_generated_code_collision_rolls_back_the_entire_import(lab_admin):
    with lab_admin.factory.begin() as db: db.get(LabDepartment, 1).department_code = 'DEP-001'
    with lab_admin.factory() as db: before, seq = totals(db), counters(db)
    assert apply(lab_admin).status_code == 409
    with lab_admin.factory() as db: assert (totals(db), counters(db)) == (before, seq)


@pytest.mark.parametrize('panel_key', ['cbc', 'diff', 'lipid', 'liver', 'renal'])
def test_every_panel_synthetic_order_to_pdf_and_specimen_errors(api, panel_key):
    """Synthetic configuration only; no facility-specific clinical interval claim."""
    assert apply(api).status_code == 200
    catalog = service.load_catalog()
    definition = next(panel for panel in catalog.panels if panel.key == panel_key)
    tests = {test.key: test for test in catalog.tests}
    mapping = {(i['kind'], i['key']): i['record_id'] for i in preview(api)['items']}
    panel_id = mapping['panels', panel_key]
    payload = dict(patient_id=1, priority='ROUTINE', panel_ids=[panel_id], test_ids=[])
    assert call(api, 'POST', '/lab-orders', payload).status_code == 409
    members = [tests[key] for key in definition.tests]
    samples = {sample for test in members for sample in test.samples}
    departments = {test.department for test in members}
    for kind, keys, endpoint in [('departments', departments, 'departments'), ('samples', samples, 'sample-types'),
                                  ('tests', definition.tests, 'tests'), ('panels', [panel_key], 'panels')]:
        for key in keys:
            values = {'is_active': True}
            if kind == 'tests':
                values.update(default_unit='SYNTHETIC', methodology='Synthetic simulation only')
            assert call(api, 'PATCH', f'/lab/{endpoint}/{mapping[kind, key]}', values).status_code == 200
    # One inactive component blocks the complete panel rather than silently omitting it.
    first_id = mapping['tests', definition.tests[0]]
    assert call(api, 'PATCH', f'/lab/tests/{first_id}', {'is_active': False}).status_code == 200
    assert call(api, 'POST', '/lab-orders', payload).status_code == 409
    assert call(api, 'PATCH', f'/lab/tests/{first_id}', {'is_active': True}).status_code == 200
    requested = create(api, '/lab-orders', payload)
    assert {item['test_id'] for item in requested['items']} == {mapping['tests', key] for key in definition.tests}
    assert len(requested['items']) == len(definition.tests)
    assert all(item['order_panel_id'] == requested['panels'][0]['order_panel_id'] for item in requested['items'])
    # Use an active, incompatible specimen. Approval of a sample never makes it universal.
    wrong_sample = next(key for key in ['urine', 'serum', 'blood'] if key not in samples)
    assert call(api, 'PATCH', f'/lab/sample-types/{mapping["samples", wrong_sample]}', {'is_active': True}).status_code == 200
    response = call(api, 'POST', f'/lab-orders/{requested["order_id"]}/specimens',
        {'sample_type_id': mapping['samples', wrong_sample], 'order_item_ids': [requested['items'][0]['order_item_id']]})
    assert response.status_code == 409
    sample_names = []
    for sample_key in samples:
        selected_ids = {mapping['tests', key] for key in definition.tests if tests[key].samples[0] == sample_key}
        selected = [item for item in requested['items'] if item['test_id'] in selected_ids]
        if not selected:
            continue
        registered = specimen(api, requested, sample_type_id=mapping['samples', sample_key], order_item_ids=[i['order_item_id'] for i in selected])
        sample_names.append(registered['sample_type']['sample_name'])
        sid = registered['specimen_id']
        assert transition(api, 'collect', sid).status_code == 200
        assert transition(api, 'receive', sid).status_code == 200
        for item in selected:
            result_path = f'/lab-order-items/{item["order_item_id"]}/result'
            assert call(api, 'POST', result_path, {'result_value': 'not-numeric', 'specimen_id': sid}).status_code == 422
            result = create(api, result_path, {'result_value': '5', 'specimen_id': sid})
            assert call(api, 'POST', result_path, {'result_value': '6', 'specimen_id': sid}).status_code == 409
            assert advance(api, 'verify', result['result_item_id']).status_code == 409
            assert advance(api, 'review', result['result_item_id']).status_code == 200
            assert advance(api, 'verify', result['result_item_id']).status_code == 200
    generated = create(api, f'/lab-orders/{requested["order_id"]}/reports', {})
    assert len(generated['result_snapshots']) == len(definition.tests)
    assigned(api)
    assert sign(api).status_code == 200 and approve(api).status_code == 200
    for sample_key in samples:
        assert call(api, 'PATCH', f'/lab/sample-types/{mapping["samples", sample_key]}', {'sample_name': 'CHANGED AFTER SNAPSHOT'}).status_code == 200
    released = release(api)
    data = call(api, 'GET', f'/reports/{released["report_id"]}/pdf').content
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
    for expected in [definition.name, 'Sample type:', *sample_names, *[test.name for test in members]]:
        assert expected in text
    assert text.count('Sample type:') == len(sample_names)
    assert 'CHANGED AFTER SNAPSHOT' not in text
