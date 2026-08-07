"""Tests for the canonical schema contract used by deployment gates."""

from apps.data_center.infrastructure.canonical_schema_contract import (
    CANONICAL_SCHEMA_MIGRATIONS,
    CANONICAL_SCHEMA_TABLES,
    build_canonical_schema_report,
)


def test_canonical_schema_report_is_complete_for_required_tables_and_migrations() -> None:
    report = build_canonical_schema_report(CANONICAL_SCHEMA_TABLES, CANONICAL_SCHEMA_MIGRATIONS)

    assert report == {"missing_tables": [], "missing_migrations": []}
    assert "data_center_archive_member" in CANONICAL_SCHEMA_TABLES
    assert "data_center_archive_restore_audit" in CANONICAL_SCHEMA_TABLES
    assert "0063_archivemanifest_archive_restore_evidence" in CANONICAL_SCHEMA_MIGRATIONS


def test_canonical_schema_report_lists_missing_items_in_stable_order() -> None:
    report = build_canonical_schema_report(
        actual_tables={CANONICAL_SCHEMA_TABLES[-1]},
        applied_migrations=(),
    )

    assert report["missing_tables"] == sorted(CANONICAL_SCHEMA_TABLES[:-1])
    assert report["missing_migrations"] == list(CANONICAL_SCHEMA_MIGRATIONS)
