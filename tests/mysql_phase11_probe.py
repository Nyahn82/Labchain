"""Read-only analytics SQL parity on a validated disposable MySQL socket."""
from pathlib import Path
from types import SimpleNamespace
import stat
import sys
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from app import database
from app.models import UserAccount
from app.schemas.analytics import AnalyticsQuery
from app.services import analytics_service as service
from test_phase_11_analytics import rich, SECTIONS


def main(socket):
    socket=Path(socket).resolve()
    assert socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket.stat().st_mode)
    options={'hide_parameters':True,'connect_args':{'unix_socket':str(socket),'connect_timeout':5}}
    root=sa.create_engine('mysql+pymysql://root@localhost/',**options)
    with root.begin() as db: db.exec_driver_sql('CREATE DATABASE phase11_synthetic CHARACTER SET utf8mb4')
    engine=sa.create_engine('mysql+pymysql://root@localhost/phase11_synthetic',**options)
    database.engine=engine
    command.upgrade(Config(str(Path(__file__).resolve().parents[1]/'alembic.ini')),'20261005_01')
    factory=sessionmaker(bind=engine,autoflush=False)
    with factory.begin() as db: db.add(UserAccount(user_id=1,username='synthetic',password_hash='not-a-real-password',account_status='ACTIVE'))
    rich.__wrapped__(SimpleNamespace(factory=factory))
    query=AnalyticsQuery(date_from='2026-10-01',date_to='2026-10-07')
    for name in SECTIONS:
        with factory() as db:
            data=getattr(service,name)(db,query)
            encoded=data.model_dump_json()
            assert 'PRIVATE-' not in encoded and 'NaN' not in encoded
            if name=='overview':
                values={m.key:m.value for m in data.metrics}
                assert values['orders']==5 and values['tests_requested']==6 and values['returning_patients']==1
                assert values['order_to_release']==302400
            if name=='operations':
                assert data.metrics[0].value==150
                days=next(b for b in data.breakdowns if b.key=='weekday')
                assert {b.label:b.count for b in days.items}['Monday']==1
            if name=='system': assert data.turnaround[0].average_seconds==120
    for grain in ('day','week','month','quarter','year'):
        with factory() as db:
            data=service.patients(db,AnalyticsQuery(date_from='2026-10-01',date_to='2026-10-07',grain=grain))
            assert sum(p.value for p in data.series[0].points)==2
    engine.dispose(); root.dispose()
    print('Phase 11 isolated MySQL analytics checks passed')


if __name__=='__main__': main(sys.argv[1])
