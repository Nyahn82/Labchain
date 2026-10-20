"""Loopback-only synthetic browser fixture server. Never connects to application MySQL/Fabric."""
import ast,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
P=Path(sys.argv[1]).resolve()
assert str(P).startswith('/tmp/rhu-scan-') and (P/'synthetic.sqlite').is_file()
# Reuse the complete synthetic environment allowlist, without importing network guards.
tree=ast.parse((ROOT/'tests/conftest.py').read_text())
for statement in tree.body:
    if isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call) and ast.unparse(statement.value.func)=='os.environ.update':
        values = statement.value.args[0]
        os.environ.update({ast.literal_eval(k): ast.literal_eval(v) for k,v in zip(values.keys,values.values) if isinstance(v,ast.Constant)})
        os.environ['BLOCKCHAIN_ADAPTER_COMMAND'] = json.dumps(['/usr/bin/false'])
        break
else: raise RuntimeError('Synthetic environment not found')
os.environ['REPORT_STORAGE_DIR']=str(P/'reports')
os.environ['PUBLIC_BASE_URL']='https://localhost:5443'
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from app import main,database
from app.dependencies import auth
from app.models import BlockchainEvent
from app.services import blockchain_monitor_client as monitor
from datetime import datetime,timezone
engine=create_engine('sqlite:///'+str(P/'synthetic.sqlite'),hide_parameters=True)
factory=sessionmaker(bind=engine,autoflush=False)
database.engine=engine; database.SessionLocal=factory; auth.SessionLocal=factory
main.FRONTEND_BUILD_DIR=Path('/tmp/rhu-scan-build')
# Explicit synthetic Fabric double. Live Fabric is tested separately against the public site.
def query(request,kind):
    with factory() as db:
        if request['action']=='anchor':
            e=db.scalar(select(BlockchainEvent).where(BlockchainEvent.event_uuid==request['anchor_id']))
            p=json.loads(e.canonical_payload)
            return kind(anchor_id=e.event_uuid,entity_reference=e.entity_reference,event_type=e.event_type,
                content_hash=e.record_hash,previous_hash=e.previous_hash,transaction_id=e.fabric_transaction_id,
                source_node=p['source_node'],source_msp=p['source_msp'],source_peer='peer1',checked_at=datetime.now(timezone.utc))
        return kind(transaction_id=request['transaction_id'],validation_code=0,validation_status='VALID',timestamp=None,
            block_number=7,block_hash='e'*64,source_peer='peer1',checked_at=datetime.now(timezone.utc))
monitor.query=query
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=5443,ssl_keyfile=str(P/'local.key'),ssl_certfile=str(P/'local.crt'),access_log=False)
