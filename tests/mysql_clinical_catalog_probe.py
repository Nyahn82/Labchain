"""Migrate/import a fixture-owned socket-only MySQL instance, never application MySQL."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from scripts.mysql_migration_rehearsal import ENVIRONMENT
from mysql_release_rehearsal_probe import validated_socket


def main(value):
    socket=validated_socket(value)
    opts=dict(hide_parameters=True,connect_args={'unix_socket':str(socket),'connect_timeout':5})
    admin=sa.create_engine('mysql+pymysql://root@localhost',**opts)
    with admin.begin() as c:
        sock,data,no_network=c.exec_driver_sql('SELECT @@socket,@@datadir,@@skip_networking').one()
        assert Path(sock).resolve()==socket and Path(data).resolve()==socket.parent/'data' and no_network==1
        c.exec_driver_sql('CREATE DATABASE rhu_catalog_synthetic CHARACTER SET utf8mb4')
    engine=sa.create_engine('mysql+pymysql://root@localhost/rhu_catalog_synthetic',**opts)
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=socket.parent) as folder:
        folder=Path(folder);(folder/'env.py').write_text(ENVIRONMENT)
        shutil.copytree(root/'migrations/versions',folder/'versions',ignore=shutil.ignore_patterns('__pycache__'))
        cfg=Config();cfg.set_main_option('script_location',str(folder))
        os.environ['RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED']='1'
        with engine.connect() as c:
            cfg.attributes['verified_connection']=c
            command.upgrade(cfg,'20261019_01')
            c.exec_driver_sql("INSERT INTO lab_department(department_code,department_name) VALUES ('LEGACY-DEP','Synthetic original department')")
            c.exec_driver_sql("INSERT INTO test_catalog(test_code,test_name,department_id,result_type) VALUES ('LEGACY-TST','Synthetic original examination',1,'TEXT')")
            c.commit()
            before=c.exec_driver_sql('SELECT test_id,test_code,test_name,result_type,is_active FROM test_catalog').all();c.rollback()
            command.upgrade(cfg,'20261021_01')
            assert c.exec_driver_sql('SELECT test_id,test_code,test_name,result_type,is_active FROM test_catalog').all()==before
            assert c.exec_driver_sql('SELECT facility_status,result_schema FROM test_catalog').one()==(None,None)
            c.rollback();command.upgrade(cfg,'20261021_01')
            assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()=='20261021_01'
            c.rollback()
        from app.services import starter_catalog_service as importer
        from app.services.clinical_catalog_service import load_catalog,catalog_view
        factory=sessionmaker(bind=engine)
        with factory() as db:
            plan=importer.preview(db,catalog=load_catalog());assert not plan['conflicts']
            result=importer.import_catalog(db,importer.ImportRequest(fingerprint=plan['fingerprint'],acknowledge_inactive_review=True),None,None,catalog=load_catalog())
            assert result['inserted']==221
            plan=importer.preview(db,catalog=load_catalog())
            again=importer.import_catalog(db,importer.ImportRequest(fingerprint=plan['fingerprint'],acknowledge_inactive_review=True),None,None,catalog=load_catalog())
            assert again['inserted']==0 and again['skipped']==221
            view=catalog_view(db);assert len(view['tests'])==167 and len(view['panels'])==27
            assert not any(t['orderable'] for t in view['tests'])
            assert db.execute(sa.text('SELECT test_id,test_code,test_name,result_type,is_active FROM test_catalog WHERE test_id=1')).all()==before
            assert db.execute(sa.text('SELECT COUNT(*) FROM reference_range')).scalar()==0
        print('PASS native MySQL additive migration, preserved legacy codes, controlled 221-entry import, rerun idempotency and API projection')
    engine.dispose();admin.dispose()


if __name__=='__main__':main(sys.argv[1])
