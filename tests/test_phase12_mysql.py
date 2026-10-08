"""Focused native MySQL probes on a disposable, non-networked /tmp instance."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_phase_3b_mysql import disposable_mysql


@pytest.mark.parametrize('scenario', ['uniqueness', 'locking', 'concurrent', 'rollback', 'idempotency'])
def test_matrix_native_mysql(disposable_mysql, scenario):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'tests/mysql_phase12_probe.py'), disposable_mysql, scenario],
                            cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'phase12 checks passed' in result.stdout
