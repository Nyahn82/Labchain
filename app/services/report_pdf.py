"""Generic print-safe report renderer: only snapshots supply clinical content."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PillowImage
import qrcode
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from app.config import settings
from app.services.report_storage import ArtifactUnavailable, read_private

# Bundled TrueType fonts avoid host font/browser dependencies and support Latin accents.
_font_dir = Path(reportlab.__file__).parent / 'fonts'
pdfmetrics.registerFont(TTFont('RHU', str(_font_dir / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('RHU-Bold', str(_font_dir / 'VeraBd.ttf')))


def qr_png(url):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
    code.add_data(url)
    code.make(fit=True)
    output = BytesIO()
    code.make_image(fill_color='black', back_color='white').save(output, format='PNG')
    return output.getvalue()


def signature_image(relative):
    if settings.report_signature_dir is None or not relative:
        return None
    try:
        data = read_private(settings.report_signature_dir, relative)
        with PillowImage.open(BytesIO(data)) as picture:
            if picture.format not in {'PNG', 'JPEG'} or picture.width * picture.height > 4_000_000:
                return None
            picture.load()
            output = BytesIO()
            picture.convert('RGB').save(output, format='PNG')
        img = Image(BytesIO(output.getvalue()))
        img._restrictSize(130, 42)
        img.hAlign = 'LEFT'
        return img
    except (ArtifactUnavailable, OSError, ValueError, PillowImage.DecompressionBombError):
        return None


def render_pdf(report, verification_url, released_at):
    output = BytesIO()
    body = ParagraphStyle('body', fontName='RHU', fontSize=9, leading=13, spaceAfter=4)
    bold = ParagraphStyle('bold', parent=body, fontName='RHU-Bold')
    title = ParagraphStyle('title', parent=bold, fontSize=17, leading=22, spaceAfter=9)
    small = ParagraphStyle('small', parent=body, fontSize=8, leading=11)

    def paragraph(value, style=body):
        # No caller data is interpreted as markup, links, images or expressions.
        return Paragraph(escape(str(value if value is not None else '—')).replace('\n', '<br/>'), style)

    facility, patient, template = report.facility, report.patient_snapshot, report.template
    story = [paragraph(facility.facility_name, title)]
    for value in (facility.facility_type, facility.address, facility.contact_number, facility.email, facility.website):
        if value:
            story.append(paragraph(value, small))
    story += [Spacer(1, 12), paragraph(template.header_title if template and template.header_title else 'LABORATORY REPORT', bold),
        paragraph(f'{report.report_code}  |  Version {report.version_no}', bold),
        paragraph(f'Generated: {report.generated_at:%Y-%m-%d %H:%M} UTC    Released: {released_at:%Y-%m-%d %H:%M} UTC', small),
        Spacer(1, 6), paragraph(f'Patient: {patient.patient_name}', bold),
        paragraph(f'Patient code: {patient.patient_code}    Sex: {patient.sex or "—"}'),
        paragraph(f'Birth date: {patient.birth_date or "—"}    Age at report: {patient.age_at_report if patient.age_at_report is not None else "—"}'),
        paragraph(f'Requesting physician: {patient.physician_name or "—"}'), Spacer(1, 12)]
    if template and template.section_title:
        story.append(paragraph(template.section_title, bold))
    rows = [[paragraph(value, bold) for value in ('TEST', 'FLAG', 'RESULT', 'UNIT', 'REFERENCE RANGE')]]
    commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e6e6e6')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.black), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#cccccc'))]
    section = None
    # Service query already orders by snapshot.sort_order; never consult live catalog.
    for item in report.result_snapshots:
        if item.section_name_snapshot and item.section_name_snapshot != section:
            section = item.section_name_snapshot
            rows.append([paragraph(section, bold), '', '', '', ''])
            commands += [('SPAN', (0, len(rows)-1), (-1, len(rows)-1)),
                         ('BACKGROUND', (0, len(rows)-1), (-1, len(rows)-1), colors.HexColor('#f2f2f2')),
                         ('NOSPLIT', (0, len(rows)-1), (-1, len(rows)))]
        abnormal = item.flag_snapshot not in {None, '', 'NORMAL'}
        rows.append([paragraph(item.test_name_snapshot), paragraph(item.flag_snapshot or '', bold if abnormal else body),
                     paragraph(item.result_value_snapshot, bold if abnormal else body), paragraph(item.unit_snapshot or ''),
                     paragraph(item.reference_range_snapshot or '')])
    table = LongTable(rows, colWidths=[166, 62, 83, 58, 138], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle(commands))
    story += [table, Spacer(1, 14)]
    if template and template.clinical_note:
        story.append(paragraph(template.clinical_note))
    for assignment in report.signatories:
        elements = [paragraph(assignment.staff_name, bold), paragraph(assignment.signatory_type.replace('_', ' '), small)]
        if assignment.profile.license_number_snapshot:
            elements.append(paragraph('License: ' + assignment.profile.license_number_snapshot, small))
        signature = signature_image(assignment.profile.signature_image_path)
        if signature:
            elements.append(signature)
        story += [KeepTogether(elements), Spacer(1, 8)]
    code = Image(BytesIO(qr_png(verification_url)), width=102, height=102)
    code.hAlign = 'LEFT'
    story.append(KeepTogether([code, paragraph('Scan to verify authenticity', small)]))
    if template:
        for note in (template.footer_note, template.medico_legal_note):
            if note:
                story.append(paragraph(note, small))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.gray)
        canvas.line(44, 39, A4[0]-44, 39)
        canvas.setFont('RHU', 7)
        canvas.drawString(44, 27, f'Version {report.version_no} | Authenticity verification available via QR')
        canvas.drawRightString(A4[0]-44, 27, f'Page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=38, bottomMargin=52,
                            title=f'Laboratory report {report.report_code}', author='RHU LabChain')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
