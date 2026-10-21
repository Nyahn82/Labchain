import os
from pathlib import Path
import subprocess
import sys
from test_phase_3b_mysql import disposable_mysql


def test_clinical_catalog_native_mysql(disposable_mysql):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'tests/mysql_clinical_catalog_probe.py'),disposable_mysql],
        cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'PASS native MySQL' in result.stdout
    print(result.stdout)
