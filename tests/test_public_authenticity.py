"""Synthetic security tests. Fabric doubles here test failure handling, NOT live integration."""
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from sqlalchemy import select
from app.config import settings
from app.models import BlockchainEvent, FacilityProfile, LabReport, ReportResultItem, ReportVerification
from app.schemas import blockchain_monitor as schema
from app.services import blockchain_monitor_client as monitor, verification_limits
from test_phase_5b_release import api, env, password_hash, lab_api, workflow_api, results_api, reports_api, admin, ready, release, metadata, call, sign, create


def issued(api):
    ready(api); row=release(api)
    url=metadata(api)['verification_url']
    return url, (settings.report_storage_dir/row['pdf_path']).read_bytes()


def ledger(api, monkeypatch, defect=None):
    with api.factory.begin() as db:
        events=list(db.scalars(select(BlockchainEvent)))
        for event in events:
            event.event_status='CONFIRMED'; event.fabric_transaction_id=f'{event.event_id:064x}'
            event.fabric_block_number=7; event.fabric_validation_code=0; event.confirmed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    def query(request, kind):
        if defect=='unavailable': raise monitor.MonitorUnavailable()
        assert request['action'] == 'report_evidence'
        peers = []
        with api.factory() as db:
            for index in range(1, 5):
                peer_name = f'peer{index}'
                issue = defect.get(peer_name) if isinstance(defect, dict) else defect
                observations = []
                for requested in request['events']:
                    e=db.scalar(select(BlockchainEvent).where(BlockchainEvent.event_uuid==requested['anchor_id']))
                    p=json.loads(e.canonical_payload)
                    anchor=dict(anchor_id=e.event_uuid,entity_type='REPORT',entity_reference=e.entity_reference,event_type=e.event_type,
                        content_hash=e.record_hash,previous_hash=e.previous_hash,transaction_id=e.fabric_transaction_id,
                        source_node=p['source_node'],source_msp=p['source_msp'],created_at=datetime.now(timezone.utc))
                    tx=dict(transaction_id=e.fabric_transaction_id,validation_code=0,validation_status='VALID',timestamp=None,
                        block_number=7,block_hash='e'*64,channel='labchain-channel',creator_msp=p['source_msp'])
                    if issue=='digest': anchor['content_hash']='f'*64
                    if issue=='reference': anchor['entity_reference']='00000000-0000-4000-8000-000000000000'
                    if issue=='issuer': anchor['source_msp']='Org2MSP'
                    if issue=='creator': tx['creator_msp']='Org2MSP'
                    if issue=='channel': tx['channel']='wrong-channel'
                    if issue=='invalid_transaction': tx.update(validation_code=11,validation_status='INVALID_OTHER_REASON')
                    if issue=='wrong_block': tx['block_number']=8
                    if issue=='different_block_hash': tx['block_hash']='f'*64
                    if issue=='wrong_transaction': tx['transaction_id']='f'*64
                    status={'offline':'OFFLINE','timeout':'TIMEOUT','lagging':'LAGGING','missing':'MISSING','legacy_monitor':'UNAVAILABLE'}.get(issue,'OBSERVED')
                    observations.append(dict(anchor_id=e.event_uuid,status=status,evidence=dict(anchor=anchor,transaction=tx) if status=='OBSERVED' else None))
                peers.append(dict(peer=peer_name,msp='Org1MSP' if index<3 else 'Org2MSP',channel='labchain-channel',checked_at=datetime.now(timezone.utc),events=observations))
        return kind(channel='labchain-channel',checked_at=datetime.now(timezone.utc),peers=peers)
    monkeypatch.setattr(monitor,'query',query)


def compare(api,url,pdf,**headers):
    return api.client.post(url+'/compare',content=pdf,headers={'Content-Type':'application/pdf',**headers})


def test_registration_is_not_document_verification_and_issuer_is_frozen(api,monkeypatch):
    url,pdf=issued(api); ledger(api,monkeypatch)
    with api.factory.begin() as db: db.get(FacilityProfile,1).facility_name='RENAMED AFTER ISSUE'
    response=api.client.get(url); body=response.json()
    assert response.status_code==200 and body['status']=='REGISTERED'
    assert body['document_comparison']=='NOT_COMPARED' and body['blockchain_evidence']=='FOUR_PEER_VERIFIED'
    assert body['issuing_facility']!='RENAMED AFTER ISSUE' and body['issuer_evidence']=='SNAPSHOT'
    forbidden={'patient_name','patient_code','result_value','pdf_path','report_id','report_hash','transaction_id','source_msp','canonical_payload'}
    assert not forbidden.intersection(body)
    assert response.headers['cache-control']=='no-store'
    assert (settings.report_storage_dir/next(settings.report_storage_dir.rglob('*.pdf')).relative_to(settings.report_storage_dir)).read_bytes()==pdf


def test_official_match_and_copied_qr_modified_lab_value(api,monkeypatch):
    url,pdf=issued(api); ledger(api,monkeypatch)
    original=compare(api,url,pdf).json()
    assert original['document_comparison']=='MATCH' and original['blockchain_evidence']=='FOUR_PEER_VERIFIED'
    with api.factory() as db: value=db.scalar(select(ReportResultItem.result_value_snapshot).order_by(ReportResultItem.report_result_item_id))
    reader=PdfReader(BytesIO(pdf)); writer=PdfWriter(); writer.clone_document_from_reader(reader)
    changed=False
    for page in writer.pages:
        stream=page.get_contents().get_data()
        old=('('+value+')').encode()
        if old in stream:
            replacement=DecodedStreamObject(); replacement.set_data(stream.replace(old,b'(999999)',1))
            page[NameObject('/Contents')]=writer._add_object(replacement); changed=True; break
    assert changed, 'Synthetic result must actually be changed'
    output=BytesIO(); writer.write(output); altered=output.getvalue()
    assert '999999' in ''.join(p.extract_text() for p in PdfReader(BytesIO(altered)).pages)
    # The original QR image bytes survive the modified result document.
    assert [hashlib.sha256(i.data).hexdigest() for p in reader.pages for i in p.images]==[hashlib.sha256(i.data).hexdigest() for p in PdfReader(BytesIO(altered)).pages for i in p.images]
    body=compare(api,url,altered).json()
    assert body['status']=='REGISTERED' and body['document_comparison']=='MISMATCH'
    assert body['blockchain_evidence']=='FOUR_PEER_VERIFIED' # genuine registration does not certify changed bytes
    assert api.client.get(url).json()['document_comparison']=='NOT_COMPARED'
    assert len(list(settings.report_storage_dir.rglob('*.pdf')))==1
    assert next(settings.report_storage_dir.rglob('*.pdf')).read_bytes()==pdf


@pytest.mark.parametrize('defect,expected',[('unavailable','UNAVAILABLE'),('digest','CONFLICT'),('reference','CONFLICT'),('issuer','CONFLICT'),('legacy_monitor','UNAVAILABLE'),('invalid_transaction','FAILED'),('wrong_block','CONFLICT')])
def test_independent_evidence_failures_cannot_be_confirmed(api,monkeypatch,defect,expected):
    url,pdf=issued(api); ledger(api,monkeypatch,defect)
    body=compare(api,url,pdf).json()
    assert body['document_comparison']=='MATCH' and body['blockchain_evidence']==expected


def test_pending_is_not_confirmed_and_legacy_issuer_not_invented(api):
    url,pdf=issued(api)
    with api.factory.begin() as db: db.get(LabReport,1).presentation_snapshot=None
    body=compare(api,url,pdf).json()
    assert body['blockchain_evidence']=='PENDING' and body['issuer_evidence']=='LEGACY_UNAVAILABLE'
    assert 'issuing_facility' not in body


def test_revoked_and_superseded_versions_never_current(api,monkeypatch):
    url,pdf=issued(api)
    assert call(api,'POST','/reports/1/revoke',{'reason':'Synthetic withdrawal'}).status_code==200
    ledger(api,monkeypatch)
    assert compare(api,url,pdf).json()['status']=='REVOKED'
    revised=call(api,'POST','/reports/1/revise',{}); assert revised.status_code==201
    link=create(api,'/reports/2/signatories',{'signatory_id':1,'signatory_type':'PATHOLOGIST'})
    assert sign(api,link['report_signatory_id'],2).status_code==200
    assert call(api,'POST','/reports/2/approve').status_code==200
    newer=release(api,2); ledger(api,monkeypatch)
    body=compare(api,url,pdf).json(); assert body['status']=='SUPERSEDED' and body['blockchain_evidence']=='FOUR_PEER_VERIFIED'
    newpdf=(settings.report_storage_dir/newer['pdf_path']).read_bytes()
    assert compare(api,url,newpdf).json()['document_comparison']=='MISMATCH'
    assert api.client.get(url,headers={'Accept':'text/html'},follow_redirects=False).status_code==303


@pytest.mark.parametrize('token',['123','fabricated-report','x'*43,'x'*500])
def test_unknown_token_is_neutral(api,token):
    r=api.client.get('/api/v1/verify/'+token)
    assert r.status_code==200 and r.json()['status']=='NOT_FOUND'
    assert not {'report_code','issuing_facility','version'}.intersection(r.json())


@pytest.mark.parametrize('body,headers,status',[(b'NOT PDF',{},415),(b'%PDF-1.4\nhello\n%%EOF',{'Content-Type':'text/plain'},415),(b'%PDF-1.4\nhello\n%%EOF',{'Origin':'https://evil.example'},403),(b'%PDF-1.4\nhello\n%%EOF',{'Content-Encoding':'gzip'},415)])
def test_upload_validation_without_retention(api,body,headers,status):
    r=api.client.post('/api/v1/verify/'+'x'*43+'/compare',content=body,headers={'Content-Type':'application/pdf',**headers})
    assert r.status_code==status
    assert not list(settings.report_storage_dir.rglob('*'))


def test_size_rate_and_concurrency_limits(api,monkeypatch):
    monkeypatch.setattr(settings,'verification_upload_max_bytes',1024)
    assert compare(api,'/api/v1/verify/'+'x'*43,b'%PDF-1.4\n'+b'x'*1100+b'%%EOF').status_code==413
    monkeypatch.setattr(settings,'verification_requests_per_minute',2)
    verification_limits.requests.clear(); verification_limits.global_requests.clear()
    url='/api/v1/verify/'+'x'*43
    assert api.client.get(url).status_code==200
    assert api.client.get(url).status_code==200
    response=api.client.get(url); assert response.status_code==429 and response.headers['retry-after']=='60'
    verification_limits.requests.clear(); verification_limits.global_requests.clear()
    assert verification_limits.slots.acquire(False) and verification_limits.slots.acquire(False)
    try: assert api.client.get(url).status_code==503
    finally: verification_limits.slots.release(); verification_limits.slots.release()


def test_chunked_upload_size_bound_and_tampered_token(api,monkeypatch):
    url,pdf=issued(api)
    altered_token=url[:-1]+('A' if url[-1]!='A' else 'B')
    assert compare(api,altered_token,pdf).json()['status']=='NOT_FOUND'
    monkeypatch.setattr(settings,'verification_upload_max_bytes',1024)
    r=api.client.post(url+'/compare',content=iter([b'%PDF-1.4\n',b'x'*1100,b'%%EOF']),headers={'Content-Type':'application/pdf'})
    assert r.status_code==413


def test_public_access_logs_omit_capability_tokens():
    import logging
    from app.services.verification_access_log import VerificationAccessFilter
    f=VerificationAccessFilter()
    def record(path): return logging.LogRecord('uvicorn.access',20,'',0,'%s %s %s %s %s',('client','POST',path,'1.1',200),None)
    assert not f.filter(record('/api/v1/verify/SECRET/compare'))
    assert f.filter(record('/api/v1/health'))


def test_independent_monitor_rejects_stale_evidence(monkeypatch):
    import socket
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    payload={'ok':True,'result':{'anchor_id':'00000000-0000-4000-8000-000000000000','entity_reference':'00000000-0000-4000-8000-000000000001','event_type':'REPORT_RELEASED','content_hash':'a'*64,'previous_hash':None,'transaction_id':'b'*64,'source_peer':'peer1','source_node':'node1','source_msp':'Org1MSP','checked_at':(now-timedelta(minutes=2)).isoformat()}}
    class Socket:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def settimeout(self,*args): pass
        def connect(self,*args): pass
        def sendall(self,*args): pass
        def recv(self,*args): return json.dumps(payload).encode()+b'\n'
    monkeypatch.setattr(socket,'socket',lambda *a,**k:Socket())
    with pytest.raises(monitor.MonitorUnavailable): monitor.query({'action':'anchor','anchor_id':payload['result']['anchor_id']},schema.AnchorEvidence)


@pytest.mark.parametrize('fraction,second_shift,expected', [
    (0,0,True), (1,0,True), (499999,0,True), (500000,1,True),
    (696997,1,True), (999999,1,True), (499999,1,False),
    (500000,0,False), (0,1,False), (999999,2,False),
])
def test_mysql_release_timestamp_precision(fraction,second_shift,expected):
    from datetime import timedelta
    from app.services.public_authenticity_service import release_time_matches
    base=datetime(2026,10,20,23,59,59,tzinfo=timezone.utc)
    event_time=base.replace(microsecond=fraction)
    report_time=base+timedelta(seconds=second_shift)
    assert release_time_matches(event_time,report_time) is expected
    assert release_time_matches(event_time,event_time)
    assert not release_time_matches(event_time,event_time+timedelta(microseconds=2))


@pytest.mark.parametrize('offset,expected',[(0,'FOUR_PEER_VERIFIED'),(2,'FAILED')])
def test_public_verification_preserves_mysql_second_precision(api,monkeypatch,offset,expected):
    from datetime import timedelta
    url,pdf=issued(api); ledger(api,monkeypatch)
    with api.factory.begin() as db:
        event=db.scalar(select(BlockchainEvent).where(BlockchainEvent.event_type=='REPORT_RELEASED'))
        db.get(LabReport,1).released_at=(event.occurred_at+timedelta(microseconds=500000,seconds=offset)).replace(microsecond=0)
    body=compare(api,url,pdf).json()
    assert body['document_comparison']=='MATCH' and body['blockchain_evidence']==expected


@pytest.mark.parametrize('peer,defect,overall,state,count', [
    ('peer4','offline','PARTIAL','OFFLINE',3), ('peer1','offline','PARTIAL','OFFLINE',3),
    ('peer2','timeout','PARTIAL','TIMEOUT',3), ('peer3','lagging','PARTIAL','LAGGING',3),
    ('peer3','missing','PARTIAL','MISSING',3), ('peer3','digest','CONFLICT','CONFLICT',3),
    ('peer4','invalid_transaction','FAILED','FAILED',3), ('peer2','wrong_block','CONFLICT','CONFLICT',3),
    ('peer2','wrong_transaction','CONFLICT','CONFLICT',3), ('peer2','issuer','CONFLICT','CONFLICT',3),
    ('peer2','creator','FAILED','FAILED',3), ('peer2','channel','FAILED','FAILED',3),
    ('peer3','different_block_hash','CONFLICT','CONFLICT',0),
])
def test_four_peer_aggregation_never_votes_away_a_conflict(api,monkeypatch,peer,defect,overall,state,count):
    url,pdf=issued(api); ledger(api,monkeypatch,{peer:defect})
    body=compare(api,url,pdf).json()
    assert body['blockchain_evidence']==overall
    assert body['blockchain_verified_count']==count
    assert len(body['blockchain_peers'])==4
    assert next(p for p in body['blockchain_peers'] if p['peer']==peer)['status']==state
    assert body['document_comparison']=='MATCH'
    for p in body['blockchain_peers']:
        assert set(p)=={'peer','status','checked_at'}


def test_all_four_offline_cannot_reuse_mysql_confirmation(api,monkeypatch):
    url,pdf=issued(api);ledger(api,monkeypatch,{f'peer{i}':'offline' for i in range(1,5)})
    body=compare(api,url,pdf).json()
    assert body['blockchain_evidence']=='UNAVAILABLE' and body['blockchain_verified_count']==0
    assert all(p['status']=='OFFLINE' for p in body['blockchain_peers'])


@pytest.mark.parametrize('defect,expected,count', [
    ('duplicate_peer','FAILED',0), ('wrong_peer_msp','FAILED',3), ('missing_event','FAILED',3),
    ('stale','PARTIAL',3), ('future','PARTIAL',3), ('malformed','FAILED',0),
    ('timeout_invalid','FAILED',3), ('timeout_conflict','CONFLICT',3),
])
def test_four_peer_response_identity_freshness_and_partial_invalid_evidence(api,monkeypatch,defect,expected,count):
    from datetime import timedelta
    url,pdf=issued(api);ledger(api,monkeypatch)
    original=monitor.query
    def query(request,kind):
        if defect=='malformed': raise monitor.MonitorInvalidEvidence()
        result=original(request,kind)
        p=result.peers[3]
        if defect=='duplicate_peer': p.peer='peer1'
        if defect=='wrong_peer_msp': p.msp='Org1MSP'
        if defect=='missing_event': p.events[0].anchor_id='00000000-0000-4000-8000-000000000099'
        if defect=='stale': p.checked_at-=timedelta(minutes=2)
        if defect=='future': p.checked_at+=timedelta(minutes=2)
        if defect=='timeout_invalid':
            p.events[0].status='TIMEOUT';p.events[0].evidence.anchor=None
            p.events[0].evidence.transaction.validation_code=11
        if defect=='timeout_conflict':
            p.events[0].status='TIMEOUT';p.events[0].evidence.transaction=None
            p.events[0].evidence.anchor.content_hash='f'*64
        return result
    monkeypatch.setattr(monitor,'query',query)
    body=compare(api,url,pdf).json()
    assert body['blockchain_evidence']==expected and body['blockchain_verified_count']==count
