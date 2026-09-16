"""Actual InnoDB locking and repeatable-read checks on an isolated Unix socket."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', ['release', 'revise', 'supersede', 'rollback', 'stale', 'token_case', 'branches'])
def test_mysql_release_integrity(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'tests/mysql_phase5b_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'release integrity checks passed' in result.stdout
