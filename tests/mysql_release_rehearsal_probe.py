"""Real A+D migration/recovery checks, exclusively on a fixture-owned Unix socket.

Never uses application database settings, a host socket, or the populated rehearsal
schema. Ordinary invocation is through test_native_release_rehearsal.py.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from threading import Barrier
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from pypdf import PdfReader
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from scripts import mysql_migration_rehearsal as old
from scripts.mysql_auto_code_probe import check, expect_error, load_migration

ROOT = Path(__file__).resolve().parents[1]
DATABASES = {'rhu_release_success', 'rhu_release_restored', 'rhu_release_seed_failure',
             'rhu_release_revision_failure', 'rhu_release_pdf_failure', 'rhu_release_seed_recovered',
             'rhu_release_revision_recovered', 'rhu_release_pdf_recovered'}
NOW = datetime(2026, 10, 19, 0, 0)


def validated_socket(value):
    socket = Path(value).resolve()
    check(socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-'),
          'Only the disposable fixture directory is permitted.')
    check(stat.S_ISSOCK(socket.stat().st_mode), 'Expected a native Unix socket.')
    check(socket.parent.stat().st_uid == os.getuid() and socket.parent.stat().st_mode & 0o077 == 0,
          'Fixture directory must be private and owned by this user.')
    return socket


@contextmanager
def release_config(connection, root):
    # Reuse the credential-free connection-only env, retaining every revision byte.
    with tempfile.TemporaryDirectory(prefix='alembic-', dir=root) as directory:
        folder = Path(directory)
        (folder / 'env.py').write_text(old.ENVIRONMENT)
        shutil.copytree(ROOT / 'migrations/versions', folder / 'versions',
                        ignore=shutil.ignore_patterns('__pycache__'))
        cfg = Config()
        cfg.set_main_option('script_location', str(folder))
        cfg.attributes['verified_connection'] = connection
        script = ScriptDirectory.from_config(cfg)
        revisions = list(reversed(list(script.walk_revisions())))
        check(tuple(r.revision for r in revisions) == old.REVISIONS + ('20261018_01',), 'Unexpected release chain.')
        check(script.get_heads() == ['20261018_01'], 'Unexpected release head.')
        for i, revision in enumerate(revisions):
            check(revision.down_revision == (revisions[i-1].revision if i else None), 'Nonlinear chain.')
        yield cfg


def rows_snapshot(connection):
    metadata = sa.MetaData()
    metadata.reflect(connection)
    return {name: sorted(json.dumps(dict(row), default=str, sort_keys=True)
                        for row in connection.execute(sa.select(table)).mappings())
            for name, table in metadata.tables.items()}


def historical_reports(connection, files):
    # Current model includes D's column; the baseline must use reflected old DDL.
    md = sa.MetaData()
    md.reflect(connection)
    def insert(table, **values):
        connection.execute(md.tables[table].insert().values(**values))
    insert('user_account', user_id=501, username='release-synthetic', password_hash='not-a-login', account_status='ACTIVE')
    insert('facility_profile', facility_id=501, facility_name='Synthetic Rehearsal RHU')
    insert('staff_account_link', staff_id=1, user_id=501)
    insert('signatory', signatory_id=501, staff_id=1, license_number_snapshot='SYNTHETIC')
    for identifier in (501, 502, 503):
        insert('lab_order', order_id=identifier, order_code=f'SYN-ORDER-{identifier}', patient_id=1,
               order_date=NOW, priority='ROUTINE', status='COMPLETED')
        insert('lab_order_item', order_item_id=identifier, order_id=identifier, test_id=1, status='COMPLETED')
        insert('lab_result_item', result_item_id=identifier, order_item_id=identifier, result_value='5',
               flag='NORMAL', status='VERIFIED', encoded_by_user_id=501, encoded_at=NOW,
               reviewed_by_user_id=501, reviewed_at=NOW, verified_by_user_id=501, verified_at=NOW)
    for identifier in (501, 502):
        values = dict(report_id=identifier, report_code=f'SYN-REPORT-{identifier}', order_id=identifier,
                      facility_id=501, template_id=1, version_no=1, generated_by_user_id=501, generated_at=NOW,
                      report_status='RELEASED' if identifier == 501 else 'GENERATED')
        if identifier == 501:
            values.update(approved_by_user_id=501, approved_at=NOW, released_by_user_id=501,
                          released_at=NOW, pdf_path='historical/501.pdf')
        insert('lab_report', **values)
        insert('report_patient_snapshot', report_id=identifier, patient_code='PAT-000007', patient_name='Synthetic Patient')
        insert('report_result_item', report_id=identifier, result_item_id=identifier,
               test_name_snapshot='Historical Test', result_value_snapshot='5', flag_snapshot='NORMAL', sort_order=1)
    insert('report_signatory', report_id=501, signatory_id=501, signatory_type='PATHOLOGIST', signed_at=NOW, sort_order=1)
    from app.services import report_pdf
    ns = SimpleNamespace
    detail = ns(facility=ns(facility_name='Synthetic Rehearsal RHU', facility_type=None, address=None,
                           contact_number=None, email=None, website=None), template=None,
                patient_snapshot=ns(patient_name='Synthetic Patient', patient_code='PAT-000007', sex=None,
                                    birth_date=None, age_at_report=None, physician_name=None),
                report_code='SYN-REPORT-501', version_no=1, generated_at=NOW, signatories=[],
                result_snapshots=[ns(section_name_snapshot=None, flag_snapshot='NORMAL', test_name_snapshot='Historical Test',
                                     result_value_snapshot='5', unit_snapshot=None, reference_range_snapshot=None)])
    pdf = report_pdf.render_pdf(detail, 'https://synthetic.example.test/api/v1/verify/'+'a'*43, NOW)
    (files / 'historical').mkdir()
    (files / 'historical/501.pdf').write_bytes(pdf)
    insert('report_verification', report_id=501, verification_token='a'*43,
           report_hash=hashlib.sha256(pdf).hexdigest(), verification_status='AUTHENTIC', created_at=NOW)
    connection.commit()
    return pdf


def allocation_checks(engine):
    from app.models import CodeSequence, Patient
    from app.services.code_generation_service import allocate_code, MAX_COUNTER
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        start = db.get(CodeSequence, 'PATIENT').current_value
        staff_start = db.get(CodeSequence, 'STAFF').current_value
    with factory() as db:
        check([allocate_code(db, 'PATIENT') for _ in range(3)] == [f'PAT-{i:06d}' for i in range(start+1, start+4)],
              'Repeated allocations are stale.')
        db.rollback()
    with factory() as db:
        check(db.get(CodeSequence, 'PATIENT').current_value == start, 'Rollback consumed values.')
    barrier = Barrier(20, timeout=30)
    def worker(_):
        with factory.begin() as db:
            identifier = db.scalar(sa.text('SELECT CONNECTION_ID()'))
            barrier.wait()
            code = allocate_code(db, 'PATIENT')
            db.add(Patient(patient_code=code, first_name='Synthetic', last_name='Concurrent'))
            return identifier, code
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(worker, range(20)))
    check(len({i for i,c in results}) == len({c for i,c in results}) == 20, 'Concurrent connections/codes not unique.')
    with factory() as db:
        check(db.get(CodeSequence, 'PATIENT').current_value == start+20, 'Counter did not persist.')
        check(db.get(CodeSequence, 'STAFF').current_value == staff_start, 'Independent counter changed.')
    with expect_error(sa.exc.IntegrityError):
        with factory.begin() as db:
            allocate_code(db, 'PATIENT')
            db.add(Patient(patient_code=results[0][1], first_name='Synthetic', last_name='Collision'))
    with factory() as db:
        check(db.get(CodeSequence, 'PATIENT').current_value == start+20, 'Collision consumed value.')
        with expect_error(RuntimeError): allocate_code(db, 'MISSING')
        db.rollback()
    # Exercise actual capacity bounds inside rolled-back transactions, preserving seeds.
    for key, limit in [('PATIENT', 9_999_999_999_999_999), ('DEPARTMENT', MAX_COUNTER)]:
        with factory() as db:
            sequence = db.get(CodeSequence, key)
            sequence.current_value = limit-1
            db.flush([sequence])
            check(allocate_code(db, key).endswith(str(limit)), 'Last fitting code unavailable.')
            with expect_error(RuntimeError): allocate_code(db, key)
            check(sequence.current_value == limit, 'Exhaustion mutated counter.')
            db.rollback()
    print('PASS allocation_concurrency_and_rollback')


def immutable_contracts(engine):
    from app.schemas import identity, laboratory, workflow, reporting
    cases = [(identity.PatientCreate, identity.PatientPatch, 'patient_code', dict(first_name='Synthetic',last_name='Patient')),
             (identity.StaffCreate, identity.StaffPatch, 'staff_code', dict(first_name='Synthetic',last_name='Staff')),
             (laboratory.DepartmentCreate, laboratory.DepartmentPatch, 'department_code', dict(department_name='Synthetic')),
             (laboratory.TestCreate, laboratory.TestPatch, 'test_code', dict(test_name='Synthetic',department_id=1,result_type='TEXT')),
             (laboratory.PanelCreate, laboratory.PanelPatch, 'panel_code', dict(panel_name='Synthetic')),
             (workflow.ReasonCreate, workflow.ReasonPatch, 'reason_code', dict(reason_name='Synthetic')),
             (reporting.TemplateCreate, reporting.TemplatePatch, 'template_code', dict(template_name='Synthetic'))]
    with engine.connect() as c: before = old.historical_snapshot(c, load_migration())
    for create, patch, field, payload in cases:
        for cls, data in [(create, {**payload,field:'MANUAL'}),(patch,{field:'CHANGED'})]:
            with expect_error(ValidationError): cls.model_validate(data)
    with engine.connect() as c: check(old.historical_snapshot(c, load_migration()) == before, 'Validation changed identifiers.')
    print('PASS immutable_codes')


def verify_pdfs(engine, files, original):
    from app.config import settings
    from app.models import LabReport, ReportVerification
    from app.schemas import reporting as s
    from app.services import reporting_service as reports, report_release_service as release
    from app.cli.bootstrap_blockchain_nodes import ensure_blockchain_nodes
    settings.report_storage_dir = files
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory.begin() as db: ensure_blockchain_nodes(db)
    with factory() as db:
        old_report = db.get(LabReport, 501)
        verification = db.scalar(sa.select(ReportVerification).where(ReportVerification.report_id==501))
        check(release.integrity_bytes(db, old_report, verification, 501, None) == original, 'Historical PDF changed.')
        check(old_report.presentation_snapshot is None, 'Old presentation was backfilled.')
        check(reports.report_detail(db, 502)._presentation is None, 'Legacy draft no longer uses v1.')
    def sign_and_release(report_id):
        with factory() as db:
            link = reports.assign_signatory(db, report_id, s.AssignRequest(signatory_id=501,signatory_type='PATHOLOGIST'),501,None)
            reports.sign_report(db,report_id,s.SignRequest(report_signatory_id=link.report_signatory_id),501,None)
            reports.approve_report(db,report_id,501,None)
            return release.release_report(db,report_id,501,None)
    legacy = sign_and_release(502)
    with factory() as db:
        fresh = reports.generate_report(db,503,s.GenerateRequest(template_id=1),501,None)
        check(fresh._presentation['renderer']==2, 'New report missing v2 snapshot.')
    current = sign_and_release(fresh.report_id)
    def content(row): return '\n'.join(p.extract_text() for p in PdfReader(BytesIO((files/row.pdf_path).read_bytes())).pages)
    check('PDF v2' not in content(legacy) and 'PDF v2' in content(current), 'Wrong renderer selected.')
    check((files/'historical/501.pdf').read_bytes()==original,'Release rewrote historical artifact.')
    print('PASS legacy_and_new_pdf')


def main(socket_value):
    socket = validated_socket(socket_value)
    options = dict(hide_parameters=True, connect_args={'unix_socket':str(socket),'connect_timeout':5},
                   pool_size=25, max_overflow=0)
    def engine_for(database=''):
        check(not database or database in DATABASES, 'Database is outside the disposable allowlist.')
        return sa.create_engine('mysql+pymysql://root@localhost/'+database, **options)
    admin = engine_for()
    with admin.connect() as c:
        identity = c.execute(sa.text('SELECT @@socket,@@datadir,@@skip_networking,VERSION()')).one()
        check(Path(identity[0]).resolve()==socket and Path(identity[1]).resolve()==socket.parent/'data' and identity[2]==1,
              'Server identity differs from disposable fixture.')
        check(not c.scalar(sa.text("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME IN ('rhu_labchain','rhu_labchain_dev')")),
              'Unexpected application/rehearsal schema in disposable server.')
        check(not set(c.scalars(sa.text('SHOW DATABASES'))) & DATABASES,'Disposable schemas already exist.')
    with tempfile.TemporaryDirectory(prefix='release-',dir=socket.parent) as directory:
        root=Path(directory); files=root/'reports'; files.mkdir(mode=0o700)
        from app.config import settings
        settings.report_storage_dir=files
        settings.report_signature_dir=settings.report_logo_dir=None
        settings.public_base_url='https://synthetic.example.test'
        os.environ[old.FLAG]='1'  # Only this isolated process, after server identity verification.
        def create(database):
            check(database in DATABASES,'Unexpected database.')
            with admin.begin() as c: c.exec_driver_sql(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4')
            return engine_for(database)
        engine=create('rhu_release_success')
        migration=load_migration()
        with engine.connect() as c, release_config(c,root) as cfg:
            command.upgrade(cfg,old.PARENT)
            expected=old.prepare_history(c,migration)
            original=historical_reports(c,files)
            baseline=rows_snapshot(c); c.rollback()
            check(c.scalar(sa.text('SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND DB=DATABASE()'))==0,
                  'Unexpected concurrent writer.')
            c.rollback()
            with admin.begin() as a:
                a.exec_driver_sql("CREATE USER 'release_observer'@'localhost'")
                a.exec_driver_sql('GRANT SELECT ON rhu_release_success.* TO release_observer@localhost')
            observer=sa.create_engine('mysql+pymysql://release_observer@localhost/rhu_release_success',**options)
            try:
                with observer.begin() as ro:
                    check(ro.scalar(sa.text('SELECT COUNT(*) FROM patient')) == 6, 'Observer cannot read synthetic fixtures.')
                    try:
                        ro.exec_driver_sql("UPDATE patient SET first_name='FORBIDDEN' WHERE patient_id=1")
                    except sa.exc.DBAPIError as exc:
                        check(exc.orig.args[0] == 1142, 'Expected explicit UPDATE permission denial.')
                    else:
                        raise AssertionError('Observer unexpectedly wrote a record.')
            finally: observer.dispose()
            check(rows_snapshot(c)==baseline,'Denied write changed baseline.'); c.rollback()
            print('PASS writer_exclusion')
            dump=root/'baseline.sql'
            with dump.open('wb') as out:
                subprocess.run(['mysqldump','--no-defaults','--protocol=SOCKET',f'--socket={socket}','--user=root',
                                '--single-transaction','--no-tablespaces','--set-gtid-purged=OFF','rhu_release_success'],
                               stdout=out,stderr=subprocess.PIPE,check=True,timeout=30)
            backup_files=root/'files-backup'; shutil.copytree(files,backup_files)
            def restore(database):
                target=create(database)
                with dump.open('rb') as inp:
                    subprocess.run(['mysql','--no-defaults','--protocol=SOCKET',f'--socket={socket}','--user=root',database],
                                   stdin=inp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=30)
                with target.connect() as restored: check(rows_snapshot(restored)==baseline,'Database restore differs.')
                restored_files=root/(database+'-files'); shutil.copytree(backup_files,restored_files)
                check((restored_files/'historical/501.pdf').read_bytes()==original,'File restore differs.')
                return target
            restored=restore('rhu_release_restored'); restored.dispose()
            print('PASS historical_backup_restore')
            old.refusal_scenario(c,cfg,migration,value='PAT-０００９９９',table='patient',column='patient_code',expected_error='Ambiguous historical identifier')
            old.refusal_scenario(c,cfg,migration,value='REJ-9223372036854775808',table='rejection_reason',column='reason_code',expected_error='exceeds sequence capacity')
            old.upgrade_and_verify(c,cfg,migration,expected,'success'); c.rollback()
            print('PASS automatic_code_upgrade')
            before=rows_snapshot(c); c.rollback()
            command.upgrade(cfg,'20261018_01')
            after=rows_snapshot(c)
            for table in before:
                if table not in {'alembic_version','lab_report'}: check(after[table]==before[table],'Upgrade changed historical rows.')
            report_rows=[json.loads(row) for row in after['lab_report']]
            check(all(row.pop('presentation_snapshot') is None for row in report_rows), 'PDF migration backfilled history.')
            check(sorted(json.dumps(row, sort_keys=True) for row in report_rows)==before['lab_report'],
                  'PDF migration changed existing report columns.')
            c.rollback(); command.upgrade(cfg,'20261018_01')
            check(rows_snapshot(c)==after,'Repeated final upgrade changed records.'); c.rollback()
            print('PASS pdf_upgrade_preservation')
        allocation_checks(engine)
        immutable_contracts(engine)
        verify_pdfs(engine,files,original)
        engine.dispose()
        for scenario in ('seed','revision','pdf'):
            database='rhu_release_'+scenario+'_failure'
            target=restore(database)
            with target.connect() as c, release_config(c,root) as cfg:
                if scenario in ('seed','revision'):
                    old.upgrade_and_verify(c,cfg,migration,expected,scenario+'-failure'); c.rollback()
                else:
                    command.upgrade(cfg,old.HEAD)
                    def fail_version(conn,cursor,statement,params,context,executemany):
                        if statement.strip().lower().startswith('update alembic_version'): raise old.InjectedFailure()
                    sa.event.listen(c,'before_cursor_execute',fail_version)
                    try:
                        with expect_error(old.InjectedFailure): command.upgrade(cfg,'20261018_01')
                    finally: sa.event.remove(c,'before_cursor_execute',fail_version)
                    c.rollback()
                    check(old.revision(c)==(old.HEAD,),'Failed PDF migration advanced version.')
                    check('presentation_snapshot' in {col['name'] for col in sa.inspect(c).get_columns('lab_report')},'Expected partial DDL missing.')
                    c.rollback()
            # Actually restore again after each failure, into a NEW allowlisted schema.
            # Leave the failed schema untouched so recovery never hides partial DDL.
            recovered = restore('rhu_release_'+scenario+'_recovered')
            recovered.dispose()
            check((backup_files/'historical/501.pdf').read_bytes()==original,'Recovery PDF changed.')
            target.dispose()
            print('PASS '+scenario+'_failure_restore')
    admin.dispose()
    print('COMBINED_RELEASE_REHEARSAL=PASS; fixture destroys only its private server directory')


if __name__=='__main__':
    main(sys.argv[1])
