"""Migration tests using an isolated SQLite database."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.services.code_generation_service import allocate_code


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261015_01_auto_codes.py"
)

spec = importlib.util.spec_from_file_location(
    "auto_code_migration",
    MIGRATION_PATH,
)

migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def prepare_legacy_tables(connection):
    for _, _, _, table, column in migration.SEQUENCES:
        connection.execute(
            sa.text(
                f'CREATE TABLE "{table}" '
                f'("{column}" VARCHAR(40))'
            )
        )


def apply_migration(connection):
    context = MigrationContext.configure(connection)

    with Operations.context(context):
        migration.upgrade()


def test_existing_codes_initialize_counters_safely():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        prepare_legacy_tables(connection)

        connection.execute(
            sa.text(
                "INSERT INTO patient (patient_code) VALUES "
                "('001'), "
                "('P9-261008094330-A31'), "
                "('PAT-000007'), "
                "('pat-000009'), "
                "('PAT-000010-ARCHIVE')"
            )
        )

        connection.execute(
            sa.text(
                "INSERT INTO staff (staff_code) "
                "VALUES ('P9SIGN01'), ('STF-000002')"
            )
        )

        connection.execute(
            sa.text(
                "INSERT INTO test_catalog (test_code) "
                "VALUES ('P9NUM'), ('TST-0012')"
            )
        )

        apply_migration(connection)

        rows = dict(
            connection.execute(
                sa.text(
                    "SELECT sequence_key, current_value "
                    "FROM code_sequence"
                )
            ).all()
        )

        assert rows["PATIENT"] == 9
        assert rows["STAFF"] == 2
        assert rows["TEST"] == 12
        assert rows["DEPARTMENT"] == 0
        assert rows["PANEL"] == 0

    from sqlalchemy.orm import Session

    with Session(engine) as db:
        assert allocate_code(db, "PATIENT") == "PAT-000010"
        assert allocate_code(db, "STAFF") == "STF-000003"
        assert allocate_code(db, "TEST") == "TST-0013"
        db.commit()

    engine.dispose()


def test_overflow_fails_before_creating_sequence_table():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        prepare_legacy_tables(connection)

        connection.execute(
            sa.text(
                "INSERT INTO lab_department (department_code) "
                "VALUES ('DEP-9223372036854775808')"
            )
        )

        with pytest.raises(
            RuntimeError,
            match="exceeds sequence capacity",
        ):
            apply_migration(connection)

        assert not sa.inspect(connection).has_table("code_sequence")

    engine.dispose()


def test_downgrade_is_blocked():
    with pytest.raises(
        RuntimeError,
        match="intentionally blocked",
    ):
        migration.downgrade()


@pytest.mark.parametrize('key,prefix,padding,table,column', migration.SEQUENCES)
def test_all_seven_seeded_exactly_and_legacy_values_preserved(key, prefix, padding, table, column):
    engine = sa.create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as connection:
        prepare_legacy_tables(connection)
        original = ['001', 'CUSTOM-LEGACY', f'{prefix}-1', f'{prefix}-000007',
                    f'{prefix.lower()}-000009', f'{prefix}-000010-ARCHIVE']
        connection.execute(sa.text(f'INSERT INTO {table} ({column}) VALUES (:code)'),
                           [{'code': value} for value in original])
        apply_migration(connection)
        actual = connection.execute(sa.text(
            'SELECT sequence_key, prefix, padding, current_value FROM code_sequence ORDER BY sequence_key'
        )).all()
        assert actual == sorted((k, p, width, 9 if k == key else 0)
                                for k, p, width, _, _ in migration.SEQUENCES)
        assert list(connection.scalars(sa.text(f'SELECT {column} FROM {table}'))) == original
    engine.dispose()


@pytest.mark.parametrize('key,prefix,padding,table,column', migration.SEQUENCES)
def test_maximum_valid_generated_counter_is_preserved(key, prefix, padding, table, column):
    limit = 9_999_999_999_999_999 if key in {'PATIENT', 'STAFF'} else migration.MAX_COUNTER
    engine = sa.create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as connection:
        prepare_legacy_tables(connection)
        value = f'{prefix}-{limit}'
        connection.execute(sa.text(f'INSERT INTO {table} ({column}) VALUES (:code)'), {'code': value})
        apply_migration(connection)
        assert connection.scalar(sa.text('SELECT current_value FROM code_sequence WHERE sequence_key=:key'),
                                 {'key': key}) == limit
        assert connection.scalar(sa.text(f'SELECT {column} FROM {table}')) == value
    engine.dispose()


class MySQLAnswers:
    """Scripted server answers, NOT an implementation of MySQL collation.

    These tests verify control flow, SQL collation selection and refusal before
    DDL. Real equality/order results must be verified in the isolated rehearsal.
    """
    from types import SimpleNamespace
    dialect = SimpleNamespace(name='mysql')

    def __init__(self, values=(), *, collation='utf8mb4_unicode_ci', pad='PAD SPACE',
                 equality=None, in_range=None, length=20):
        self.values = list(values)
        self.metadata = ('utf8mb4', collation, length, pad)
        self.equality = equality or {}
        self.in_range = in_range or {}
        self.calls = []

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        if 'information_schema.COLUMNS' in str(statement):
            return self.SimpleNamespace(one_or_none=lambda: self.metadata)
        assert str(statement).startswith('SELECT `') and 'LIKE' not in str(statement)
        return self.SimpleNamespace(all=lambda: [(value,) for value in self.values])

    def scalar(self, statement, parameters):
        sql = str(statement)
        self.calls.append((sql, parameters))
        assert 'COLLATE ' + self.metadata[1] in sql
        assert parameters['value'] not in sql  # No interpolated identifiers/PII.
        if 'candidate' in parameters:
            return self.equality[(parameters['value'], parameters['candidate'])]
        assert parameters['lower'] == 'PAT-000000'
        assert parameters['upper'] == 'PAT-' + '9' * 16
        return self.in_range[parameters['value']]


@pytest.mark.parametrize('collation,pad', [
    ('utf8mb4_unicode_ci', 'PAD SPACE'),
    ('utf8mb4_0900_ai_ci', 'NO PAD'),
    ('utf8mb4_bin', 'PAD SPACE'),
    ('utf8mb4_0900_bin', 'NO PAD'),
])
def test_mysql_column_metadata_and_ascii_legacy_policy(collation, pad):
    values = ['PAT-000007', 'pat-000009', 'PAT-1', 'P9-LEGACY', 'PAT-000010-ARCHIVE', '001']
    connection = MySQLAnswers(values, collation=collation, pad=pad)
    assert migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT') == 9
    query, parameters = connection.calls[0]
    assert 'c.COLLATION_NAME' in query and 'k.PAD_ATTRIBUTE' in query
    assert 'c.TABLE_SCHEMA = DATABASE()' in query
    assert parameters == {'table_name': 'patient', 'column_name': 'patient_code'}
    assert connection.values == values


@pytest.mark.parametrize('equivalent,expected', [(1, 9), (0, 0)])
def test_accented_prefix_uses_server_equality_not_python_normalization(equivalent, expected):
    value = 'PÁT-000009'
    connection = MySQLAnswers([value], equality={(value, 'PAT-000009'): equivalent},
                              in_range={value: 0})
    assert migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT') == expected
    assert any('candidate' in (parameters or {}) for _, parameters in connection.calls)
    assert connection.values == [value]


@pytest.mark.parametrize('pad,collation,expected', [
    ('PAD SPACE', 'utf8mb4_unicode_ci', 9),
    ('NO PAD', 'utf8mb4_0900_ai_ci', 0),
])
def test_trailing_spaces_follow_effective_pad_attribute(pad, collation, expected):
    value = 'PAT-000009 '
    connection = MySQLAnswers([value], collation=collation, pad=pad,
                              equality={(value, 'PAT-000009'): 1})
    assert migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT') == expected
    comparisons = [parameters for _, parameters in connection.calls if parameters and 'candidate' in parameters]
    assert bool(comparisons) is (pad == 'PAD SPACE')
    assert connection.values == [value]


def test_unrelated_unicode_legacy_code_is_preserved_when_server_rules_out_overlap():
    value = 'LEGACY-患者'
    connection = MySQLAnswers([value], in_range={value: 0})
    assert migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT') == 0
    assert connection.values == [value]


@pytest.mark.parametrize('value,equality', [
    ('PAT-０００００１', {}),
    ('PÁT-000001\u200b', {}),
    ('PAT-000001\t', {}),
    ('PÁT-000001', {('PÁT-000001', 'PAT-000001'): 0}),
])
def test_unresolved_values_in_generated_range_refuse_without_raw_code(value, equality):
    connection = MySQLAnswers([value], equality=equality, in_range={value: 1})
    with pytest.raises(RuntimeError, match='Ambiguous historical identifier') as error:
        migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT')
    assert value not in str(error.value)
    assert 'patient.patient_code' in str(error.value)


@pytest.mark.parametrize('metadata', [
    None,
    ('latin1', 'latin1_swedish_ci', 20, 'PAD SPACE'),
    ('utf8mb4', 'utf8mb4_tr_0900_ai_ci', 20, 'NO PAD'),
    ('utf8mb4', 'untrusted; SELECT secret', 20, 'PAD SPACE'),
    ('utf8mb4', 'utf8mb4_unicode_ci', 20, 'UNKNOWN'),
])
def test_unsupported_metadata_refuses_before_any_ddl(monkeypatch, metadata):
    connection = MySQLAnswers()
    connection.metadata = metadata
    monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', '1')
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    monkeypatch.setattr(migration.op, 'create_table', lambda *a, **k: pytest.fail('DDL started'))
    monkeypatch.setattr(migration.op, 'bulk_insert', lambda *a, **k: pytest.fail('Seeding started'))
    with pytest.raises(RuntimeError, match='Unsupported identifier collation metadata'):
        migration.upgrade()
    assert len(connection.calls) == 1


@pytest.mark.parametrize('key,prefix,padding,table,column', migration.SEQUENCES)
def test_ambiguity_in_any_resource_stops_before_sequence_creation(monkeypatch, key, prefix, padding, table, column):
    # Script only the server's answers; all seven real scanner calls still run.
    connection = MySQLAnswers()
    scanned = []
    original_execute = connection.execute

    def execute(statement, parameters=None):
        sql = str(statement)
        if 'information_schema.COLUMNS' in sql:
            scanned.append(parameters['table_name'])
            return original_execute(statement, parameters)
        values = [f'{prefix}-１２３'] if f'FROM `{table}`' in sql else []
        return connection.SimpleNamespace(all=lambda: [(v,) for v in values])

    monkeypatch.setattr(connection, 'execute', execute)
    monkeypatch.setattr(connection, 'scalar', lambda statement, parameters: 1)
    monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', '1')
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    monkeypatch.setattr(migration.op, 'create_table', lambda *a, **k: pytest.fail('DDL started'))
    monkeypatch.setattr(migration.op, 'bulk_insert', lambda *a, **k: pytest.fail('Seeding started'))
    with pytest.raises(RuntimeError, match=f'Ambiguous historical identifier in {table}.{column}'):
        migration.upgrade()
    assert scanned == [entry[3] for entry in migration.SEQUENCES[:len(scanned)]]
    assert scanned[-1] == table


def test_sqlite_does_not_pretend_to_validate_mysql_unicode_equivalence():
    engine = sa.create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as connection:
        prepare_legacy_tables(connection)
        connection.execute(sa.text('INSERT INTO patient (patient_code) VALUES (:value)'), {'value': 'PÁT-000001'})
        with pytest.raises(RuntimeError, match='requires MySQL collation preflight'):
            apply_migration(connection)
        assert not sa.inspect(connection).has_table('code_sequence')
        assert connection.scalar(sa.text('SELECT patient_code FROM patient')) == 'PÁT-000001'
    engine.dispose()


def test_mysql_ddl_has_exact_model_check_names(monkeypatch):
    from io import StringIO
    from app.models.base import Base
    from app.models.code_sequence import CodeSequence
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable

    output = StringIO()
    context = MigrationContext.configure(dialect_name='mysql', opts={
        'as_sql': True, 'output_buffer': output, 'target_metadata': Base.metadata,
    })
    # Compile DDL only. No engine/connection, server query or migration is run.
    monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', '1')
    monkeypatch.setattr(migration, 'existing_maximum', lambda *args: 0)
    with Operations.context(context):
        migration.upgrade()
    ddl = output.getvalue()
    model = str(CreateTable(CodeSequence.__table__).compile(dialect=dialect()))
    for name in ('ck_code_sequence_nonnegative_value', 'ck_code_sequence_valid_padding'):
        assert f'CONSTRAINT {name} CHECK' in ddl
        assert f'CONSTRAINT {name} CHECK' in model
    assert 'ck_code_sequence_ck_' not in ddl
    assert 'current_value >= 0' in ddl and 'padding >= 1 AND padding <= 16' in ddl
    assert 'ENGINE=InnoDB' in ddl and 'CHARSET=utf8mb4' in ddl


@pytest.mark.parametrize('acknowledgement', [None, '0', 'yes'])
def test_mysql_writer_exclusion_requires_explicit_acknowledgement(monkeypatch, acknowledgement):
    connection = MySQLAnswers()
    if acknowledgement is None:
        monkeypatch.delenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', raising=False)
    else:
        monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', acknowledgement)
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    monkeypatch.setattr(migration.op, 'create_table', lambda *a, **k: pytest.fail('DDL started'))
    with pytest.raises(RuntimeError, match='all application/import writers stopped'):
        migration.upgrade()
    assert connection.calls == []


def test_multiple_mysql_aliases_reserve_the_largest_confirmed_number():
    values = ['PAT-000002', 'pat-3', 'PÁT-000007', 'PAT-000009 ', 'PAT-000010-ARCHIVE']
    connection = MySQLAnswers(values, equality={
        ('PÁT-000007', 'PAT-000007'): 1, ('PAT-000009 ', 'PAT-000009'): 1,
    })
    assert migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT') == 9
    assert connection.values == values


def test_mysql_confirmed_alias_overflow_refuses_before_ddl(monkeypatch):
    value = f'PÁT-{migration.MAX_COUNTER + 1}'
    connection = MySQLAnswers([value], length=40,
                              equality={(value, f'PAT-{migration.MAX_COUNTER + 1}'): 1})
    monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', '1')
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    monkeypatch.setattr(migration.op, 'create_table', lambda *a, **k: pytest.fail('DDL started'))
    with pytest.raises(RuntimeError, match='exceeds sequence capacity') as error:
        migration.upgrade()
    assert value not in str(error.value)


@pytest.mark.parametrize('answer', [None, 2])
def test_inconclusive_mysql_comparison_fails_closed(answer):
    value = 'PÁT-000007'
    connection = MySQLAnswers([value], equality={(value, 'PAT-000007'): answer})
    with pytest.raises(RuntimeError, match='comparison was inconclusive'):
        migration.existing_maximum(connection, 'patient', 'patient_code', 'PAT')


def test_effective_column_capacity_preflight_refuses_before_ddl(monkeypatch):
    connection = MySQLAnswers(length=9)  # PAT- plus six digits requires ten.
    monkeypatch.setenv('RHU_AUTO_CODE_MIGRATION_WRITERS_STOPPED', '1')
    monkeypatch.setattr(migration.op, 'get_bind', lambda: connection)
    monkeypatch.setattr(migration.op, 'create_table', lambda *a, **k: pytest.fail('DDL started'))
    with pytest.raises(RuntimeError, match='column capacity is insufficient'):
        migration.upgrade()


def test_reentry_cannot_reset_existing_counter_or_replace_identifiers():
    from sqlalchemy.orm import Session
    engine = sa.create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as connection:
        prepare_legacy_tables(connection)
        connection.execute(sa.text("INSERT INTO patient (patient_code) VALUES ('PAT-000007')"))
        apply_migration(connection)
    with Session(engine) as session:
        assert allocate_code(session, 'PATIENT') == 'PAT-000008'
        session.commit()
    with engine.begin() as connection:
        with pytest.raises(sa.exc.OperationalError, match='already exists'):
            apply_migration(connection)
        assert connection.scalar(sa.text("SELECT current_value FROM code_sequence WHERE sequence_key='PATIENT'")) == 8
        assert connection.scalar(sa.text('SELECT COUNT(*) FROM code_sequence')) == 7
        assert connection.scalar(sa.text('SELECT patient_code FROM patient')) == 'PAT-000007'
    engine.dispose()
