"""Opt-in native MySQL code-allocation checks; importing this module is offline.

Run via ``python -m scripts.mysql_auto_code_probe``. See
``docs/AUTO_CODE_MYSQL_PROBE.md`` for the isolated database contract.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
import getpass
import importlib.util
import os
from pathlib import Path
import sys
from threading import Barrier
from uuid import uuid4
import warnings


EXPECTED_HOST = "127.0.0.1"
EXPECTED_DATABASE = "rhu_labchain_dev"
EXPECTED_USER = "rhu_dev"
EXPECTED_PORT = 3306
ALLOWED_TABLES = ("code_sequence", "auto_code_probe_record", "auto_code_probe_legacy")
LOCK_NAME = "rhu_labchain_dev.auto_code_probe"
WORKERS = 20


class SafetyRefusal(Exception):
    """Fixed, credential-free refusal reason."""


@dataclass(frozen=True)
class Config:
    host: str
    database: str
    user: str
    password: str = field(repr=False)
    port: int = EXPECTED_PORT

    def validate_target(self):
        if (self.host, self.database, self.user, self.port) != (
            EXPECTED_HOST, EXPECTED_DATABASE, EXPECTED_USER, EXPECTED_PORT,
        ):
            raise SafetyRefusal("Only the fixed local development database and account are permitted.")

    def validate(self):
        self.validate_target()
        if not isinstance(self.password, str) or not self.password:
            raise SafetyRefusal("A nonempty test password is required.")


def load_config(environ, *, prompt=False):
    # No DATABASE_URL, generic DB_* settings, .env file, or MySQL defaults file.
    names = ("RHU_CODE_TEST_HOST", "RHU_CODE_TEST_DATABASE", "RHU_CODE_TEST_USER")
    if any(not environ.get(name) for name in names):
        raise SafetyRefusal("Development-only host, database, and user variables must be set explicitly.")
    try:
        port = int(environ.get("RHU_CODE_TEST_PORT", str(EXPECTED_PORT)))
    except (TypeError, ValueError):
        raise SafetyRefusal("Invalid test port.") from None
    # Validate the target before even prompting for a password.
    config = Config(*(environ[name] for name in names), password="", port=port)
    config.validate_target()
    password = environ.get("RHU_CODE_TEST_PASSWORD", "")
    if not password and prompt:
        if not sys.stdin.isatty():
            raise SafetyRefusal("Password prompting requires an interactive terminal.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Isolated MySQL test password: ")
    config = Config(config.host, config.database, config.user, password, port)
    config.validate()
    return config


def check_available_tables(existing):
    if set(existing).intersection(ALLOWED_TABLES):
        raise SafetyRefusal("A reserved probe table already exists; refusing to reuse or delete it.")


def check_table_owner(name, owned_names, row, marker):
    if name not in ALLOWED_TABLES or name not in owned_names:
        raise SafetyRefusal("Attempt to modify a table not owned by this run.")
    if row is None or row[0] != marker or row[1] != "InnoDB":
        raise SafetyRefusal("Probe table ownership or InnoDB engine changed; refusing modification.")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def expect_error(kind, message=None):
    try:
        yield
    except kind as exc:
        if message is not None:
            check(str(exc) == message, "Unexpected application error.")
    else:
        raise AssertionError("Expected error was not raised.")


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261015_01_auto_codes.py"
    spec = importlib.util.spec_from_file_location("auto_code_probe_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_mysql(config):
    """The sole online entry point. Only main(--run) calls this function."""
    config.validate()
    import sqlalchemy as sa
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker
    from app.models.code_sequence import CodeSequence
    from app.services.code_generation_service import MAX_COUNTER, allocate_code

    url = sa.URL.create(
        "mysql+pymysql", username=config.user, password=config.password,
        host=config.host, port=config.port, database=config.database,
    )
    engine = sa.create_engine(
        url, echo=False, hide_parameters=True, isolation_level="REPEATABLE READ",
        pool_size=WORKERS, max_overflow=1, pool_timeout=30,
        connect_args={"connect_timeout": 5, "read_timeout": 45, "write_timeout": 15,
                      "charset": "utf8mb4"},
    )

    @sa.event.listens_for(engine, "connect")
    def check_connection(connection, _record):
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), CURRENT_USER(), USER()")
            database, account, login = cursor.fetchone()
            if (database != EXPECTED_DATABASE or account.split("@", 1)[0] != EXPECTED_USER
                    or login.split("@", 1)[0] != EXPECTED_USER):
                raise SafetyRefusal("Connected database or authenticated account does not match the allowlist.")
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 15")

    metadata = sa.MetaData()
    # Clone only this model's DDL, never Base.metadata.create_all(). The service
    # still uses the original ORM model against the same physical table.
    sequences = CodeSequence.__table__.to_metadata(metadata)
    records = sa.Table(
        "auto_code_probe_record", metadata,
        sa.Column("record_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("sequence_key", sa.String(40), nullable=False),
        sa.UniqueConstraint("code", name="uq_auto_code_probe_record_code"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    legacy = sa.Table(
        "auto_code_probe_legacy", metadata,
        sa.Column("record_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(40), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    tables = (sequences, records, legacy)
    check(tuple(table.name for table in tables) == ALLOWED_TABLES, "Unexpected table declaration.")
    marker = "rhu-auto-code-probe:" + uuid4().hex
    for table in tables:
        table.comment = marker
    owned = []
    factory = sessionmaker(bind=engine, autoflush=False)

    def verify_owner(connection, table):
        row = connection.execute(sa.text(
            "SELECT TABLE_COMMENT, ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = :database AND TABLE_NAME = :table"
        ), {"database": EXPECTED_DATABASE, "table": table.name}).one_or_none()
        check_table_owner(table.name, [item.name for item in owned], row, marker)

    def reset():
        with engine.begin() as connection:
            for table in reversed(tables):
                verify_owner(connection, table)
                connection.execute(table.delete())
            connection.execute(sequences.insert(), [
                dict(sequence_key="PATIENT", prefix="PAT", current_value=0, padding=6),
                dict(sequence_key="STAFF", prefix="STF", current_value=0, padding=6),
            ])

    def persisted(key="PATIENT"):
        with factory() as db:
            return db.get(CodeSequence, key).current_value

    def record_count():
        with engine.connect() as connection:
            return connection.scalar(sa.select(sa.func.count()).select_from(records))

    def allocate_record(db, key="PATIENT"):
        code = allocate_code(db, key)
        db.execute(records.insert().values(code=code, sequence_key=key))
        db.flush()
        return code

    def sequential_persistence():
        for number in (1, 2, 3):
            with factory.begin() as db:
                check(allocate_record(db) == f"PAT-{number:06d}", "Wrong sequential identifier.")
            check(persisted() == number, "Committed counter did not persist in a new session.")
        check(record_count() == 3, "Committed records did not persist.")

    def concurrent_allocations():
        barrier = Barrier(WORKERS, timeout=30)

        def worker(_index):
            with factory.begin() as db:
                connection_id = db.scalar(sa.text("SELECT CONNECTION_ID()"))
                # Each worker holds its own connection before allocations start.
                barrier.wait()
                code = allocate_record(db)
            return connection_id, code

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(worker, i) for i in range(WORKERS)]
            results = [future.result(timeout=60) for future in futures]
        check(len({identifier for identifier, _ in results}) == WORKERS, "Connections were not independent.")
        codes = [code for _, code in results]
        check(len(set(codes)) == WORKERS, "Concurrent allocations produced duplicate identifiers.")
        check(set(codes) == {f"PAT-{i:06d}" for i in range(1, WORKERS + 1)}, "Unexpected concurrent codes.")
        check(persisted() == WORKERS and record_count() == WORKERS, "Concurrent commits were not atomic.")

    def rollback_reuses_code():
        with factory() as db:
            check(allocate_code(db, "PATIENT") == "PAT-000001", "Wrong first code.")
            db.flush()  # Exercise a real database UPDATE, not just ORM state.
            db.rollback()
        check(persisted() == 0, "Rollback consumed a code.")
        with factory.begin() as db:
            check(allocate_code(db, "PATIENT") == "PAT-000001", "Rolled-back number was not reusable.")
        check(persisted() == 1, "Reused counter did not commit.")

    def collision_rolls_back():
        with engine.begin() as connection:
            connection.execute(records.insert().values(code="PAT-000001", sequence_key="PATIENT"))
        with expect_error(IntegrityError):
            with factory.begin() as db:
                code = allocate_code(db, "PATIENT")
                db.flush()
                db.execute(records.insert().values(code=code, sequence_key="PATIENT"))
        check(persisted() == 0 and record_count() == 1, "Collision left a counter increment or partial record.")

    def independent_counters():
        with factory.begin() as db:
            check(allocate_record(db, "PATIENT") == "PAT-000001", "Patient counter incorrect.")
            check(allocate_record(db, "STAFF") == "STF-000001", "Staff counter incorrect.")
            check(allocate_record(db, "PATIENT") == "PAT-000002", "Patient counter interfered with staff.")
        check((persisted("PATIENT"), persisted("STAFF")) == (2, 1), "Counters are not independent.")

    def missing_sequence():
        with expect_error(RuntimeError, "Code sequence is not configured: MISSING"):
            with factory.begin() as db:
                allocate_code(db, "MISSING")
        check(persisted() == 0 and record_count() == 0, "Missing sequence changed state.")

    def exhaustion():
        # Department codes can hold a full BIGINT suffix; PAT/STF cannot.
        with factory.begin() as db:
            db.add(CodeSequence(sequence_key="DEPARTMENT", prefix="DEP", padding=3,
                                current_value=MAX_COUNTER - 1))
        with factory.begin() as db:
            check(allocate_code(db, "DEPARTMENT") == f"DEP-{MAX_COUNTER}", "Last counter value unavailable.")
        with expect_error(RuntimeError, "Code sequence exhausted."):
            with factory.begin() as db:
                allocate_code(db, "DEPARTMENT")
        check(persisted("DEPARTMENT") == MAX_COUNTER, "Exhaustion changed the counter.")

        limit = 9_999_999_999_999_999
        for key, prefix, table, column in (
            ("PATIENT", "PAT", "patient", "patient_code"),
            ("STAFF", "STF", "staff", "staff_code"),
        ):
            with factory.begin() as db:
                db.get(CodeSequence, key).current_value = limit - 1
            with factory.begin() as db:
                code = allocate_code(db, key)
                check(code == f"{prefix}-{limit}" and len(code) == 20, "Last fitting code unavailable.")
            with expect_error(RuntimeError,
                              f"Code sequence exhausted: {key} exceeds {table}.{column} capacity (20 characters)."):
                with factory.begin() as db:
                    allocate_code(db, key)
            check(persisted(key) == limit, "Column-capacity failure consumed a value.")

    def migration_formats():
        migration = load_migration()
        # Only call the migration's read-only format scanner against our fixture;
        # never call upgrade/downgrade or access its real application tables.
        with engine.begin() as connection:
            for _key, prefix, padding, _table, _column in migration.SEQUENCES:
                values = ["001", "P9-LEGACY", f"{prefix}-{7:0{padding}d}",
                          f"{prefix.lower()}-{9:0{padding}d}", f"{prefix}-000010-ARCHIVE"]
                connection.execute(legacy.insert(), [{"code": value} for value in values])
            before = list(connection.execute(sa.select(legacy).order_by(legacy.c.record_id)))
            for key, prefix, padding, _table, _column in migration.SEQUENCES:
                maximum = migration.existing_maximum(connection, legacy.name, "code", prefix)
                check(maximum == 9, "Migration format scanner chose an incorrect counter.")
                connection.execute(sequences.delete().where(sequences.c.sequence_key == key))
                connection.execute(sequences.insert().values(
                    sequence_key=key, prefix=prefix, current_value=maximum, padding=padding,
                ))
            check(list(connection.execute(sa.select(legacy).order_by(legacy.c.record_id))) == before,
                  "Migration scanner modified legacy codes.")
        with factory.begin() as db:
            for key, prefix, padding, _table, _column in migration.SEQUENCES:
                check(allocate_record(db, key) == f"{prefix}-{10:0{padding}d}", "Migration continuation incorrect.")
        with engine.begin() as connection:
            connection.execute(legacy.insert().values(code=f"PAT-{MAX_COUNTER + 1}"))
            with expect_error(RuntimeError, "Existing auto_code_probe_legacy code exceeds sequence capacity."):
                migration.existing_maximum(connection, legacy.name, "code", "PAT")

    def record_and_counter_atomicity():
        with factory.begin() as db:
            check(allocate_record(db) == "PAT-000001", "First atomic allocation incorrect.")
        check((persisted(), record_count()) == (1, 1), "Successful transaction only partially committed.")
        with expect_error(RuntimeError, "synthetic abort"):
            with factory.begin() as db:
                check(allocate_record(db) == "PAT-000002", "Second atomic allocation incorrect.")
                raise RuntimeError("synthetic abort")
        check((persisted(), record_count()) == (1, 1), "Aborted transaction only partially rolled back.")
        with factory.begin() as db:
            check(allocate_record(db) == "PAT-000002", "Aborted number was consumed.")
        check((persisted(), record_count()) == (2, 2), "Recovery did not commit both changes.")

    def repeated_unflushed_allocations():
        # Deliberately matches app.database's autoflush=False without importing it.
        # No caller-side flush: the allocator must persist its own counter
        # increment without flushing unrelated pending application changes.
        with factory.begin() as db:
            first = allocate_code(db, "PATIENT")
            second = allocate_code(db, "PATIENT")
            check((first, second) == ("PAT-000001", "PAT-000002"),
                  "Repeated allocations in one autoflush=False transaction reused a code.")
        check(persisted() == 2, "Unflushed sequential allocations lost a counter update.")

    cases = (
        sequential_persistence, concurrent_allocations, rollback_reuses_code,
        collision_rolls_back, independent_counters, missing_sequence,
        exhaustion, migration_formats, record_and_counter_atomicity,
        repeated_unflushed_allocations,
    )
    failures = 0
    try:
        # A held connection owns this advisory lock throughout creation, tests,
        # and cleanup. A competing harness refuses to run instead of sharing data.
        with engine.connect() as guard:
            if guard.scalar(sa.text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}) != 1:
                raise SafetyRefusal("Another automatic-code probe holds the database lock.")
            guard.commit()
            try:
                existing = set(guard.scalars(sa.text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = :database"
                ), {"database": EXPECTED_DATABASE}))
                check_available_tables(existing)
                guard.commit()
                for table in tables:
                    table.create(guard, checkfirst=False)
                    owned.append(table)
                    guard.commit()
                    verify_owner(guard, table)
                guard.commit()
                for case in cases:
                    reset()
                    try:
                        case()
                    except Exception as exc:
                        # Never emit DBAPI messages, SQL parameters, URLs, or passwords.
                        print(f"FAIL {case.__name__} ({type(exc).__name__})")
                        failures += 1
                    else:
                        print(f"PASS {case.__name__}")
            finally:
                # Never drop pre-existing tables. Check our unique ownership marker
                # again before every DROP; failed/interrupted cleanup fails closed.
                try:
                    guard.rollback()
                    for table in reversed(owned):
                        verify_owner(guard, table)
                        table.drop(guard, checkfirst=False)
                        guard.commit()
                finally:
                    guard.execute(sa.text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})
                    guard.commit()
    finally:
        engine.dispose()
    print(f"MYSQL_CODE_PROBE: {len(cases) - failures} passed, {failures} failed")
    return 1 if failures else 0


def main(argv=None, *, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true", help="Explicitly authorize connections to the isolated test database")
    modes.add_argument("--check", action="store_true", help="Validate runtime configuration without creating an engine or connecting")
    parser.add_argument("--prompt-password", action="store_true", help="Read the test password privately from a terminal")
    args = parser.parse_args(argv)
    if not args.run and not args.check:
        print("SKIP: MySQL probe is disabled; use --run only after isolated-database authorization.")
        return 0
    try:
        config = load_config(os.environ if environ is None else environ, prompt=args.prompt_password)
        if args.check:
            print("CONFIGURATION_VALIDATED: no engine created, no connection attempted.")
            return 0
        return run_mysql(config)
    except SafetyRefusal as exc:
        print(f"REFUSED: {exc}")
        return 2
    except (Exception, KeyboardInterrupt) as exc:
        print(f"FAILED: {type(exc).__name__}; exception details suppressed to protect credentials.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
