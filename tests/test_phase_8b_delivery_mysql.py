"""Real InnoDB semantics on a disposable socket, separate from production."""
import os
from pathlib import Path
import subprocess
import sys

from test_phase_3b_mysql import disposable_mysql


def test_mysql_delivery_claims_leases_fencing_and_recovery(disposable_mysql):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'tests/mysql_phase8b_delivery_probe.py'), disposable_mysql],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Phase 8B delivery concurrency checks passed' in result.stdout
