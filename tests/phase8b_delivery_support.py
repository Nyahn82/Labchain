"""Synthetic fixtures shared with the isolated MySQL subprocess probe."""
from datetime import datetime
import hashlib
from uuid import uuid4
from sqlalchemy import select
from app.models import BlockchainEvent, BlockchainNode
from app.services.blockchain_outbox_service import canonicalize

NOW = datetime(2026, 9, 27, 12)
TX = 'b' * 64


def seed(factory, number=1, *, predecessor=None, event_type='REPORT_RELEASED', **changes):
    with factory.begin() as db:
        if db.get(BlockchainNode, 1) is None:
            db.add(BlockchainNode(node_id=1, node_code='node1', port=7051, is_active=True))
            db.flush()
        previous = db.get(BlockchainEvent, predecessor) if predecessor else None
        reference = previous.entity_reference if previous else str(uuid4())
        previous_hash = previous.record_hash if previous else None
        payload = canonicalize(event_type=event_type, entity_reference=reference, report_version=1,
            artifact_sha256='a'*64, occurred_at=NOW, previous_hash=previous_hash,
            source_node='node1', source_msp='Org1MSP',
            superseding_entity_reference=str(uuid4()) if event_type == 'REPORT_SUPERSEDED' else None)
        values = dict(event_id=number, event_uuid=str(uuid4()), origin_node_id=1, entity_type='REPORT',
            entity_id=previous.entity_id if previous else number, event_type=event_type,
            record_hash=hashlib.sha256(payload.encode()).hexdigest(), event_status='PENDING',
            deduplication_key=f'{event_type}:{number}', entity_reference=reference,
            canonical_payload=payload, previous_hash=previous_hash, predecessor_event_id=predecessor,
            occurred_at=NOW, next_attempt_at=NOW, attempt_count=0, updated_at=NOW)
        values.update(changes)
        db.add(BlockchainEvent(**values))
    return number


def state(factory, number=1):
    with factory() as db:
        return dict(db.execute(select(BlockchainEvent.__table__).where(
            BlockchainEvent.event_id == number)).mappings().one())


def anchor(claim):
    return dict(claim.expected_anchor(), created_at='2026-09-27T13:01:02.123Z', transaction_id=TX)


class FakeAdapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.check = None

    def call(self, request, timeout):
        assert timeout > 0
        self.calls.append((request, timeout))
        if self.check:
            self.check()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
