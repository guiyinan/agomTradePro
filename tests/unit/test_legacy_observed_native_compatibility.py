"""Proof graph rejection mechanics; synthetic inputs grant no deployment qualification."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_legacy_observed_native_compatibility as verifier


def _proof(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, dict[str, object]]]:
    candidate = tmp_path / "candidate"
    migrations = candidate / "apps/data_center/migrations"
    migrations.mkdir(parents=True)
    (migrations / "0118_example.py").write_text("# synthetic migration bytes\n", encoding="utf-8")
    (candidate / ".agom-release-manifest.json").write_text(
        json.dumps({"source_commit": "a" * 40, "image_id": "sha256:" + "b" * 64}), encoding="utf-8"
    )
    evidence = {
        scope: {"row_count": 1, "fields": ["id", "value"], "rows_sha256": "1" * 64}
        for scope in verifier._ROW_SCOPES
    }
    legacy: dict[str, object] = {
        "schema": verifier._SUMMARY_SCHEMA,
        "side": "legacy",
        "database_identity": {"database_name": "data02_compat_untouched"},
        "native_numeric_columns_present": False,
        "field_sets": {scope: ["id", "value"] for scope in verifier._ROW_SCOPES},
        "row_evidence": evidence,
        "member_fact_hash_pairs": {"row_count": 1, "pairs_sha256": "2" * 64},
        "numeric_state": {"native_columns_present": False},
        "data_center_catalog": {
            "database_name": "data02_compat_untouched",
            "tables": {
                table: {"fields": ["id", "value"], "order": ["id"], "rows": 1, "sha256": "7" * 64}
                for table in ("data_center_financial_fact", "data_center_canonical_publication")
            },
        },
    }
    migrated = copy.deepcopy(legacy)
    migrated.update(
        side="migrated",
        database_identity={"database_name": "data02_compat_migrated"},
        native_numeric_columns_present=True,
        numeric_state={
            "schema_counts": {"legacy-decimal-v1": 1},
            "native_decimal_v2_count": 0,
            "legacy_decimal_v1_count": 1,
            "legacy_nonnull_value_count": 1,
        },
        new_evidence_and_governance_table_rows={f"synthetic_table_{i}": 0 for i in range(10)},
    )
    old_boot_summary = copy.deepcopy(legacy)
    migrated["data_center_catalog"] = {
        "database_name": "data02_compat_migrated",
        "tables": {
            table: {
                "legacy_fields": row["fields"],
                "current_fields": [*row["fields"], "added_field"],
                "primary_key_order": row["order"],
                "legacy_projection": copy.deepcopy(row),
            }
            for table, row in legacy["data_center_catalog"]["tables"].items()
        },
    }
    old_boot_summary["database_identity"] = {"database_name": "data02_compat_migrated"}
    artifacts = {
        "legacy_summary": legacy,
        "migrated_summary": migrated,
        "guard_0115": {
            "migration": "0115_calendar_history_catalog_immutability",
            "database_identity": {"database_name": "data02_compat_migrated"},
            "synthetic_rows_rolled_back": True,
            "persistent_rows_created": False,
            "legal_active_transition": "active true->false accepted",
        },
        "pending_migrations": {
            "schema": verifier._SUMMARY_SCHEMA,
            "database_identity": {"database_name": "data02_compat_migrated"},
            "leaf_migration_count": 1,
            "leaf_migrations": ["data_center.0118_example"],
            "applied_leaf_migrations": ["data_center.0118_example"],
            "pending_migration_count": 0,
            "pending_migrations": [],
        },
        "legacy_readonly_boot": {
            "schema": "ops.data02-legacy-native-old-boot.v1",
            "source_commit": verifier.LEGACY_SOURCE_COMMIT,
            "image_id": verifier.LEGACY_IMAGE_ID,
            "runtime_source_origin": "immutable_image_without_candidate_mount",
            "database_read_only": True,
            "provider_http_attempt_count": 0,
            "old_orm_schema_check": {"managed_models_checked": 1, "missing_tables_or_columns": []},
            "summary": old_boot_summary,
        },
    }
    model_tables = {
        name: f"data_center_synthetic_{index}"
        for index, name in enumerate(sorted(verifier._EMPTY_MODEL_NAMES))
    }
    (candidate / "governance").mkdir()
    (candidate / "governance/data_dictionary.json").write_text(
        json.dumps(
            {
                "apps": {
                    "data_center": {
                        "models": [
                            {"class_name": name, "meta": {"db_table": table}}
                            for name, table in model_tables.items()
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    migrated["new_evidence_and_governance_table_rows"] = dict.fromkeys(model_tables.values(), 0)
    inventory = [
        {
            "model": "data_center.LegacySyntheticModel",
            "table": "data_center_legacy",
            "columns": ["id", "value"],
        }
    ]
    legacy["legacy_orm_inventory"] = inventory
    artifacts["legacy_readonly_boot"]["old_orm_schema_check"]["checked_inventory"] = inventory
    for name in ("legacy_summary", "migrated_summary", "guard_0115", "pending_migrations"):
        artifacts[name]["database_identity"]["system_identifier"] = "1234567890"
    old_boot_summary["database_identity"]["system_identifier"] = "1234567890"
    artifacts["pending_migrations"]["migration_source_trace"] = {
        "origin": "candidate_read_only_mount",
        "runtime_root": "/app",
        "migration_tree_sha256": verifier.migration_tree_digest(candidate),
        "app_mount_read_only": True,
        "loaded_app_migrations": [
            {
                "key": "data_center.0118_example",
                "relative_path": "apps/data_center/migrations/0118_example.py",
                "sha256": hashlib.sha256((migrations / "0118_example.py").read_bytes()).hexdigest(),
            }
        ],
    }
    artifacts["pending_migrations"]["migration_graph"] = {
        "nodes": ["data_center.0118_example"],
        "edges": [],
    }
    report: dict[str, object] = {
        "schema": verifier._REPORT_SCHEMA,
        "candidate_source_commit": "a" * 40,
        "migration_tree_sha256": verifier.migration_tree_digest(candidate),
        "baseline_sha256": "3" * 64,
        "legacy_source_commit": verifier.LEGACY_SOURCE_COMMIT,
        "legacy_image_id": verifier.LEGACY_IMAGE_ID,
        "migration_execution_image_id": verifier.LEGACY_IMAGE_ID,
        "backup": {"sha256": "4" * 64, "size_bytes": 284481443},
        "isolation": {
            "postgres_container_id": "5" * 64,
            "network_id": "6" * 64,
            "network_internal": True,
            "legacy_database": "data02_compat_untouched",
            "migrated_database": "data02_compat_migrated",
            "postgres_system_identifier": "1234567890",
        },
        "artifacts": {},
        "production_qualification": False,
    }
    return tmp_path / "proof.json", candidate, report, artifacts


def _write(
    report_path: Path, report: dict[str, object], artifacts: dict[str, dict[str, object]]
) -> str:
    refs = {}
    for name, payload in artifacts.items():
        path = report_path.parent / f"{name}.json"
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        refs[name] = {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    report["artifacts"] = refs
    raw = json.dumps(report, sort_keys=True).encode()
    report_path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_complete_synthetic_proof_round_trip(tmp_path: Path) -> None:
    path, candidate, report, artifacts = _proof(tmp_path)
    digest = _write(path, report, artifacts)
    verifier.verify_compatibility(
        path, sha256=digest, candidate_root=candidate, baseline_sha256="3" * 64
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("old_boot_on_original_database", "OBSERVED_NATIVE_OLD_IMAGE_READ_UNVERIFIED"),
        ("native_row_present", "OBSERVED_NATIVE_NUMERIC_STATE_INVALID"),
        ("new_governance_row", "OBSERVED_NATIVE_NEW_BUSINESS_ROWS_PRESENT"),
        ("legacy_row_changed", "OBSERVED_NATIVE_ORIGINAL_ROWS_CHANGED"),
        ("migration_pending", "OBSERVED_NATIVE_PENDING_MIGRATIONS"),
        ("third_execution_image", "OBSERVED_NATIVE_EXECUTION_IMAGE_INVALID"),
        ("nonfinancial_table_changed", "OBSERVED_NATIVE_DATABASE_CATALOG_CHANGED"),
        ("old_orm_fields_unverified", "OBSERVED_NATIVE_OLD_ORM_SCHEMA_UNVERIFIED"),
        ("fake_zero_table", "OBSERVED_NATIVE_NEW_BUSINESS_ROWS_PRESENT"),
        ("another_cluster", "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH"),
        ("missing_loaded_modules", "OBSERVED_NATIVE_MIGRATION_MODULES_INCOMPLETE"),
        ("leaf_subset", "OBSERVED_NATIVE_MIGRATION_LEAF_INVENTORY_INCOMPLETE"),
        ("old_orm_subset", "OBSERVED_NATIVE_OLD_ORM_SCHEMA_UNVERIFIED"),
        ("member_pairs_subset", "OBSERVED_NATIVE_PUBLICATION_MEMBERS_INCOMPLETE"),
    ],
)
def test_rehashed_but_semantically_invalid_evidence_still_blocks(
    tmp_path: Path, mutation: str, code: str
) -> None:
    path, candidate, report, artifacts = _proof(tmp_path)
    if mutation == "old_boot_on_original_database":
        artifacts["legacy_readonly_boot"]["summary"]["database_identity"][
            "database_name"
        ] = "data02_compat_untouched"
    elif mutation == "native_row_present":
        artifacts["migrated_summary"]["numeric_state"]["native_decimal_v2_count"] = 1
    elif mutation == "new_governance_row":
        artifacts["migrated_summary"]["new_evidence_and_governance_table_rows"][
            "data_center_synthetic_0"
        ] = 1
    elif mutation == "legacy_row_changed":
        artifacts["migrated_summary"]["row_evidence"]["financial_facts"]["rows_sha256"] = "f" * 64
    elif mutation == "migration_pending":
        artifacts["pending_migrations"]["pending_migration_count"] = 1
    elif mutation == "third_execution_image":
        report["migration_execution_image_id"] = "sha256:" + "f" * 64
    elif mutation == "nonfinancial_table_changed":
        artifacts["migrated_summary"]["data_center_catalog"]["tables"][
            "data_center_canonical_publication"
        ]["legacy_projection"]["sha256"] = ("f" * 64)
    elif mutation == "old_orm_fields_unverified":
        artifacts["legacy_readonly_boot"]["old_orm_schema_check"]["managed_models_checked"] = 0
    elif mutation == "fake_zero_table":
        zeros = artifacts["migrated_summary"]["new_evidence_and_governance_table_rows"]
        zeros.pop(next(iter(zeros)))
        zeros["data_center_unrelated_zero"] = 0
    elif mutation == "another_cluster":
        artifacts["migrated_summary"]["database_identity"]["system_identifier"] = "9876543210"
    elif mutation == "missing_loaded_modules":
        artifacts["pending_migrations"]["migration_source_trace"]["loaded_app_migrations"] = []
    elif mutation == "leaf_subset":
        artifacts["pending_migrations"]["migration_graph"]["nodes"] = [
            "auth.0001_synthetic",
            "data_center.0118_example",
        ]
    elif mutation == "old_orm_subset":
        artifacts["legacy_summary"]["legacy_orm_inventory"].append(
            {"model": "task_monitor.OtherModel", "table": "task_monitor_other", "columns": ["id"]}
        )
    elif mutation == "member_pairs_subset":
        for name in ("legacy_summary", "migrated_summary"):
            artifacts[name]["member_fact_hash_pairs"]["row_count"] = 0
        artifacts["legacy_readonly_boot"]["summary"]["member_fact_hash_pairs"]["row_count"] = 0
    digest = _write(path, report, artifacts)
    with pytest.raises(verifier.LegacyBaselineBlocked, match=code):
        verifier.verify_compatibility(
            path, sha256=digest, candidate_root=candidate, baseline_sha256="3" * 64
        )


def test_unbound_original_or_changed_candidate_migration_cannot_reuse_proof(tmp_path: Path) -> None:
    path, candidate, report, artifacts = _proof(tmp_path)
    digest = _write(path, report, artifacts)
    (path.parent / "guard_0115.json").write_bytes(b"{}")
    with pytest.raises(
        verifier.LegacyBaselineBlocked, match="OBSERVED_NATIVE_PROOF_DIGEST_MISMATCH"
    ):
        verifier.verify_compatibility(
            path, sha256=digest, candidate_root=candidate, baseline_sha256="3" * 64
        )
    digest = _write(path, report, artifacts)
    (candidate / "apps/data_center/migrations/0118_example.py").write_text(
        "# changed\n", encoding="utf-8"
    )
    with pytest.raises(
        verifier.LegacyBaselineBlocked, match="OBSERVED_NATIVE_MIGRATION_TREE_MISMATCH"
    ):
        verifier.verify_compatibility(
            path, sha256=digest, candidate_root=candidate, baseline_sha256="3" * 64
        )
