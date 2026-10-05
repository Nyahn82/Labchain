"""Phase 11 fixed MySQL date/duration expressions and aggregate query parity."""
from pathlib import Path
import os
import subprocess
import sys
from sqlalchemy import column, select
from sqlalchemy.dialects import mysql, sqlite
from app.services.analytics_sql import SecondsBetween, MondayWeekday
from test_phase_10_migration import disposable_mysql


def test_fixed_dialect_expressions():
    statement=select(SecondsBetween(column('started'),column('ended')),MondayWeekday(column('created')))
    native=str(statement.compile(dialect=mysql.dialect()))
    portable=str(statement.compile(dialect=sqlite.dialect()))
    assert 'TIMESTAMPDIFF(MICROSECOND, started, ended)' in native and 'WEEKDAY(created)' in native
    assert 'julianday(ended)' in portable and "strftime('%w', created)" in portable


def test_native_analytics_with_rich_synthetic_data(disposable_mysql):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'tests/mysql_phase11_probe.py'),disposable_mysql],
        cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'Phase 11 isolated MySQL analytics checks passed' in result.stdout
