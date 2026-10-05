"""Unapplied production migration verified against disposable databases only."""
from io import StringIO
from pathlib import Path
import os
import subprocess
import sys
import shutil
import tempfile
import time
from alembic import command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from test_phase_2a_migration import config, revision, HEAD, PHASE_8B


@pytest.fixture(scope='module')
def disposable_mysql():
    executable = shutil.which('mysqld')
    if executable is None:
        pytest.skip('mysqld is required for the isolated native migration test')
    with tempfile.TemporaryDirectory(prefix='rhu-phase3b-mysql-', dir='/tmp') as directory:
        root = Path(directory)
        socket = root / 'mysql.sock'
        common = [executable, '--no-defaults', f'--datadir={root / "data"}',
                  f'--log-error={root / "error.log"}', '--innodb-buffer-pool-size=32M',
                  '--innodb-redo-log-capacity=16M', '--performance-schema=OFF']
        try:
            subprocess.run(common + ['--initialize-insecure'], check=True, capture_output=True, timeout=180)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pytest.fail('Disposable initialization failed: ' + (root / 'error.log').read_text()[-3000:])
        process = subprocess.Popen(common + ['--skip-networking', '--mysqlx=OFF',
            f'--socket={socket}', f'--pid-file={root / "mysql.pid"}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 30
            while not socket.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail('Disposable MySQL failed to start: ' + (root / 'error.log').read_text()[-3000:])
                time.sleep(0.1)
            yield str(socket)
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)



def test_chain_and_offline_mysql_upgrade():
    assert ScriptDirectory.from_config(config()).get_heads() == [HEAD] == ['20261005_01']
    assert revision(HEAD).down_revision == PHASE_8B
    output = StringIO()
    command.upgrade(config(output), f'{PHASE_8B}:{HEAD}', sql=True)
    sql = output.getvalue()
    assert "ENUM('ACTIVE','INACTIVE','LOCKED','SUSPENDED','DISABLED')" in sql
    assert 'ON DELETE SET NULL' in sql and 'suspension_reason VARCHAR(500)' in sql
    assert 'UPDATE user_account' not in sql and 'CREATE TABLE' not in sql
    with pytest.raises(RuntimeError, match='online data preservation'):
        command.downgrade(config(StringIO()), f'{HEAD}:{PHASE_8B}', sql=True)


def test_sqlite_preserves_legacy_and_refuses_lossy_downgrade(monkeypatch):
    from app import database
    engine = sa.create_engine('sqlite://')
    monkeypatch.setattr(database, 'engine', engine)
    cfg = config()
    command.upgrade(cfg, PHASE_8B)
    with engine.begin() as db:
        db.execute(sa.text("INSERT INTO user_account (user_id,username,password_hash,account_status) VALUES (1,'legacy','synthetic','INACTIVE')"))
    command.upgrade(cfg, HEAD)
    with engine.begin() as db:
        assert db.scalar(sa.text('SELECT account_status FROM user_account')) == 'INACTIVE'
        db.execute(sa.text("UPDATE user_account SET account_status='SUSPENDED', suspension_reason='preserve history'"))
    with pytest.raises(RuntimeError, match='downgrade refused'):
        command.downgrade(cfg, PHASE_8B)
    with engine.begin() as db:
        assert MigrationContext.configure(db).get_current_revision() == HEAD
        db.execute(sa.text("UPDATE user_account SET account_status='ACTIVE'"))
    with pytest.raises(RuntimeError, match='downgrade refused'):
        command.downgrade(cfg, PHASE_8B)
    with engine.begin() as db:
        db.execute(sa.text('UPDATE user_account SET suspension_reason=NULL'))
    command.downgrade(cfg, PHASE_8B)
    assert 'suspension_reason' not in {c['name'] for c in sa.inspect(engine).get_columns('user_account')}
    engine.dispose()


def test_native_mysql_migration_queries_and_login_serialization(disposable_mysql):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'tests/mysql_phase10_probe.py'), disposable_mysql],
        cwd=root, env={**os.environ, 'PYTHONPATH':str(root)}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Phase 10 isolated MySQL checks passed' in result.stdout
