"""Create the project-specific operator PDF and copyable Markdown guide."""
from pathlib import Path
from html import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parent
for name,file in [('Body','DejaVuSans.ttf'),('Bold','DejaVuSans-Bold.ttf'),('Code','DejaVuSansMono.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+file))
NAVY=HexColor('#112B3C'); TEAL=HexColor('#087F8C'); GRAY=HexColor('#557080')
styles={
 'title':ParagraphStyle('title',fontName='Bold',fontSize=23,leading=29,textColor=NAVY,spaceAfter=14),
 'sub':ParagraphStyle('sub',fontName='Bold',fontSize=12,leading=16,textColor=TEAL,spaceBefore=10,spaceAfter=6),
 'body':ParagraphStyle('body',fontName='Body',fontSize=10.3,leading=15,spaceAfter=8,textColor=NAVY),
 'small':ParagraphStyle('small',fontName='Body',fontSize=9,leading=13,spaceAfter=5,textColor=GRAY),
 'table':ParagraphStyle('table',fontName='Body',fontSize=9,leading=12,textColor=NAVY),
 'code':ParagraphStyle('code',fontName='Code',fontSize=8.3,leading=11.4,textColor=NAVY),
}
story=[]; md=[]; page_count=0
def para(t,style='body'):
    story.append(Paragraph(escape(t).replace('\n','<br/>'),styles[style])); md.append(t+'\n')
def heading(t):
    story.append(Paragraph(escape(t),styles['sub'])); md.append('### '+t+'\n')
def page(title):
    global page_count
    if page_count: story.append(PageBreak())
    page_count+=1
    story.append(Paragraph(escape(title),styles['title'])); md.append('\n## '+title+'\n')
def code(s,lang='bash'):
    s=s.strip('\n')
    for ln in s.splitlines():
        if pdfmetrics.stringWidth(ln,'Code',8.3)>492:
            raise ValueError('Code line too wide: '+ln)
    table=Table([[Preformatted(s,styles['code'])]],colWidths=[511],hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#EDF3F6')),('BOX',(0,0),(-1,-1),.5,HexColor('#D7E2E8')),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.extend([table,Spacer(1,8)]); md.append('```'+lang+'\n'+s+'\n```\n')
def table(headers,rows,widths):
    data=[[Paragraph(escape(str(v)),styles['table']) for v in row] for row in [headers]+rows]
    t=Table(data,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#DDEDF0')),('ROWBACKGROUNDS',(0,1),(-1,-1),[white,HexColor('#F3F6F8')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,0),.7,TEAL)]))
    story.extend([t,Spacer(1,9)])
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows))

page('RHU LabChain\nPeer and ledger command guide')
para('Prepared for your existing VPS and source tree. Verified on 28 October 2026, approximately 2:22 PM Singapore time. Commands use Bash on the server, not the browser console.')
heading('What this guide covers')
table(['Page','Task'],[
 ['2','Set up the read-only helper; prove Hyperledger Fabric is running'],
 ['3','Stop and restore peer4 for a controlled demonstration'],
 ['4','Read one peer’s ledger status and locate its persistent volume'],
 ['5','Find an event reference and read its blockchain fingerprint'],
 ['6','Compare the PDF fingerprint with the event commitment'],
 ['7','Read a block or transaction directly from a selected peer'],
 ['8','Verify active organizations, MSPs and endorsement policy'],
 ['9–10','Locate the network, hashing, chaincode and verification code'],
 ['11','Run a short defense demonstration and resolve common errors'],
],[42,469])
heading('Verified live snapshot')
para('Fabric peer binary: v2.5.16. Channel: labchain-channel. Chaincode: labchain-anchor, version 1.0.0, sequence 1. All four peers returned height 17 and matching latest block hashes. The active configuration contains Org1MSP, Org2MSP and OrdererMSP, with etcdraft (Raft) ordering.')
para('This is a snapshot, not a permanent expected height. All peers share one VPS. Matching heights alone do not prove a particular report is authentic.')
heading('What was actually executed')
para('Only inspection and read-only queries were run to prepare this guide. The block, anchor, history and transaction commands were checked against existing ledger data. No peer was stopped or started, no report was changed, and no ledger transaction was submitted.')
para('Only the clearly marked STOP and START commands on page 3 change a running service. Ordinary queries use the existing operator identities; they do not require opening public Fabric ports.', 'small')

page('2 / Setup and proof of Fabric')
para('Use the existing Fabric operator account (rhuadmin) on this VPS. It already needs Docker access and the existing organization administrator files. Do not copy private keys into the presentation or terminal output.')
heading('Initialize the short command once per terminal')
code(r'''cd /opt/rhu-labchain
rhu_peer() {
  bash /opt/rhu-labchain/docs/defense-commands/peer-read.sh "$@"
}
bash docs/defense-commands/peer-read.sh --help''')
para('rhu_peer is a convenience function created for this guide, not a built-in Fabric command. The helper permits only listed read operations. It selects the existing peer address, TLS certificate and organization identity. Its complete source is in the path above.')
heading('Show the real binary and deployed network')
code(r'''docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker exec labchain-peer4 peer version
rhu_peer peer4 channels
rhu_peer peer4 definition''')
para('Expected: Fabric v2.5.16 inside the running peer; channel labchain-channel; chaincode labchain-anchor; approvals for Org1MSP and Org2MSP. The version command inside the container proves more than a local CLI installation alone.')
table(['Peer / container','Organization','Host TLS endpoint'],[
 ['peer1 / labchain-peer1','Org1MSP','127.0.0.1:7051'],
 ['peer2 / labchain-peer2','Org1MSP','127.0.0.1:8051'],
 ['peer3 / labchain-peer3','Org2MSP','127.0.0.1:9051'],
 ['peer4 / labchain-peer4','Org2MSP','127.0.0.1:10051'],
],[201,125,185])
para('Orderer: labchain-orderer / OrdererMSP / 127.0.0.1:7050. External chaincode services: labchain-anchor1 through labchain-anchor4. A chaincode service is not an additional peer.')

page('3 / Stop and restore one peer')
para('Use peer4 for the demonstration. This temporarily takes its Fabric endpoint offline; it does not revoke membership, remove the organization or erase its ledger. The other peers and the orderer remain running.')
heading('Before the demonstration — READ ONLY')
code(r'''rhu_peer peer4 info
docker inspect --format '{{.State.Status}}' labchain-peer4''')
heading('STOP peer4 — CHANGES SERVICE AVAILABILITY')
code(r'''docker stop --timeout 30 labchain-peer4
docker inspect --format '{{.State.Status}}' labchain-peer4''')
para('Expected container state: exited. Refresh the website’s Network tab and the chosen report’s verification page. If the other three peers provide complete matching evidence and there are no other failures or pending lifecycle events, expect PARTIAL / 3 of 4, with peer4 offline. Allow the request to refresh; an old screen is not a new observation.')
heading('START the same existing peer — RESTORES SERVICE')
code(r'''docker start labchain-peer4
docker inspect --format '{{.State.Status}}' labchain-peer4
rhu_peer peer4 info''')
para('Wait for readiness and repeat the final query if startup is still in progress. Then refresh report verification. Full verification requires all required evidence to be fresh and matching; “running” alone is insufficient.')
heading('Check recovery if needed')
code(r'''docker logs --tail 60 labchain-peer4
cd /opt/rhu-labchain/blockchain/network
scripts/single-vps-status.sh peer4 --channel''')
para('Stopping only labchain-peer4 leaves its separate labchain-anchor4 service in place. If that service was independently stopped, diagnose it before restarting it. Do not use down -v, volume deletion, identity regeneration or a new channel to recover from this demonstration.')
para('An offline peer cannot answer queries. Start that same peer to query its retained ledger, or select another running peer to query that peer’s own copy. Stopping peer4 does not remove historical copies elsewhere.', 'small')

page('4 / Read and locate a peer ledger')
heading('Read one selected peer — READ ONLY')
code(r'''rhu_peer peer4 channels
rhu_peer peer4 info
rhu_peer peer4 definition''')
para('info uses peer channel getinfo against peer4’s direct TLS endpoint. height is the number of blocks: height 17 means blocks 0–16. currentBlockHash identifies the latest block header; previousBlockHash identifies its predecessor. Neither is a laboratory report’s PDF fingerprint.')
heading('Compare all four peers')
code(r'''for p in peer1 peer2 peer3 peer4; do
  printf '\n--- %s ---\n' "$p"
  rhu_peer "$p" info
done''')
para('Lag or an offline endpoint can make observations differ. Equal heights are a network observation. For report-specific evidence, compare its anchor and transaction and use the report verifier.')
heading('Find peer4’s persistent storage')
code(r'''docker inspect --format \
  '{{range .Mounts}}{{println .Type .Name .Destination}}{{end}}' \
  labchain-peer4
docker volume inspect --format '{{.Mountpoint}}' \
  labchain-peer4-ledger
docker exec labchain-peer4 sh -c \
  'ls -d /var/hyperledger/production/ledgersData/*' ''')
para('The verified ledger mount is labchain-peer4-ledger → /var/hyperledger/production. Fabric keeps its block store, LevelDB world state and history/index data beneath the ledger data tree. The volume inspection returns this host’s actual mountpoint; do not assume a Docker storage root.')
para('Use Fabric queries to inspect records. The database files are not readable JSON. Do not edit, remove or copy live LevelDB files as an ordinary way to inspect the ledger.')
heading('Open a container shell, if you need directory inspection')
code('docker exec -it labchain-peer4 sh')
para('Use exit to leave the container. A container shell is not necessary for rhu_peer queries. Each peer has its own separately named ledger volume.', 'small')

page('5 / Read a report’s blockchain anchor')
heading('Get the correct identifier from the website')
para('Sign in with BLOCKCHAIN_EXPLORER_VIEW permission. Open /administration/blockchain → Anchors. Expand Anchor details and copy the full event reference. This is event_uuid, and becomes the ledger anchor_id. Also note the record hash, transaction ID and block number.')
para('Do not substitute the report number, entity reference, QR token or transaction ID for the event reference. Each release, revocation or supersession event has its own anchor ID.')
heading('Read that anchor from peer4 — READ ONLY')
code(r'''read -r -p "Event reference: " ANCHOR_ID
rhu_peer peer4 exists "$ANCHOR_ID"
rhu_peer peer4 anchor "$ANCHOR_ID"
rhu_peer peer4 history "$ANCHOR_ID"''')
table(['Ledger field','Meaning'],[
 ['anchor_id','The event UUID used as the lookup key'],
 ['content_hash','SHA-256 commitment of the canonical event'],
 ['entity_reference','Opaque report UUID, not a patient identifier'],
 ['previous_hash','Linked release-event commitment when applicable'],
 ['source_msp / source_node','Submitting organization and logical source'],
 ['transaction_id','Transaction that created the anchor'],
],[155,356])
heading('The native query inside the helper')
code(r'''# Excerpt inside the helper; TLS/admin settings are required.
peer chaincode query -C labchain-channel -n labchain-anchor \
  -c '{"Args":["ReadAnchor","PASTE_EVENT_UUID_HERE"]}' ''')
para('Use rhu_peer for terminal execution; this native excerpt needs the TLS/admin environment selected inside the helper. ReadAnchor reads world state; GetAnchorHistory reads that key’s history. The contract has no update/delete method. Later lifecycle events create other linked anchors, so one key’s history is not the report’s entire lifecycle.')
heading('Read the same event from another peer')
code('rhu_peer peer3 anchor "$ANCHOR_ID"')
para('Compare content_hash and the other event fields. A matching anchor alone is narrower than the application’s full verification, which also checks committed transactions, blocks, lifecycle coverage and freshness.', 'small')

page('6 / Check both kinds of fingerprint')
para('There are two related hashes. D = SHA-256(exact released PDF bytes). C = SHA-256(canonical event bytes), where the event includes D, report identity, version and lifecycle fields. The ledger content_hash is C, not D.')
heading('Calculate the PDF fingerprint on the machine holding it')
code(r'''read -r -p "Path to downloaded official PDF: " pdf_file
sha256sum -- "$pdf_file"''')
para('Use the exact downloaded issued PDF. Editing or re-saving it can change the bytes. Compare this digest with the stored report hash, not directly with the ledger content_hash.')
heading('View all four values in the website')
para('In /administration/blockchain → Integrity, enter the numeric Report ID. This tab additionally requires BLOCKCHAIN_INTEGRITY_VERIFY. It shows PDF SHA-256, Stored report hash, Event record hash and Ledger content hash. The first pair should agree (D); the second pair should agree (C). This Integrity tab is separate from the report scanner’s independent four-peer verification.')
heading('Optional SQL — read-only, in your approved database session')
para('If you already have authorized database access, select the application database and run this query. Replace the placeholder with the event reference. No database password or connection secret is needed in the guide.')
code(r'''SELECT event_uuid, event_status,
       JSON_UNQUOTE(JSON_EXTRACT(
         canonical_payload, '$.artifact_sha256')) AS pdf_sha256,
       record_hash AS event_sha256,
       SHA2(canonical_payload, 256) AS recomputed_event_sha256,
       fabric_transaction_id, fabric_block_number
FROM blockchain_event
WHERE event_uuid = 'PASTE_EVENT_UUID_HERE';''','sql')
para('Compare event_sha256 with recomputed_event_sha256 and peer4’s content_hash. This query is documented from the schema; it was not executed against the application database while preparing the guide.')
heading('Where the report file is stored')
para('The application uses REPORT_STORAGE_DIR plus lab_report.pdf_path. The example configuration uses /var/lib/rhu-labchain/reports; the configured value is authoritative. Relative released files follow released/<year>/<report-id>-<random>.pdf. Prefer downloading through the authenticated application instead of exposing the private storage directory.')
para('A digest match verifies matching bytes under the checks. It does not establish clinical accuracy. A QR identifies the original record but cannot authenticate altered surrounding printed values.', 'small')

page('7 / Read blocks and transactions')
para('These operations query QSCC on the selected peer. They do not use the orderer as a substitute for that peer’s ledger.')
heading('Export a block from peer4 — READ ONLY')
code(r'''umask 077
LEDGER_VIEW=$(mktemp -d /tmp/labchain-view.XXXXXX)
rhu_peer peer4 block 0 > "$LEDGER_VIEW/block0.json"
python3 -m json.tool "$LEDGER_VIEW/block0.json" | less''')
para('Block 0 is the initial channel configuration. Press q to leave less. For a report event, use the block number shown in Anchors; it must be less than that peer’s current height.')
code(r'''read -r -p "Report event block number: " BLOCK_NUMBER
rhu_peer peer4 block "$BLOCK_NUMBER" \
  > "$LEDGER_VIEW/report-block.json"''')
heading('Read the report’s committed transaction')
code(r'''read -r -p "Transaction ID: " TX_ID
rhu_peer peer4 transaction "$TX_ID" \
  > "$LEDGER_VIEW/transaction.json"
python3 - "$LEDGER_VIEW/transaction.json" <<'PY'
import json, sys
tx = json.load(open(sys.argv[1]))
print("Validation code:", tx["validationCode"])
PY''')
para('Validation code 0 means VALID. A transaction can exist in a block without being valid, so mere existence is insufficient. The read helper decodes protos.ProcessedTransaction for this query.')
heading('Native peer-block query used by the helper')
code(r'''peer chaincode query -C labchain-channel -n qscc \
  -c '{"Args":["GetBlockByNumber","labchain-channel","0"]}' \
  --hex''')
para('This native excerpt runs inside the helper’s TLS/admin environment. The helper converts hex to exact bytes, then uses configtxlator proto_decode --type common.Block. This avoids the binary-decode failure observed with this CLI’s --raw output. Transactions use GetTransactionByID and protos.ProcessedTransaction.')
para('Files are created only in the new local directory printed by: printf "%s\\n" "$LEDGER_VIEW". Decoded ledger exports contain identifiers and public certificate metadata; use a synthetic example for public demonstration.', 'small')

page('8 / Verify organizations and policies')
heading('Inspect the active channel configuration — READ ONLY')
code(r'''rhu_peer peer4 organizations
rhu_peer peer4 definition''')
para('organizations fetches the current configuration block from the orderer using the selected organization’s existing admin identity. It is explicitly an orderer configuration read, unlike the direct-peer block query on page 7. It decodes the current block and prints only a summary.')
table(['Verified configuration item','Value at inspection'],[
 ['Application organization / MSP','Org1 → Org1MSP; Org2 → Org2MSP'],
 ['Orderer organization / MSP','OrdererOrg → OrdererMSP'],
 ['Consensus type','etcdraft (Raft)'],
 ['Application endorsement policy','2-of-2 peer principals: Org1MSP and Org2MSP'],
 ['Committed chaincode','labchain-anchor; v1.0.0; sequence 1'],
 ['Chaincode organization approvals','Org1MSP: true; Org2MSP: true'],
],[224,287])
para('MSP means Membership Service Provider: the identity and trust rules for an organization. An organization name and its MSP ID are related but different fields. Two organizations here are logical groups on one host, not two independently operated hospitals.')
heading('Show the running peer’s own configured organization')
code(r'''docker exec labchain-peer4 sh -c \
  'printf "%s %s\n" "$CORE_PEER_ID" "$CORE_PEER_LOCALMSPID"'
# Expected: peer4 Org2MSP''')
heading('Where these values come from')
para('The active configuration read is stronger evidence than a source-file claim. The source declares the intended organizations and policy in blockchain/network/config/configtx.single-vps.yaml. Peer-specific MSP IDs are also declared in compose/docker-compose.single-vps.yml.')
para('Endorsement is a transaction acceptance rule. The application’s four-peer verification is a later report-evidence rule. They are not the same vote. Four matching observations are required for a full report verification result; contradictory evidence cannot be overridden by a majority.')
para('There is no running Fabric CA service in this prototype configuration: identities were bootstrapped with cryptogen. Absence of a Fabric CA container does not mean the peers are not Hyperledger Fabric.', 'small')

page('9 / Network and chaincode code locations')
para('All paths below are relative to /opt/rhu-labchain. Line numbers refer to the source inspected for this guide; they may move after edits.')
table(['File : starting line','What to show during defense'],[
 ['blockchain/network/compose/\ndocker-compose.single-vps.yml:62', 'peer1 service. peer2 starts at 167; peer3 at 272; peer4 at 377. Images, MSP IDs, TLS, ports and ledger volumes.'],
 ['blockchain/network/config/\nconfigtx.single-vps.yaml:2', 'Org1, Org2 and OrdererOrg. Endorsement policy at 43; Raft configuration at 46.'],
 ['blockchain/network/versions.json:1', 'Pinned Fabric version and reviewed image digests; cryptogen bootstrap and no CA service.'],
 ['blockchain/network/scripts/\nsingle-vps-common.sh:45', 'single_peer(): maps peer number to organization, host port, TLS root and admin identity.'],
 ['blockchain/network/scripts/\nsingle-vps-status.sh:1', 'Read-only health, joined channels and optional ledger info.'],
 ['blockchain/chaincode/labchain-anchor/\nlib/anchor-contract.js:30', 'CreateAnchor validates identity and fields; rejects an existing key; stores content_hash at line 47 and writes at line 55.'],
 ['blockchain/chaincode/labchain-anchor/\nlib/anchor-contract.js:60', 'ReadAnchor reads world state. AnchorExists starts at 67; GetAnchorHistory at 72.'],
 ['docs/defense-commands/peer-read.sh:1', 'New read-only command helper supplied with this guide. No invoke or service-control operation is allowed.'],
],[285,226])
heading('Print the exact source with line numbers')
code(r'''cd /opt/rhu-labchain
nl -ba blockchain/network/config/configtx.single-vps.yaml \
  | sed -n '1,80p'
nl -ba blockchain/chaincode/labchain-anchor/lib/anchor-contract.js \
  | sed -n '27,93p' ''')
para('To locate a function after edits, use rg -n with its name instead of relying only on an old line number.', 'small')

page('10 / Application and fingerprint code')
table(['File : starting line','Responsibility'],[
 ['app/services/report_release_service.py:119', 'hashlib.sha256(data).hexdigest() calculates D from exact PDF bytes. Line 120 stores report_hash; line 130 captures the release event.'],
 ['app/services/\nblockchain_event_validation.py:38', 'canonicalize(): fixed event fields and serialization. Line 63 uses sorted keys and compact JSON.'],
 ['app/services/\nblockchain_outbox_service.py:25', 'capture(): builds event. Line 56 calculates C as SHA-256 of UTF-8 canonical_payload.'],
 ['app/services/\nblockchain_delivery_service.py:207', 'Worker delivers or reconciles an anchor. confirm() at 191 checks event fields before confirmation.'],
 ['blockchain/gateway-adapter/src/adapter.js:25', 'Proposal, endorsement, submission and commit-status checks. This is the write integration.'],
 ['blockchain/gateway-adapter/src/monitor.js:13', 'Peer/organization endpoints. openPeer at 109; directSession at 121; committedReport at 260; reportEvidence at 289.'],
 ['app/services/public_authenticity_service.py:38', 'aggregate_peer_evidence() checks four-peer agreement. ledger_evidence at 103; public_verification at 141.'],
 ['app/services/\nblockchain_monitor_service.py:82', 'Integrity comparison of PDF, stored hash, immutable event and live ledger evidence.'],
 ['frontend/src/pages/BlockchainMonitor.tsx:110', 'Anchor details show event reference and record hash; line 121 shows both pairs of integrity hashes.'],
 ['app/api/blockchain_monitor.py:14', 'Permission-protected explorer routes. Integrity requires an additional permission.'],
],[285,226])
heading('Find the fingerprint calculations quickly')
code(r'''cd /opt/rhu-labchain
rg -n 'sha256|capture_release' \
  app/services/report_release_service.py
rg -n 'canonical_payload|record_hash|sha256' \
  app/services/blockchain_outbox_service.py
rg -n 'content_hash|putState|ReadAnchor' \
  blockchain/chaincode/labchain-anchor/lib/anchor-contract.js''')

page('11 / Defense sequence and troubleshooting')
heading('A short demonstration sequence')
para('1. Show the running container’s Fabric version.\n2. Show organizations, channel and committed chaincode.\n3. Select a synthetic released report and copy its event reference.\n4. Read its anchor from peer4; explain content_hash.\n5. Show the PDF hash pair and event-hash pair in Integrity.\n6. Optionally stop peer4 using page 3; refresh report verification.\n7. Restart peer4, confirm readiness and refresh verification again.\n8. Show the hashing and CreateAnchor source locations.')
heading('Common problems')
table(['Symptom','Meaning / next check'],[
 ['rhu_peer: command not found','Repeat the function definition on page 2 in this terminal.'],
 ['Missing tool / Python YAML error','Use the existing operator environment and pinned tools. Default tool path: blockchain/network/tools. Do not replace network identities to fix tool errors.'],
 ['Connection refused / unavailable','The selected peer may be stopped or not ready. Check its state and logs; repeat after readiness.'],
 ['Anchor not found','Check event reference, target peer and channel; confirm delivery is CONFIRMED. A report UUID or QR token is not an anchor ID.'],
 ['Height matches but report not verified','Inspect that report’s commitment, transaction validity and lifecycle coverage. Height is not report-specific proof.'],
 ['Permission denied in the website','Explorer needs BLOCKCHAIN_EXPLORER_VIEW; Integrity additionally needs BLOCKCHAIN_INTEGRITY_VERIFY. Use the approved account.'],
 ['Three peers match, but result is CONFLICT','Contradictory evidence takes precedence; do not treat three votes as full verification.'],
],[176,335])
heading('Validation record and limits')
para('Checked: Bash syntax, pinned CLI and running peer binary, all four ledger heights, channel membership, committed definition, active organization/policy summary, peer4 block decoding, existing anchor/history reads, and a committed transaction with validation code 0. No new transaction was submitted. Stop/start instructions and optional SQL were not executed for this guide.')
para('Sources: current local source files listed on pages 9–10; blockchain/docs/OPERATIONS.md; docs/FOUR_PEER_QR_VERIFICATION_COMPLETION.md; docs/PHASE_8B_TRANSACTIONAL_OUTBOX.md. Earlier Phase 8A documents describe an earlier implementation stage; the live snapshot here was checked separately.', 'small')

def footer(c,doc):
    c.saveState(); c.setStrokeColor(HexColor('#D7E2E8')); c.line(42,40,553,40)
    c.setFont('Body',8); c.setFillColor(GRAY)
    c.drawString(42,25,'RHU LabChain | Operator and defense reference | 28 Oct 2026')
    c.drawRightString(553,25,str(doc.page)); c.restoreState()

pdf_path=ROOT/'RHU_LabChain_Peer_Ledger_Command_Guide.pdf'
doc=SimpleDocTemplate(str(pdf_path),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=55,
    title='RHU LabChain — Peer, Ledger and Fingerprint Command Guide',author='RHU LabChain')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
(ROOT/'RHU_LabChain_Peer_Ledger_Command_Guide.md').write_text('\n'.join(md))
print('Created:',pdf_path)
print('Planned pages:',page_count)
