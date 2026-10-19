"""Combined release rehearsal on the existing disposable socket-only MySQL fixture."""
import os
from pathlib import Path
import subprocess
import sys

from test_phase_3b_mysql import disposable_mysql


def test_combined_migration_preservation_and_recovery(disposable_mysql):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tests/mysql_release_rehearsal_probe.py'), disposable_mysql],
        cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
        capture_output=True, text=True, timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for stage in ('writer_exclusion', 'historical_backup_restore', 'automatic_code_upgrade',
                  'pdf_upgrade_preservation', 'allocation_concurrency_and_rollback',
                  'immutable_codes', 'legacy_and_new_pdf', 'seed_failure_restore',
                  'revision_failure_restore', 'pdf_failure_restore'):
        assert 'PASS ' + stage in result.stdout
    print(result.stdout)
