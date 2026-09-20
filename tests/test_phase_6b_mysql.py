"""Real MySQL replay and one-time-use races on isolated Unix sockets."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', ['challenge', 'recovery', 'totp', 'attempts', 'stale_revoked'])
def test_mysql_mfa_serialization(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'tests/mysql_phase6b_probe.py'), disposable_mysql, scenario],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'MFA serialization checks passed' in result.stdout
