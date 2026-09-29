"""Only a new, socket-only disposable mysqld; never load production DB settings."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import stat
import sys
import threading

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services.blockchain_adapter_service import DeliveryError, WorkerOptions
from app.services.blockchain_delivery_service import DeliveryWorker, TABLE
from phase8b_delivery_support import NOW, FakeAdapter, anchor, seed, state


def main(socket):
    socket = Path(socket).resolve()
    assert socket.parent.parent == Path('/tmp') and socket.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket.stat().st_mode)
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket),
        'connect_timeout': 5, 'read_timeout': 10, 'write_timeout': 10}}
    admin = create_engine('mysql+pymysql://root@localhost/', **options)
    with admin.begin() as db:
        db.exec_driver_sql('CREATE DATABASE phase8b_delivery_synthetic CHARACTER SET utf8mb4')
    engine = create_engine('mysql+pymysql://root@localhost/phase8b_delivery_synthetic', **options)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        Base.metadata.create_all(engine)
        seed(factory)
        seed(factory, 2)
        locked = threading.Event()
        release = threading.Event()
        thread = [None]
        statements = []

        @event.listens_for(engine, 'after_cursor_execute')
        def hold_claim(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
            if threading.get_ident() == thread[0] and statement.startswith('UPDATE blockchain_event'):
                # Worker A has acquired the row lock, changed lease state, and has
                # not committed. Worker B must skip A's row without blocking.
                locked.set()
                assert release.wait(8), 'second worker blocked instead of skipping'

        first = DeliveryWorker(factory, FakeAdapter(), now=lambda: NOW)
        second = DeliveryWorker(factory, FakeAdapter(), now=lambda: NOW)
        def claim_first():
            thread[0] = threading.get_ident()
            return first.claim()
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_first = pool.submit(claim_first)
            try:
                assert locked.wait(5)
                pending_second = pool.submit(second.claim)
                claim_b = pending_second.result(timeout=5)
                assert claim_b is not None and claim_b.event_id == 2
            finally:
                release.set()
            claim_a = pending_first.result(timeout=5)
        event.remove(engine, 'after_cursor_execute', hold_claim)
        assert claim_a.event_id == 1 and claim_a.lease_token != claim_b.lease_token
        assert any('FOR UPDATE SKIP LOCKED' in statement for statement in statements)
        assert second.claim() is None  # neither active lease is eligible
        print('PASS concurrent independent claims and SKIP LOCKED')

        # Lock the only available row in session A and prove B immediately sees
        # no eligible row; same-row ownership cannot be acquired twice.
        seed(factory, 3)
        with factory.begin() as session_a:
            session_a.execute(select(TABLE).where(TABLE.c.event_id == 3).with_for_update()).first()
            assert second.claim() is None
        third = second.claim()
        assert third.event_id == 3 and second.claim() is None
        print('PASS two sessions cannot own the same row; active leases excluded')

        first.now = lambda: NOW + timedelta(seconds=121)
        fresh = first.claim()
        assert fresh.event_id == 1 and fresh.attempt == 2 and fresh.lease_token != claim_a.lease_token
        before = state(factory)
        assert not second.confirm(claim_a, anchor(claim_a))
        assert not second.fail(claim_a, DeliveryError('GATEWAY_UNAVAILABLE'))
        assert not second.fail(claim_a, DeliveryError('CREDENTIAL_INVALID'))
        assert state(factory) == before
        print('PASS expired reclaim and stale confirm/retry/dead fencing')

        # This time the old process committed remotely, then died. The new worker
        # sees the exact existing anchor and records its ORIGINAL transaction ID.
        first.adapter.responses = [True, anchor(fresh)]
        first.deliver(fresh)
        assert state(factory)['event_status'] == 'CONFIRMED'
        assert state(factory)['fabric_validation_code'] == 0
        assert [c[0]['action'] for c in first.adapter.calls] == ['anchor_exists', 'read_anchor']
        assert not second.confirm(claim_a, anchor(claim_a))
        print('PASS lost acknowledgement reconciliation on MySQL')
        print('Phase 8B delivery concurrency checks passed')
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.exec_driver_sql('DROP DATABASE phase8b_delivery_synthetic')
        admin.dispose()


if __name__ == '__main__':
    main(sys.argv[1])
