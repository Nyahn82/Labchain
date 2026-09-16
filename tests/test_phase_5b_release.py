"""Synthetic Phase 5B API, artifact, security and failure-safety tests."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re

from PIL import Image
from pypdf import PdfReader
import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api import verification
from app.config import settings, Settings
from app.models import (AuditLog, LabReport, LabResultItem, Patient, PrintLog, ReportPatientSnapshot,
    ReportResultItem, ReportSignatory, ReportTemplate, ReportVerification, TestCatalog as Catalog)
from app.services import report_pdf, report_release_service as service, report_storage
from app.services.permission_catalog import ensure_permissions
from test_phase_5a_reports import (env, password_hash, lab_api, workflow_api, results_api, reports_api,
    admin, generated, assigned, sign, approve, report, call, create, login, count)
from test_phase_5a_reports import test_auth_rbac_csrf_every_operation as check_access


@pytest.fixture
def api(admin, tmp_path, monkeypatch):
    root = tmp_path / 'reports'
    root.mkdir(mode=0o700)
    monkeypatch.setattr(settings, 'report_storage_dir', root)
    monkeypatch.setattr(settings, 'public_base_url', 'https://verify.example.test')
    monkeypatch.setattr(settings, 'report_signature_dir', None)
    admin.app.include_router(verification.router, prefix='/api/v1')
    return admin


def ready(api):
    template = create(api, '/report-templates', {'template_code': 'GEN', 'template_name': 'General',
        'header_title': 'Official laboratory report', 'section_title': 'Examination results',
        'clinical_note': 'Configured clinical note', 'footer_note': 'Configured footer',
        'medico_legal_note': 'Configured disclaimer'})
    row = generated(api, template_id=template['template_id'])
    assigned(api)
    assert sign(api).status_code == 200
    assert approve(api).status_code == 200
    return row


def release(api, report_id=1):
    response = call(api, 'POST', f'/reports/{report_id}/release')
    assert response.status_code == 200, response.text
    return response.json()


def metadata(api, report_id=1):
    response = call(api, 'GET', f'/reports/{report_id}/verification')
    assert response.status_code == 200, response.text
    return response.json()


def verify(api, report_id=1):
    url = metadata(api, report_id)['verification_url']
    # No cookies, authentication or CSRF headers supplied.
    from fastapi.testclient import TestClient
    with TestClient(api.app, base_url='https://verify.example.test') as public:
        return public.get(url)


ENDPOINTS = [
    ('POST', '/reports/999/release', None, 'REPORT_RELEASE'),
    ('GET', '/reports/999/pdf', None, 'REPORT_DOWNLOAD'),
    ('POST', '/reports/999/print', {'copies': 1}, 'REPORT_PRINT'),
    ('GET', '/reports/999/verification', None, 'REPORT_READ'),
    ('POST', '/reports/999/revoke', {'reason': 'Administrative'}, 'REPORT_REVOKE'),
    ('POST', '/reports/999/revise', {}, 'REPORT_REVISE'),
]


@pytest.mark.parametrize('method,path,body,permission', ENDPOINTS)
def test_access(reports_api, method, path, body, permission):
    check_access(reports_api, method, path, body, permission)


def test_release_snapshots_pdf_qr_hash_and_download(api, monkeypatch):
    original = ready(api)
    with api.factory.begin() as db:
        db.get(Patient, 1).first_name = 'LIVE_NAME_MUST_NOT_RENDER'
        db.get(Catalog, 1).test_name = 'LIVE_TEST_MUST_NOT_RENDER'
        lines = list(db.scalars(select(ReportResultItem).order_by(ReportResultItem.sort_order)))
        lines[0].test_name_snapshot = 'Hemoglobin <img src="file:///private"> & literal'
        lines[0].section_name_snapshot = 'HEMATOLOGY'
        lines[0].flag_snapshot = 'HIGH'
        expected_lines = [(line.test_name_snapshot, line.result_value_snapshot) for line in lines]
    payloads = []
    original_qr = report_pdf.qr_png
    monkeypatch.setattr(report_pdf, 'qr_png', lambda url: (payloads.append(url), original_qr(url))[1])
    row = release(api)
    assert row['report_status'] == 'RELEASED' and row['released_by_user_id'] == 1 and row['released_at']
    assert row['generated_at'] == original['generated_at']
    assert row['verification_status'] == 'AUTHENTIC' and row['is_current_released']
    assert not Path(row['pdf_path']).is_absolute()
    data = (settings.report_storage_dir / row['pdf_path']).read_bytes()
    assert data.startswith(b'%PDF-')
    meta = metadata(api)
    assert re.fullmatch('[0-9a-f]{64}', meta['report_hash'])
    assert meta['report_hash'] == hashlib.sha256(data).hexdigest()
    assert payloads == [meta['verification_url']]
    assert re.fullmatch(r'https://verify.example.test/api/v1/verify/[A-Za-z0-9_-]{43}', payloads[0])
    assert original['patient_snapshot']['patient_code'] not in payloads[0]
    reader = PdfReader(BytesIO(data))
    text = ' '.join(' '.join(page.extract_text() for page in reader.pages).split())
    for expected in ('Synthetic RHU', row['report_code'], original['patient_snapshot']['patient_name'],
                     original['patient_snapshot']['patient_code'], 'Synthetic Signer1', 'SYNTH-LIC', 'HEMATOLOGY',
                     'Configured clinical note', 'Configured footer', 'Configured disclaimer', 'Examination results',
                     '<img src="file:///private"> & literal', 'Scan to verify authenticity'):
        assert expected in text
    assert 'LIVE_NAME_MUST_NOT_RENDER' not in text and 'LIVE_TEST_MUST_NOT_RENDER' not in text
    positions = [text.index(name) for name, value in expected_lines]
    assert positions == sorted(positions)
    for name, value in expected_lines:
        assert value in text
    assert sum(len(page.images) for page in reader.pages) >= 1
    response = call(api, 'GET', '/reports/1/pdf')
    assert response.content == data and response.headers['content-type'] == 'application/pdf'
    assert 'attachment;' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'no-store'
    public = verify(api)
    assert public.status_code == 200 and public.json()['status'] == 'VERIFIED'
    assert public.headers['cache-control'] == 'no-store'
    assert set(public.json()) == {'status', 'issuing_facility', 'report_date', 'version', 'message'}
    for secret in (original['patient_snapshot']['patient_name'], original['patient_snapshot']['patient_code'], str(settings.report_storage_dir)):
        assert secret not in public.text
    assert call(api, 'POST', '/reports/1/release').status_code == 409
    assert (settings.report_storage_dir / row['pdf_path']).read_bytes() == data
    with api.factory() as db:
        assert count(db, ReportVerification) == 1
        assert {'REPORT_RELEASE', 'REPORT_DOWNLOAD'} <= set(db.scalars(select(AuditLog.action)))


@pytest.mark.parametrize('status', ['GENERATED', 'REVOKED', 'RELEASED'])
def test_release_state_guard(api, status):
    ready(api)
    with api.factory.begin() as db:
        db.get(LabReport, 1).report_status = status
    assert call(api, 'POST', '/reports/1/release').status_code == 409
    assert not list(settings.report_storage_dir.rglob('*.pdf'))


@pytest.mark.parametrize('defect', ['patient', 'results', 'unsigned', 'no_signatories', 'source', 'inactive_template',
    'provenance', 'existing_verification', 'storage', 'public_url'])
def test_release_prerequisites(api, defect, monkeypatch):
    ready(api)
    with api.factory.begin() as db:
        if defect == 'patient': db.execute(delete(ReportPatientSnapshot))
        if defect == 'results': db.execute(delete(ReportResultItem))
        if defect == 'unsigned': db.scalar(select(ReportSignatory)).signed_at = None
        if defect == 'no_signatories': db.execute(delete(ReportSignatory))
        if defect == 'source': db.scalar(select(LabResultItem)).status = 'REVIEWED'
        if defect == 'inactive_template': db.get(ReportTemplate, 1).is_active = False
        if defect == 'provenance': db.get(LabReport, 1).approved_at = None
        if defect == 'existing_verification':
            db.add(ReportVerification(report_id=1, verification_token='x'*43, report_hash='0'*64, verification_status='AUTHENTIC'))
    if defect == 'storage': monkeypatch.setattr(settings, 'report_storage_dir', settings.report_storage_dir / 'missing')
    if defect == 'public_url': monkeypatch.setattr(settings, 'public_base_url', None)
    response = call(api, 'POST', '/reports/1/release')
    assert response.status_code in {409, 503}, response.text
    with api.factory() as db:
        row = db.get(LabReport, 1)
        assert row.report_status == 'APPROVED' and row.pdf_path is row.released_at is None


@pytest.mark.parametrize('failure', ['render', 'invalid_pdf', 'storage', 'audit', 'commit', 'collision'])
def test_failed_release_rolls_back_and_cleans_artifact(api, monkeypatch, failure):
    ready(api)
    if failure == 'render':
        def fail(*args): raise ValueError('sensitive local path')
        monkeypatch.setattr(report_pdf, 'render_pdf', fail)
    elif failure == 'invalid_pdf': monkeypatch.setattr(report_pdf, 'render_pdf', lambda *args: b'not a pdf')
    elif failure == 'storage':
        def fail(*args): raise report_storage.ArtifactUnavailable()
        monkeypatch.setattr(report_storage, 'publish_pdf', fail)
    elif failure == 'audit':
        def fail(conn, cursor, statement, *args):
            if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic failure')
        event.listen(api.engine, 'before_cursor_execute', fail)
    elif failure == 'commit':
        def fail(session): raise SQLAlchemyError('Synthetic commit failure')
        event.listen(api.factory, 'before_commit', fail)
    elif failure == 'collision':
        # Force the DB uniqueness guard using another report's token.
        row = release(api)
        revised = call(api, 'POST', '/reports/1/revise', {}).json()
        link = create(api, '/reports/2/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
        assert sign(api, link['report_signatory_id'], 2).status_code == 200
        assert call(api, 'POST', '/reports/2/approve').status_code == 200
        token = metadata(api)['verification_url'].rsplit('/', 1)[1]
        monkeypatch.setattr(service.secrets, 'token_urlsafe', lambda n: token)
    target = 2 if failure == 'collision' else 1
    try:
        response = call(api, 'POST', f'/reports/{target}/release')
        assert response.status_code in {409, 503}, response.text
    finally:
        if failure == 'audit': event.remove(api.engine, 'before_cursor_execute', fail)
        if failure == 'commit': event.remove(api.factory, 'before_commit', fail)
    with api.factory() as db:
        row = db.get(LabReport, target)
        assert row.report_status == 'APPROVED' and row.pdf_path is None
        assert count(db, ReportVerification) == (1 if failure == 'collision' else 0)
    assert len(list(settings.report_storage_dir.rglob('*.pdf'))) == (1 if failure == 'collision' else 0)
    assert not list(settings.report_storage_dir.rglob('*.tmp'))


@pytest.mark.parametrize('damage', ['tamper', 'missing', 'traversal', 'absolute', 'symlink'])
def test_integrity_failures_are_private_and_audited(api, damage, tmp_path):
    ready(api)
    row = release(api)
    path = settings.report_storage_dir / row['pdf_path']
    if damage == 'tamper':
        path.chmod(0o600)
        path.write_bytes(b'%PDF-tampered')
    if damage == 'missing': path.unlink()
    if damage == 'symlink':
        path.unlink()
        outside = tmp_path / 'secret.pdf'
        outside.write_bytes(b'secret')
        path.symlink_to(outside)
    if damage in {'traversal', 'absolute'}:
        with api.factory.begin() as db:
            db.get(LabReport, 1).pdf_path = '../secret.pdf' if damage == 'traversal' else '/etc/passwd'
    response = verify(api)
    assert response.json()['status'] == 'ALTERED'
    assert str(tmp_path) not in response.text and '/etc/passwd' not in response.text
    assert call(api, 'GET', '/reports/1/pdf').status_code == 409
    assert call(api, 'POST', '/reports/1/print', {'copies': 1}).status_code == 409
    with api.factory() as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.action == 'REPORT_INTEGRITY_MISMATCH')))
        assert len(rows) == 3
        assert all(row.new_value['severity'] == 'HIGH' for row in rows)
        assert all(set(row.new_value) == {'severity', 'failure'} for row in rows)
        assert count(db, PrintLog) == 0


@pytest.mark.parametrize('token', ['unknown', 'x'*43, 'x'*121, 'x'*500, '123'])
def test_neutral_not_found(api, token):
    response = api.client.get('/api/v1/verify/' + token)
    assert response.json() == {'status': 'NOT_FOUND', 'message': 'Verification record not found.'}
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('copies', [0, -1, 21, 1.5, True, '2', None])
def test_invalid_print_copies(api, copies):
    assert call(api, 'POST', '/reports/999/print', {'copies': copies}).status_code == 422


def test_print_and_revocation_preserve_history(api):
    ready(api)
    row = release(api)
    original = (settings.report_storage_dir / row['pdf_path']).read_bytes()
    for copies in (1, 3):
        assert call(api, 'POST', '/reports/1/print', {'copies': copies}).content == original
    for reason in ('', '   ', None):
        assert call(api, 'POST', '/reports/1/revoke', {'reason': reason}).status_code == 422
    response = call(api, 'POST', '/reports/1/revoke', {'reason': 'Administrative correction'})
    assert response.status_code == 200
    row = response.json()
    assert row['report_status'] == 'REVOKED' and row['revoked_by_user_id'] == 1
    assert row['revocation_reason'] == 'Administrative correction'
    meta = metadata(api)
    assert meta['verification_status'] == 'REVOKED' and meta['revoked_at'] == row['revoked_at']
    assert verify(api).json()['status'] == 'REVOKED'
    assert call(api, 'POST', '/reports/1/revoke', {'reason': 'Again'}).status_code == 409
    assert call(api, 'GET', '/reports/1/pdf').content == original
    assert call(api, 'POST', '/reports/1/print', {'copies': 2}).content == original
    with api.factory() as db:
        assert list(db.scalars(select(PrintLog.copies).order_by(PrintLog.print_log_id))) == [1, 3, 2]
        assert count(db, ReportVerification) == 1
        assert {'REPORT_PRINT', 'REPORT_REVOKE'} <= set(db.scalars(select(AuditLog.action)))


def test_revision_supersession_and_snapshot_refresh(api):
    ready(api)
    old = release(api)
    original = (settings.report_storage_dir / old['pdf_path']).read_bytes()
    with api.factory.begin() as db:
        db.get(Patient, 1).first_name = 'Updated'
        db.get(Catalog, 1).test_name = 'Current catalog name'
    response = call(api, 'POST', '/reports/1/revise', {'remarks': 'Administrative corrected version'})
    assert response.status_code == 201, response.text
    new = response.json()
    assert new['report_id'] == 2 and new['version_no'] == 2 and new['supersedes_report_id'] == 1
    assert new['report_status'] == 'GENERATED' and new['signatories'] == [] and new['pdf_path'] is None
    assert new['patient_snapshot']['patient_name'].startswith('Updated')
    assert any(line['test_name_snapshot'] == 'Current catalog name' for line in new['result_snapshots'])
    assert report(api) == old
    assert verify(api).json()['status'] == 'VERIFIED'
    link = create(api, '/reports/2/signatories', {'signatory_id': 1, 'signatory_type': 'PATHOLOGIST'})
    assert sign(api, link['report_signatory_id'], 2).status_code == 200
    assert call(api, 'POST', '/reports/2/approve').status_code == 200
    assert verify(api).json()['status'] == 'VERIFIED'
    released = release(api, 2)
    assert verify(api).json()['status'] == 'REVOKED'
    assert verify(api, 2).json()['status'] == 'VERIFIED'
    old = report(api)
    assert old['revoked_at'] == released['released_at']
    assert old['revocation_reason'] == 'Superseded by report ' + released['report_code']
    assert call(api, 'GET', '/reports/1/pdf').content == original
    rows = call(api, 'GET', '/lab-orders/1/reports').json()['items']
    assert [row['version_no'] for row in rows] == [2, 1]
    assert [row['is_current_released'] for row in rows] == [True, False]
    assert call(api, 'POST', '/reports/1/revise', {}).json()['version_no'] == 3
    with api.factory() as db:
        assert {'REPORT_REVISE', 'REPORT_SUPERSEDE'} <= set(db.scalars(select(AuditLog.action)))
        assert all(row.status == 'VERIFIED' for row in db.scalars(select(LabResultItem)))


@pytest.mark.parametrize('status', ['GENERATED', 'APPROVED'])
def test_revision_source_guard(api, status):
    ready(api)
    with api.factory.begin() as db: db.get(LabReport, 1).report_status = status
    assert call(api, 'POST', '/reports/1/revise', {}).status_code == 409


def test_multipage_renderer_repeats_headers_and_preserves_line_order(api):
    ready(api)
    with api.factory() as db:
        from app.services.reporting_service import report_detail
        detail = report_detail(db, 1)
    seed = detail.result_snapshots[0]
    detail.result_snapshots = [seed.model_copy(update={'sort_order': n, 'test_name_snapshot': f'Analyte {n:03}',
        'section_name_snapshot': None}) for n in range(160)]
    data = report_pdf.render_pdf(detail, 'https://verify.example.test/api/v1/verify/'+'x'*43, detail.generated_at)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) >= 4
    texts = [page.extract_text() for page in reader.pages]
    for text in texts:
        if 'Analyte' in text:
            assert 'REFERENCE RANGE' in text and 'TEST' in text
        assert 'Version 1' in text and 'Page ' in text
    combined = '\n'.join(texts)
    assert [combined.index(f'Analyte {n:03}') for n in range(160)] == sorted(combined.index(f'Analyte {n:03}') for n in range(160))


def test_signatures_restricted_and_no_clobber(api, tmp_path, monkeypatch):
    root = tmp_path / 'signatures'
    root.mkdir()
    Image.new('RGB', (120, 35), 'white').save(root / 'signature.png')
    monkeypatch.setattr(settings, 'report_signature_dir', root)
    assert report_pdf.signature_image('signature.png') is not None
    for name in ('../signature.png', '/etc/passwd', 'https://example.test/sign.png', 'missing.png'):
        assert report_pdf.signature_image(name) is None
    (root / 'alias.png').symlink_to(root / 'signature.png')
    assert report_pdf.signature_image('alias.png') is None
    report_storage.publish_pdf(b'first', 'released/test.pdf')
    with pytest.raises(report_storage.ArtifactUnavailable): report_storage.publish_pdf(b'second', 'released/test.pdf')
    assert report_storage.read_private(settings.report_storage_dir, 'released/test.pdf') == b'first'


def test_permissions_idempotent(api):
    with api.factory.begin() as db:
        assert ensure_permissions(db) == []


def test_openapi_public_and_pdf_media():
    from app.main import app
    paths = app.openapi()['paths']
    assert not paths['/api/v1/verify/{verification_token}']['get'].get('security')
    assert 'application/pdf' in paths['/api/v1/reports/{report_id}/pdf']['get']['responses']['200']['content']


@pytest.mark.parametrize('values', [
    {'report_storage_dir': 'relative/path'},
    {'report_storage_dir': str(Path(__file__).resolve().parents[1] / 'frontend/private')},
    {'report_signature_dir': 'relative/signatures'},
    {'public_base_url': 'file:///private'},
    {'public_base_url': 'https://user:pass@example.test'},
    {'public_base_url': 'https://example.test?private=query'},
    {'public_base_url': 'https://example.test/path'},
    {'public_base_url': 'http://example.test', 'environment': 'production'},
])
def test_unsafe_configuration_rejected(values):
    from pydantic import ValidationError
    with pytest.raises(ValidationError): Settings(**values)


def test_generic_template_and_revoked_missing_artifact(api):
    generated(api)
    assigned(api)
    assert sign(api).status_code == 200
    assert approve(api).status_code == 200
    row = release(api)
    assert row['template_id'] is None
    assert call(api, 'POST', '/reports/1/revoke', {'reason': 'Synthetic'}).status_code == 200
    (settings.report_storage_dir / row['pdf_path']).unlink()
    assert verify(api).json()['status'] == 'REVOKED'


def test_unavailable_verification_and_unreleased_artifact(api):
    ready(api)
    assert call(api, 'GET', '/reports/1/verification').status_code == 404
    assert call(api, 'GET', '/reports/1/pdf').status_code == 409
    assert call(api, 'POST', '/reports/1/print', {'copies': 1}).status_code == 409


def test_qr_pixels_match_url_only():
    import qrcode
    url = 'https://verify.example.test/api/v1/verify/' + 'a'*43
    expected = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
    expected.add_data(url)
    expected.make(fit=True)
    actual = Image.open(BytesIO(report_pdf.qr_png(url))).convert('RGB')
    assert actual.tobytes() == expected.make_image().convert('RGB').tobytes()


def test_uncertain_commit_preserves_private_artifact(api):
    from sqlalchemy.exc import OperationalError
    ready(api)
    def lost_ack(session):
        raise OperationalError('COMMIT', {}, Exception(2013, 'Synthetic lost acknowledgement'), connection_invalidated=True)
    event.listen(api.factory, 'before_commit', lost_ack)
    try:
        assert call(api, 'POST', '/reports/1/release').status_code == 503
    finally:
        event.remove(api.factory, 'before_commit', lost_ack)
    assert len(list(settings.report_storage_dir.rglob('*.pdf'))) == 1
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'APPROVED'
        assert count(db, ReportVerification) == 0
