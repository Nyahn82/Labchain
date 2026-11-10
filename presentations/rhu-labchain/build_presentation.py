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
OUT = ROOT / 'RHU_LabChain_System_Presentation'
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
all_notes=[]; bounds=[]; slide=None; count=0

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

def start(title,section,source,notes,dark=False):
    global slide,count
    if count: pdf.showPage()
    count+=1; slide=prs.slides.add_slide(prs.slide_layouts[6]); rect(0,0,W,H,NAVY if dark else BG)
    text('RHU LABCHAIN  /  '+section.upper(),40,24,880,10,MINT if dark else TEAL,True)
    text(title,40,55,880,29,WHITE if dark else NAVY,True,h=82)
    line(40,502,920,502,'355160' if dark else LINE,1)
    text(source,40,513,830,8.3,'ADC3CF' if dark else MUTED)
    text(f'{count:02}',893,510,30,12,MINT if dark else TEAL,True)
    slide.notes_slide.notes_text_frame.text=notes+'\n\nSources: '+source
    all_notes.append((count,title,notes,source))

def card(x,y,w,h,title,body,accent=TEAL,fill=WHITE,body_size=17):
    rect(x,y,w,h,fill,LINE,8); rect(x,y,4,h,accent)
    th=text(title,x+18,y+16,w-36,19,accent,True)
    text(body,x+18,y+24+th,w-36,body_size,INK,h=h-34-th)

def banner(t,y=448,fill=PALE,c=TEAL,size=17):
    rect(40,y,880,40,fill,None,7); text(t,55,y+9,850,size,c,True,h=31)

def step(x,y,w,num,title,body,h=136):
    rect(x,y,w,h,WHITE,LINE,8)
    text(num,x+14,y+12,w-28,12,TEAL,True)
    th=text(title,x+14,y+37,w-28,18,NAVY,True)
    text(body,x+14,y+46+th,w-28,15.5,MUTED,h=h-55-th)

# 01
start('Laboratory records.\nVerifiable reports.','System presentation','Based on papers.pdf, Chapters III–VI; local RHU LabChain implementation.',
      'Introduce RHU LabChain, the Block-Chain Powered Laboratory Records and Verification System. The study focuses on laboratory workflows at the RHU of M’lang, North Cotabato. Explain that the presentation follows one report from laboratory request through release, blockchain commitment, and later verification. Suggested duration: 12–15 minutes, with most time on slides 6–13. The system is an academic prototype using synthetic laboratory records.',True)
text('Block-Chain Powered Laboratory Records\nand Verification System',40,155,800,22,'C8DEE7')
text('RHU of M’lang, North Cotabato',40,225,800,16,MINT)
for x,num,head,sub in [(40,'01','PROCESS','From request to released PDF'),(340,'02','BLOCKCHAIN','From fingerprint to evidence'),(640,'03','EVALUATION','Technical observations + survey')]:
    rect(x,319,280,123,'1B394A',None,8); text(num,x+18,334,240,12,MINT,True)
    text(head,x+18,359,240,19,WHITE,True); text(sub,x+18,394,244,14,'C8DEE7')

# 02
start('The system adds evidence to a laboratory report','Purpose','Paper: pp. 3–5, 18–21.',
      'The project addresses laboratory record handling and the need to check whether a released report has changed. Structured workflows manage the work; the blockchain adds a reference for report integrity and lifecycle verification. Keep this distinction clear: favorable usability is not automatically a blockchain benefit. This is a laboratory information and report verification system, not a full electronic health record or a diagnostic engine.')
card(40,156,270,238,'Manage the workflow','Link patients, orders, specimens, results and report approvals in one process.')
card(345,156,270,238,'Preserve the artifact','Keep an official released PDF and the exact fingerprint associated with its version.')
card(650,156,270,238,'Verify later','Check the report’s status, compare its PDF and inspect committed blockchain evidence.')
banner('Core question: Does this document match the issued report and its recorded history?')

# 03
start('Three access paths support different tasks','People and permissions','Paper: pp. 4–5, 18–20, 31–37.',
      'Authorized staff handle registration, laboratory processing, verification, signing, approval and release according to permissions. Patients use authenticated accounts to access eligible reports belonging to them. A public verifier can look up limited report information without receiving patient names or laboratory findings. Scanning a QR does not grant access to private clinical content.')
card(40,154,270,257,'Authorized personnel','Register → process → review\n\nSign → approve → release\n\nActions depend on permissions.',body_size=17)
card(345,154,270,257,'Patients','Sign in to the patient portal.\n\nView eligible released reports associated with their account.',body_size=17)
card(650,154,270,257,'Public verifier','Scan a QR or enter a code.\n\nSee limited verification status; compare a submitted PDF.',body_size=17)
banner('Patient data and official PDF access remain protected by the application.')

# 04
start('From laboratory request to released report','System process','Paper: pp. 4, 18–20, 31–36.',
      'Walk through the eight steps in reading order. Registration associates the patient and request. Specimen records connect the sample to the order. Staff enter findings and authorized personnel verify them. The report snapshot then goes through signing and approval before release. At release the system generates the final PDF and captures the blockchain event. Later corrections use another report version and approval cycle rather than silently changing the released report.')
items=[('01','Register patient','Identify the patient'),('02','Create order','Select examinations'),('03','Handle specimen','Register and track sample'),('04','Enter results','Record laboratory findings'),('05','Verify results','Review before reporting'),('06','Prepare report','Create result snapshot'),('07','Sign + approve','Complete required review'),('08','Release PDF','Issue report + capture event')]
for i,(n,t,b) in enumerate(items):
    x=40+(i%4)*225; y=151+(i//4)*151; step(x,y,205,n,t,b,132)
    if i%4<3: line(x+207,y+65,x+221,y+65,TEAL,1.6,True)
banner('Released reports are preserved; corrections follow a new version and approval cycle.')

# 05
start('Clinical records and blockchain evidence work together','Architecture','Paper: pp. 18–21; architecture diagram redrawn for this presentation.',
      'The React interface sends requests to FastAPI. MySQL stores operational records and lifecycle information, while private storage retains released PDFs. A background worker and Node.js adapter deliver commitments to Hyperledger Fabric. A separate protected monitor reads report-specific evidence from peers during verification. The database remains the operational source of truth. IPFS is not part of the implemented system.')
rect(40,146,880,58,NAVY,None,8); text('React interface',57,158,215,20,WHITE,True); line(279,175,331,175,MINT,2,True); text('FastAPI application',350,158,530,20,WHITE,True)
card(40,231,410,161,'PRIVATE APPLICATION STORAGE','MySQL: patients, workflow, report versions and outbox\nPrivate files: exact released PDFs',body_size=17)
card(510,231,410,161,'PERMISSIONED BLOCKCHAIN','Hyperledger Fabric: event commitments, report references and linked lifecycle evidence',body_size=17)
line(244,205,244,225,TEAL,2,True); line(714,205,714,225,TEAL,2,True)
text('Worker + Node.js adapter → writes',50,410,440,15,TEAL,True)
text('Protected monitor → peer evidence reads',510,410,410,15,TEAL,True)
banner('Patient records and PDF files stay off-chain. Fabric stores verification anchors.')

# 06
start('Release captures the report and queues its evidence','Release → blockchain','Paper: pp. 18–20; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.',
      'On release, the application generates the final PDF, stores it privately and computes the digest of those exact bytes. It constructs the canonical lifecycle event and saves the release state and outbox row in one MySQL transaction. The outbox is a durable delivery queue. The worker later submits the commitment to Fabric. Release and blockchain confirmation therefore occur separately. PENDING means captured for delivery, not confirmed on-chain.')
step(40,157,200,'01','Finalize PDF','QR + approved snapshot',150)
step(265,157,200,'02','Hash the PDF','SHA-256 of exact bytes',150)
step(490,157,200,'03','Build event','Identity + version + digest',150)
step(715,157,205,'04','Save release','Report state + outbox row',150)
for x in [241,466,691]: line(x,228,x+19,228,TEAL,1.8,True)
rect(40,337,880,79,NAVY,None,8)
text('One database transaction',58,352,310,20,WHITE,True)
text('Report release and outbox capture commit together.\nA background worker delivers the queued commitment.',382,351,510,17,'D4E5EC')
banner('A report can be RELEASED while its blockchain delivery is still PENDING.')

# 07
start('Two hashes bind the PDF to its blockchain anchor','Blockchain / fingerprint','Paper: pp. 16, 20–21; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.',
      'There are two different hashes. D is the SHA-256 digest of the exact released PDF bytes. The canonical event includes D plus the report UUID, report version, event type, occurrence time, source identity and relevant lifecycle links. Canonical means a fixed serialization: the same event produces the same bytes. C is the SHA-256 hash of those canonical bytes. The chaincode anchor stores C as content_hash, plus selected metadata. The PDF digest and report version are bound through C, not stored as separate PDF fields in the anchor. Hashing is not encryption and cannot establish that the original laboratory findings were clinically correct.')
rect(40,149,880,89,NAVY,None,8)
text('D = SHA-256(exact released PDF bytes)',58,166,840,24,WHITE,True)
text('D is the document fingerprint.',58,205,840,15,MINT)
line(480,240,480,263,TEAL,2,True)
rect(40,268,880,87,WHITE,LINE,8)
text('Canonical event',58,280,225,19,TEAL,True)
text('Report UUID + version + D + event type + time + lifecycle links',58,317,835,17,INK)
line(480,357,480,380,TEAL,2,True)
rect(40,386,880,94,PALE,None,8)
text('C = SHA-256(canonical event bytes)',58,399,840,24,TEAL,True)
text('Fabric anchor stores C as content_hash, with selected anchor metadata.',58,442,840,16,INK)

# 08
start('How an event becomes a committed Fabric transaction','Blockchain / transaction','Paper: p. 20; gateway-adapter/src/adapter.js; network/config/configtx.single-vps.yaml.',
      'The worker validates the frozen event and uses an identified Fabric client through the Gateway. A CreateAnchor proposal is endorsed under the configured policy; the repository channel configuration requires endorsement from Org1 and Org2. Endorsement simulates the chaincode operation. The orderer orders the endorsed transaction into a block. Peers then validate endorsements and concurrency conditions and commit the block; only valid writes update world state. The adapter checks commit status and the worker reconciles the anchor before confirmation. The smart contract checks allowed identities and event fields and rejects an existing anchor ID. These transaction rules differ from the later application requirement to query all four peers.')
for i,(n,t,b) in enumerate([('01','Propose','Worker calls CreateAnchor'),('02','Endorse','Required organizations sign'),('03','Order','Orderer sequences transactions'),('04','Validate + commit','Peers validate and append')]):
    x=40+i*225; step(x,151,205,n,t,b,164)
    if i<3: line(x+208,230,x+220,230,TEAL,1.6,True)
card(40,340,420,93,'Chaincode checks','Allowed identity • valid fields • unique anchor ID',body_size=15)
card(480,340,440,93,'Confirmation receipt','Valid transaction • transaction ID • block reference',body_size=15)
banner('Transaction endorsement and later four-peer report verification are separate checks.',size=16)

# 09
start('Four peers, two organizations, one shared host','Blockchain / network','Paper: pp. 17, 20–21; blockchain/network/config/configtx.single-vps.yaml.',
      'Draw attention to the outer boundary: every node runs on the same VPS. Org1 contains peer1 and peer2; Org2 contains peer3 and peer4. A single Raft orderer orders transactions for the channel. Separate identities and ledger copies demonstrate logical distribution. They do not establish independent institutions or physical fault tolerance. One host failure affects the entire network, and one orderer is also an availability dependency. Blockchain replication does not back up the private PDF and clinical database.')
rect(40,145,880,278,WHITE,LINE,10); text('SINGLE VPS / SHARED PHYSICAL DEPENDENCY',58,158,820,11,MUTED,True)
rect(70,200,280,188,PALE,None,8); text('Organization 1',90,215,240,19,TEAL,True)
rect(610,200,280,188,'EAF1F9',None,8); text('Organization 2',630,215,240,19,BLUE,True)
for x,y,label,col in [(90,258,'peer1',TEAL),(90,320,'peer2',TEAL),(630,258,'peer3',BLUE),(630,320,'peer4',BLUE)]:
    rect(x,y,240,48,WHITE,None,6); text(label,x+16,y+10,210,19,col,True)
rect(395,257,170,79,NAVY,None,8); text('1 orderer',412,271,145,20,WHITE,True); text('Raft ordering',412,305,145,13,MINT)
line(392,297,353,297,TEAL,2,True); line(568,297,607,297,BLUE,2,True)
banner('Logical distribution is demonstrated; independent-host resilience is not.',fill=AMBER_BG,c=AMBER)

# 10
start('Verification joins document, lifecycle and ledger evidence','Blockchain / verification','Paper: pp. 19–21, 36–42.',
      'A QR, code or supported report URL identifies a report. The application looks up registration, lifecycle and available issuer information; checks the stored official artifact; and retrieves report-specific evidence from four peers. If the verifier submits a PDF, its digest is compared with the issued artifact. These checks produce distinct outcomes. A copied genuine QR can still identify the original report even when surrounding printed values were altered. Verification of the exact document requires byte comparison of the PDF.')
rect(40,145,880,52,NAVY,None,8); text('Scan QR / enter code → identify the registered report',58,156,842,21,WHITE,True)
for x,t,b in [(40,'Application checks','Registration\nCurrent / revoked / superseded\nStored PDF + issuer evidence'),(340,'Peer evidence','Read required report events\nCheck committed transaction\nCompare four fresh observations'),(640,'Submitted PDF','Optional file comparison\nHash the presented bytes\nCompare with released digest')]:
    card(x,225,280,184,t,b,body_size=16)
banner('A recognized QR identifies the report; a matching PDF verifies the compared bytes.',size=16)

# 11
start('Four-peer verification has explicit outcomes','Blockchain / evidence rules','Paper: pp. 20–21, 25, 39–42; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md.',
      'All four peers must supply complete, fresh and matching evidence for all required lifecycle events. An offline or lagging peer with other verified observations produces PARTIAL. Contradictory evidence produces CONFLICT; three matching peers do not override it. Invalid transactions or mandatory validation failures produce FAILED. Pending receipts and unavailable evidence cannot support full verification. Equal ledger height or an online indicator is only a network health observation. The checks concern the specific report commitment, transaction validity, relevant block and lifecycle links.')
rows=[('4 / 4 matching','VERIFIED','Complete, fresh report evidence from every peer.',TEAL,PALE),('3 / 4 + one offline','PARTIAL','One peer cannot supply the required evidence.',AMBER,AMBER_BG),('Contradictory evidence','CONFLICT','Matching peers do not override a contradiction.',RED,RED_BG),('Invalid / no evidence','FAILED / UNAVAILABLE','The required proof cannot be accepted or obtained.',MUTED,WHITE)]
for i,(a,b,d,c,f) in enumerate(rows):
    y=148+i*72; rect(40,y,880,62,f,LINE,6); text(a,55,y+9,230,17,INK,True); text(b,310,y+9,280,16,c,True); text(d,310,y+34,586,13.5,INK)
banner('Network health and equal ledger heights do not establish report authenticity.',size=16)

# 12
start('A report’s history survives correction or withdrawal','Blockchain / report lifecycle','Paper: pp. 16, 20, 34; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md.',
      'REPORT_RELEASED records an issued version. A correction goes through a new draft, signing, approval and release cycle. The new version receives a release event, and the predecessor receives REPORT_SUPERSEDED evidence referring to the replacement. Explicit withdrawal creates REPORT_REVOKED. Revocation and supersession link to that report’s original release commitment. Old artifacts and anchors are retained. A historical PDF can therefore match its original bytes and have valid ledger evidence while being marked superseded or revoked; integrity does not imply current clinical use.')
card(40,161,245,169,'Version 1 released','Official PDF v1\nREPORT_RELEASED\nOriginal event commitment',body_size=16)
card(370,161,245,169,'Version 2 released','New approval cycle\nREPORT_RELEASED\nNew PDF + commitment',body_size=16)
line(289,244,362,244,TEAL,2,True)
card(700,161,220,169,'Version 1 replaced','REPORT_SUPERSEDED\nLinks to v1 release\nReferences replacement',body_size=15)
line(620,244,691,244,TEAL,2,True)
rect(40,357,880,62,WHITE,LINE,7); text('Withdrawal path',57,369,215,18,RED,True); text('REPORT_REVOKED links to the original release event.',285,371,610,17,INK)
banner('Valid historical evidence does not mean the report is still current.',size=17)

# 13
start('The queue separates clinical work from ledger delivery','Blockchain / reliability','Paper: pp. 18–20; docs/PHASE_8B_DELIVERY_WORKER.md.',
      'Clinical release captures an outbox event without requiring a synchronous Fabric call. If delivery is temporarily unavailable, the worker uses bounded retries. Before submission and after uncertain outcomes it checks for an existing anchor; matching evidence can reconcile a lost acknowledgement. A conflicting existing anchor is not overwritten. Events become CONFIRMED only with matching committed evidence. Permanent failures or exhausted retries require investigation. This improves delivery handling while the application and database are available; it does not remove the single-host failure boundary. The slide is an implementation explanation, not a measured availability claim.')
for i,(n,t,b) in enumerate([('01','Capture','Durable outbox event'),('02','Deliver','Submit through Gateway'),('03','Confirm','Check committed evidence')]):
    x=40+i*300; step(x,150,280,n,t,b,139)
    if i<2: line(x+282,220,x+296,220,TEAL,1.8,True)
card(40,320,425,108,'Temporary interruption','Retry with limits; reconcile an existing anchor before resubmission.',body_size=16)
card(490,320,430,108,'Conflict or exhausted retries','Keep the failure visible and require investigation.',accent=AMBER,body_size=16)
banner('PENDING is a delivery state. CONFIRMED is backed by a matching committed anchor.',size=16)

# 14
start('The paper shows successful and incomplete verification','Demonstration evidence','Paper: Fig. 4.9 (p. 37), Fig. 4.12 (p. 40), Fig. 4.14 (p. 41); synthetic report examples.',
      'Use these original paper figures as visual evidence. Figure 4.9 shows a presented PDF MATCH and four peers verified. Figure 4.12 shows a mismatch warning for a changed file. Figure 4.14 shows partial verification with three peers verified and peer4 offline; the presented file is NOT COMPARED in that case. Each screenshot documents a displayed scenario. These are not repeated benchmarks, measured detection rates or proof of broad production readiness. Demonstration suggestion: explain the original PDF first, then a changed copy carrying a genuine QR, and finally the partial peer state.')
for x,title,im,caption,c in [(40,'Original PDF','verification','MATCH + four peers verified',TEAL),(340,'Changed PDF','mismatch','MISMATCH for submitted file',RED),(640,'One peer offline','partial','PARTIAL verification: 3/4',AMBER)]:
    rect(x,145,280,285,WHITE,LINE,8); text(title,x+15,159,250,19,c,True)
    pic(im,x+10,202,260,167); text(caption,x+15,384,250,15,c,True)
banner('Observed interface states support the demonstrated cases; they are not benchmarks.',size=15.5)

# 15
start('Survey feedback was favorable in both groups','Concise survey findings','Paper: Tables 4.3–4.4, pp. 42–44; corrected staff tally.',
      'Keep this slide brief. The patient group contains 30 convenience-sampled respondents. The staff group is the census of 11 eligible individuals: eight laboratory personnel and three IT personnel. Each instrument has 30 statements on a five-point agreement scale. Overall means are 4.64 for patients and 4.62 for staff. The table retains the three research-question sections separately because the questionnaires cover role-specific tasks. These ratings represent perceptions, not measured technical security or faster processing. Do not combine the two groups into one score or interpret item-rating percentages as respondent percentages.')
rect(40,145,425,87,NAVY,None,8); text('4.64 / 5',57,153,205,30,WHITE,True); text('Patients · n = 30',57,200,380,15,MINT)
rect(490,145,430,87,TEAL,None,8); text('4.62 / 5',508,153,205,30,WHITE,True); text('Staff · n = 11  (8 laboratory + 3 IT)',508,200,390,15,WHITE)
rect(40,250,880,36,LINE); text('Research area',55,258,550,15,INK,True); text('Patients',645,258,120,15,INK,True); text('Staff',810,258,90,15,INK,True)
for i,(name,a,b) in enumerate([('Security, privacy and integrity','4.66','4.75'),('Usability, accessibility and efficiency','4.62','4.56'),('User acceptance and trust','4.64','4.53')]):
    y=287+i*45; rect(40,y,880,44,WHITE if i%2==0 else 'EBF1F4'); text(name,55,y+11,570,16,INK); text(a,655,y+9,100,18,TEAL,True); text(b,815,y+9,90,18,TEAL,True)
banner('Descriptive perceptions on a 1–5 scale; groups analyzed separately.',size=16)

# 16
start('The prototype’s boundaries guide the next evaluation','Limits and next steps','Paper: pp. 20–25, 42, 47–50.',
      'Pair each limit with a practical next step. All peers share one VPS, so separate-host deployment and recovery testing are needed. A digest match proves byte correspondence, not the clinical correctness of the original result; clinical workflow review and authorization remain necessary. The paper contains screenshots rather than comprehensive repeated logs, so document conflicting evidence, outage recovery and permission denial cases. Aggregated survey tallies and absent timed comparisons limit conclusions about reliability and objective efficiency; collect anonymized respondent-level data and repeatable task measurements. Keep the conclusion at academic prototype level.')
rows=[('Shared VPS and one orderer','Evaluate independent hosts and recovery.'),('Document integrity ≠ clinical accuracy','Review clinical workflow before real use.'),('Limited recorded technical scenarios','Record conflict, outage and access-denial tests.'),('Aggregate surveys; no timed comparison','Collect item-level data and task-time evidence.')]
for i,(left,right) in enumerate(rows):
    y=147+i*73; rect(40,y,880,62,WHITE,LINE,7); text(left,57,y+13,404,17,INK,True); text('→',475,y+12,25,20,TEAL,True); text(right,520,y+13,380,16,MUTED)
banner('Academic prototype using synthetic reports; clinical readiness remains future work.',fill=AMBER_BG,c=AMBER,size=16)

# 17
start('From a released report to evidence that can be checked','Takeaway','Paper: Chapters III, IV and VI.',
      'Close by following the chain once more: the laboratory workflow creates an approved release; the PDF is fingerprinted; its identity, version and digest are bound in an event; that event commitment is recorded in Fabric; later verification combines report lifecycle, document comparison and peer evidence. The contribution is integrated workflow plus tamper-evident report verification under the stated prototype conditions. Survey feedback is positive, while broader operational and clinical evaluation remains future work. Invite questions.',True)
for i,(label,detail) in enumerate([('CONTROL THE WORKFLOW','Patient → order → specimen → result → release'),('COMMIT THE EVIDENCE','PDF fingerprint → canonical event → Fabric anchor'),('VERIFY THE REPORT','Lifecycle + document comparison + four-peer evidence')]):
    y=153+i*96; text(f'0{i+1}',40,y,60,24,MINT,True); text(label,114,y,790,18,WHITE,True); text(detail,114,y+33,790,18,'C8DEE7')
text('Questions & demonstration',40,456,880,22,MINT,True)

# 18
start('Sources and presenter reference','Appendix','Source material supplied by the user and local project files; no external claims added.',
      'This reference slide is optional during delivery. All survey values and study conclusions come from the supplied papers.pdf. Detailed transaction and delivery descriptions are cross-checked against the local source and project documentation. Where documentation describes separate implementation tests, those have not been presented as participant results or added to the paper’s empirical findings. Original screenshots retain the resolution of the supplied paper. The PowerPoint diagrams, labels and survey table are editable native shapes and text.')
text('Primary study',40,147,880,20,TEAL,True)
text('papers.pdf — 54 pages\nSystem and blockchain model: pp. 18–21\nWorkflow and observed verification: pp. 31–42\nSurvey results: pp. 42–45  •  Conclusions and limits: pp. 48–50',40,181,875,17)
text('Implementation cross-checks',40,294,880,20,TEAL,True)
text('docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md\ndocs/PHASE_8B_DELIVERY_WORKER.md\ndocs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md\nFabric gateway adapter, anchor contract and single-VPS channel configuration',40,330,875,15.5)
text('The paper’s findings and implementation explanations remain distinct.',40,457,880,16,MUTED,True)

for n,x,y,w,h,t in bounds:
    if x<0 or y<0 or x+w>W+.5 or y+h>H+.5:
        raise ValueError(f'Slide {n} out-of-bounds text: {t}')
prs.save(OUT.with_suffix('.pptx')); pdf.save()
with (ROOT/'Presenter_Notes.md').open('w') as f:
    f.write('# RHU LabChain — presenter notes\n\nSuggested delivery: 12–15 minutes plus questions. Slides 1–17 form the presentation; slide 18 is a reference appendix. Survey findings are limited to slide 15.\n\n')
    for n,title,notes,source in all_notes:
        f.write(f'## {n:02}. {title.replace(chr(10), " ")}\n\n{notes}\n\n**Sources:** {source}\n\n')
print(f'Created {count} slides: {OUT.with_suffix(".pptx")}')
print('All text boxes passed slide-boundary and planned-height checks.')
