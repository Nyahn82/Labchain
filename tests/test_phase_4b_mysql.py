"""Phase 4B native MySQL tests on a disposable isolated Unix socket only."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', [
    'duplicate_create', 'review', 'verify', 'parallel_verify', 'create_cancel', 'verify_cancel',
    'create_reject', 'patch_review', 'range_snapshot', 'rollback_decimal',
])
def test_mysql_result_integrity(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_phase4b_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'result integrity checks passed' in result.stdout
