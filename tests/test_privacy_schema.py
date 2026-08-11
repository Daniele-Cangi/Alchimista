from pathlib import Path


def test_vault_schema_enforces_document_lifecycle_for_new_and_existing_databases() -> None:
    schema = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text(encoding="utf-8")

    assert "CONSTRAINT pii_vault_document_fk" in schema
    assert "REFERENCES documents(doc_id) ON DELETE CASCADE" in schema
    assert "DELETE FROM pii_vault AS vault" in schema
    assert "ADD CONSTRAINT pii_vault_document_fk" in schema


def test_runtime_settings_are_separate_from_historical_document_evidence() -> None:
    schema = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS runtime_settings (" in schema
    assert "CREATE TABLE IF NOT EXISTS runtime_settings_history (" in schema
    assert "CREATE TABLE IF NOT EXISTS document_privacy (" in schema
    assert "privacy_detector TEXT NOT NULL CHECK" in schema
