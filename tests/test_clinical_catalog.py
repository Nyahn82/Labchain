"""Isolated clinical catalog acceptance. All patients, approvals and Fabric are synthetic."""
import hashlib
import json
from io import BytesIO
import pytest
from pypdf import PdfReader
from sqlalchemy import select, func
from app.models import (AuditLog, CodeSequence, LabDepartment, LabOrderItem, LabResultItem,
    PanelTest, SampleType, TestCatalog as Catalog, TestPanel as Panel, TestSampleType, ReferenceRange)
from app.services.clinical_catalog_service import load_catalog
from app.services import starter_catalog_service as importer
from test_public_authenticity import (api, env, password_hash, lab_api, workflow_api, results_api,
    reports_api, admin, ledger, compare, call, create, sign, release, metadata)


def imported(api):
    preview=call(api,'GET','/lab/clinical-catalog')
    assert preview.status_code==200, preview.text
    response=call(api,'POST','/lab/clinical-catalog',{'fingerprint':preview.json()['fingerprint'],'acknowledge_inactive_review':True})
    assert response.status_code==200, response.text
    return response.json()


def ids(api):
    with api.factory() as db:
        return {(a.entity_type,a.new_value['catalog_key']):a.record_id for a in db.scalars(select(AuditLog).where(AuditLog.action=='STARTER_CATALOG_CREATE'))}


def approve_synthetic(api, mapping, panel_keys=(), test_keys=()):
    """Only fixture approvals; never call against operational data."""
    with api.factory.begin() as db:
        required={mapping['test_catalog',k] for k in test_keys}
        for key in panel_keys:
            p=db.get(Panel,mapping['test_panel',key]);p.is_active=True;p.facility_status='APPROVED';p.approval_note='SYNTHETIC isolated acceptance only'
            required.update(db.scalars(select(PanelTest.test_id).where(PanelTest.panel_id==p.panel_id)))
        for tid in required:
            t=db.get(Catalog,tid);t.is_active=True;t.facility_status='APPROVED';t.methodology='SYNTHETIC method';t.approval_note='SYNTHETIC reference applicability reviewed; no intervals'
            db.get(LabDepartment,t.department_id).is_active=True
            for sid in db.scalars(select(TestSampleType.sample_type_id).where(TestSampleType.test_id==tid)):
                db.get(SampleType,sid).is_active=True
    return required


def test_manifest_has_real_coverage_and_unset_reference_intervals():
    c=load_catalog()
    assert len(c.departments)==8 and len(c.tests)>=120 and len(c.panels)>=20
    assert len({t.key for t in c.tests})==len(c.tests)
    assert all(t.reference_policy.startswith('UNSET:') and t.sources and t.samples for t in c.tests)
    assert next(t for t in c.tests if t.key=='hiv_screen').restricted_workflow
    assert {'edta_blood','citrate_plasma','serum','urine','stool','csf'} <= {s.key for s in c.samples}
    assert next(p for p in c.panels if p.key=='glycemic').tests==['fbs','hba1c']


def test_import_preserves_codes_config_and_is_idempotent(api):
    with api.factory() as db:
        before=[(t.test_id,t.test_code,t.test_name,t.is_active) for t in db.scalars(select(Catalog))]
        old_ranges=db.scalar(select(func.count()).select_from(ReferenceRange))
    first=imported(api); assert first['inserted']==221 and first['updated']==first['rejected']==0
    mapping=ids(api)
    with api.factory.begin() as db:
        test=db.get(Catalog,mapping['test_catalog','hemoglobin']);test.approval_note='MANUAL FACILITY NOTE'
        counters={s.sequence_key:s.current_value for s in db.scalars(select(CodeSequence))}
    second=imported(api);assert second['inserted']==0 and second['skipped']==221
    with api.factory() as db:
        assert [(db.get(Catalog,i).test_id,db.get(Catalog,i).test_code,db.get(Catalog,i).test_name,db.get(Catalog,i).is_active) for i,*_ in before]==before
        assert {s.sequence_key:s.current_value for s in db.scalars(select(CodeSequence))}==counters
        assert db.get(Catalog,mapping['test_catalog','hemoglobin']).approval_note=='MANUAL FACILITY NOTE'
        assert db.scalar(select(func.count()).select_from(ReferenceRange))==old_ranges
    browser=call(api,'GET','/lab/catalog-browser').json()
    assert len(browser['tests'])==169 and not any(t['orderable'] for t in browser['tests'] if t['catalog_metadata'])
    assert call(api,'POST','/lab-orders',{'patient_id':1,'priority':'ROUTINE','test_ids':[mapping['test_catalog','hemoglobin']]}).status_code==409
    assert call(api,'PATCH',f"/lab/tests/{mapping['test_catalog','hemoglobin']}",{'is_active':True}).status_code==409
    assert call(api,'PATCH',f"/lab/tests/{mapping['test_catalog','hiv_screen']}",{'facility_status':'APPROVED','approval_note':'Unjustified approval','methodology':'Example'}).status_code==409
    assert call(api,'GET','/lab/tests?search=Hgb').json()['total']==1


@pytest.mark.parametrize('panel_keys,test_keys',[
    (['cbc_diff'],['hemoglobin']), (['urinalysis'],[]), (['comprehensive_metabolic'],[]),
    (['cbc_diff','cbc','glycemic'],['urine_ph']),
])
def test_order_specimens_results_report_and_qr(api,monkeypatch,panel_keys,test_keys):
    imported(api);mapping=ids(api);required=approve_synthetic(api,mapping,panel_keys,test_keys)
    order=create(api,'/lab-orders',{'patient_id':1,'physician_id':1,'priority':'ROUTINE',
        'panel_ids':[mapping['test_panel',k] for k in panel_keys], 'test_ids':[mapping['test_catalog',k] for k in test_keys]})
    assert {i['test_id'] for i in order['items']}==required and len(order['items'])==len(required)
    reread=call(api,'GET',f"/lab-orders/{order['order_id']}").json();assert reread['items']==order['items']
    # Different specimen requirements must remain separate; reject wrong association.
    assert call(api,'POST',f"/lab-orders/{order['order_id']}/specimens",{'sample_type_id':1,'order_item_ids':[i['order_item_id'] for i in order['items']]}).status_code==409
    grouped={}
    for item in order['items']:
        sid=item['definition_snapshot']['specimens'][0]['sample_type_id'];grouped.setdefault(sid,[]).append(item)
    for sample_id,items in grouped.items():
        sp=create(api,f"/lab-orders/{order['order_id']}/specimens",{'sample_type_id':sample_id,'order_item_ids':[i['order_item_id'] for i in items]})
        for action in ['collect','receive']: assert call(api,'POST',f"/specimens/{sp['specimen_id']}/{action}").status_code==200
        for item in items:
            t=item['definition_snapshot']['test'];schema=t['result_schema'] or {}; scalar=next((f for f in schema.get('fields',[]) if f['key']=='result_value'),None)
            value=scalar['choices'][0] if scalar else ('12.3' if t['result_type']=='NUMERIC' else 'SYNTHETIC observation')
            result=create(api,f"/lab-order-items/{item['order_item_id']}/result",{'result_value':value,'specimen_id':sp['specimen_id']})
            assert call(api,'PATCH',f"/results/{result['result_item_id']}",{'remarks':'SYNTHETIC draft resumed'}).status_code==200
            for action in ['review','verify']: assert call(api,'POST',f"/results/{result['result_item_id']}/{action}").status_code==200
    order=call(api,'GET',f"/lab-orders/{order['order_id']}").json()
    assert order['status']=='COMPLETED' and all(p['status']=='COMPLETED' for p in order['panels'])
    report=create(api,f"/lab-orders/{order['order_id']}/reports",{})
    profile=create(api,'/signatories',{'staff_id':1,'license_number_snapshot':'SYNTHETIC-NOT-CLINICAL'})
    assignment=create(api,f"/reports/{report['report_id']}/signatories",{'signatory_id':profile['signatory_id'],'signatory_type':'MEDICAL_TECHNOLOGIST'})
    assert sign(api,assignment_id=assignment['report_signatory_id'],report_id=report['report_id']).status_code==200
    assert call(api,'POST',f"/reports/{report['report_id']}/approve").status_code==200
    release(api,report['report_id'])
    pdf=call(api,'GET',f"/reports/{report['report_id']}/pdf").content
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert all(i['test']['test_name'] in text for i in order['items'])
    assert all(p['panel']['panel_name'] in text for p in order['panels'])
    assert 'SYNTHETIC-NOT-CLINICAL' in text and 'Specimen' in text
    url=metadata(api,report['report_id'])['verification_url'];ledger(api,monkeypatch)
    assert compare(api,url,pdf).json()['document_comparison']=='MATCH'
    assert compare(api,url,pdf.replace(b'%%EOF', b'% synthetic alteration\n%%EOF')).json()['document_comparison']=='MISMATCH'
    response=call(api,'POST','/verify/staff/resolve',{'token':url.rsplit('/',1)[1]})
    assert response.status_code==200 and response.json()['verification']['blockchain_evidence']=='VERIFIED'
    assert response.json()['ledger_details']
    assert hashlib.sha256(call(api,'GET',f"/reports/{report['report_id']}/pdf").content).digest()==hashlib.sha256(pdf).digest()


def test_structured_culture_validation_draft_review_and_history(api):
    imported(api);mapping=ids(api);approve_synthetic(api,mapping,test_keys=['urine_culture'])
    order=create(api,'/lab-orders',{'patient_id':1,'priority':'ROUTINE','test_ids':[mapping['test_catalog','urine_culture']]})
    item=order['items'][0];sid=item['definition_snapshot']['specimens'][0]['sample_type_id']
    sp=create(api,f"/lab-orders/{order['order_id']}/specimens",{'sample_type_id':sid,'order_item_ids':[item['order_item_id']]})
    for action in ['collect','receive']:assert call(api,'POST',f"/specimens/{sp['specimen_id']}/{action}").status_code==200
    draft=create(api,f"/lab-order-items/{item['order_item_id']}/result",{'result_value':'Synthetic culture','specimen_id':sp['specimen_id']})
    path=f"/results/{draft['result_item_id']}"
    assert call(api,'POST',path+'/review').status_code==422
    values={'growth':'Synthetic growth','organisms':'Synthetic organism','method':'Synthetic method','susceptibility':[dict(organism='Synthetic organism',antimicrobial='Synthetic agent',measurement='10',unit='mm',interpretation='NOT_INTERPRETED',method='Synthetic method',standard='Synthetic test only')]}
    assert call(api,'PATCH',path,{'structured_values':{**values,'unconfigured':'bad'}}).status_code==422
    assert call(api,'PATCH',path,{'structured_values':values}).status_code==200
    assert call(api,'POST',path+'/review').status_code==200
    assert call(api,'PATCH',path,{'structured_values':{}}).status_code==409
    assert call(api,'PATCH',f"/lab/tests/{item['test_id']}",{'result_schema':{'fields':[]}}).status_code==409
    assert call(api,'GET',path).json()['structured_values']==values
    assert call(api,'POST',path+'/verify').status_code==200
    report=create(api,f"/lab-orders/{order['order_id']}/reports",{})
    profile=create(api,'/signatories',{'staff_id':1,'license_number_snapshot':'SYNTHETIC-NOT-CLINICAL'})
    assignment=create(api,f"/reports/{report['report_id']}/signatories",{'signatory_id':profile['signatory_id'],'signatory_type':'MEDICAL_TECHNOLOGIST'})
    assert sign(api,assignment_id=assignment['report_signatory_id'],report_id=report['report_id']).status_code==200
    assert call(api,'POST',f"/reports/{report['report_id']}/approve").status_code==200
    release(api,report['report_id'])
    pdf=call(api,'GET',f"/reports/{report['report_id']}/pdf").content
    rendered=' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert 'Synthetic growth' in rendered and 'Synthetic organism' in rendered and 'Synthetic agent' in rendered
    assert 'NOT_INTERPRETED' in rendered


def test_order_freezes_memberships_specimens_and_names(api):
    imported(api);mapping=ids(api);approve_synthetic(api,mapping,panel_keys=['cbc'])
    order=create(api,'/lab-orders',{'patient_id':1,'priority':'ROUTINE','panel_ids':[mapping['test_panel','cbc']]})
    original=order['items'][0]
    assert call(api,'PATCH',f"/lab/tests/{original['test_id']}",{'test_name':'Renamed after ordering'}).status_code==200
    assert call(api,'PUT',f"/lab/panels/{mapping['test_panel','cbc']}/tests",{'tests':[]}).status_code==200
    assert call(api,'PUT',f"/lab/tests/{original['test_id']}/sample-types",{'sample_types':[]}).status_code==200
    saved=call(api,'GET',f"/lab-orders/{order['order_id']}").json()
    assert saved['items']==order['items'] and saved['panels']==order['panels']


@pytest.mark.skipif(not __import__('os').environ.get('RHU_CATALOG_BROWSER_EXPORT'), reason='Explicit isolated browser export only')
def test_export_clinical_browser_fixture(api,monkeypatch):
    import os,shutil
    from pathlib import Path
    from app.config import settings
    from test_public_authenticity import issued
    target=Path(os.environ['RHU_CATALOG_BROWSER_EXPORT']).resolve()
    assert str(target).startswith('/tmp/rhu-scan-') and target.is_dir()
    imported(api);mapping=ids(api)
    approve_synthetic(api,mapping,panel_keys=['cbc_diff','urinalysis','comprehensive_metabolic','glycemic'],test_keys=['urine_culture'])
    monkeypatch.setattr(settings,'public_base_url','https://labchain.online')
    url,pdf=issued(api);ledger(api,monkeypatch)
    shutil.copyfile(api.engine.url.database,target/'synthetic.sqlite')
    shutil.copytree(settings.report_storage_dir,target/'reports',dirs_exist_ok=True)
    (target/'fixture.json').write_text(json.dumps({'token':url.rsplit('/',1)[1],'pdf_sha256':hashlib.sha256(pdf).hexdigest()}))
    (target/'catalog-ids.json').write_text(json.dumps({kind+':'+key:value for (kind,key),value in mapping.items()}))
    images=[image for page in PdfReader(BytesIO(pdf)).pages for image in page.images]
    assert len(images)==1
    (target/'synthetic-qr.png').write_bytes(images[0].data)


def test_specimen_label_is_private_audited_and_has_accession(api):
    from app.models import Permission, RolePermission, UserRole
    from sqlalchemy import delete
    order=create(api,'/lab-orders',{'patient_id':1,'priority':'ROUTINE','test_ids':[1]})
    sp=create(api,f"/lab-orders/{order['order_id']}/specimens",{'sample_type_id':1,'order_item_ids':[order['items'][0]['order_item_id']]})
    path=f"/specimens/{sp['specimen_id']}/label"
    response=call(api,'GET',path)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    reader=PdfReader(BytesIO(response.content)); text=reader.pages[0].extract_text()
    assert sp['specimen_code'] in text and 'Synthetic1' not in text
    assert b' re ' in reader.pages[0].get_contents().get_data()  # Code128 bar rectangles.
    with api.factory.begin() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='SPECIMEN_LABEL_VIEW'))==1
        permission=db.scalar(select(Permission.permission_id).where(Permission.permission_code=='SPECIMEN_READ'))
        db.execute(delete(RolePermission).where(RolePermission.permission_id==permission))
        db.execute(delete(UserRole).where(UserRole.user_id==1, UserRole.role_id==2))
    assert call(api,'GET',path).status_code==403
    api.client.cookies.clear()
    assert api.client.get('/api/v1'+path).status_code==401


def test_new_catalog_and_barcode_permissions_do_not_bypass_staff_boundary(api):
    from app.models import UserRole,Role,RolePermission,Permission
    from sqlalchemy import delete
    with api.factory.begin() as db:
        db.execute(delete(UserRole).where(UserRole.user_id==1,UserRole.role_id==2))
    assert call(api,'GET','/lab/catalog-browser').status_code==403
    assert call(api,'GET','/lab/clinical-catalog').status_code==403
    assert call(api,'POST','/lab/clinical-catalog',{'fingerprint':'a'*64,'acknowledge_inactive_review':True}).status_code==403
    api.client.cookies.clear()
    assert api.client.get('/api/v1/lab/catalog-browser').status_code==401


def test_manual_service_requires_explicit_facility_review(api):
    created=create(api,'/lab/tests',{'test_name':'SYNTHETIC new service','department_id':1,'result_type':'NUMERIC'})
    assert created['facility_status']=='UNREVIEWED' and not created['is_active']
    path=f"/lab/tests/{created['test_id']}"
    assert call(api,'PATCH',path,{'is_active':True}).status_code==409
    assert call(api,'PATCH',path,{'facility_status':'APPROVED','approval_note':'Synthetic SOP review'}).status_code==422
    approved=call(api,'PATCH',path,{'facility_status':'APPROVED','approval_note':'Synthetic SOP review','methodology':'Synthetic assay','default_unit':'mg/dL','is_active':True})
    assert approved.status_code==200 and approved.json()['is_active']
    changed=call(api,'PATCH',path,{'default_unit':'mmol/L'})
    assert changed.status_code==200 and changed.json()['facility_status']=='UNREVIEWED' and not changed.json()['is_active']
