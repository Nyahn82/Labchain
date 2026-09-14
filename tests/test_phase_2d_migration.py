from datetime import date, datetime
from io import StringIO
from hashlib import sha256
from pathlib import Path
import re

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa

from app.models import Base
from test_phase_2a_migration import config, revision, REVISION, PHASE_2B, PHASE_2C, HEAD
from test_phase_2d_models import TABLES, PREVIOUS_TABLES, UNIQUES, ENUMS

ORDER = [
    "report_template", "lab_report", "report_result_item", "report_patient_snapshot",
    "signatory", "report_signatory", "report_verification", "email_log", "print_log",
    "audit_log", "login_log", "attachment", "blockchain_node", "blockchain_event",
    "blockchain_verification_log", "blockchain_sync_log",
]
NOW = datetime(2026, 9, 14, 12, 0)
# Synthetic storage fixtures only; these are never seeded by the migration.
ROWS = {
    "report_template": dict(template_id=1, template_code="SYNTH", template_name="Synthetic"),
    "lab_report": dict(report_id=1, report_code="SYNTH-1", order_id=1, facility_id=1,
                       version_no=1, report_status="GENERATED", generated_by_user_id=1, generated_at=NOW),
    "report_result_item": dict(report_result_item_id=1, report_id=1, result_item_id=1,
                               test_name_snapshot="Printed synthetic test", result_value_snapshot="1.125",
                               unit_snapshot="synthetic unit", reference_range_snapshot="synthetic range", sort_order=1),
    "report_patient_snapshot": dict(report_id=1, patient_code="SYNTH", patient_name="Printed Test Person",
                                    birth_date=date(2000, 1, 1), age_at_report=26),
    "signatory": dict(signatory_id=1, staff_id=1),
    "report_signatory": dict(report_signatory_id=1, report_id=1, signatory_id=1,
                             signatory_type="MEDICAL_TECHNOLOGIST", sort_order=1),
    "report_verification": dict(verification_id=1, report_id=1, verification_token="synthetic-token-a",
                                report_hash="a" * 64, verification_status="AUTHENTIC"),
    "email_log": dict(email_log_id=1, recipient_email="synthetic@example.invalid", status="PENDING"),
    "print_log": dict(print_log_id=1, report_id=1, printed_by_user_id=1, printed_at=NOW, copies=1),
    "audit_log": dict(audit_id=1, action="SYNTHETIC_ACTION", entity_type="LAB_REPORT",
                      old_value=None, new_value={"status": "GENERATED"}, ip_address="2001:db8::1"),
    "login_log": dict(login_log_id=1, username_attempted="unknown-synthetic", login_time=NOW, status="FAILED"),
    "attachment": dict(attachment_id=1, order_id=1, file_name="synthetic.txt",
                       file_path="synthetic/attachment.txt", uploaded_at=NOW),
    "blockchain_node": dict(node_id=1, node_code="SYNTH-1", port=15001),
    "blockchain_event": dict(event_id=1, event_uuid="00000000-0000-4000-8000-000000000001", origin_node_id=1,
                             entity_type="LAB_REPORT", entity_id=1, event_type="SYNTHETIC_EVENT",
                             record_hash="b" * 64, event_status="PENDING"),
    "blockchain_verification_log": dict(verification_log_id=1, event_id=1, node_id=1,
                                        database_hash="b" * 64, chain_hash="b" * 64,
                                        verification_status="MATCH", checked_at=NOW),
    "blockchain_sync_log": dict(sync_log_id=1, source_node_id=1, target_node_id=1,
                                sync_status="SUCCESS", synced_at=NOW),
}


def test_single_head_and_offline_mysql_scope(monkeypatch):
    from app.database import engine

    def no_connection():
        pytest.fail("Offline migration must not open a database connection")

    monkeypatch.setattr(engine, "connect", no_connection)
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PHASE_2C
    assert [r.revision for r in scripts.walk_revisions()] == [HEAD, PHASE_2C, PHASE_2B, REVISION]
    output = StringIO()
    command.upgrade(config(output), f"{PHASE_2C}:{HEAD}", sql=True)
    sql = output.getvalue()
    assert re.findall(r"CREATE TABLE `?([a-z_]+)`? \(", sql) == ORDER
    assert sql.count("AUTO_INCREMENT") == 15
    assert sql.count("ENGINE=InnoDB") == 16
    assert sql.count("CHARSET=utf8mb4") == 16
    assert sql.count("FOREIGN KEY") == 32
    assert sql.count("CREATE INDEX") == 31
    assert sql.count("UNIQUE (") == 6
    assert "CONSTRAINT ck_attachment_parent_required CHECK (order_id IS NOT NULL OR report_id IS NOT NULL)" in sql
    assert "supersedes_report_id) REFERENCES lab_report (report_id)" in sql
    assert "old_value JSON" in sql and "new_value JSON" in sql
    assert "event_uuid CHAR(36)" in sql
    assert "report_hash CHAR(64)" in sql and "record_hash CHAR(64)" in sql
    assert "database_hash CHAR(64)" in sql and "chain_hash CHAR(64)" in sql
    for table, column, values in ENUMS:
        assert "ENUM(" + ",".join(repr(v) for v in values) + ")" in sql
    assert "INSERT INTO" not in sql and "DELETE FROM" not in sql
    assert "ALTER TABLE" not in sql and "synthetic-test-only" not in sql
    for name in ORDER:
        for fk in Base.metadata.tables[name].foreign_keys:
            if fk.column.table.name in TABLES:
                # Self-reference is defined inside lab_report's CREATE TABLE.
                assert ORDER.index(fk.column.table.name) <= ORDER.index(name)
    output = StringIO()
    command.downgrade(config(output), f"{HEAD}:{PHASE_2C}", sql=True)
    assert re.findall(r"DROP TABLE `?([a-z_]+)`?;", output.getvalue()) == list(reversed(ORDER))
    assert "DROP INDEX" not in output.getvalue()


@pytest.fixture
def reporting_connection():
    engine = sa.create_engine("sqlite://")
    t = Base.metadata.tables
    try:
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(c)):
                for rev in (REVISION, PHASE_2B, PHASE_2C):
                    revision(rev).upgrade()
            previous_rows = {
                "facility_profile": dict(facility_id=1, facility_name="Synthetic facility"),
                "patient": dict(patient_id=1, patient_code="SYNTH", first_name="Test", last_name="Person", birth_date=date(2000, 1, 1)),
                "staff": dict(staff_id=1, staff_code="SYNTH", first_name="Test", last_name="Staff"),
                "user_account": dict(user_id=1, username="synthetic", password_hash="synthetic-only", account_status="ACTIVE"),
                "lab_department": dict(department_id=1, department_code="SYNTH", department_name="Synthetic"),
                "test_catalog": dict(test_id=1, test_code="SYNTH", test_name="Synthetic test", department_id=1, result_type="NUMERIC"),
                "test_panel": dict(panel_id=1, panel_code="SYNTH", panel_name="Synthetic panel"),
                "lab_order": dict(order_id=1, order_code="SYNTH", patient_id=1, order_date=NOW, priority="ROUTINE", status="REQUESTED"),
                "lab_order_item": dict(order_item_id=1, order_id=1, test_id=1, status="REQUESTED"),
                "lab_result_item": dict(result_item_id=1, order_item_id=1, result_value="1.125", status="VERIFIED",
                                        encoded_by_user_id=1, encoded_at=NOW, reviewed_by_user_id=1,
                                        reviewed_at=NOW, verified_by_user_id=1, verified_at=NOW),
            }
            for name, values in previous_rows.items():
                c.execute(t[name].insert().values(**values))
            before = {name: c.execute(sa.select(t[name])).all() for name in PREVIOUS_TABLES}
            c.commit()
            with Operations.context(MigrationContext.configure(c)):
                revision(HEAD).upgrade()
            assert set(sa.inspect(c).get_table_names()) == PREVIOUS_TABLES | TABLES
            for name in ORDER:
                assert c.scalar(sa.select(sa.func.count()).select_from(t[name])) == 0
                c.execute(t[name].insert().values(**ROWS[name]))
            yield c
            with Operations.context(MigrationContext.configure(c)):
                revision(HEAD).downgrade()
            assert set(sa.inspect(c).get_table_names()) == PREVIOUS_TABLES
            assert {name: c.execute(sa.select(t[name])).all() for name in PREVIOUS_TABLES} == before
            with Operations.context(MigrationContext.configure(c)):
                for rev in (PHASE_2C, PHASE_2B, REVISION):
                    revision(rev).downgrade()
            assert sa.inspect(c).get_table_names() == []
    finally:
        engine.dispose()


def test_all_foreign_keys_and_required_values(reporting_connection):
    c = reporting_connection
    for name in ORDER:
        table = Base.metadata.tables[name]
        for fk in table.foreign_key_constraints:
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(table.update().values(**{col.name: 999 for col in fk.columns}))
        for column in table.c:
            if column.nullable or column.primary_key:
                continue
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(table.update().values(**{column.name: None}))
    for name in ("lab_report", "report_template", "signatory", "blockchain_node", "blockchain_event",
                 "lab_order", "lab_result_item", "facility_profile", "staff", "user_account"):
        # report_template is optional: explicitly link it before checking deletion.
        if name == "report_template":
            c.execute(Base.metadata.tables["lab_report"].update().values(template_id=1))
        with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
            c.execute(Base.metadata.tables[name].delete())


def test_uniqueness_snapshot_key_and_allowed_multiplicity(reporting_connection):
    c = reporting_connection
    t = Base.metadata.tables
    for name, uniques in UNIQUES.items():
        table = t[name]
        pk = next(iter(table.primary_key.columns)).name
        for unique in uniques:
            values = {**ROWS[name], pk: 2}
            if name == "blockchain_node":
                # Exercise each independent unique key without masking the other.
                values.update(node_code="SYNTH-2", port=15002)
                values[unique[0]] = ROWS[name][unique[0]]
            with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
                c.execute(table.insert().values(**values))
    with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
        c.execute(t["report_patient_snapshot"].insert().values(**ROWS["report_patient_snapshot"]))
    for name in ("signatory", "report_signatory", "report_result_item", "print_log", "email_log", "audit_log", "login_log"):
        table = t[name]
        pk = next(iter(table.primary_key.columns)).name
        c.execute(table.insert().values(**{**ROWS[name], pk: 2}))
        assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 2
    c.execute(t["report_verification"].insert().values(**{
        **ROWS["report_verification"], "verification_id": 2, "verification_token": "synthetic-token-b",
    }))
    assert c.scalar(sa.select(sa.func.count()).select_from(t["report_verification"])) == 2


def test_attachment_accepts_either_or_both_parents_but_never_neither(reporting_connection):
    c = reporting_connection
    table = Base.metadata.tables["attachment"]
    for attachment_id, order_id, report_id in [(2, 1, None), (3, None, 1), (4, 1, 1)]:
        c.execute(table.insert().values(**{
            **ROWS["attachment"], "attachment_id": attachment_id, "order_id": order_id, "report_id": report_id,
        }))
    with c.begin_nested(), pytest.raises(sa.exc.IntegrityError, match="ck_attachment_parent_required"):
        c.execute(table.insert().values(**{**ROWS["attachment"], "attachment_id": 5, "order_id": None}))
    with c.begin_nested(), pytest.raises(sa.exc.IntegrityError, match="ck_attachment_parent_required"):
        c.execute(table.update().where(table.c.attachment_id == 1).values(order_id=None, report_id=None))


def test_report_version_link_and_stored_snapshots(reporting_connection):
    c = reporting_connection
    t = Base.metadata.tables
    c.execute(t["lab_report"].update().values(report_status="RELEASED", released_by_user_id=1, released_at=NOW))
    c.execute(t["lab_report"].insert().values(**{
        **ROWS["lab_report"], "report_id": 2, "report_code": "SYNTH-2", "version_no": 2, "supersedes_report_id": 1,
    }))
    c.execute(t["report_patient_snapshot"].insert().values(**{
        **ROWS["report_patient_snapshot"], "report_id": 2, "patient_name": "Corrected printed name",
    }))
    with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
        c.execute(t["lab_report"].delete().where(t["lab_report"].c.report_id == 1))
    # A dedicated version without child rows isolates self-FK protection.
    for report_id, prior in [(3, None), (4, 3)]:
        c.execute(t["lab_report"].insert().values(**{
            **ROWS["lab_report"], "report_id": report_id, "report_code": f"SYNTH-{report_id}",
            "version_no": report_id, "supersedes_report_id": prior,
        }))
    with c.begin_nested(), pytest.raises(sa.exc.IntegrityError):
        c.execute(t["lab_report"].delete().where(t["lab_report"].c.report_id == 3))
    with c.begin_nested() as change:
        c.execute(t["patient"].update().values(first_name="Changed", birth_date=date(2001, 1, 1)))
        c.execute(t["test_catalog"].update().values(test_name="Changed catalog name"))
        c.execute(t["lab_result_item"].update().values(result_value="Changed live value"))
        patient = c.execute(sa.select(t["report_patient_snapshot"]).where(t["report_patient_snapshot"].c.report_id == 1)).one()
        line = c.execute(sa.select(t["report_result_item"])).one()
        assert patient.patient_name == "Printed Test Person" and patient.age_at_report == 26
        assert patient.birth_date == date(2000, 1, 1)
        assert line.test_name_snapshot == "Printed synthetic test"
        assert line.result_value_snapshot == "1.125"
        assert line.reference_range_snapshot == "synthetic range"
        change.rollback()  # Preserve earlier-phase fixture data for downgrade checks.


def test_json_optional_log_references_and_defaults(reporting_connection):
    c = reporting_connection
    t = Base.metadata.tables
    row = c.execute(sa.select(t["audit_log"])).one()
    assert row.old_value is None and row.new_value == {"status": "GENERATED"}
    assert row.user_id is None and row.ip_address == "2001:db8::1"
    assert c.scalar(sa.select(t["audit_log"].c.old_value.is_(None))) is True
    assert c.scalar(sa.select(t["login_log"].c.user_id)) is None
    email = c.execute(sa.select(t["email_log"])).one()
    assert email.report_id is None and email.patient_id is None
    assert email.recipient_email == "synthetic@example.invalid"
    for name in ("report_template", "signatory", "blockchain_node"):
        assert c.scalar(sa.select(t[name].c.is_active)) is True
    for name in ("report_verification", "audit_log", "blockchain_event"):
        assert c.scalar(sa.select(t[name].c.created_at)) is not None


@pytest.mark.parametrize("filename,expected_digest", [
    ('migrations/versions/20260914_01_phase_2a_identity_auth.py',
     'ad3f34d73c20c01fb810c056c28a95a0b5d44e930466020a80f09d9241e433ff'),
    ('migrations/versions/20260914_02_phase_2b_laboratory_master_data.py',
     'f31c42a50e766ee8f4e438c629bdd733f59df97e844805198b2e81806e1dfb32'),
    ('migrations/versions/20260914_03_phase_2c_laboratory_workflow.py',
     '03e84df36ace7aa3d8216486bd6013dd7849b5ddae1a6453dc72e1a06eab2b26'),
])
def test_deployed_migration_files_are_unchanged(filename, expected_digest):
    # Freeze deployed history independently of mutable model metadata.
    path = Path(__file__).resolve().parents[1] / filename
    assert sha256(path.read_bytes()).hexdigest() == expected_digest
