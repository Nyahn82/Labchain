"""Native MySQL report locks tested only on an isolated disposable Unix socket."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', [
    'generate', 'assign', 'sign', 'approve', 'facility', 'template_approve',
    'stale_snapshots', 'stale_template', 'stale_signatory', 'rollback',
])
def test_mysql_reporting_integrity(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_phase5a_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'report integrity checks passed' in result.stdout
