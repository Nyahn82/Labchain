"""Real MySQL locking tests on an ephemeral Unix socket; never use production.

The subprocess probe only knows the disposable socket, not app DB credentials.
Hosts without mysqld skip these tests; API and offline DDL tests still run.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import pytest


@pytest.fixture(scope='module')
def disposable_mysql():
    executable = shutil.which('mysqld')
    if executable is None:
        pytest.skip('mysqld is needed for isolated MySQL concurrency verification')
    with tempfile.TemporaryDirectory(prefix='rhu-phase3b-mysql-', dir='/tmp') as directory:
        root = Path(directory)
        socket = root / 'mysql.sock'
        common = [executable, '--no-defaults', f'--datadir={root / "data"}',
                  f'--log-error={root / "error.log"}']
        # --no-defaults and --skip-networking isolate this instance from host config
        # and every TCP port, including production MySQL and the MySQL X plugin.
        subprocess.run(common + ['--initialize-insecure'], check=True, capture_output=True, timeout=60)
        process = subprocess.Popen(common + [
            '--skip-networking', '--mysqlx=OFF', f'--socket={socket}', f'--pid-file={root / "mysql.pid"}',
            '--innodb-buffer-pool-size=32M', '--innodb-redo-log-capacity=16M', '--performance-schema=OFF',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 30
            while not socket.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail('Disposable MySQL did not start: ' + (root / 'error.log').read_text()[-3000:])
                time.sleep(0.1)
            yield str(socket)
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize('scenario', ['disable', 'roles', 'mixed', 'account', 'login_disable'])
def test_mysql_concurrency(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_phase3b_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'concurrency checks passed' in result.stdout
