"""Canonical Data Center schema contract used by deployment gates."""

from __future__ import annotations

from collections.abc import Collection

CANONICAL_SCHEMA_TABLES: tuple[str, ...] = (
    "data_center_canonical_publication",
    "data_center_coverage_snapshot",
    "data_center_publication_member",
    "data_center_quarantine_record",
    "data_center_sync_run",
    "data_center_sync_batch",
    "data_center_sync_checkpoint",
    "data_center_raw_payload",
    "data_center_schema_fingerprint",
    "data_center_archive_manifest",
    "data_center_archive_member",
    "data_center_archive_restore_audit",
    "data_center_retention_policy",
    "data_center_storage_hold",
    "data_center_data_owner_registration",
    "data_center_dataset_contract",
    "data_center_dataset_provider_binding",
    "data_center_dataset_publication_policy",
    "data_center_reconciliation_evidence",
    "data_center_retention_run",
    "data_center_retention_plan",
    "data_center_retention_plan_member",
    "data_center_publication_rollback",
)

CANONICAL_SCHEMA_MIGRATIONS: tuple[str, ...] = (
    "0057_publicationrollbackmodel",
    "0063_archivemanifest_archive_restore_evidence",
    "0064_retention_exact_plan_members",
    "0065_widen_retention_member_digests",
)


def build_canonical_schema_report(
    actual_tables: Collection[str],
    applied_migrations: Collection[str],
) -> dict[str, list[str]]:
    """Return missing canonical tables and migration markers in stable order."""

    actual_table_set = {str(value) for value in actual_tables}
    applied_migration_set = {str(value) for value in applied_migrations}
    return {
        "missing_tables": sorted(set(CANONICAL_SCHEMA_TABLES) - actual_table_set),
        "missing_migrations": sorted(set(CANONICAL_SCHEMA_MIGRATIONS) - applied_migration_set),
    }


__all__ = [
    "CANONICAL_SCHEMA_MIGRATIONS",
    "CANONICAL_SCHEMA_TABLES",
    "build_canonical_schema_report",
]
