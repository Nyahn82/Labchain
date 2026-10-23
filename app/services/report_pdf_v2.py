"""Print-friendly PDF v2, exclusively from captured report presentation and snapshots."""
import base64
from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


def render(report, verification_url, released_at, context):
    from app.services.report_pdf import qr_png
    output = BytesIO()
    ink = colors.HexColor('#183344')
    blue = colors.HexColor('#104b6a')
    light = colors.HexColor('#edf4f8')
    rule = colors.HexColor('#cbdce5')
    width = A4[0] - 100
    body = ParagraphStyle('v2body', fontName='RHU', fontSize=8, leading=11, textColor=ink, spaceAfter=0)
    bold = ParagraphStyle('v2bold', parent=body, fontName='RHU-Bold')
    small = ParagraphStyle('v2small', parent=body, fontSize=7, leading=10)
    heading = ParagraphStyle('v2heading', parent=bold, fontSize=12, leading=16, textColor=blue)
    letterhead = ParagraphStyle('v2letterhead', parent=bold, fontSize=16, leading=20, textColor=colors.white)
    white = ParagraphStyle('v2white', parent=small, textColor=colors.white)
    group_heading = ParagraphStyle('v2group', parent=bold, textColor=colors.white)
    column_heading = ParagraphStyle('v2column', parent=bold, fontSize=7, leading=10, textColor=blue)
    note_heading = ParagraphStyle('v2noteheading', parent=bold, textColor=blue, spaceBefore=7, spaceAfter=3, keepWithNext=True)
    result_style = ParagraphStyle('v2result', parent=body, alignment=2)
    abnormal_style = ParagraphStyle('v2abnormal', parent=result_style, fontName='RHU-Bold')
    centered = ParagraphStyle('v2centered', parent=small, alignment=1)
    centered_bold = ParagraphStyle('v2centeredbold', parent=bold, alignment=1)
    flag_style = ParagraphStyle('v2flag', parent=body, alignment=1)
    flag_bold = ParagraphStyle('v2flagbold', parent=bold, alignment=1)
    result_heading = ParagraphStyle('v2resultheading', parent=column_heading, alignment=2)
    flag_heading = ParagraphStyle('v2flagheading', parent=column_heading, alignment=1)
    qr_caption = ParagraphStyle('v2qr', parent=small, alignment=1, textColor=blue)

    def p(value, style=body):
        return Paragraph(escape(str(value if value is not None else '—')).replace('\n', '<br/>'), style)

    def date(value):
        if not value:
            return '—'
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime('%d %b %Y %H:%M UTC')

    def table(rows, widths, commands=(), **kwargs):
        result = LongTable(rows, colWidths=widths, hAlign='LEFT', splitInRow=1, **kwargs)
        result.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            *commands,
        ]))
        return result

    facility = context['facility']
    template = context.get('template') or {}
    patient = report.patient_snapshot
    # The preview's illustrative branding is not report data. Only captured,
    # configured facility details and logo may appear in this letterhead.
    identity = [p(facility['facility_name'], letterhead)]
    if facility.get('facility_type'):
        identity.append(p(facility['facility_type'], white))
    if facility.get('address'):
        identity.append(p(facility['address'], white))
    contact = '  |  '.join(facility[key] for key in ('contact_number', 'email', 'website') if facility.get(key))
    if contact:
        identity.append(p(contact, white))
    header_cells = [identity, [p('LABORATORY REPORT', white), Spacer(1, 5), p(f'VERSION {report.version_no}', white)]]
    header_widths = [width - 120, 120]
    if context.get('logo_png'):
        logo = Image(BytesIO(base64.b64decode(context['logo_png'], validate=True)))
        logo._restrictSize(56, 48)
        logo.hAlign = 'LEFT'
        header_cells.insert(0, logo)
        header_widths = [72, width - 192, 120]
    story = [table([header_cells], header_widths, [
        ('BACKGROUND', (0, 0), (-1, -1), blue),
        ('TOPPADDING', (0, 0), (-1, -1), 12), ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 3, colors.HexColor('#2783a1')),
    ]), Spacer(1, 8), p(template.get('header_title') or 'LABORATORY REPORT', heading), Spacer(1, 8)]
    if report.supersedes_report_id is not None:
        story += [p(f'Amended report — supersedes report #{report.supersedes_report_id}. Previous versions remain in the record.', small), Spacer(1, 6)]

    summary_width = width - 114
    summary = table([
        [p(f'Patient: {patient.patient_name}', bold), p(f'Patient code: {patient.patient_code}')],
        [p(f'Birth date: {patient.birth_date or "—"}'), p(f'Sex: {patient.sex or "—"}  |  Age at report: {patient.age_at_report if patient.age_at_report is not None else "—"}')],
        [p(f'Requesting physician: {patient.physician_name or "—"}'), p(f'Priority: {context["priority"]}')],
        [p(f'Order: {context["order_code"]}', small), ''],
    ], [summary_width * .60, summary_width * .40], [('SPAN', (0, 3), (-1, 3))])
    code = Image(BytesIO(qr_png(verification_url)), width=90, height=90)
    code.hAlign = 'CENTER'
    info = table([[summary, [code, p('Scan to verify authenticity', qr_caption)]]], [summary_width, 114], [
        ('BACKGROUND', (0, 0), (-1, -1), light), ('BOX', (0, 0), (-1, -1), .6, rule),
        ('LINEBEFORE', (1, 0), (1, 0), .6, rule),
        ('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (0, 0), (0, 0), 0),
    ])
    story += [info, Spacer(1, 8), p(f'{report.report_code}  |  Version {report.version_no}  |  RELEASED', bold), Spacer(1, 4)]
    story += [table([
        [p(f'Requested: {date(context["order_date"])}', small), p(f'Generated: {date(report.generated_at.isoformat())}', small)],
        [p(f'Approved: {date(report.approved_at.isoformat() if report.approved_at else None)}', small), p(f'Released: {date(released_at.isoformat())}', small)],
    ], [width / 2, width / 2], [('LINEBELOW', (0, -1), (-1, -1), .6, rule),
        ('BACKGROUND', (0, 0), (-1, -1), light), ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]), Spacer(1, 8)]
    if template.get('section_title'):
        story += [p(template['section_title'], note_heading), Spacer(1, 3)]

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
        rows = [[p(label, group_heading), '', '', '', ''],
                [p(value, style) for value, style in zip(
                    ('TEST', 'FLAG', 'RESULT', 'UNIT', 'REFERENCE RANGE'),
                    (column_heading, flag_heading, result_heading, column_heading, column_heading))]]
        commands = [('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 0), blue), ('BACKGROUND', (0, 1), (-1, 1), light),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('LINEBELOW', (0, 1), (-1, 1), .7, ink),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
        details = []
        specimens = {}
        for line, extra in lines:
            if extra.get('specimen_code'):
                specimen = tuple(extra.get(field) for field in ('specimen_code', 'sample_type', 'collected_at', 'received_at'))
                specimens.setdefault(specimen, []).append(line.test_name_snapshot)
        specimen_details = []
        for (code, sample, collected, received), test_names in specimens.items():
            specimen_rows = [[p(f'Specimen: {code}', small), p(f'Sample type: {sample}', small) if sample else '']]
            if collected or received:
                specimen_rows.append([p(f'Collected: {date(collected)}', small) if collected else '',
                                      p(f'Received: {date(received)}', small) if received else ''])
            specimen_details += [p('Specimen details', note_heading), table(specimen_rows, [width / 2, width / 2], [
                ('BACKGROUND', (0, 0), (-1, -1), light), ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2)])]
            if len(test_names) != len(lines):
                specimen_details.append(p('Tests: ' + '; '.join(test_names), small))
        for line, extra in lines:
            abnormal = line.flag_snapshot not in (None, '', 'NORMAL')
            rows.append([p(line.test_name_snapshot), p(line.flag_snapshot or '', flag_bold if abnormal else flag_style),
                p(line.result_value_snapshot, abnormal_style if abnormal else result_style),
                p(line.unit_snapshot or ''), p(line.reference_range_snapshot or '')])
            notes = []
            notes.extend(extra.get('structured_results') or [])
            for field, title in [('methodology', 'Method'), ('remarks', 'Remarks')]:
                if extra.get(field): notes.append(f'{title}: {extra[field]}')
            for field, title in [('verified_at', 'Verified')]:
                if extra.get(field): notes.append(f'{title}: {date(extra[field])}')
            if notes:
                details += [p(line.test_name_snapshot + ' — test details', note_heading), p('\n'.join(notes), small)]
            commands.append(('LINEBELOW', (0, len(rows)-1), (-1, len(rows)-1), .25, colors.HexColor('#bcc6cc')))
        results_table = LongTable(rows, colWidths=[width*.30, width*.12, width*.18, width*.13, width*.27],
                          repeatRows=2, splitInRow=1, hAlign='LEFT')
        results_table.setStyle(TableStyle(commands))
        story += [results_table, Spacer(1, 3), *specimen_details, *details, Spacer(1, 8)]
    story.append(p('Flags are supplied by the laboratory workflow. Bold flags and results identify recorded abnormal findings.', small))
    if report.remarks:
        story += [p('Report remarks', note_heading),
                  table([[p(report.remarks)]], [width], [('BACKGROUND', (0, 0), (-1, -1), light)])]
    if template.get('clinical_note'):
        story += [Spacer(1, 5), p(template['clinical_note'])]
    story.append(Spacer(1, 6))
    # Signatures follow the notes without stretching the page. A single signer
    # is centered across the report; multiple signers retain two columns.
    signatures = [[p('Authorized signatories', note_heading), '']]
    signature_commands = [('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('SPAN', (0, 0), (-1, 0)), ('LINEABOVE', (0, 0), (-1, 0), .7, rule)]
    single_signer = len(report.signatories) == 1
    name_style = centered_bold if single_signer else bold
    signing_style = centered if single_signer else small
    cells = []
    for assignment in report.signatories:
        captured = context['signatories'].get(str(assignment.report_signatory_id))
        if assignment.signed_at is None or captured is None:
            raise ValueError('Signed presentation is incomplete')
        elements = [p(captured['name'], name_style), p(captured['capacity'].replace('_', ' '), signing_style)]
        if captured.get('designation'): elements.append(p(captured['designation'], signing_style))
        if captured.get('license'): elements.append(p('License: ' + captured['license'], signing_style))
        elements.append(p('Electronically signed: ' + date(captured['signed_at']), signing_style))
        cells.append(elements)
        if len(cells) == 2:
            signatures.append(cells)
            cells = []
    if cells:
        signatures.append([*cells, ''])
        if single_signer:
            signature_commands.append(('SPAN', (0, 1), (-1, 1)))
    for key in ('footer_note', 'medico_legal_note'):
        if template.get(key):
            signatures.append([p(template[key], centered if single_signer else small), ''])
            signature_commands.append(('SPAN', (0, len(signatures)-1), (-1, len(signatures)-1)))
    story.append(table(signatures, [width / 2, width / 2], signature_commands, repeatRows=1))

    def furniture(canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(blue)
            canvas.setFont('RHU-Bold', 7)
            canvas.drawString(50, A4[1]-26, f'{report.report_code} | Version {report.version_no}')
            canvas.drawRightString(A4[0]-50, A4[1]-26, 'LABORATORY REPORT')
            canvas.setFont('RHU', 7)
            canvas.drawString(50, A4[1]-39, f'Patient code: {patient.patient_code}')
        canvas.setFillColor(blue)
        canvas.rect(50, 20, width, 22, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont('RHU', 7)
        canvas.drawString(58, 28, f'PDF v2 | Version {report.version_no} | Verify authenticity using the QR')
        canvas.drawRightString(A4[0]-58, 28, f'Page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=44, bottomMargin=44, title=f'Laboratory report {report.report_code}', author=facility['facility_name'])
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return output.getvalue()
