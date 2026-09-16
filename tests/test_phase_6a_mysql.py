"""Concurrency checks use only an isolated MySQL process with networking disabled."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', ['issue', 'redeem', 'issue_redeem', 'username', 'stale_token', 'rollback', 'revoked', 'relinked'])
def test_mysql_patient_activation_and_ownership(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'tests/mysql_phase6a_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'patient activation and ownership checks passed' in result.stdout
