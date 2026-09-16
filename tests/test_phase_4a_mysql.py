"""Native MySQL transitions, current reads, unique codes and rollback."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', [
    'collect', 'receive', 'reject', 'register_cancel', 'collect_cancel', 'register_twice',
    'panel_snapshot', 'sample_snapshot', 'code_collisions', 'rollback_decimal',
])
def test_mysql_workflow_integrity(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_phase4a_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'workflow integrity checks passed' in result.stdout
