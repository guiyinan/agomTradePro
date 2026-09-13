"""Verify publication evidence migrations retain legacy rows and schema state."""

from __future__ import annotations

from contextlib import contextmanager

from django.db import connections
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

_ALIAS = "data16_publication_evidence_migration"
_LEGACY_MIGRATION = ("data_center", "0076_publication_policy_versions")
_PUBLICATION_TABLE = "data_center_canonical_publication"
_MEMBER_TABLE = "data_center_publication_member"
_LEGACY_PUBLICATION_COLUMNS = (
    "publication_id",
    "dataset_key",
    "publication_key",
    "policy_version",
    "state",
    "selected_source",
    "publication_hash",
    "member_count",
    "conflict_count",
    "coverage_requested_count",
    "coverage_eligible_count",
    "coverage_selected_count",
    "coverage_missing_count",
    "coverage_conflict_count",
    "as_of",
    "published_at",
    "superseded_at",
    "must_not_use_for_decision",
    "blocked_reason",
    "created_by",
    "run_id",
    "created_at",
    "updated_at",
    "reinstated_at",
)
_LEGACY_MEMBER_COLUMNS = (
    "member_id",
    "publication_id",
    "dataset_key",
    "natural_key",
    "source",
    "source_record_id",
    "fact_table",
    "fact_pk",
    "observed_at",
    "raw_payload_hash",
    "quality_status",
    "revision_number",
)
_NEW_MEMBER_COLUMNS = (
    "available_at",
    "fact_content_hash",
    "fetched_at",
    "raw_payload_scope",
    "source_published_at",
)


@contextmanager
def _isolated_legacy_schema(django_db_blocker):
    """Create only the legacy publication tables on an in-memory SQLite alias."""

    settings = dict(connections["default"].settings_dict)
    settings["NAME"] = ":memory:"
    wrapper = connections["default"].__class__(settings, alias=_ALIAS)
    connections[_ALIAS] = wrapper
    with django_db_blocker.unblock():
        try:
            with override_settings(MIGRATION_MODULES={}):
                loader = MigrationLoader(wrapper)
                state = loader.project_state([_LEGACY_MIGRATION])
                with wrapper.schema_editor() as editor:
                    for model_name in ("CanonicalPublicationModel", "PublicationMemberModel"):
                        editor.create_model(state.apps.get_model("data_center", model_name))
                yield wrapper, loader, state
        finally:
            wrapper.close()
            del connections[_ALIAS]


def _insert_legacy_rows(wrapper) -> None:
    """Insert one pre-evidence publication and member row with stable legacy values."""

    with wrapper.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_center_canonical_publication "
            "(publication_id, dataset_key, publication_key, policy_version, state, "
            "selected_source, publication_hash, member_count, conflict_count, "
            "coverage_requested_count, coverage_eligible_count, coverage_selected_count, "
            "coverage_missing_count, coverage_conflict_count, as_of, published_at, "
            "superseded_at, must_not_use_for_decision, blocked_reason, created_by, run_id, "
            "created_at, updated_at, reinstated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,"
            "CURRENT_TIMESTAMP,NULL,%s,%s,%s,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL)",
            [
                "11111111-1111-4111-8111-111111111111",
                "equity.valuation.fact",
                "current",
                "legacy-policy",
                "published",
                "legacy-source",
                "a" * 64,
                1,
                0,
                1,
                1,
                1,
                0,
                0,
                False,
                "",
                "migration-test",
            ],
        )
        cursor.execute(
            "INSERT INTO data_center_publication_member "
            "(member_id, publication_id, dataset_key, natural_key, source, source_record_id, "
            "fact_table, fact_pk, observed_at, raw_payload_hash, quality_status, revision_number) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s)",
            [
                "22222222-2222-4222-8222-222222222222",
                "11111111-1111-4111-8111-111111111111",
                "equity.valuation.fact",
                "000001.SZ:2026-09-11:legacy",
                "legacy-source",
                "legacy-record",
                "data_center_valuation_fact",
                "42",
                "b" * 64,
                "accepted",
                1,
            ],
        )


def _fetch_row(wrapper, table: str, columns: tuple[str, ...]) -> dict[str, object]:
    """Fetch one row by the fixed migration-test table and column names."""

    with wrapper.cursor() as cursor:
        cursor.execute(f"SELECT {', '.join(columns)} FROM {table}")
        row = cursor.fetchone()
    assert row is not None
    return dict(zip(columns, row, strict=True))


def _column_names(wrapper, table: str) -> set[str]:
    """Return the actual columns created by the migration schema editor."""

    with wrapper.cursor() as cursor:
        return {
            column.name for column in wrapper.introspection.get_table_description(cursor, table)
        }


def test_forward_evidence_migrations_preserve_legacy_rows_and_default_new_fields(
    django_db_blocker,
) -> None:
    """Forward migrations retain legacy values and leave new evidence unpopulated."""

    with _isolated_legacy_schema(django_db_blocker) as (wrapper, loader, state_0076):
        _insert_legacy_rows(wrapper)
        before_publication = _fetch_row(wrapper, _PUBLICATION_TABLE, _LEGACY_PUBLICATION_COLUMNS)
        before_member = _fetch_row(wrapper, _MEMBER_TABLE, _LEGACY_MEMBER_COLUMNS)

        migration_0077 = loader.get_migration(
            "data_center", "0077_publication_evidence_identity_width"
        )
        migration_0078 = loader.get_migration(
            "data_center", "0078_frozen_publication_member_evidence"
        )
        with wrapper.schema_editor() as editor:
            state_0077 = migration_0077.apply(state_0076, editor)
            state_0078 = migration_0078.apply(state_0077, editor)

        after_publication = _fetch_row(wrapper, _PUBLICATION_TABLE, _LEGACY_PUBLICATION_COLUMNS)
        after_member = _fetch_row(
            wrapper, _MEMBER_TABLE, _LEGACY_MEMBER_COLUMNS + _NEW_MEMBER_COLUMNS
        )
        assert after_publication == before_publication
        assert {key: after_member[key] for key in _LEGACY_MEMBER_COLUMNS} == before_member
        assert after_member["available_at"] is None
        assert after_member["fetched_at"] is None
        assert after_member["source_published_at"] is None
        assert after_member["raw_payload_scope"] == ""
        assert after_member["fact_content_hash"] == ""

        policy_field = state_0077.apps.get_model(
            "data_center", "CanonicalPublicationModel"
        )._meta.get_field("policy_version")
        assert policy_field.max_length == 128
        member_state = state_0078.apps.get_model("data_center", "PublicationMemberModel")
        assert {field.name for field in member_state._meta.local_fields} >= set(_NEW_MEMBER_COLUMNS)
        assert _column_names(wrapper, _MEMBER_TABLE) >= set(_NEW_MEMBER_COLUMNS)


def test_reverse_evidence_migrations_restore_legacy_schema_without_rewriting_rows(
    django_db_blocker,
) -> None:
    """Reverse migrations restore the legacy schema while preserving old row values."""

    with _isolated_legacy_schema(django_db_blocker) as (wrapper, loader, state_0076):
        _insert_legacy_rows(wrapper)
        before_publication = _fetch_row(wrapper, _PUBLICATION_TABLE, _LEGACY_PUBLICATION_COLUMNS)
        before_member = _fetch_row(wrapper, _MEMBER_TABLE, _LEGACY_MEMBER_COLUMNS)
        state_before_0077 = state_0076.clone()
        migration_0077 = loader.get_migration(
            "data_center", "0077_publication_evidence_identity_width"
        )
        migration_0078 = loader.get_migration(
            "data_center", "0078_frozen_publication_member_evidence"
        )
        with wrapper.schema_editor() as editor:
            state_0077 = migration_0077.apply(state_0076, editor)
            state_before_0078 = state_0077.clone()
            migration_0078.apply(state_0077, editor)
            migration_0078.unapply(state_before_0078, editor)
            migration_0077.unapply(state_before_0077, editor)

        assert (
            _fetch_row(wrapper, _PUBLICATION_TABLE, _LEGACY_PUBLICATION_COLUMNS)
            == before_publication
        )
        assert _fetch_row(wrapper, _MEMBER_TABLE, _LEGACY_MEMBER_COLUMNS) == before_member
        assert not _column_names(wrapper, _MEMBER_TABLE).intersection(_NEW_MEMBER_COLUMNS)
        policy_field = state_before_0077.apps.get_model(
            "data_center", "CanonicalPublicationModel"
        )._meta.get_field("policy_version")
        assert policy_field.max_length == 80
