"""Print-friendly PDF v2, exclusively from captured report presentation and snapshots."""
import base64
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


def render(report, verification_url, released_at, context):
    from app.services.report_pdf import qr_png
    output = BytesIO()
    ink = colors.HexColor('#183344')
    light = colors.HexColor('#edf1f3')
    width = A4[0] - 100
    body = ParagraphStyle('v2body', fontName='RHU', fontSize=8.5, leading=12, spaceAfter=5)
    bold = ParagraphStyle('v2bold', parent=body, fontName='RHU-Bold')
    small = ParagraphStyle('v2small', parent=body, fontSize=7, leading=10)
    heading = ParagraphStyle('v2heading', parent=bold, fontSize=17, leading=22, textColor=ink, spaceAfter=9)
    note_heading = ParagraphStyle('v2noteheading', parent=bold, keepWithNext=True)
    result_style = ParagraphStyle('v2result', parent=body, alignment=2)
    abnormal_style = ParagraphStyle('v2abnormal', parent=result_style, fontName='RHU-Bold')

    def p(value, style=body):
        return Paragraph(escape(str(value if value is not None else '—')).replace('\n', '<br/>'), style)

    def date(value):
        return str(value).replace('T', ' ') + ' UTC' if value else '—'

    facility = context['facility']
    template = context.get('template') or {}
    patient = report.patient_snapshot
    story = []
    if context.get('logo_png'):
        logo = Image(BytesIO(base64.b64decode(context['logo_png'], validate=True)))
        logo._restrictSize(110, 52)
        logo.hAlign = 'LEFT'
        story.append(logo)
    story.append(p(facility['facility_name'], heading))
    for key in ('facility_type', 'address', 'contact_number', 'email', 'website'):
        if facility.get(key): story.append(p(facility[key], small))
    story += [Spacer(1, 10), p(template.get('header_title') or 'LABORATORY REPORT', heading),
              p(f'{report.report_code}  |  Version {report.version_no}  |  RELEASED', bold)]
    if report.supersedes_report_id is not None:
        story.append(p(f'Amended report — supersedes report #{report.supersedes_report_id}. Previous versions remain in the record.', small))
    summary = [
        [p(f'Patient: {patient.patient_name}', bold), p(f'Patient code: {patient.patient_code}')],
        [p(f'Birth date: {patient.birth_date or "—"}'), p(f'Sex: {patient.sex or "—"}  |  Age at report: {patient.age_at_report if patient.age_at_report is not None else "—"}')],
        [p(f'Order: {context["order_code"]}'), p(f'Priority: {context["priority"]}')],
        [p(f'Requesting physician: {patient.physician_name or "—"}'), p(f'Requested: {date(context["order_date"])}', small)],
    ]
    info = LongTable(summary, colWidths=[width * .55, width * .45], hAlign='LEFT', splitInRow=1)
    info.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), light), ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story += [Spacer(1, 8), info, Spacer(1, 10),
        p(f'Generated: {date(report.generated_at.isoformat())}', small),
        p(f'Approved: {date(report.approved_at.isoformat() if report.approved_at else None)}', small),
        p(f'Released: {date(released_at.isoformat())}', small), Spacer(1, 8)]
    if template.get('section_title'): story.append(p(template['section_title'], bold))

    # Keep the established clinical snapshot order; repeat group and column
    # headers across page breaks. Long notes use independently splittable paragraphs.
    groups = []
    for line in report.result_snapshots:
        extra = context['results'].get(str(line.result_item_id), {})
        key = (extra.get('department'), extra.get('panel'), line.section_name_snapshot)
        if not groups or groups[-1][0] != key: groups.append((key, []))
        groups[-1][1].append((line, extra))
    for key, lines in groups:
        label = ' / '.join(dict.fromkeys(part for part in key if part)) or 'Laboratory results'
        rows = [[p(label, bold), '', '', '', ''],
                [p(value, bold) for value in ('TEST', 'FLAG', 'RESULT', 'UNIT', 'REFERENCE RANGE')]]
        commands = [('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 1), light),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 1), (-1, 1), .7, ink),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]
        details = []
        for line, extra in lines:
            abnormal = line.flag_snapshot not in (None, '', 'NORMAL')
            rows.append([p(line.test_name_snapshot), p(line.flag_snapshot or '', bold if abnormal else body),
                p(line.result_value_snapshot, abnormal_style if abnormal else result_style),
                p(line.unit_snapshot or ''), p(line.reference_range_snapshot or '')])
            notes = []
            for field, title in [('methodology', 'Method'), ('remarks', 'Remarks'),
                                 ('specimen_code', 'Specimen')]:
                if extra.get(field): notes.append(f'{title}: {extra[field]}')
            for field, title in [('collected_at', 'Collected'), ('received_at', 'Received'), ('verified_at', 'Verified')]:
                if extra.get(field): notes.append(f'{title}: {date(extra[field])}')
            if notes:
                details += [p(line.test_name_snapshot + ' — specimen and test details', note_heading), p('\n'.join(notes), small)]
            commands.append(('LINEBELOW', (0, len(rows)-1), (-1, len(rows)-1), .25, colors.HexColor('#bcc6cc')))
        table = LongTable(rows, colWidths=[width*.30, width*.13, width*.18, width*.12, width*.27],
                          repeatRows=2, splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle(commands))
        story += [table, Spacer(1, 10), *details, Spacer(1, 6)]
    story.append(p('Flags are supplied by the laboratory workflow. Bold flags and results identify recorded abnormal findings.', small))
    if report.remarks: story += [p('Report remarks', bold), p(report.remarks)]
    if template.get('clinical_note'): story.append(p(template['clinical_note']))
    story += [Spacer(1, 12), p('Authorized signatories', bold)]
    for assignment in report.signatories:
        captured = context['signatories'].get(str(assignment.report_signatory_id))
        if assignment.signed_at is None or captured is None:
            raise ValueError('Signed presentation is incomplete')
        elements = [p(captured['name'], bold), p(captured['capacity'].replace('_', ' '), small)]
        if captured.get('designation'): elements.append(p(captured['designation'], small))
        if captured.get('license'): elements.append(p('License: ' + captured['license'], small))
        elements.append(p('Electronically signed: ' + date(captured['signed_at']), small))
        story += [KeepTogether(elements), Spacer(1, 8)]
    code = Image(BytesIO(qr_png(verification_url)), width=90, height=90)
    code.hAlign = 'LEFT'
    story += [KeepTogether([code, p('Scan to verify authenticity', small),
        p('Check the current status before relying on this report. The QR contains only the verification URL.', small)])]
    for key in ('footer_note', 'medico_legal_note'):
        if template.get(key): story.append(p(template[key], small))

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(ink)
        canvas.setFont('RHU', 7)
        canvas.drawString(50, A4[1]-26, f'{report.report_code} | Version {report.version_no}')
        canvas.drawRightString(A4[0]-50, A4[1]-26, 'LABORATORY REPORT')
        canvas.setStrokeColor(colors.HexColor('#bcc6cc'))
        canvas.line(50, 39, A4[0]-50, 39)
        canvas.drawString(50, 27, f'PDF v2 | Version {report.version_no} | Verify authenticity using the QR')
        canvas.drawRightString(A4[0]-50, 27, f'Page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=44, bottomMargin=52, title=f'Laboratory report {report.report_code}', author=facility['facility_name'])
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return output.getvalue()
