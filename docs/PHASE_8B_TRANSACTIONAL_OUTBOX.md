# Phase 8B-1: transactional report lifecycle capture

Phase 8B-1 adds source code, one migration, a registry bootstrap CLI, and tests.
It does not deploy a Fabric client or worker. `PENDING` means recorded in MySQL;
it does **not** mean blockchain anchored. The existing single-VPS prototype and
its shared physical failure domain are unchanged.

## Transaction and forward-only capture

`release_report` adds the outbox event inside its existing `mutation(db)` block,
after the final PDF hash and release metadata exist, before the final flush and
single commit. Report state, verification, audits, and outbox commit together.
The helper never opens a Session or commits. Insertion failures propagate and
roll back the report transaction; existing definite-failure PDF cleanup and
uncertain-commit artifact retention remain in force.

There are no Fabric availability checks, network calls, or submission commands
in capture. `/api/v1/ready` remains based on the core application/MySQL.

At first release, a report receives an application-generated lowercase UUIDv4
in `lab_report.blockchain_entity_uuid`. Assignment occurs in the release
transaction, including for drafts created before deployment. Already released
historical reports remain NULL; this phase performs no backfill.

| Operation | Captured event | Previous event | Replacement reference |
| --- | --- | --- | --- |
| First release | REPORT_RELEASED | None | None |
| Explicit revoke of captured report | REPORT_REVOKED | That report's REPORT_RELEASED | None |
| Draft revision | None | N/A | N/A |
| Replacement release | Replacement REPORT_RELEASED and predecessor REPORT_SUPERSEDED | Superseded report's REPORT_RELEASED | Replacement UUID |

Both revoked and superseded events link directly to their report's release
event, even if it remains PENDING/FAILED. The future worker must enforce
predecessor confirmation ordering. Supersession is captured for an already
revoked predecessor too, without changing its clinical revocation metadata.
Supersession does not also create an explicit REPORT_REVOKED event.

Legacy revocation/supersession continues clinically without fabricated anchors.
A same-transaction `BLOCKCHAIN_CAPTURE_SKIPPED` audit records only
`reason_code=LEGACY_REPORT_NOT_ANCHORED` and the requested event type in its
new-value payload. Ordinary audit actor/record references remain in MySQL.
A report with a UUID but a missing release event is an integrity failure, not
legacy data; its operation rolls back for investigation.

## Canonical bytes and privacy

The exact, closed key set is:

```text
schema_version, event_type, entity_type, entity_reference, report_version,
artifact_sha256, occurred_at, previous_hash, source_node, source_msp,
superseding_entity_reference
```

`schema_version=1`, `entity_type=REPORT`, and `report_version` is a positive
integer (booleans and strings are rejected). UUIDs must be lowercase UUIDv4;
hashes must be lowercase 64-character SHA-256 hex. The deployed chaincode does
not accept UUIDv5.

Serialization uses UTF-8, sorted keys, `separators=(',', ':')`,
`ensure_ascii=False`, no insignificant whitespace, and explicit JSON null for
inapplicable fields. Timestamps use exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
Aware timestamps are converted to UTC; existing application naive timestamps
are interpreted as UTC. `canonical_payload` stores those exact JSON bytes as text.

- `artifact_sha256` is `report_verification.report_hash`, the SHA-256 of the
  exact released PDF bytes.
- `record_hash` is `SHA256(canonical_payload.encode('utf-8')).hexdigest()`.
- `previous_hash` is the preceding **release event's canonical hash**, not its
  PDF hash.

The serializer accepts only explicit keyword arguments. No report object,
API response, patient data, report code, result, token, URL, path, reason,
free text, internal primary key, staff identity, username, or IP can be
serialized through it. Internal `entity_id`, `created_by_user_id`, and the
deduplication key stay in MySQL only.

Source node/MSP values are frozen into the canonical payload. Later configuration
changes cannot rewrite old events. A future Fabric identity must also use
non-personal certificate metadata because Fabric records transaction creators.

## Identity, deduplication and immutability

`event_uuid` is generated once as a lowercase UUIDv4, then reused as the future
Fabric anchor ID. `entity_reference` is the immutable report UUID.

MySQL-only unique logical keys:

```text
REPORT_RELEASED:<report_id>
REPORT_REVOKED:<report_id>
REPORT_SUPERSEDED:<predecessor_report_id>:<replacement_report_id>
```

Repeated capture returns the existing event only if all immutable semantic
fields match; any conflict raises a sanitized integrity exception. The producer
also handles pending Session objects before flush. Report/order locks serialize
clinical producers; the unique key is the final race guard. A uniqueness failure
is not swallowed: the entire caller transaction rolls back.

ORM updates protect all event columns except delivery fields. ORM event deletion
is rejected. Report UUID reassignment/removal is rejected, including when the
attribute has expired. A view-only predecessor relationship avoids mutable
relationship assignment or recursive response serialization. Raw SQL/Core bulk
writes bypass ORM safeguards and must not be used by application capture or a
future worker to change immutable fields. These are application safeguards,
not protection against a database administrator.

## Schema

Revision `20260924_01`, parent `20260920_01`. Historical migrations are unchanged.
Before any DDL, upgrade reads `blockchain_event` and refuses to proceed if **any**
row exists, requiring manual review. No existing event is deleted or reclassified.
Offline SQL generation is refused because it cannot enforce this guard.

`lab_report.blockchain_entity_uuid` is nullable `CHAR(36) CHARACTER SET ascii
COLLATE ascii_bin`, with `uq_lab_report_blockchain_entity_uuid`. Multiple NULLs
are permitted. There is no generated default or historical assignment.

Full `blockchain_event` schema after migration (`—` = no explicit default):

| Column | MySQL type | NULL? | Default |
| --- | --- | --- | --- |
| event_id | BIGINT | No | AUTO_INCREMENT, primary key |
| event_uuid | CHAR(36) | No | — |
| origin_node_id | BIGINT | No | — |
| entity_type | VARCHAR(80) | No | — |
| entity_id | BIGINT | No | — |
| event_type | VARCHAR(80) | No | — |
| record_hash | CHAR(64) | No | — |
| event_status | ENUM('PENDING','PROCESSING','CONFIRMED','FAILED','DEAD') | No | 'PENDING' |
| created_by_user_id | BIGINT | Yes | NULL |
| created_at | DATETIME | No | CURRENT_TIMESTAMP |
| deduplication_key | VARCHAR(160) | No | — |
| entity_reference | CHAR(36), ascii/ascii_bin | No | — |
| canonical_payload | TEXT | No | — |
| previous_hash | CHAR(64) | Yes | NULL |
| predecessor_event_id | BIGINT | Yes | NULL |
| occurred_at | DATETIME(6) | No | — |
| attempt_count | INT UNSIGNED | No | 0 |
| next_attempt_at | DATETIME(6) | No | — |
| processing_started_at | DATETIME(6) | Yes | NULL |
| lease_token | CHAR(36), ascii/ascii_bin | Yes | NULL |
| lease_expires_at | DATETIME(6) | Yes | NULL |
| last_error_code | VARCHAR(64) | Yes | NULL |
| last_error | VARCHAR(512) | Yes | NULL |
| fabric_transaction_id | CHAR(64) | Yes | NULL |
| fabric_block_number | BIGINT UNSIGNED | Yes | NULL |
| fabric_validation_code | INT | Yes | NULL |
| confirmed_at | DATETIME(6) | Yes | NULL |
| updated_at | DATETIME(6) | No | CURRENT_TIMESTAMP(6) |

Existing event UUID uniqueness, origin/actor FKs and indexes are preserved.
Added unique key: `uq_blockchain_event_deduplication_key`.
Added indexes:

- `ix_blockchain_event_eligible(event_status,next_attempt_at,event_id)`
- `ix_blockchain_event_lease(event_status,lease_expires_at,event_id)`
- `ix_blockchain_event_entity(entity_type,entity_id,event_id)`
- `ix_blockchain_event_predecessor_event_id(predecessor_event_id)`

Added self-FK: `fk_blockchain_event_predecessor_event_id_blockchain_event`.
No cascading actions are added.

Checks (also validated by application code):

- `ck_blockchain_event_processing_lease_required`: PROCESSING requires start,
  token, and expiry.
- `ck_blockchain_event_confirmation_required`: CONFIRMED requires transaction
  ID, confirmation time, and non-NULL validation code 0 (Fabric VALID).
- `ck_blockchain_event_lifecycle_previous_required`: revoked/superseded events
  require a previous hash.
- `ck_blockchain_event_attempt_count_nonnegative`: attempts cannot be negative.

A confirmation does not require block number. Delivery-state fields reserve the
future worker schema; no claim/retry/lease-recovery code exists in Phase 8B-1.
`updated_at` is set explicitly by capture and must be updated by future delivery
mutations. No automatic `ON UPDATE` behavior is installed.

## Registry and later deployment prerequisites

The explicit CLI `python -m app.cli.bootstrap_blockchain_nodes` ensures:

| node_code | port | node_role |
| --- | --- | --- |
| node1 | 7051 | Org1MSP peer1 |
| node2 | 8051 | Org1MSP peer2 |
| node3 | 9051 | Org2MSP peer3 |
| node4 | 10051 | Org2MSP peer4 |

It creates active nodes, leaves matching rows unchanged, and fails on conflicting
codes, ports, roles, or inactive rows. Its single transaction rolls back partial
work. It makes no Docker or Fabric call. Capture requires an active configured
registry entry and does not bootstrap during requests.

Configuration adds only `BLOCKCHAIN_SOURCE_NODE=node1` and
`BLOCKCHAIN_SOURCE_MSP=Org1MSP`; node/MSP pairing is validated. Existing application
`NODE_ID=node-1` is not used as a Fabric source node.

This implementation does not run the migration/bootstrap against production.
A later deployment must coordinate code activation with the reviewed migration
and registry initialization. MySQL DDL is not transactional: quiesce application
writers, and investigate any partial DDL failure before retrying. Downgrade
refuses to remove nonempty events or assigned report UUIDs.

No normal Fabric application identity, Gateway package/adapter, worker, service
unit, blockchain status endpoint, or frontend badge is added. Pending events
will accumulate until the later delivery phase is deployed.

## Validation

Focused tests cover exact canonical bytes/hash, privacy allowlists, UUID and
event immutability, deduplication, lifecycle/legacy behavior, rollback, bootstrap,
and release without network/subprocess access. Regression suites retain existing
report and patient semantics.

The MySQL probe starts a separate `mysqld --no-defaults --skip-networking` under
`/tmp`, using only its Unix socket and synthetic database. It executes the real
Alembic environment from the previous revision, tests all old statuses against
the nonempty guard, compares both changed tables to ORM metadata, and exercises
native enums/checks, microseconds, unsigned block numbers, nullable UUID uniqueness,
self-FK, downgrade guards, and upgrade/downgrade round trips.

Schema comparison is scoped to the two changed tables: full-database MySQL
comparison also reports an existing MFA `secret_nonce` reflection difference
(`TINYBLOB` versus `LargeBinary(12)`), unrelated to Phase 8B. No MFA schema change
is included here.
