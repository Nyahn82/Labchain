"""Offline PDF layout, historical preservation and presentation migration checks."""
from copy import deepcopy
from io import BytesIO, StringIO
import hashlib
import re
from pathlib import Path

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from PIL import Image
from pypdf import PdfReader
import pytest
import sqlalchemy as sa

from app.config import settings
from app.models import FacilityProfile, LabReport, LabResultItem, Staff, TestCatalog as Catalog, ReportVerification
from app.services import report_pdf, report_presentation
from app.services.reporting_service import report_detail
from test_phase_5b_release import (env, password_hash, lab_api, workflow_api, results_api,
    reports_api, admin, api, ready, release, call, metadata)
from test_phase_2a_migration import config


def pdf_text(data):
    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def detail_for(api):
    with api.factory() as db:
        return report_detail(db, 1)


def test_presentation_freezes_sources_signatories_and_is_private(api):
    with api.factory.begin() as db:
        db.get(Catalog, 1).methodology = 'Synthetic photometry'
        db.get(Staff, 1).position_title = 'Synthetic laboratory scientist'
    ready(api)
    before = detail_for(api)._presentation
    assert before['renderer'] == 2
    assert before['results']['1']['methodology'] == 'Synthetic photometry'
    assert before['signatories']['1']['designation'] == 'Synthetic laboratory scientist'
    with api.factory.begin() as db:
        db.get(Catalog, 1).methodology = 'LIVE_METHOD_MUST_NOT_RENDER'
        db.get(Staff, 1).first_name = 'LIVE_SIGNER_MUST_NOT_RENDER'
        db.get(FacilityProfile, 1).facility_name = 'LIVE_FACILITY_MUST_NOT_RENDER'
    response = call(api, 'GET', '/reports/1')
    assert response.status_code == 200
    assert 'presentation_snapshot' not in response.text and '_presentation' not in response.text
    row = release(api)
    data = (settings.report_storage_dir / row['pdf_path']).read_bytes()
    text = pdf_text(data)
    for expected in ['Synthetic photometry', 'Synthetic laboratory scientist', 'Synthetic RHU',
                     'Synthetic Signer1', 'SYNTH-LIC', 'Electronically signed', 'PDF v2', 'RELEASED', 'Order:', 'Verified:']:
        assert expected in text
    assert 'LIVE_' not in text
    assert detail_for(api)._presentation == before
    assert metadata(api)['report_hash'] == hashlib.sha256(data).hexdigest()


def test_legacy_release_and_download_never_rerender(api, monkeypatch):
    ready(api)
    with api.factory.begin() as db:
        db.get(LabReport, 1).presentation_snapshot = None
    row = release(api)
    data = (settings.report_storage_dir / row['pdf_path']).read_bytes()
    assert 'PDF v2' not in pdf_text(data)
    def forbid(*args): raise AssertionError('A stored report must never be rerendered')
    monkeypatch.setattr(report_pdf, 'render_pdf', forbid)
    assert call(api, 'GET', '/reports/1/pdf').content == data
    with api.factory() as db:
        assert db.scalar(sa.select(ReportVerification.report_hash)) == hashlib.sha256(data).hexdigest()


def test_older_v2_snapshot_without_sample_type_remains_renderable(api):
    ready(api)
    with api.factory.begin() as db:
        row = db.get(LabReport, 1)
        snapshot = deepcopy(row.presentation_snapshot)
        for extra in snapshot['results'].values():
            extra.pop('sample_type', None)
        row.presentation_snapshot = snapshot
    released = release(api)
    data = (settings.report_storage_dir / released['pdf_path']).read_bytes()
    assert 'PDF v2' in pdf_text(data)
    assert 'Sample type:' not in pdf_text(data)
    assert metadata(api)['report_hash'] == hashlib.sha256(data).hexdigest()


def test_mixed_specimens_in_one_group_keep_test_associations(api):
    ready(api)
    detail = detail_for(api)
    seed = detail.result_snapshots[0]
    detail.result_snapshots = [seed.model_copy(update={'result_item_id': i, 'test_name_snapshot': name})
                               for i, name in [(1, 'First test'), (2, 'Second test')]]
    detail._presentation = deepcopy(detail._presentation)
    original = detail._presentation['results']['1']
    detail._presentation['results'] = {
        str(i): {**original, 'specimen_code': f'SP-SYN-{i}', 'sample_type': sample,
                 'collected_at': detail.generated_at.isoformat(), 'received_at': detail.generated_at.isoformat()}
        for i, sample in [(1, 'Whole blood'), (2, 'Serum')]
    }
    data = report_pdf.render_pdf(detail, 'https://verify.example.test/api/v1/verify/'+'x'*43, detail.generated_at)
    text = pdf_text(data)
    for expected in ['Tests: First test', 'Tests: Second test', 'SP-SYN-1', 'SP-SYN-2', 'Sample type: Whole blood', 'Sample type: Serum']:
        assert expected in text
    assert text.count('Sample type:') == 2


def test_revised_report_selects_v2_and_preserves_legacy_bytes(api):
    ready(api)
    with api.factory.begin() as db: db.get(LabReport, 1).presentation_snapshot = None
    original = release(api)
    data = (settings.report_storage_dir / original['pdf_path']).read_bytes()
    response = call(api, 'POST', '/reports/1/revise', {'remarks': 'Synthetic amendment'})
    assert response.status_code == 201
    with api.factory() as db:
        revised = db.get(LabReport, response.json()['report_id'])
        assert revised.presentation_snapshot['renderer'] == 2
        assert revised.presentation_snapshot['signatories'] == {}
        assert revised.supersedes_report_id == 1 and revised.report_status == 'GENERATED'
    assert call(api, 'GET', '/reports/1/pdf').content == data


def test_long_multiline_report_repeats_headers_and_preserves_all_values(api, monkeypatch):
    ready(api)
    detail = detail_for(api)
    seed = detail.result_snapshots[0]
    detail.result_snapshots = [seed.model_copy(update={
        'test_name_snapshot': f'Analyte {i:03} with a long descriptive laboratory test name',
        'result_value_snapshot': 'Positive qualitative finding' if i % 2 else '123.450',
        'reference_range_snapshot': 'Negative qualitative interpretation' if i % 2 else '0.1 - 150.0',
        'section_name_snapshot': 'Synthetic section', 'flag_snapshot': 'HIGH' if i % 2 else 'NORMAL',
    }) for i in range(100)]
    detail._presentation = deepcopy(detail._presentation)
    extra = detail._presentation['results'][str(seed.result_item_id)]
    extra.update(department='Clinical chemistry', panel='Synthetic panel', remarks='Long authorized remark ' * 100)
    detail.remarks = 'REPORT REMARK START ' + ('Multiline report commentary.\n' * 300) + ' REPORT REMARK END'
    from reportlab.platypus import Paragraph
    from reportlab.lib.pagesizes import A4
    draw = Paragraph.drawOn
    boxes = []
    def checked_draw(paragraph, canvas, x, y, _sW=0):
        # Use the renderer's full transform; PDF extraction callbacks do not
        # reliably preserve nested table/paragraph transforms.
        left, bottom = canvas.absolutePosition(x, y)
        assert left >= 44 and left + paragraph.width <= A4[0] - 44 + 0.1
        assert bottom >= 50 and bottom + paragraph.height <= A4[1] - 40
        boxes.append((canvas.getPageNumber(), left, bottom, paragraph.width, paragraph.height))
        return draw(paragraph, canvas, x, y, _sW)
    monkeypatch.setattr(Paragraph, 'drawOn', checked_draw)
    data = report_pdf.render_pdf(detail, 'https://verify.example.test/api/v1/verify/'+'x'*43, detail.generated_at)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) > 4
    texts = [page.extract_text() for page in reader.pages]
    combined = '\n'.join(texts)
    for i in range(100): assert f'Analyte {i:03}' in combined
    normalized = ' '.join(combined.split())
    assert 'REPORT REMARK END' in normalized and 'Positive qualitative finding' in normalized
    for text in texts:
        assert 'Page ' in text and 'PDF v2' in text
        if '123.450' in text or 'Positive qualitative' in ' '.join(text.split()):
            assert 'REFERENCE RANGE' in text and 'Clinical chemistry' in text and 'Synthetic panel' in text
    for text in texts[1:]:
        assert f'Patient code: {detail.patient_snapshot.patient_code}' in text
    assert not re.search(r'\d{2}:\d{2}:\d{2}\.\d+', combined)
    assert len(boxes) > 500
    # Distinct text boxes may share a row but cannot overlap in both axes.
    for i, (page, x, y, width, height) in enumerate(boxes):
        for other_page, ox, oy, ow, oh in boxes[i+1:]:
            if page != other_page: continue
            overlap_x = min(x+width, ox+ow) - max(x, ox)
            overlap_y = min(y+height, oy+oh) - max(y, oy)
            assert overlap_x <= 0.1 or overlap_y <= 0.1


def test_invalid_presentation_fails_release_without_artifact_or_verification(api):
    ready(api)
    with api.factory.begin() as db:
        db.get(LabReport, 1).presentation_snapshot = {'renderer': 99}
    response = call(api, 'POST', '/reports/1/release')
    assert response.status_code == 503 and '99' not in response.text
    with api.factory() as db:
        assert db.get(LabReport, 1).report_status == 'APPROVED'
        assert list(db.scalars(sa.select(ReportVerification))) == []
    assert not list(settings.report_storage_dir.rglob('*.pdf'))


def test_logo_only_uses_safe_private_assets_and_is_frozen(api, tmp_path, monkeypatch):
    root = tmp_path / 'logos'
    root.mkdir()
    Image.new('RGB', (120, 60), 'navy').save(root / 'facility.png')
    monkeypatch.setattr(settings, 'report_logo_dir', root)
    for path in ['../outside.png', '/etc/passwd', 'https://example.invalid/logo.png']:
        assert report_presentation.logo_snapshot(path) is None
    (root / 'alias.png').symlink_to(root / 'facility.png')
    assert report_presentation.logo_snapshot('alias.png') is None
    with api.factory.begin() as db: db.get(FacilityProfile, 1).logo_path = 'facility.png'
    ready(api)
    (root / 'facility.png').unlink()
    row = release(api)
    reader = PdfReader(BytesIO((settings.report_storage_dir / row['pdf_path']).read_bytes()))
    assert sum(len(page.images) for page in reader.pages) >= 2  # Captured logo and QR.


def test_presentation_migration_preserves_existing_rows_offline_and_sqlite():
    scripts = ScriptDirectory.from_config(config())
    migration = scripts.get_revision('20261018_01').module
    assert scripts.get_heads() == ['20261021_01']
    assert migration.down_revision == '20261015_01'
    output = StringIO()
    command.upgrade(config(output), '20261015_01:20261018_01', sql=True)
    sql = output.getvalue()
    assert 'ADD COLUMN presentation_snapshot JSON' in sql
    assert 'UPDATE lab_report' not in sql and 'DROP TABLE' not in sql
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE lab_report (report_id INTEGER PRIMARY KEY, report_code TEXT, pdf_path TEXT)'))
        connection.execute(sa.text("INSERT INTO lab_report VALUES (1, 'LEGACY', 'stored.pdf')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            with pytest.raises(RuntimeError, match='preserved'): migration.downgrade()
        assert connection.execute(sa.text('SELECT * FROM lab_report')).one() == (1, 'LEGACY', 'stored.pdf', None)
    engine.dispose()
    assert LabReport.__table__.c.presentation_snapshot.nullable
    assert isinstance(LabReport.__table__.c.presentation_snapshot.type, sa.JSON)


@pytest.mark.parametrize('field', ['presentation_snapshot', '_presentation'])
def test_renderer_context_cannot_be_submitted_by_clients(api, field):
    response = call(api, 'POST', '/lab-orders/1/reports', {field: {'renderer': 1}})
    assert response.status_code == 422
    with api.factory() as db:
        assert list(db.scalars(sa.select(LabReport))) == []


@pytest.mark.parametrize('count', [1, 10])
def test_compact_blue_report_keeps_qr_and_signatures_on_one_a4_page(api, monkeypatch, count):
    """Short panels retain their warnings, upper-right QR and signed final section."""
    ready(api)
    detail = detail_for(api)
    detail._presentation = deepcopy(detail._presentation)
    context = detail._presentation
    context['template'] = {
        'header_title': 'LABORATORY REPORT — SIMULATION ONLY',
        'footer_note': 'NOT FOR CLINICAL USE — Fictional training data.',
    }
    seed = detail.result_snapshots[0]
    detail.result_snapshots = [seed.model_copy(update={
        'result_item_id': i, 'test_name_snapshot': f'Synthetic examination {i:02}',
        'section_name_snapshot': None, 'reference_range_snapshot': None,
    }) for i in range(1, count + 1)]
    context['results'] = {str(i): {
        'department': 'Hematology', 'panel': 'Synthetic panel',
        'specimen_code': 'SP-SYNTHETIC', 'sample_type': 'Whole blood',
        'collected_at': detail.generated_at.isoformat(), 'received_at': detail.generated_at.isoformat(),
    } for i in range(1, count + 1)}
    detail.remarks = 'SIMULATION ONLY — No actual laboratory examination performed.'
    from reportlab.platypus import Image as PdfImage, Paragraph
    from reportlab.lib.pagesizes import A4
    image_draw, paragraph_draw = PdfImage.drawOn, Paragraph.drawOn
    images, signature_positions = [], []

    def capture_image(image, canvas, x, y, _sW=0):
        images.append((canvas.getPageNumber(), *canvas.absolutePosition(x, y), image.drawWidth, image.drawHeight))
        return image_draw(image, canvas, x, y, _sW)

    def capture_signature(paragraph, canvas, x, y, _sW=0):
        if paragraph.getPlainText().startswith('Electronically signed:'):
            signature_positions.append(canvas.absolutePosition(x, y)[1])
        return paragraph_draw(paragraph, canvas, x, y, _sW)

    monkeypatch.setattr(PdfImage, 'drawOn', capture_image)
    monkeypatch.setattr(Paragraph, 'drawOn', capture_signature)
    data = report_pdf.render_pdf(detail, 'https://verify.example.test/api/v1/verify/' + 'x' * 43, detail.generated_at)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(A4[0], abs=.01)
    assert float(reader.pages[0].mediabox.height) == pytest.approx(A4[1], abs=.01)
    text = ' '.join(pdf_text(data).split())
    for expected in ['SIMULATION ONLY', 'NOT FOR CLINICAL USE', 'Hematology / Synthetic panel',
                     'REFERENCE RANGE', 'Specimen: SP-SYNTHETIC', 'Electronically signed:', f'Synthetic examination {count:02}']:
        assert expected in text
    assert 'Not configured' not in text  # Missing reference ranges are not invented.
    assert len(images) == 1  # No invented facility logo or signature image.
    page, x, y, w, h = images[0]
    assert page == 1 and x > A4[0] / 2 and y > A4[1] / 2
    assert x + w < A4[0] - 44 and y + h < A4[1] - 40
    assert signature_positions and all(50 < y < 180 for y in signature_positions)


def test_many_signatories_and_long_footer_continue_without_losing_stored_text(api):
    ready(api)
    detail = detail_for(api)
    detail._presentation = deepcopy(detail._presentation)
    seed = detail.signatories[0]
    captured = detail._presentation['signatories']['1']
    detail.signatories = [seed.model_copy(update={'report_signatory_id': i}) for i in range(1, 31)]
    detail._presentation['signatories'] = {
        str(i): {**captured, 'name': f'Synthetic authorized signer {i:02}'} for i in range(1, 31)
    }
    detail._presentation['template']['footer_note'] = ('Recorded footer text.\n' * 150) + 'FOOTER END'
    data = report_pdf.render_pdf(detail, 'https://verify.example.test/api/v1/verify/' + 'x' * 43, detail.generated_at)
    text = pdf_text(data)
    assert len(PdfReader(BytesIO(data)).pages) > 1
    assert 'FOOTER END' in text
    for i in range(1, 31):
        assert f'Synthetic authorized signer {i:02}' in text


def test_v2_download_after_layout_update_uses_existing_bytes(api, monkeypatch):
    ready(api)
    row = release(api)
    original = (settings.report_storage_dir / row['pdf_path']).read_bytes()
    original_hash = metadata(api)['report_hash']

    def forbid(*args):
        raise AssertionError('Layout updates must not regenerate released PDFs')

    monkeypatch.setattr(report_pdf, 'render_pdf', forbid)
    assert call(api, 'GET', '/reports/1/pdf').content == original
    assert call(api, 'POST', '/reports/1/print', {'copies': 1}).content == original
    assert metadata(api)['report_hash'] == original_hash == hashlib.sha256(original).hexdigest()
