"""Synthetic authorized QR-to-original-PDF workflow, never live clinical fixtures."""
import hashlib,json,os,shutil
from pathlib import Path
from datetime import datetime,timezone
import pytest
from sqlalchemy import select,delete
from fastapi.testclient import TestClient
from app.config import settings
from app.models import AuditLog,UserRole,Role,RolePermission,Permission,Staff,LabReport
from test_public_authenticity import (api,env,password_hash,lab_api,workflow_api,results_api,reports_api,admin,
    issued,ledger,call,sign,create,release,metadata)


def resolve(api,url):
    return call(api,'POST','/verify/staff/resolve',{'token':url.rsplit('/',1)[1]})


def test_staff_scan_returns_exact_report_pdf_real_checks_contract_and_audits(api,monkeypatch):
    url,pdf=issued(api); ledger(api,monkeypatch)
    result=resolve(api,url)
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    body=result.json(); assert body['report_id']==1 and body['verification']['version']==1
    assert body['verification']['blockchain_evidence']=='VERIFIED'
    assert body['verification']['document_comparison']=='NOT_COMPARED'
    assert body['ledger_details_authorized'] and body['ledger_details'][0]['artifact_sha256']==hashlib.sha256(pdf).hexdigest()
    downloaded=api.client.get('/api/v1/reports/1/pdf')
    assert downloaded.status_code==200 and downloaded.content==pdf
    with api.factory() as db:
        events=list(db.scalars(select(AuditLog).where(AuditLog.action.in_(['REPORT_QR_VERIFY','REPORT_DOWNLOAD']))))
        assert {e.action for e in events}=={'REPORT_QR_VERIFY','REPORT_DOWNLOAD'}
        assert all(e.user_id==1 and e.record_id==1 for e in events)
        assert url.rsplit('/',1)[1] not in json.dumps([e.new_value for e in events])
    public=api.client.get(url).json()
    assert not {'report_id','ledger_details','transaction_id','pdf_path'} & public.keys()


def personnel(api,permissions):
    with api.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id==1,UserRole.role_id==2))
        for name in permissions:
            permission=db.scalar(select(Permission).where(Permission.permission_code==name))
            db.add(RolePermission(role_id=1,permission_id=permission.permission_id))


@pytest.mark.parametrize('permissions',[[],['REPORT_READ'],['REPORT_DOWNLOAD']])
def test_staff_scan_requires_both_report_permissions(api,permissions):
    url,_=issued(api); personnel(api,permissions)
    assert resolve(api,url).status_code==403


def test_basic_staff_gets_live_evidence_without_privileged_ledger_identifiers(api,monkeypatch):
    url,_=issued(api); ledger(api,monkeypatch); personnel(api,['REPORT_READ','REPORT_DOWNLOAD'])
    body=resolve(api,url).json()
    assert body['verification']['blockchain_evidence']=='VERIFIED'
    assert body['ledger_details']==[] and body['ledger_details_authorized'] is False


@pytest.mark.parametrize('failure',['inactive_staff','patient_role','inactive_role'])
def test_staff_identity_role_controls(api,monkeypatch,failure):
    url,_=issued(api); personnel(api,['REPORT_READ','REPORT_DOWNLOAD'])
    with api.factory.begin() as db:
        if failure=='inactive_staff': db.get(Staff,1).is_active=False
        elif failure=='inactive_role': db.get(Role,1).is_active=False
        else:
            db.add(Role(role_id=99,role_code='PATIENT',role_name='Patient',is_active=True)); db.flush()
            db.add(UserRole(user_id=1,role_id=99,assigned_at=datetime.now(timezone.utc))); monkeypatch.setattr(settings,'patient_mfa_required',False)
    assert resolve(api,url).status_code==403


def test_anonymous_csrf_invalid_and_modified_tokens_cannot_reveal_pdf(api):
    url,pdf=issued(api); token=url.rsplit('/',1)[1]
    with TestClient(api.app,base_url='https://testserver') as anonymous:
        assert anonymous.post('/api/v1/verify/staff/resolve',json={'token':token}).status_code==401
        assert anonymous.get('/api/v1/reports/1/pdf').status_code==401
    assert api.client.post('/api/v1/verify/staff/resolve',json={'token':token}).status_code==403
    assert call(api,'POST','/verify/staff/resolve',{'token':'x'*43}).status_code==404
    assert call(api,'POST','/verify/staff/resolve',{'token':'https://unrelated.example/'}).status_code==422
    assert call(api,'POST','/verify/staff/resolve',{'token':token,'report_id':999}).status_code==422


def test_revoked_and_superseded_scan_keeps_exact_original_version(api,monkeypatch):
    url,pdf=issued(api)
    assert call(api,'POST','/reports/1/revise',{}).status_code==201
    link=create(api,'/reports/2/signatories',{'signatory_id':1,'signatory_type':'PATHOLOGIST'})
    assert sign(api,assignment_id=link['report_signatory_id'],report_id=2).status_code==200
    assert call(api,'POST','/reports/2/approve').status_code==200
    release(api,2); newer=metadata(api,2)['verification_url']; ledger(api,monkeypatch)
    original=resolve(api,url).json(); current=resolve(api,newer).json()
    assert original['report_id']==1 and original['verification']['version']==1 and original['verification']['status']=='SUPERSEDED'
    assert current['report_id']==2 and current['verification']['version']==2 and current['verification']['status']=='REGISTERED'
    assert api.client.get('/api/v1/reports/1/pdf').content==pdf
    assert call(api,'POST','/reports/2/revoke',{'reason':'Synthetic acceptance'}).status_code==200
    ledger(api,monkeypatch)
    assert resolve(api,newer).json()['verification']['status']=='REVOKED'


def test_ledger_unavailable_still_allows_authorized_original_with_honest_state(api,monkeypatch):
    url,pdf=issued(api); ledger(api,monkeypatch,'unavailable')
    body=resolve(api,url).json()
    assert body['verification']['blockchain_evidence']=='UNAVAILABLE' and body['ledger_details']==[]
    assert api.client.get('/api/v1/reports/1/pdf').content==pdf


@pytest.mark.skipif(not os.environ.get('RHU_SCANNER_EXPORT_DIR'), reason='Optional isolated browser fixture export')
def test_export_synthetic_browser_fixture(api,monkeypatch):
    target=Path(os.environ['RHU_SCANNER_EXPORT_DIR']).resolve()
    assert str(target).startswith('/tmp/rhu-scan-') and target.is_dir()
    monkeypatch.setattr(settings,'public_base_url','https://labchain.online')
    url,pdf=issued(api); ledger(api,monkeypatch)
    shutil.copyfile(api.engine.url.database,target/'synthetic.sqlite')
    shutil.copytree(settings.report_storage_dir,target/'reports',dirs_exist_ok=True)
    (target/'fixture.json').write_text(json.dumps({'token':url.rsplit('/',1)[1],'pdf_sha256':hashlib.sha256(pdf).hexdigest()}))
    from pypdf import PdfReader
    from io import BytesIO
    images=[i for page in PdfReader(BytesIO(pdf)).pages for i in page.images]
    assert len(images)==1
    (target/'synthetic-qr.png').write_bytes(images[0].data)
    assert pdf.startswith(b'%PDF-')
