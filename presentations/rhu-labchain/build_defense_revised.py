"""Build editable PowerPoint plus a matching vector PDF and speaker notes.
Run with python-pptx, Pillow, reportlab and pymupdf installed.
"""
from pathlib import Path
import math
import textwrap
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'RHU_LabChain_Defense_Revised'
W,H = 960,540
NAVY='112B3C'; INK='173446'; TEAL='087F8C'; MINT='59D8BE'; BLUE='3876B7'
BG='F4F7F9'; WHITE='FFFFFF'; MUTED='557080'; LINE='D7E2E8'; PALE='E5F4F1'
AMBER='A76910'; AMBER_BG='FFF3DD'; RED='AF4350'; RED_BG='FBECEF'
FONT='DejaVu Sans'
for name,file in [('regular','DejaVuSans.ttf'),('bold','DejaVuSans-Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+file))

prs=Presentation(); prs.slide_width=Inches(13.333333); prs.slide_height=Inches(7.5)
prs.core_properties.title='RHU LabChain | Laboratory Records and Blockchain Verification'
prs.core_properties.subject='System workflow, report anchoring, four-peer verification, and concise survey findings'
prs.core_properties.author='RHU LabChain'
pdf=canvas.Canvas(str(OUT.with_suffix('.pdf')),pagesize=(W,H))
pdf.setTitle(prs.core_properties.title)
all_notes=[]; bounds=[]; slide=None; count=0; authored=[]

def color(h): return RGBColor.from_string(h)
def pc(h): return tuple(int(h[i:i+2],16)/255 for i in (0,2,4))
def rect(x,y,w,h,fill=WHITE,stroke=None,r=0):
    s=slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if r else MSO_SHAPE.RECTANGLE,Pt(x),Pt(y),Pt(w),Pt(h))
    s.fill.solid(); s.fill.fore_color.rgb=color(fill)
    if stroke: s.line.color.rgb=color(stroke); s.line.width=Pt(.8)
    else: s.line.fill.background()
    if r:
        try: s.adjustments[0]=.12
        except Exception: pass
    pdf.setFillColorRGB(*pc(fill))
    pdf.setStrokeColorRGB(*pc(stroke or fill)); pdf.setLineWidth(.8)
    if r: pdf.roundRect(x,H-y-h,w,h,r,fill=1,stroke=bool(stroke))
    else: pdf.rect(x,H-y-h,w,h,fill=1,stroke=bool(stroke))
    return s

def line(x1,y1,x2,y2,c=TEAL,width=2,arrow=False):
    s=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Pt(x1),Pt(y1),Pt(x2),Pt(y2))
    s.line.color.rgb=color(c); s.line.width=Pt(width)
    pdf.setStrokeColorRGB(*pc(c)); pdf.setLineWidth(width); pdf.line(x1,H-y1,x2,H-y2)
    if arrow:
        a=math.atan2(y2-y1,x2-x1)
        for d in [-.5,.5]:
            xx=x2-7*math.cos(a+d); yy=y2-7*math.sin(a+d)
            line(xx,yy,x2,y2,c,width)

def wrap(t,w,size,bold=False):
    out=[]; f='bold' if bold else 'regular'
    for para in t.split('\n'):
        if not para: out.append(''); continue
        cur=''
        for word in para.split():
            nxt=(cur+' '+word).strip()
            if pdfmetrics.stringWidth(nxt,f,size)>w and cur:
                out.append(cur); cur=word
            else: cur=nxt
        out.append(cur)
    return out

def text(t,x,y,w,size=18,c=INK,bold=False,h=None,leading=1.28):
    ls=wrap(t,w,size,bold); lh=size*leading
    authored.append((count, ls, size))
    needed=len(ls)*lh+3
    if h and needed>h+1: raise ValueError(f'Slide {count}: text overflow {t[:55]} {needed:.1f}>{h}')
    height=h or needed
    bounds.append((count,x,y,w,height,t[:60]))
    box=slide.shapes.add_textbox(Pt(x),Pt(y),Pt(w),Pt(height))
    tf=box.text_frame; tf.clear(); tf.word_wrap=False
    tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
    tf.vertical_anchor=MSO_ANCHOR.TOP
    for i,ln in enumerate(ls):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.text=ln; p.font.name=FONT; p.font.size=Pt(size); p.font.bold=bold; p.font.color.rgb=color(c)
        p.space_before=Pt(0); p.space_after=Pt(0); p.line_spacing=Pt(lh)
    pdf.setFont('bold' if bold else 'regular',size); pdf.setFillColorRGB(*pc(c))
    for i,ln in enumerate(ls): pdf.drawString(x,H-y-size*.93-i*lh,ln)
    return needed

def pic(name,x,y,w,h):
    path=ROOT/'assets'/f'{name}.png'; im=Image.open(path); iw,ih=im.size
    scale=min(w/iw,h/ih); ww=iw*scale; hh=ih*scale; xx=x+(w-ww)/2; yy=y+(h-hh)/2
    slide.shapes.add_picture(str(path),Pt(xx),Pt(yy),width=Pt(ww),height=Pt(hh))
    pdf.drawImage(str(path),xx,H-yy-hh,ww,hh,mask='auto')

def begin(title,notes,source,dark=False):
    global slide,count
    if count: pdf.showPage()
    count+=1
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    rect(0,0,W,H,NAVY if dark else BG)
    rect(48,28,70,5,MINT if dark else TEAL)
    if title: text(title,48,52,864,36,WHITE if dark else NAVY,True,h=57)
    line(48,512,912,512,'355160' if dark else LINE,1)
    full=f'PRESENTATION CUE — approximately 45–60 seconds.\n\n{notes}\n\nSOURCE: {source}'
    slide.notes_slide.notes_text_frame.text=full
    all_notes.append((count,title or 'Title',notes,source))

def rows(items,flow=False,colors=None):
    for i,t in enumerate(items):
        y=147+i*69
        accent=colors[i] if colors else TEAL
        rect(48,y,864,57,WHITE,LINE,8)
        rect(48,y,5,57,accent)
        text(t,70,y+12,818,24,accent if colors else INK,h=36)
        if flow and i<len(items)-1: line(480,y+59,480,y+67,TEAL,1.6,True)

# 01 — Title. Official study title, with no invented researcher names.
begin('',
      'Introduce RHU LabChain using the full study title. The setting is the Rural Health Unit of M’lang, North Cotabato. This is an academic laboratory-record and report-verification prototype using synthetic reports. State the main question: after a laboratory report is released, how can another person check its document integrity and current status? Explain that the presentation emphasizes the system process and blockchain, followed by concise technical observations and one survey slide. This deck adapts the guide’s machine-learning sections to a system-development study; there is no predictive model or model-training dataset.',
      'papers.pdf, pp. 3–5, 18–21; Defense_PPT-Gudelines.pdf, pp. 1–2.',True)
text('RHU LabChain',48,66,864,30,MINT,True)
text('Block-Chain Powered\nLaboratory Records\nand Verification System',48,153,864,42,WHITE,True,h=173)
text('RHU of M’lang, North Cotabato',48,404,864,24,'D4E5EC')
for x in [700,765,830]:
    rect(x,61,40,40,'234857',None,5)
line(741,81,763,81,MINT,2,True); line(806,81,828,81,MINT,2,True)

# 02 — Explicit problem statement.
begin('Problem statement',
      'The paper identifies the difficulty of retrieving and tracking paper-based laboratory records and the need to protect sensitive findings. Issued reports also need a way to verify integrity and distinguish current versions from withdrawn or replaced versions. These are the motivations for the prototype, not measured findings that every existing RHU system has the same weaknesses. Relate the problem to the research questions: security and integrity, usability and efficiency, and user acceptance and trust. No controlled paper-versus-system time comparison was supplied, so do not claim a numerical efficiency improvement.',
      'papers.pdf, pp. 1–5, 42, 49.')
rows(['Paper records complicate retrieval and tracking.',
      'Released reports need reliable integrity checks.',
      'Sensitive findings require controlled access.',
      'Replaced reports must remain clearly identifiable.'])

# 03 — A study-specific gap, without claiming universal research novelty.
begin('Research gap',
      'Frame the gap as a practical integration need in this study. Digitization can improve record organization, but it does not by itself provide the report-event evidence implemented here. The study brings together controlled laboratory processing, issued PDF versions and later integrity and lifecycle verification. The contribution is this integration for the stated RHU prototype setting. Avoid claiming that no prior blockchain healthcare system exists: the literature review describes several. This is a synthesis of the paper’s motivation and contribution, not a new systematic-literature-review finding.',
      'papers.pdf, pp. 2, 5–9, 15–16, 18–21.')
rows(['Digitization alone does not establish report integrity.',
      'Laboratory workflows need evidence linked to releases.',
      'Report versions need traceable verification histories.',
      'This study integrates these functions for RHU workflows.'])

# 04 — Objectives follow the paper’s three research questions.
begin('Objectives',
      'The general objective is to design, develop and evaluate the laboratory-record and blockchain verification prototype. The first evaluation objective concerns access controls, change detection and perceived security, privacy and integrity. The second concerns usability, accessibility and workflow efficiency using participant feedback and available task evidence. The third concerns acceptance, trust and willingness to adopt the system. Explain that technical observations and user perceptions answer different parts of these questions. Positive ratings alone do not establish objective security or speed.',
      'papers.pdf, pp. 3–4, 24–25, 48–49.')
rows(['Develop the laboratory and blockchain verification prototype.',
      'Evaluate access controls and report-integrity verification.',
      'Assess usability, accessibility and perceived workflow efficiency.',
      'Examine user acceptance, trust and adoption intentions.'])

# 05 — Pipeline equivalent to the guide’s ML pipeline requirement.
begin('Conceptual framework',
      'Follow the pipeline from input to verification. Patient information, requests, specimens and findings enter controlled laboratory processing. Staff validate required information and complete verification, signing and approval before the final report is released. The released PDF is fingerprinted; its digest is included in a canonical lifecycle event. The event commitment is delivered to Fabric. Verification later combines document comparison, report lifecycle and peer evidence. The diagram is the system-specific equivalent of Input → Preprocessing → Features → Model → Output; fingerprinting and blockchain rules are not learned features or a trained model. Patients and PDFs remain in private off-chain storage.',
      'papers.pdf, pp. 18–21, Figure 2; guide p. 1, pipeline requirement.')
rows(['Input: laboratory records and approved reports',
      'Validate: identifiers, required fields and associations',
      'Fingerprint: PDF digest and event commitment',
      'Anchor: record the commitment in Fabric',
      'Verify: compare documents, lifecycle and peers'],flow=True)

# 06 — Dataset, sampling, and instruments.
begin('Dataset and participants',
      'Separate the development examples from the user evaluation. The system demonstration uses synthetic laboratory records and sample reports; the paper does not establish a large clinical training dataset. Thirty patient respondents were recruited through convenience sampling. All eleven eligible staff participated, comprising eight laboratory staff and three IT personnel. The two role-specific questionnaires contain thirty statements each, using a five-point agreement scale. The paper provides aggregated frequency tallies, totaling 900 patient item ratings and 330 staff item ratings. Patient and staff datasets are analyzed separately. These are evaluation data, not data for training an ML classifier.',
      'papers.pdf, pp. 4, 21–24, 29–30, 42–44.')
rows(['Synthetic records and sample laboratory reports',
      'Patient survey: 30 respondents; convenience sampling',
      'Staff survey: 11 personnel; total enumeration',
      'Staff: eight laboratory and three IT personnel',
      'Separate questionnaires: 30 items; five-point agreement scale'])

# 07 — Detailed clinical process in five stages.
begin('Laboratory system process',
      'Explain each linked stage. Registration establishes the patient and laboratory request. Specimen handling associates the sample with the correct order. Personnel record findings, and authorized users verify results. A report snapshot then receives the required signatures and approval. Release produces the official PDF and captures a lifecycle event in the outbox. The worker subsequently delivers its commitment to Fabric. These actions are permission-controlled. Patients access eligible released reports through authenticated ownership checks; public verification returns limited information. Corrections require a new version and approval cycle rather than editing an already issued artifact.',
      'papers.pdf, pp. 4, 18–20, 31–36.')
rows(['Register patient → create laboratory order',
      'Handle specimen → enter laboratory findings',
      'Verify results → prepare report snapshot',
      'Sign and approve → release official PDF',
      'Capture event → deliver blockchain commitment'],flow=True)

# 08 — Data preparation / feature-engineering equivalent.
begin('Preprocessing and fingerprints',
      'Preparation validates identifiers, required fields, formats and record associations; missing clinical findings are not statistically invented. D is the SHA-256 digest of the exact released PDF bytes. The canonical event binds D to the report UUID, version, event type, occurrence time, source identity and applicable lifecycle links. Canonical serialization uses fixed formatting, so equivalent event data produce the same bytes. C is the hash of those bytes. The Fabric anchor stores C as content_hash and selected metadata; the PDF digest and report version are bound through C rather than being independent chaincode fields. This is deterministic evidence preparation, not ML feature engineering. Hashing does not encrypt data or prove clinical accuracy. For survey preparation, the paper checks item totals and records the corrected staff S16 tally.',
      'papers.pdf, pp. 16, 20–24; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.')
rows(['Validate identifiers, fields and record associations.',
      'D = SHA-256(exact released PDF bytes)',
      'Canonical event binds D, version and lifecycle.',
      'C = SHA-256(canonical event bytes)',
      'Fabric stores C with selected anchor metadata.'],flow=True)

# 09 — Model / technology choice; native topology diagram.
begin('Why Hyperledger Fabric?',
      'Fabric fits the prototype’s need for identified participants, governed transactions and chaincode rules for report anchors. The contract permits authorized organizations, checks allowed event fields and rejects an existing anchor ID; lifecycle changes create additional anchors. Four peers are divided between Org1 and Org2. All four peers and a single Raft orderer share one VPS. This is logical distribution, not four independent physical fault domains or separate institutions. The topology therefore does not demonstrate resilience to complete host failure. MySQL and private PDF storage retain clinical data off-chain. The guide’s model rationale is addressed through this technology-choice explanation; no classifier is trained.',
      'papers.pdf, pp. 7, 17, 20–21; blockchain/chaincode/labchain-anchor/lib/anchor-contract.js; blockchain/network/config/configtx.single-vps.yaml.')
text('Permissioned identities govern transaction participation.',48,135,864,24,INK)
text('Chaincode validates and preserves report anchors.',48,184,864,24,INK)
rect(48,249,405,121,PALE,LINE,9); rect(507,249,405,121,'EAF1F9',LINE,9)
text('Org1: peer1 + peer2',72,292,360,24,TEAL,True)
text('Org2: peer3 + peer4',531,292,360,24,BLUE,True)
line(455,310,504,310,TEAL,2)
rect(48,408,864,69,AMBER_BG,None,8)
text('One VPS; one orderer; shared failure risk.',70,428,818,24,AMBER)

# 10 — Development/configuration and transaction flow in place of ML training.
begin('Blockchain commitment process',
      'The release transaction captures report state and its durable outbox row together. A worker validates the frozen event, checks for an existing anchor and proposes CreateAnchor through the Node.js Gateway adapter. Required organizations endorse according to the configured policy; the channel configuration requires Org1 and Org2. The orderer sequences the transaction. Peers validate endorsements and concurrency conditions, append the block and apply valid writes. The worker checks committed matching evidence before marking delivery CONFIRMED. Temporary failures receive bounded retries and uncertain acknowledgements are reconciled; conflicts or exhausted attempts remain visible for review. PENDING is not blockchain confirmation. This is configured software execution rather than model training. These implementation details explain the mechanism; they are not additional measured participant results.',
      'papers.pdf, pp. 18–21; docs/PHASE_8B_DELIVERY_WORKER.md; blockchain/gateway-adapter/src/adapter.js; blockchain/network/config/configtx.single-vps.yaml.')
rows(['Capture release and outbox together',
      'Worker proposes; required organizations endorse',
      'Orderer sequences; peers validate and commit',
      'Worker checks committed evidence before confirmation',
      'Pending delivery does not mean blockchain confirmation'],flow=True)

# 11 — Verification and linked lifecycle events.
begin('Verification and report lifecycle',
      'QR recognition identifies the registered report. The application checks lifecycle and available historical issuer information, verifies the stored artifact and optionally compares the submitted PDF bytes with the released digest. A protected monitor retrieves report-specific evidence from four peers, including the required commitment, transaction validity, relevant block and lifecycle links. Full verification requires complete, fresh and matching evidence from every peer. A majority does not override contradictory evidence. REPORT_REVOKED and REPORT_SUPERSEDED link to the original release event; a replacement also receives its own release event. A historical report may match its original artifact while no longer being current. Four-peer report verification is separate from Fabric endorsement policy.',
      'papers.pdf, pp. 16, 19–21, 34, 36–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.')
rows(['Scan QR → locate the registered report',
      'Check current, revoked or superseded status',
      'Compare submitted PDF with released PDF digest',
      'Query four peers for required report events',
      'Four fresh matching observations support full verification'],flow=True)

# 12 — Evaluation criteria paired with actual documented observations.
begin('Evaluation and observed results',
      'Describe the evaluation as expected-versus-observed scenarios. The supplied paper shows MATCH for the original PDF, MISMATCH for a changed PDF, four peers VERIFIED and PARTIAL verification with three verified peers while peer4 is offline. These correspond to Figures 4.9, 4.12 and 4.14 and Table 4.2. They are observed interface outputs under the documented conditions, not a measured accuracy rate or repeated reliability benchmark. Complete authorization test logs and controlled timing comparisons are not supplied in the paper. Do not invent accuracy, precision, recall, F1, false-positive rates or a confusion matrix. Such metrics would require a defined evaluation dataset and recorded outcomes; the system is not presented as a predictive classifier.',
      'papers.pdf, pp. 25–27, 37–42, Table 4.2 and Figures 4.9, 4.12, 4.14.')
rows(['Original PDF → MATCH in documented example',
      'Changed PDF → MISMATCH in documented example',
      'Four-peer agreement → VERIFIED in documented example',
      'One peer offline → PARTIAL, three peers verified',
      'Screenshots document scenarios, not measured performance rates'],
      colors=[TEAL,RED,TEAL,AMBER,MUTED])

# 13 — Explainability adapted to deterministic verification outcomes.
begin('Interpreting verification results',
      'MATCH means the compared bytes match the issued artifact under the checks. MISMATCH establishes different bytes, which can result from editing, resaving or another file change; it does not independently prove malicious forgery. PARTIAL means the required peer evidence is incomplete. CONFLICT means contradictory evidence prevents full verification, even if a majority agrees. The conflict rule describes implementation behavior; the paper does not supply a complete observed contradictory-hash experiment. A genuine QR copied onto altered printed content still refers to the original report and cannot authenticate surrounding printed values. The same separation applies to clinical accuracy: a matching document can faithfully reproduce an originally incorrect result. This slide satisfies interpretation and explainability through transparent verification rules, not ML feature importance.',
      'papers.pdf, pp. 20–21, 39–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md.')
rows(['MATCH: compared PDF bytes match issued artifact',
      'MISMATCH: bytes differ; cause remains undetermined',
      'PARTIAL: evidence is incomplete across required peers',
      'CONFLICT: contradictory evidence blocks full verification',
      'QR recognition alone cannot verify printed values'],
      colors=[TEAL,RED,AMBER,RED,MUTED])

# 14 — Original system output enlarged; no invented UI.
begin('System output',
      'Show the paper’s actual Figure 4.9, which uses a synthetic laboratory report. Point to the official PDF viewer on the left and the verification status on the right. The screenshot displays a registered and current report, official PDF integrity MATCH, presented-document MATCH and four individually verified peers. Explain that these are distinct checks on one screen. The screenshot is evidence of one observed successful case, not a measure of detection accuracy. In a live demonstration, show the original file first, then compare a changed file carrying the same genuine QR. Use an authorized synthetic demonstration and explain that public responses omit clinical findings. The image retains the source paper’s resolution; the caption summarizes the important result for distant viewers.',
      'papers.pdf, p. 37, Figure 4.9; screenshot extracted directly from the supplied paper.')
rect(48,130,864,333,WHITE,LINE,8)
pic('verification',60,138,840,317)
text('Official PDF, lifecycle and four-peer verification',48,471,864,24,TEAL,True)

# 15 — One concise, zero-baseline chart. All numbers come from the paper.
begin('Overall survey means',
      'Give the survey thirty to forty-five seconds. Patients reported an overall mean of 4.64 out of 5; staff reported 4.62. There were thirty convenience-sampled patients and eleven eligible staff, including eight laboratory and three IT personnel. These are separate role-specific instruments, so do not treat the small difference as a statistical group comparison or combine the scores. The bar tracks run from zero to five. The section means, if asked, are patient/staff: security, privacy and integrity 4.66/4.75; usability, accessibility and efficiency 4.62/4.56; acceptance and trust 4.64/4.53. Staff results use the corrected S16 tally of four Agree and seven Strongly Agree. Favorable perceptions support user acceptance in these groups; there is no timed evidence of efficiency gains. Aggregated tallies do not support respondent-level reliability analysis.',
      'papers.pdf, pp. 42–44, Tables 4.3–4.4; overall means also reported on p. 48.')
for y,label,value,c in [(151,'Patients (n = 30)',4.64,TEAL),(280,'Staff (n = 11)',4.62,BLUE)]:
    text(label,48,y,600,24,INK,True)
    text(f'{value:.2f} / 5',750,y,162,22,c,True)
    rect(48,y+47,864,38,LINE,None,7)
    rect(48,y+47,864*value/5,38,c,None,7)
text('Favorable perceptions; measured efficiency gains remain unproven.',48,450,864,24,INK)

# 16 — Explicit limitations are kept separate from observed results.
begin('Study limitations',
      'The infrastructure shares one VPS and one orderer, so it cannot demonstrate independent-host resilience. Hash comparison checks byte identity rather than the accuracy of the original laboratory measurement. The paper supplies screenshots and selected scenarios, not repeated performance or comprehensive security benchmarks. The patient sample is a convenience sample; the eleven staff form the full defined eligible staff population. The questionnaires are different by role, and only aggregate frequencies are available. Consequently, respondent-level reliability statistics and correlations cannot be calculated from these files. The study remains an academic prototype and does not establish nationwide adoption or clinical readiness.',
      'papers.pdf, pp. 4, 20–25, 42, 47–50.')
rows(['Shared hosting limits independent fault tolerance.',
      'PDF integrity does not establish clinical accuracy.',
      'Screenshots do not establish repeated performance benchmarks.',
      'Patient convenience sampling limits broader generalization.',
      'Aggregate tallies prevent respondent-level reliability analysis.'])

# 17 — Concrete recommendations from the study.
begin('Recommendations',
      'Connect each recommendation to a limitation. Independent hosts and redundant ordering infrastructure would allow meaningful resilience evaluation. Record contradictory-evidence, outage and recovery behavior under defined test conditions. Document authorization denial for wrong roles and patient ownership. Compare matched paper and digital tasks with recorded completion time, errors and assistance. Where permitted, retain anonymized respondent-level responses to support reliability analysis, and evaluate laboratory and IT tasks separately. Before actual clinical use, the paper also recommends institutional authorization, privacy assessment, clinical workflow review and operational-readiness testing. These are future work, not completed evaluation claims.',
      'papers.pdf, pp. 49–50.')
rows(['Distribute peers and orderers across independent hosts.',
      'Test conflicting evidence and outage recovery.',
      'Document role and ownership access-denial checks.',
      'Measure task time against paper-based workflows.',
      'Retain anonymized respondent-level data for reliability analysis.'])

# 18 — End on the contribution, as the guide requests.
begin('Conclusion and contribution',
      'Close with the complete contribution: controlled laboratory processing is connected to preserved report versions and blockchain-backed evidence that another verifier can check. The documented examples show original-file matching, changed-file detection and a partial result when one peer is unavailable. Patient and staff feedback was favorable, within the sample and measurement limits. The system supports tamper-evident report verification; it does not prove clinical accuracy or absolute security. The strongest closing sentence is: RHU LabChain connects laboratory workflow to traceable reports and checkable blockchain evidence. Invite questions after this statement. No reference-only slide follows; full sources are in each slide’s speaker notes and the companion guide.',
      'papers.pdf, pp. 48–50; Defense_PPT-Gudelines.pdf, p. 2, contribution statement.',True)
for y,t in [(170,'Controlled laboratory workflows.'),(260,'Traceable report versions.'),(350,'Blockchain evidence that can be checked.')]:
    rect(48,y-5,8,55,MINT)
    text(t,82,y+4,810,26,WHITE,True)
text('Academic prototype; further clinical evaluation remains necessary.',48,459,864,24,'C8DEE7')

# Quality checks: count every authored line, including headings. Screenshots
# contain source UI text, which is documented separately in the guide.
import json
from collections import defaultdict
stats=defaultdict(lambda: {'lines':0,'max_words':0,'font_sizes':set()})
for n,ls,size in authored:
    stats[n]['lines']+=len(ls)
    stats[n]['max_words']=max(stats[n]['max_words'],max(len(s.split()) for s in ls))
    stats[n]['font_sizes'].add(size)
for n,st in stats.items():
    assert st['lines']<=6, f'Slide {n}: {st["lines"]} lines exceeds 6'
    assert st['max_words']<=8, f'Slide {n}: {st["max_words"]} words exceeds 8'
    assert min(st['font_sizes'])>=22, f'Slide {n}: font below 22 pt'
for n,x,y,w,h,t in bounds:
    if x<0 or y<0 or x+w>W+.5 or y+h>H+.5:
        raise ValueError(f'Slide {n} out-of-bounds text: {t}')
assert count==18
prs.core_properties.title='RHU LabChain — Revised Defense Presentation'
prs.core_properties.subject='Defense-guideline adaptation for a blockchain system-development study'
prs.save(OUT.with_suffix('.pptx')); pdf.save()
with (ROOT/'Defense_Revised_Presenter_Notes.md').open('w') as f:
    f.write('# Revised defense presentation — presenter notes\n\n18 slides. Allow 45–60 seconds per slide: approximately 13.5–18 minutes, excluding questions. Rehearse actual delivery. All technical and study sources appear below and in the PowerPoint speaker notes.\n\n')
    for n,title,notes,source in all_notes:
        f.write(f'## {n:02}. {title}\n\n{notes}\n\n**Source:** {source}\n\n')
audit={n:{**v,'font_sizes':sorted(v['font_sizes'])} for n,v in stats.items()}
(ROOT/'Defense_Revised_Layout_Checks.json').write_text(json.dumps(audit,indent=2))
print(f'Created {count} slides: {OUT.with_suffix(".pptx")}')
print('Passed: <=6 authored lines per slide, <=8 words per line, >=22 pt authored text, and slide-boundary checks.')

