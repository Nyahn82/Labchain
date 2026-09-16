"""Phase 3C locking and Decimal checks on a disposable MySQL instance only."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', [
    'overlap_create', 'overlap_activate', 'overlap_patch', 'samples', 'panels',
    'shared_samples', 'shared_tests', 'decimal_rollback', 'retry_exhausted', 'connection_error',
])
def test_mysql_lab_integrity(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_phase3c_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'laboratory integrity checks passed' in result.stdout
