import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from sequence_vault.adapters.persistence.migrate import migrations_dir, upgrade
from sequence_vault.adapters.persistence.tables import metadata

SEED = """
INSERT INTO tenant VALUES ('t1', 'Dept');
INSERT INTO project (id, tenant_id, name) VALUES ('p1', 't1', 'Antibodies');
INSERT INTO app_user VALUES ('u1', 't1', 'alice@corp', 'Alice');
INSERT INTO source_file (id, tenant_id, project_id, uploaded_by, original_name, declared_bytes,
    declared_sha256, object_key)
VALUES ('f1', 't1', 'p1', 'u1', 'a.fasta', 10, repeat('a', 64), 'k1');
INSERT INTO extraction_run (id, file_id, generation, schema_version, qc_version)
VALUES ('r1', 'f1', 1, '1.0', '1.0');
INSERT INTO document_block
VALUES ('r1', 'p1', 0, 'sequence', 'MKT', '{"kind": "text"}', 'text_parser');
INSERT INTO sequence_entity (id, tenant_id, molecule_type, canonical_sequence, length, sha256)
VALUES ('e1', 't1', 'protein', 'MKT', 3, 'h1');
INSERT INTO record (id, tenant_id, project_id, name_key, display_name)
VALUES ('rec1', 't1', 'p1', 'abc', 'ABC');
INSERT INTO record_version (id, record_id, version_no, sequence_entity_id, is_current, created_by)
VALUES ('v1', 'rec1', 1, 'e1', true, 'u1');
"""


def seed(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(SEED))


def test_migrated_schema_matches_table_definitions(engine: Engine) -> None:
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), metadata)
    # Trigram, partial and expression indexes can only be expressed in the migration.
    migration_only = {
        "record_name_trgm",
        "record_one_current_version",
        "stage_job_ready",
        "app_user_subject_lower",
    }
    relevant = [d for d in differences if getattr(d[1], "name", None) not in migration_only]
    assert relevant == []


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE document_block SET raw_text = 'XXX'",
        "DELETE FROM document_block",
        "UPDATE sequence_entity SET canonical_sequence = 'MKW'",
        "UPDATE record_version SET sequence_entity_id = 'e1', version_no = 2",
        "DELETE FROM record_version",
    ],
)
def test_evidence_and_published_content_are_immutable(engine: Engine, statement: str) -> None:
    seed(engine)
    with pytest.raises(DBAPIError, match=r"immutable|only be superseded"), engine.begin() as c:
        c.execute(text(statement))


def test_a_version_can_be_superseded_but_not_revived(engine: Engine) -> None:
    seed(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE record_version SET is_current = false"))
    with pytest.raises(DBAPIError, match="only be superseded"), engine.begin() as c:
        c.execute(text("UPDATE record_version SET is_current = true"))


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO sequence_entity (id, tenant_id, molecule_type, canonical_sequence,"
        " length, sha256) VALUES ('e2', 't1', 'protein', 'MKT', 3, 'h1')",
        "INSERT INTO record (id, tenant_id, project_id, name_key, display_name)"
        " VALUES ('rec2', 't1', 'p1', 'abc', 'abc')",
        "INSERT INTO record_version (id, record_id, version_no, sequence_entity_id, is_current,"
        " created_by) VALUES ('v2', 'rec1', 1, 'e1', false, 'u1')",
        "INSERT INTO record_version (id, record_id, version_no, sequence_entity_id, is_current,"
        " created_by) VALUES ('v2', 'rec1', 2, 'e1', true, 'u1')",
        "INSERT INTO sequence_entity (id, tenant_id, molecule_type, canonical_sequence,"
        " length, sha256) VALUES ('e3', 't1', 'protein', 'MKT', 4, 'h3')",
    ],
)
def test_uniqueness_and_consistency_constraints(engine: Engine, statement: str) -> None:
    seed(engine)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(statement))


def test_migration_0005_stops_on_sign_in_names_differing_in_case(
    engine: Engine, database_url: str
) -> None:
    """The unique lower(subject) index cannot be built over case variants: say which."""
    config = Config(str(migrations_dir() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.downgrade(config, "0004")
    with engine.begin() as connection:
        connection.execute(text(SEED.split("\n")[1]))
        connection.execute(
            text(
                "INSERT INTO app_user VALUES ('u1', 't1', 'alice@corp', 'Alice'), "
                "('u2', 't1', 'Alice@Corp', 'Alice 2')"
            )
        )
    with pytest.raises(RuntimeError, match=r"alice@corp \(2 users\)"):
        upgrade(database_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0004"
        )
