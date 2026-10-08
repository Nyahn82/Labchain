"""Isolated policy/transaction tests; never connect to application DB settings."""
import json

import pytest
from sqlalchemy import Integer, MetaData, create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.cli import bootstrap_role_permissions as cli
from app.models import Base, Permission, Role, RolePermission, Staff, Patient, UserAccount, UserRole
from app.services import role_permission_matrix as matrix
from app.services.auth_service import utc_now
from app.services.permission_catalog import PERMISSION_CATALOG, ensure_permissions
from app.services.rbac_service import ensure_core_roles

STAFF = set('''PATIENT_READ PATIENT_CREATE PATIENT_UPDATE PHYSICIAN_READ LAB_MASTER_READ
LAB_ORDER_READ LAB_ORDER_CREATE PAYMENT_READ SPECIMEN_READ SPECIMEN_REGISTER SPECIMEN_COLLECT
SPECIMEN_RECEIVE LAB_RESULT_READ LAB_RESULT_ENTER REPORT_READ REPORT_DOWNLOAD REPORT_PRINT'''.split())
EXTRA = set('''LAB_ORDER_CANCEL SPECIMEN_REJECT REJECTION_REASON_MANAGE LAB_RESULT_REVIEW
LAB_RESULT_VERIFY REPORT_GENERATE REPORT_TEMPLATE_READ SIGNATORY_READ SIGNATORY_MANAGE
REPORT_APPROVE REPORT_RELEASE REPORT_REVISE REPORT_REVOKE ANALYTICS_VIEW BLOCKCHAIN_STATUS_VIEW'''.split())


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "rbac.sqlite"}', hide_parameters=True)
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        clone = table.to_metadata(metadata)
        for column in clone.primary_key:
            if column.autoincrement is True:
                column.type = Integer()
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory.begin() as db:
        ensure_core_roles(db)
        ensure_permissions(db)
    yield factory
    engine.dispose()


def grant(factory, role_code, code):
    with factory.begin() as db:
        role = db.scalar(select(Role).where(Role.role_code == role_code))
        permission = db.scalar(select(Permission).where(Permission.permission_code == code))
        db.add(RolePermission(role_id=role.role_id, permission_id=permission.permission_id))


def snapshot(factory):
    with factory() as db:
        return {table.name: [tuple(row) for row in db.execute(select(table))]
                for table in Base.metadata.sorted_tables}


def test_exact_approved_policy():
    assert matrix.ROLE_PERMISSION_MATRIX_VERSION == '1.0.0'
    assert matrix.ROLE_PERMISSION_MATRIX == {
        'LAB_STAFF': STAFF, 'LAB_SUPERVISOR': STAFF | EXTRA, 'LAB_SIGNER': {'REPORT_SIGN'}}
    assert len(STAFF) == 17 and len(STAFF | EXTRA) == 32 and STAFF <= STAFF | EXTRA
    assert 'REPORT_SIGN' not in STAFF | EXTRA
    assert matrix.UNMANAGED_ROLES == {'SYSTEM_ADMIN', 'PATIENT', 'DOCTOR'}
    assert all(codes <= {r[0] for r in PERMISSION_CATALOG} for codes in matrix.ROLE_PERMISSION_MATRIX.values())
    with pytest.raises(TypeError):
        matrix.ROLE_PERMISSION_MATRIX['DOCTOR'] = frozenset()


def test_role_metadata_is_idempotent_and_preserves_existing(factory):
    with factory.begin() as db:
        role = db.scalar(select(Role).where(Role.role_code == 'LAB_SIGNER'))
        assert role.role_name == 'Laboratory Signer'
        assert role.description == 'Identity-bound laboratory report signing capability.'
        role.role_name, role.is_active = 'Existing name', False
    with factory.begin() as db:
        assert ensure_core_roles(db) == []
    with factory() as db:
        role = db.scalar(select(Role).where(Role.role_code == 'LAB_SIGNER'))
        assert role.role_name == 'Existing name' and not role.is_active
        assert not list(db.scalars(select(RolePermission)))


def test_default_cli_preflight_no_writes(factory, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, 'SessionLocal', factory)
    before = snapshot(factory)
    statements = []
    def trace(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(factory.kw['bind'], 'before_cursor_execute', trace)
    try:
        assert cli.main(['--receipt-file', str(tmp_path / 'unused')]) == 0
    finally:
        event.remove(factory.kw['bind'], 'before_cursor_execute', trace)
    assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
    assert snapshot(factory) == before and not (tmp_path / 'unused').exists()
    output = capsys.readouterr().out
    assert 'PREFLIGHT_ONLY' in output and 'assignment_count' in output
    assert cli.parse_args([]).execute is False


@pytest.mark.parametrize('change', ['missing_role', 'inactive_role', 'missing_permission', 'unknown_permission', 'extra_grant'])
def test_unsafe_preflight_refuses_execute(factory, change):
    with factory.begin() as db:
        role = db.scalar(select(Role).where(Role.role_code == 'LAB_SIGNER'))
        if change == 'missing_role':
            db.delete(role)
        elif change == 'inactive_role':
            role.is_active = False
        elif change == 'missing_permission':
            db.delete(db.scalar(select(Permission).where(Permission.permission_code == 'REPORT_SIGN')))
        elif change == 'unknown_permission':
            db.add(Permission(permission_code='UNKNOWN', permission_name='Unknown'))
    if change == 'extra_grant':
        grant(factory, 'LAB_SIGNER', 'REPORT_READ')
    before = snapshot(factory)
    plan = matrix.preflight(factory)
    assert not plan['safe_to_execute']
    with pytest.raises(matrix.MatrixError):
        matrix.execute_matrix(factory, plan)
    assert snapshot(factory) == before


def test_partial_state_only_adds_missing_and_is_idempotent(factory):
    grant(factory, 'LAB_STAFF', 'PATIENT_READ')
    plan = matrix.preflight(factory)
    assert plan == matrix.preflight(factory)
    staff = next(r for r in plan['roles'] if r['role_code'] == 'LAB_STAFF')
    assert staff['current_count'] == 1 and staff['expected_count'] == 17
    assert staff['missing_grants'] == sorted(STAFF - {'PATIENT_READ'})
    added = matrix.execute_matrix(factory, plan)
    assert len(added) == 49
    assert matrix.execute_matrix(factory, matrix.preflight(factory)) == []
    with factory() as db:
        rows = list(db.scalars(select(RolePermission)))
        assert len(rows) == 50 and len({(r.role_id, r.permission_id) for r in rows}) == 50


def test_only_managed_grant_rows_change(factory):
    for code in matrix.UNMANAGED_ROLES:
        grant(factory, code, 'ACCOUNT_READ')
    with factory.begin() as db:
        db.add(UserAccount(user_id=1, username='synthetic', password_hash='synthetic', account_status='ACTIVE'))
        db.add(Staff(staff_id=1, staff_code='SYNTHETIC', first_name='Test', last_name='Staff'))
        db.add(Patient(patient_id=1, patient_code='SYNTHETIC', first_name='Test', last_name='Patient'))
        db.flush()
        role = db.scalar(select(Role).where(Role.role_code == 'LAB_STAFF'))
        db.add(UserRole(user_id=1, role_id=role.role_id, assigned_at=utc_now()))
    before = snapshot(factory)
    plan = matrix.preflight(factory)
    assert next(r for r in plan['roles'] if r['role_code'] == 'LAB_STAFF')['assignment_count'] == 1
    assert len(matrix.execute_matrix(factory, plan)) == 50
    after = snapshot(factory)
    assert {k: v for k, v in before.items() if k != 'role_permission'} == {
        k: v for k, v in after.items() if k != 'role_permission'}
    assert set(before['role_permission']) <= set(after['role_permission'])


def test_injected_partial_failure_rolls_back(factory):
    before = snapshot(factory)
    def fail(db, context, instances):
        if db.scalar(select(RolePermission.role_permission_id)) is not None:
            raise RuntimeError('synthetic failure after an insertion')
    event.listen(factory, 'before_flush', fail)
    try:
        with pytest.raises(RuntimeError):
            matrix.execute_matrix(factory, matrix.preflight(factory))
    finally:
        event.remove(factory, 'before_flush', fail)
    assert snapshot(factory) == before


def test_evidence_failure_rolls_back(factory):
    def fail(rows):
        assert len(rows) == 50
        raise OSError('Synthetic evidence failure')
    with pytest.raises(OSError):
        matrix.execute_matrix(factory, matrix.preflight(factory), record_prepared=fail)
    assert all(r['current_count'] == 0 for r in matrix.preflight(factory)['roles'])


def test_changed_state_refused(factory):
    old = matrix.preflight(factory)
    grant(factory, 'LAB_STAFF', 'PATIENT_READ')
    before = snapshot(factory)
    with pytest.raises(matrix.MatrixError, match='changed'):
        matrix.execute_matrix(factory, old)
    assert snapshot(factory) == before


def test_cli_execute_receipt_and_second_no_changes(factory, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, 'SessionLocal', factory)
    first, second = tmp_path / 'first.json', tmp_path / 'second.json'
    assert cli.main(['--execute', '--receipt-file', str(first)]) == 0
    receipt = json.loads(first.read_text())
    assert receipt['state'] == 'COMMITTED' and len(receipt['added']) == 50
    assert first.stat().st_mode & 0o777 == 0o600
    assert all(set(r) == {'role_permission_id', 'role_id', 'role_code', 'permission_id', 'permission_code'}
               for r in receipt['added'])
    assert cli.main(['--execute', '--receipt-file', str(second)]) == 0
    assert 'NO_CHANGES' in capsys.readouterr().out
    before = snapshot(factory)
    assert cli.main(['--execute', '--receipt-file', str(first)]) == 1
    assert snapshot(factory) == before


def test_unmanaged_roles_remain_empty_in_clean_environment(factory):
    matrix.execute_matrix(factory, matrix.preflight(factory))
    with factory() as db:
        assert not list(db.scalars(select(RolePermission).join(Role).where(Role.role_code.in_(matrix.UNMANAGED_ROLES))))
    assert matrix.preflight(factory)['action'] == 'NO_CHANGES'


def test_same_count_assignment_replacement_invalidates_plan(factory):
    with factory.begin() as db:
        for uid in (1, 2):
            db.add(UserAccount(user_id=uid, username=f'user-{uid}', password_hash='synthetic', account_status='ACTIVE'))
        db.flush()
        rid = db.scalar(select(Role.role_id).where(Role.role_code == 'LAB_STAFF'))
        db.add(UserRole(user_id=1, role_id=rid, assigned_at=utc_now()))
    old = matrix.preflight(factory)
    with factory.begin() as db:
        db.scalar(select(UserRole)).user_id = 2
    with pytest.raises(matrix.MatrixError, match='changed'):
        matrix.execute_matrix(factory, old)
    assert all(r['current_count'] == 0 for r in matrix.preflight(factory)['roles'])


def test_missing_administration_mutex_preflight_refuses(factory):
    with factory.begin() as db:
        db.delete(db.scalar(select(Role).where(Role.role_code == 'SYSTEM_ADMIN')))
    assert not matrix.preflight(factory)['safe_to_execute']
