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


@pytest.mark.parametrize("mutation", ["none", "missing", "changed", "wrong_key"])
def test_candidate_shared_migrations_require_complete_exact_source_trace(
    tmp_path: Path, mutation: str
) -> None:
    _, candidate, _, artifacts = _proof(tmp_path)
    migration = candidate / "shared/migrations/0001_history.py"
    migration.parent.mkdir(parents=True)
    migration.write_text("# historical shared migration\n", encoding="utf-8")
    pending = artifacts["pending_migrations"]
    pending["migration_graph"]["nodes"].append("shared.0001_history")
    pending["migration_graph"]["nodes"].sort()
    pending["leaf_migrations"].append("shared.0001_history")
    pending["leaf_migrations"].sort()
    if mutation != "missing":
        pending["migration_source_trace"]["loaded_app_migrations"].append(
            {
                "key": "other.0001_history" if mutation == "wrong_key" else "shared.0001_history",
                "relative_path": "shared/migrations/0001_history.py",
                "sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
            }
        )
    if mutation == "changed":
        migration.write_text("# changed historical migration\n", encoding="utf-8")
    if mutation == "none":
        verifier._source_graph_verified(pending, candidate)
    else:
        with pytest.raises(ValueError, match="OBSERVED_NATIVE_MIGRATION_MODULES_INCOMPLETE"):
            verifier._source_graph_verified(pending, candidate)


@pytest.mark.parametrize("omit_referenced_app_leaf", [False, True])
def test_migration_leaves_follow_django_per_app_dependency_semantics(
    tmp_path: Path, omit_referenced_app_leaf: bool
) -> None:
    _, candidate, _, artifacts = _proof(tmp_path)
    migration = candidate / "apps/account/migrations/0001_history.py"
    migration.parent.mkdir(parents=True)
    migration.write_text("# synthetic cross-app dependency\n", encoding="utf-8")
    pending = artifacts["pending_migrations"]
    trace = pending["migration_source_trace"]
    trace["migration_tree_sha256"] = verifier.migration_tree_digest(candidate)
    trace["loaded_app_migrations"].append(
        {
            "key": "account.0001_history",
            "relative_path": "apps/account/migrations/0001_history.py",
            "sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
        }
    )
    pending["migration_graph"] = {
        "nodes": ["account.0001_history", "data_center.0118_example"],
        "edges": [["account.0001_history", "data_center.0118_example"]],
    }
    pending["leaf_migrations"] = ["account.0001_history", "data_center.0118_example"]
    if omit_referenced_app_leaf:
        pending["leaf_migrations"].remove("data_center.0118_example")
        with pytest.raises(ValueError, match="OBSERVED_NATIVE_MIGRATION_LEAF_INVENTORY_INCOMPLETE"):
            verifier._source_graph_verified(pending, candidate)
    else:
        verifier._source_graph_verified(pending, candidate)


def _phased_proof(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, dict[str, object]]]:
    path, candidate, report, artifacts = _proof(tmp_path)
    folder = candidate / "apps/ai_provider/migrations"
    folder.mkdir(parents=True)
    for name in (
        "0004_aiuserfallbackquota_aiproviderconfig_owner_user_and_more",
        "0005_drop_plaintext_api_key",
    ):
        (folder / f"{name}.py").write_text("class Migration:\n    pass\n", encoding="utf-8")
    deferred = "ai_provider.0005_drop_plaintext_api_key"
    predecessor = "ai_provider.0004_aiuserfallbackquota_aiproviderconfig_owner_user_and_more"
    tree_hash = verifier.migration_tree_digest(candidate)
    pending = artifacts["pending_migrations"]
    pending["migration_source_trace"]["migration_tree_sha256"] = tree_hash
    for module in sorted(folder.glob("*.py")):
        pending["migration_source_trace"]["loaded_app_migrations"].append(
            {
                "key": f"ai_provider.{module.stem}",
                "relative_path": module.relative_to(candidate).as_posix(),
                "sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
            }
        )
    leaves = sorted([deferred, "data_center.0118_example"])
    pending.update(leaf_migration_count=2, leaf_migrations=leaves, applied_leaf_migrations=leaves)
    pending["migration_graph"] = {
        "nodes": sorted([predecessor, *leaves]),
        "edges": [[deferred, predecessor]],
    }
    phase_a_state = copy.deepcopy(pending)
    phase_a_state.update(
        pending_migration_count=1,
        pending_migrations=[deferred],
        applied_leaf_migrations=["data_center.0118_example"],
    )
    phase_a = copy.deepcopy(artifacts["migrated_summary"])
    old_inventory = artifacts["legacy_summary"]["legacy_orm_inventory"]
    old_inventory.insert(
        0,
        {
            "model": "ai_provider.AIProviderConfig",
            "table": "ai_provider_config",
            "columns": ["id", "api_key", "api_key_encrypted"],
        },
    )
    boot = artifacts["legacy_readonly_boot"]
    boot["old_orm_schema_check"]["managed_models_checked"] = len(old_inventory)
    current_inventory = copy.deepcopy(old_inventory)
    current_inventory[0]["columns"].remove("api_key")
    phase_a["runtime_orm_inventory"] = current_inventory
    for summary, present in ((phase_a, True), (artifacts["migrated_summary"], False)):
        summary["retired_legacy_column"] = {
            "table": "ai_provider_config",
            "column": "api_key",
            "present": present,
            "encrypted_column": "api_key_encrypted",
            "encrypted_column_present": True,
            "nonempty_plaintext_rows": 0 if present else None,
            "row_count": 1,
            "encrypted_values_sha256": "e" * 64,
        }
        summary["database_identity"].update(
            default_transaction_read_only="on", transaction_read_only="on"
        )
    artifacts["migrated_summary"]["current_orm_schema_check"] = {
        "managed_models_checked": len(current_inventory),
        "checked_inventory": current_inventory,
        "missing_tables_or_columns": [],
    }
    boot.update(
        compatibility_phase="phase_a",
        phase_a_migrations_sha256=hashlib.sha256(
            json.dumps(phase_a_state, sort_keys=True).encode()
        ).hexdigest(),
    )
    artifacts.update(phase_a_migrations=phase_a_state, phase_a_summary=phase_a)
    report.update(
        schema="ops.data02-legacy-native-compatibility.v2",
        migration_tree_sha256=tree_hash,
        bootstrap_migration_plan={
            "schema": "ops.observed-bootstrap-migration-plan.v1",
            "deferred_migration": deferred,
            "deferred_migration_sha256": hashlib.sha256(
                (folder / "0005_drop_plaintext_api_key.py").read_bytes()
            ).hexdigest(),
            "phase_a_post_migrate_signals_deferred": True,
            "retire_baseline_before_phase_b": True,
        },
    )
    return path, candidate, report, artifacts


def test_phased_bootstrap_proof_preserves_old_schema_before_retirement(tmp_path: Path) -> None:
    path, candidate, report, artifacts = _phased_proof(tmp_path)
    digest = _write(path, report, artifacts)
    verifier.verify_compatibility(
        path, sha256=digest, candidate_root=candidate, baseline_sha256="3" * 64
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unretired_baseline", "OBSERVED_NATIVE_PHASE_PLAN_INVALID"),
        ("wrong_deferred_source", "OBSERVED_NATIVE_PHASE_PLAN_INVALID"),
        ("extra_phase_a_pending", "OBSERVED_NATIVE_PHASE_A_PENDING_INVALID"),
        ("old_boot_after_retirement", "OBSERVED_NATIVE_PHASE_A_OLD_BOOT_UNVERIFIED"),
        ("phase_b_old_column_remains", "OBSERVED_NATIVE_RETIREMENT_SCHEMA_UNVERIFIED"),
        ("encrypted_values_changed", "OBSERVED_NATIVE_RETIREMENT_SCHEMA_UNVERIFIED"),
        ("phase_b_current_schema_missing", "OBSERVED_NATIVE_CURRENT_ORM_SCHEMA_UNVERIFIED"),
        ("phase_a_rows_changed", "OBSERVED_NATIVE_PHASE_A_ROWS_CHANGED"),
        ("phase_a_other_cluster", "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH"),
    ],
)
def test_phased_bootstrap_rejects_incomplete_or_misbound_phases(
    tmp_path: Path, mutation: str, code: str
) -> None:
    path, candidate, report, artifacts = _phased_proof(tmp_path)
    if mutation == "unretired_baseline":
        report["bootstrap_migration_plan"]["retire_baseline_before_phase_b"] = False
    elif mutation == "wrong_deferred_source":
        report["bootstrap_migration_plan"]["deferred_migration_sha256"] = "0" * 64
    elif mutation == "extra_phase_a_pending":
        artifacts["phase_a_migrations"]["pending_migrations"].append("other.0001")
        artifacts["phase_a_migrations"]["pending_migration_count"] = 2
    elif mutation == "old_boot_after_retirement":
        artifacts["legacy_readonly_boot"]["compatibility_phase"] = "phase_b"
    elif mutation == "phase_b_old_column_remains":
        artifacts["migrated_summary"]["retired_legacy_column"]["present"] = True
    elif mutation == "encrypted_values_changed":
        artifacts["migrated_summary"]["retired_legacy_column"]["encrypted_values_sha256"] = "0" * 64
    elif mutation == "phase_b_current_schema_missing":
        artifacts["migrated_summary"]["current_orm_schema_check"]["missing_tables_or_columns"] = [
            "missing"
        ]
    elif mutation == "phase_a_rows_changed":
        artifacts["phase_a_summary"]["row_evidence"]["financial_facts"]["row_count"] = 2
    elif mutation == "phase_a_other_cluster":
        artifacts["phase_a_migrations"]["database_identity"]["system_identifier"] = "999"
    digest = _write(path, report, artifacts)
    with pytest.raises(ValueError, match=code):
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
