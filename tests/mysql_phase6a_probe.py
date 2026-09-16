"""Native InnoDB probes on a disposable Unix socket, never the application DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import stat
import sys
from threading import Barrier

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.dependencies.patient import PatientContext
from app.models import (AuditLog, FacilityProfile, LabOrder, LabReport, Patient, PatientAccountLink,
    PatientActivationToken, Role, UserAccount, UserRole)
from app.schemas.patient_portal import ActivationRequest
from app.services import patient_activation_service as activation, patient_portal_service as portal
from app.services.auth_service import utc_now
from app.security.tokens import hash_token


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'issue', 'redeem', 'issue_redeem', 'username', 'stale_token', 'rollback', 'revoked', 'relinked'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db: db.execute(text('CREATE DATABASE phase6a_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase6a_synthetic', isolation_level='REPEATABLE READ', **options)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        # Exercise the real migration chain on MySQL, including the new table.
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
            for revision in reversed(list(scripts.walk_revisions())): revision.module.upgrade()
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='issuer', password_hash='not-a-password', account_status='ACTIVE'))
            db.add(Role(role_id=1, role_code='PATIENT', role_name='Patient', is_active=True))
            db.add_all(Patient(patient_id=i, patient_code=f'SYNTH-{i}', first_name='Synthetic', last_name=f'Patient{i}') for i in (1, 2))
        def issue(db, patient_id=1): return activation.issue_token(db, patient_id, 1, None).activation_token
        def redeem(db, token, username='patient'):
            return activation.activate(db, ActivationRequest(activation_token=token, username=username,
                password='Synthetic-password-123!'), None)
        with factory() as db: token = issue(db)
        if scenario == 'username':
            with factory() as db: token2 = issue(db, 2)
        if scenario in {'issue', 'redeem', 'issue_redeem', 'username'}:
            barrier = Barrier(2)
            def contend(number):
                with factory() as db:
                    # Establish older snapshots before contention.
                    list(db.scalars(select(PatientActivationToken)))
                    list(db.scalars(select(PatientAccountLink)))
                    list(db.scalars(select(UserAccount)))
                    barrier.wait(timeout=10)
                    try:
                        if scenario == 'issue' or (scenario == 'issue_redeem' and number == 1): issue(db)
                        else: redeem(db, token2 if scenario == 'username' and number == 2 else token)
                        return 200
                    except HTTPException as exc: return exc.status_code
            with ThreadPoolExecutor(max_workers=2) as pool: statuses = sorted(pool.map(contend, (1, 2)))
            expected = {'issue': [[200, 200]], 'redeem': [[200, 400]],
                'issue_redeem': [[200, 400], [200, 409]], 'username': [[200, 409]]}[scenario]
            assert statuses in expected, statuses
            with factory() as db:
                active = list(db.scalars(select(PatientActivationToken).where(PatientActivationToken.patient_id == 1,
                    PatientActivationToken.used_at.is_(None), PatientActivationToken.revoked_at.is_(None),
                    PatientActivationToken.expires_at > utc_now())))
                assert len(active) <= 1
                if scenario == 'issue':
                    assert len(active) == 1 and db.scalar(select(func.count()).select_from(PatientActivationToken)) == 3
                    assert db.scalar(select(func.count()).select_from(UserAccount)) == 1
                elif scenario in {'redeem', 'username'}:
                    assert db.scalar(select(func.count()).select_from(UserAccount)) == 2
                    assert db.scalar(select(func.count()).select_from(PatientAccountLink)) == 1
                    assert db.scalar(select(func.count()).select_from(UserRole)) == 1
                    assert db.scalar(select(func.count()).select_from(PatientActivationToken).where(PatientActivationToken.used_at.is_not(None))) == 1
        elif scenario == 'stale_token':
            with factory() as stale:
                old = stale.scalar(select(PatientActivationToken))
                with factory() as db: issue(db)
                try:
                    redeem(stale, token)
                    raise AssertionError('Stale revoked token accepted')
                except HTTPException as exc: assert exc.status_code == 400
        elif scenario == 'rollback':
            def fail_audit(connection, cursor, statement, params, context, executemany):
                if statement.startswith('INSERT INTO audit_log '): raise SQLAlchemyError('Synthetic rollback')
            event.listen(engine, 'before_cursor_execute', fail_audit)
            try:
                with factory() as db:
                    try:
                        redeem(db, token)
                        raise AssertionError('Expected failure')
                    except SQLAlchemyError: pass
            finally: event.remove(engine, 'before_cursor_execute', fail_audit)
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(UserAccount)) == 1
                assert db.scalar(select(PatientActivationToken)).used_at is None
                assert db.scalar(select(func.count()).select_from(PatientAccountLink)) == 0
                redeem(db, token)
        else:
            with factory() as db: account = redeem(db, token)
            now = utc_now()
            with factory.begin() as db:
                db.add(FacilityProfile(facility_id=1, facility_name='Synthetic RHU'))
                db.add(LabOrder(order_id=1, order_code='SYNTH', patient_id=1, order_date=now, status='COMPLETED', priority='ROUTINE'))
                db.flush()
                db.add(LabReport(report_id=1, report_code='SYNTH', order_id=1, facility_id=1, version_no=1,
                    report_status='RELEASED', generated_by_user_id=1, generated_at=now, released_at=now))
            with factory() as stale:
                context = PatientContext(user_id=account.user_id, patient=stale.get(Patient, 1))
                stale.scalar(portal.owned_reports(context))
                with factory.begin() as db:
                    if scenario == 'revoked': db.get(LabReport, 1).report_status = 'REVOKED'
                    else: db.get(PatientAccountLink, 1).user_id = 1
                try:
                    portal.require_patient_report_ownership(stale, context, 1)
                    raise AssertionError('Stale ownership or status accepted')
                except HTTPException as exc: assert exc.status_code == 404
        print('patient activation and ownership checks passed')
    finally:
        with engine.begin() as db: db.execute(text('DROP DATABASE phase6a_synthetic'))
        engine.dispose()


if __name__ == '__main__': main(*sys.argv[1:])
