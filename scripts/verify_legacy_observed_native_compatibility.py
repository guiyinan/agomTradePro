#!/usr/bin/env python3
"""Verify real isolated legacy-migration originals before the bounded cutover."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import capture_legacy_observed_runtime as observer  # noqa: E402
from scripts.legacy_observed_runtime_baseline import (  # noqa: E402
    LEGACY_IMAGE_ID,
    LEGACY_SOURCE_COMMIT,
    LegacyBaselineBlocked,
)

_REPORT_SCHEMA = "ops.data02-legacy-native-compatibility.v1"
_SUMMARY_SCHEMA = "ops.data02-legacy-native-compat.proof.v1"
_ARTIFACTS = frozenset(
    {
        "legacy_summary",
        "migrated_summary",
        "guard_0115",
        "pending_migrations",
        "legacy_readonly_boot",
    }
)
_ROW_SCOPES = frozenset(
    {
        "financial_facts",
        "financial_publications",
        "financial_publication_members",
        "financial_publication_pointers",
        "financial_publication_coverages",
    }
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys rather than silently substituting proof facts."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LegacyBaselineBlocked("OBSERVED_NATIVE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(value: str) -> object:
    """Reject JSON NaN and infinities at the original-byte boundary."""
    raise LegacyBaselineBlocked("OBSERVED_NATIVE_JSON_CONSTANT_INVALID")


def _load(path: Path, *, sha256: str | None = None) -> dict[str, object]:
    """Read bounded regular proof bytes and verify their caller-pinned digest."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
        raise LegacyBaselineBlocked("OBSERVED_NATIVE_PROOF_FILE_INVALID")
    raw = path.read_bytes()
    if sha256 is not None and (
        re.fullmatch(r"[0-9a-f]{64}", sha256) is None or hashlib.sha256(raw).hexdigest() != sha256
    ):
        raise LegacyBaselineBlocked("OBSERVED_NATIVE_PROOF_DIGEST_MISMATCH")
    return observer._object(json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant))


def migration_tree_digest(root: Path) -> str:
    """Hash all candidate app migration bytes in exact relative POSIX order."""
    paths = sorted(
        (
            path
            for path in (root / "apps").glob("*/migrations/**/*.py")
            if "__pycache__" not in path.parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise LegacyBaselineBlocked("OBSERVED_NATIVE_MIGRATION_TREE_EMPTY")
    digest = hashlib.sha256()
    for path in paths:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise LegacyBaselineBlocked("OBSERVED_NATIVE_MIGRATION_FILE_INVALID")
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _require(condition: bool, code: str) -> None:
    """Stop at one stable, non-sensitive evidence mismatch."""
    if not condition:
        raise LegacyBaselineBlocked(code)


def _rows(summary: dict[str, object]) -> dict[str, object]:
    """Require the complete five-scope original-row evidence, including empty scopes."""
    evidence = observer._object(summary.get("row_evidence"))
    field_sets = observer._object(summary.get("field_sets"))
    _require(
        set(evidence) == set(field_sets) == _ROW_SCOPES, "OBSERVED_NATIVE_ROW_SCOPES_INCOMPLETE"
    )
    for name, value in evidence.items():
        row = observer._object(value)
        fields = observer._array(row.get("fields"))
        _require(
            set(row) == {"row_count", "fields", "rows_sha256"},
            "OBSERVED_NATIVE_ROW_EVIDENCE_INVALID",
        )
        observer._integer(row.get("row_count"))
        _require(
            bool(fields)
            and fields == field_sets[name]
            and all(type(item) is str for item in fields),
            "OBSERVED_NATIVE_ROW_FIELDS_INVALID",
        )
        _require(
            re.fullmatch(r"[0-9a-f]{64}", observer._string(row.get("rows_sha256"))) is not None,
            "OBSERVED_NATIVE_ROW_DIGEST_INVALID",
        )
    return evidence


def _catalog_preserved(legacy: dict[str, object], migrated: dict[str, object]) -> None:
    """Compare every original data-center table and reject nonempty new tables."""
    before = observer._object(observer._object(legacy.get("data_center_catalog")).get("tables"))
    after = observer._object(observer._object(migrated.get("data_center_catalog")).get("tables"))
    _require(
        {"data_center_financial_fact", "data_center_canonical_publication"}.issubset(before)
        and set(before).issubset(after),
        "OBSERVED_NATIVE_DATABASE_CATALOG_INCOMPLETE",
    )
    for name, value in before.items():
        old = observer._object(value)
        current = observer._object(after[name])
        fields = observer._array(old.get("fields"))
        _require(
            set(old) == {"fields", "order", "rows", "sha256"}
            and bool(fields)
            and current.get("legacy_projection") == old
            and current.get("legacy_fields") == fields
            and current.get("primary_key_order") == old.get("order")
            and {observer._string(item) for item in fields}.issubset(
                observer._string(item) for item in observer._array(current.get("current_fields"))
            ),
            "OBSERVED_NATIVE_DATABASE_CATALOG_CHANGED",
        )
        observer._integer(old.get("rows"))
        _require(
            re.fullmatch(r"[0-9a-f]{64}", observer._string(old.get("sha256"))) is not None,
            "OBSERVED_NATIVE_DATABASE_CATALOG_INVALID",
        )
    for name in set(after) - set(before):
        row = observer._object(after[name])
        _require(
            type(row.get("rows")) is int and row["rows"] == 0,
            "OBSERVED_NATIVE_NEW_BUSINESS_ROWS_PRESENT",
        )


_EMPTY_MODEL_NAMES = frozenset(
    {
        "StatutorySourceDocumentRevisionModel",
        "StatutorySourceDocumentCaptureModel",
        "StatutorySourceDocumentBundleModel",
        "StatutorySourceDocumentBundleMemberModel",
        "InstitutionalCalendarEventModel",
        "FinancialNumericSourceDocumentCaptureModel",
        "FinancialMetricSourceCatalogEntryModel",
        "FinancialMetricSourceCatalogOwnerEventModel",
        "FinancialAvailabilityGovernanceRecordModel",
        "FinancialAvailabilityOwnerEventModel",
    }
)


def _empty_tables(candidate_root: Path) -> set[str]:
    """Resolve selected empty models from the candidate's generated ORM projection."""
    dictionary = _load(candidate_root / "governance/data_dictionary.json")
    app = observer._object(observer._object(dictionary.get("apps")).get("data_center"))
    selected: dict[str, str] = {}
    for value in observer._array(app.get("models")):
        model = observer._object(value)
        name = observer._string(model.get("class_name"))
        if name in _EMPTY_MODEL_NAMES:
            _require(name not in selected, "OBSERVED_NATIVE_MODEL_PROJECTION_DUPLICATE")
            selected[name] = observer._string(observer._object(model.get("meta")).get("db_table"))
    _require(set(selected) == _EMPTY_MODEL_NAMES, "OBSERVED_NATIVE_MODEL_PROJECTION_INCOMPLETE")
    return set(selected.values())


def _orm_inventory(value: object) -> list[object]:
    """Require a nonduplicate canonical model/table/column inventory."""
    inventory = observer._array(value)
    names: list[str] = []
    for raw in inventory:
        row = observer._object(raw)
        _require(set(row) == {"model", "table", "columns"}, "OBSERVED_NATIVE_ORM_INVENTORY_INVALID")
        names.append(observer._string(row.get("model")))
        observer._string(row.get("table"))
        columns = observer._array(row.get("columns"))
        _require(
            bool(columns)
            and all(type(column) is str and column for column in columns)
            and len(columns) == len({observer._string(column) for column in columns}),
            "OBSERVED_NATIVE_ORM_INVENTORY_INVALID",
        )
    _require(
        bool(inventory) and names == sorted(set(names)), "OBSERVED_NATIVE_ORM_INVENTORY_INCOMPLETE"
    )
    return inventory


def _source_graph_verified(pending: dict[str, object], candidate_root: Path) -> None:
    """Bind loaded migration modules and graph leaves to actual candidate bytes."""
    trace = observer._object(pending.get("migration_source_trace"))
    _require(
        trace.get("origin") == "candidate_read_only_mount"
        and trace.get("runtime_root") == "/app"
        and trace.get("app_mount_read_only") is True
        and trace.get("migration_tree_sha256") == migration_tree_digest(candidate_root),
        "OBSERVED_NATIVE_MIGRATION_RUNTIME_SOURCE_UNVERIFIED",
    )
    expected: dict[str, tuple[str, str]] = {}
    replaced: set[str] = set()
    for path in (candidate_root / "apps").glob("*/migrations/*.py"):
        if re.fullmatch(r"[0-9]{4}_.+", path.stem) is None:
            continue
        relative = path.relative_to(candidate_root).as_posix()
        key = f"{path.parent.parent.name}.{path.stem}"
        expected[relative] = (key, hashlib.sha256(path.read_bytes()).hexdigest())
        module = ast.parse(path.read_bytes(), filename=relative)
        classes = (
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "Migration"
        )
        for migration_class in classes:
            for node in migration_class.body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "replaces"
                    for target in node.targets
                ):
                    pairs: object = ast.literal_eval(node.value)
                    for pair in observer._array(pairs):
                        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                            raise LegacyBaselineBlocked(
                                "OBSERVED_NATIVE_MIGRATION_REPLACEMENT_INVALID"
                            )
                        replaced.add(f"{observer._string(pair[0])}.{observer._string(pair[1])}")
    loaded: dict[str, tuple[str, str]] = {}
    loaded_keys: set[str] = set()
    for raw in observer._array(trace.get("loaded_app_migrations")):
        row = observer._object(raw)
        _require(
            set(row) == {"key", "relative_path", "sha256"},
            "OBSERVED_NATIVE_MIGRATION_MODULE_INVALID",
        )
        relative = observer._string(row.get("relative_path"))
        key = observer._string(row.get("key"))
        digest = observer._string(row.get("sha256"))
        _require(
            key not in loaded_keys and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "OBSERVED_NATIVE_MIGRATION_MODULE_INVALID",
        )
        loaded_keys.add(key)
        if relative.startswith(("@python/", "@root/")):
            continue
        _require(relative not in loaded, "OBSERVED_NATIVE_MIGRATION_MODULE_DUPLICATE")
        loaded[relative] = (key, digest)
    _require(bool(expected) and loaded == expected, "OBSERVED_NATIVE_MIGRATION_MODULES_INCOMPLETE")
    graph = observer._object(pending.get("migration_graph"))
    nodes = [observer._string(node) for node in observer._array(graph.get("nodes"))]
    _require(bool(nodes) and nodes == sorted(set(nodes)), "OBSERVED_NATIVE_MIGRATION_GRAPH_INVALID")
    parents: set[str] = set()
    for raw in observer._array(graph.get("edges")):
        edge = observer._array(raw)
        _require(len(edge) == 2, "OBSERVED_NATIVE_MIGRATION_GRAPH_INVALID")
        child, parent = observer._string(edge[0]), observer._string(edge[1])
        _require(
            child != parent and child in nodes and parent in nodes,
            "OBSERVED_NATIVE_MIGRATION_GRAPH_INVALID",
        )
        parents.add(parent)
    _require(
        {key for key, _digest in expected.values()}.issubset(set(nodes) | replaced),
        "OBSERVED_NATIVE_MIGRATION_GRAPH_INCOMPLETE",
    )
    _require(
        pending.get("leaf_migrations") == sorted(set(nodes) - parents),
        "OBSERVED_NATIVE_MIGRATION_LEAF_INVENTORY_INCOMPLETE",
    )


def verify_compatibility(
    report_path: Path,
    *,
    sha256: str,
    candidate_root: Path,
    baseline_sha256: str,
) -> None:
    """Validate same-source isolated originals; grant only pre-native bootstrap safety."""
    report = _load(report_path, sha256=sha256)
    expected_keys = {
        "schema",
        "candidate_source_commit",
        "migration_tree_sha256",
        "baseline_sha256",
        "legacy_source_commit",
        "legacy_image_id",
        "migration_execution_image_id",
        "backup",
        "isolation",
        "artifacts",
        "production_qualification",
    }
    _require(
        set(report) == expected_keys and report.get("schema") == _REPORT_SCHEMA,
        "OBSERVED_NATIVE_REPORT_SCHEMA_INVALID",
    )
    _require(
        report.get("production_qualification") is False,
        "OBSERVED_NATIVE_REPORT_QUALIFICATION_INVALID",
    )
    manifest = _load(candidate_root / ".agom-release-manifest.json")
    _require(
        report.get("candidate_source_commit") == manifest.get("source_commit")
        and re.fullmatch(r"[0-9a-f]{40}", observer._string(report.get("candidate_source_commit")))
        is not None,
        "OBSERVED_NATIVE_CANDIDATE_MISMATCH",
    )
    _require(
        report.get("migration_tree_sha256") == migration_tree_digest(candidate_root),
        "OBSERVED_NATIVE_MIGRATION_TREE_MISMATCH",
    )
    _require(
        report.get("baseline_sha256") == baseline_sha256
        and re.fullmatch(r"[0-9a-f]{64}", baseline_sha256) is not None,
        "OBSERVED_NATIVE_BASELINE_MISMATCH",
    )
    _require(
        report.get("legacy_source_commit") == LEGACY_SOURCE_COMMIT
        and report.get("legacy_image_id") == LEGACY_IMAGE_ID,
        "OBSERVED_NATIVE_LEGACY_IMAGE_MISMATCH",
    )
    _require(
        report.get("migration_execution_image_id") in {LEGACY_IMAGE_ID, manifest.get("image_id")},
        "OBSERVED_NATIVE_EXECUTION_IMAGE_INVALID",
    )
    backup = observer._object(report.get("backup"))
    _require(
        set(backup) == {"sha256", "size_bytes"}
        and observer._integer(backup.get("size_bytes")) > 0
        and re.fullmatch(r"[0-9a-f]{64}", observer._string(backup.get("sha256"))) is not None,
        "OBSERVED_NATIVE_BACKUP_INVALID",
    )
    isolation = observer._object(report.get("isolation"))
    _require(
        set(isolation)
        == {
            "postgres_container_id",
            "network_id",
            "network_internal",
            "legacy_database",
            "migrated_database",
            "postgres_system_identifier",
        },
        "OBSERVED_NATIVE_ISOLATION_INVALID",
    )
    _require(isolation.get("network_internal") is True, "OBSERVED_NATIVE_NETWORK_NOT_INTERNAL")
    for key in ("postgres_container_id", "network_id"):
        _require(
            re.fullmatch(r"[0-9a-f]{64}", observer._string(isolation.get(key))) is not None,
            "OBSERVED_NATIVE_ISOLATION_INVALID",
        )
    legacy_db = observer._string(isolation.get("legacy_database"))
    migrated_db = observer._string(isolation.get("migrated_database"))
    system_id = observer._string(isolation.get("postgres_system_identifier"))
    _require(
        re.fullmatch(r"[0-9]{1,20}", system_id) is not None and int(system_id) > 0,
        "OBSERVED_NATIVE_CLUSTER_IDENTITY_INVALID",
    )
    _require(
        legacy_db == "data02_compat_untouched" and migrated_db == "data02_compat_migrated",
        "OBSERVED_NATIVE_DATABASE_ISOLATION_INVALID",
    )
    artifact_refs = observer._object(report.get("artifacts"))
    _require(set(artifact_refs) == _ARTIFACTS, "OBSERVED_NATIVE_ARTIFACTS_INCOMPLETE")
    originals: dict[str, dict[str, object]] = {}
    for name, value in artifact_refs.items():
        ref = observer._object(value)
        relative = Path(observer._string(ref.get("path")))
        _require(
            set(ref) == {"path", "sha256"}
            and len(relative.parts) == 1
            and relative.name not in {".", ".."}
            and not relative.is_absolute()
            and "/" not in str(relative)
            and "\\" not in str(relative),
            "OBSERVED_NATIVE_ARTIFACT_PATH_INVALID",
        )
        originals[name] = _load(
            report_path.parent / relative, sha256=observer._string(ref.get("sha256"))
        )
    legacy = originals["legacy_summary"]
    migrated = originals["migrated_summary"]
    for summary, side, database in (
        (legacy, "legacy", legacy_db),
        (migrated, "migrated", migrated_db),
    ):
        _require(
            summary.get("schema") == _SUMMARY_SCHEMA
            and summary.get("side") == side
            and observer._object(summary.get("database_identity")).get("database_name") == database,
            "OBSERVED_NATIVE_SUMMARY_IDENTITY_MISMATCH",
        )
        _require(
            observer._object(summary.get("database_identity")).get("system_identifier")
            == system_id,
            "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH",
        )
    legacy_rows = _rows(legacy)
    _require(
        legacy_rows == _rows(migrated) and legacy.get("field_sets") == migrated.get("field_sets"),
        "OBSERVED_NATIVE_ORIGINAL_ROWS_CHANGED",
    )
    _catalog_preserved(legacy, migrated)
    _require(
        legacy.get("native_numeric_columns_present") is False
        and migrated.get("native_numeric_columns_present") is True,
        "OBSERVED_NATIVE_SCHEMA_NOT_EXERCISED",
    )
    pairs = observer._object(legacy.get("member_fact_hash_pairs"))
    _require(
        set(pairs) == {"row_count", "pairs_sha256"}
        and pairs == migrated.get("member_fact_hash_pairs")
        and re.fullmatch(r"[0-9a-f]{64}", observer._string(pairs.get("pairs_sha256"))) is not None,
        "OBSERVED_NATIVE_PUBLICATION_MEMBERS_CHANGED",
    )
    observer._integer(pairs.get("row_count"))
    _require(
        pairs.get("row_count")
        == observer._object(legacy_rows["financial_publication_members"]).get("row_count"),
        "OBSERVED_NATIVE_PUBLICATION_MEMBERS_INCOMPLETE",
    )
    numeric = observer._object(migrated.get("numeric_state"))
    facts_count = observer._integer(
        observer._object(legacy_rows["financial_facts"]).get("row_count")
    )
    _require(
        set(numeric)
        == {
            "schema_counts",
            "native_decimal_v2_count",
            "legacy_decimal_v1_count",
            "legacy_nonnull_value_count",
        }
        and type(numeric.get("native_decimal_v2_count")) is int
        and numeric["native_decimal_v2_count"] == 0
        and type(numeric.get("legacy_decimal_v1_count")) is int
        and numeric["legacy_decimal_v1_count"] == facts_count
        and type(numeric.get("legacy_nonnull_value_count")) is int
        and numeric["legacy_nonnull_value_count"] == facts_count
        and numeric.get("schema_counts")
        == ({"legacy-decimal-v1": facts_count} if facts_count else {}),
        "OBSERVED_NATIVE_NUMERIC_STATE_INVALID",
    )
    zeros = observer._object(migrated.get("new_evidence_and_governance_table_rows"))
    _require(
        set(zeros) == _empty_tables(candidate_root)
        and all(type(count) is int and count == 0 for count in zeros.values()),
        "OBSERVED_NATIVE_NEW_BUSINESS_ROWS_PRESENT",
    )
    guard = originals["guard_0115"]
    _require(
        observer._object(guard.get("database_identity")).get("system_identifier") == system_id,
        "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH",
    )
    _require(
        guard.get("migration") == "0115_calendar_history_catalog_immutability"
        and observer._object(guard.get("database_identity")).get("database_name") == migrated_db
        and guard.get("synthetic_rows_rolled_back") is True
        and guard.get("persistent_rows_created") is False
        and guard.get("legal_active_transition") == "active true->false accepted",
        "OBSERVED_NATIVE_CALENDAR_GUARD_UNVERIFIED",
    )
    pending = originals["pending_migrations"]
    _require(
        observer._object(pending.get("database_identity")).get("system_identifier") == system_id,
        "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH",
    )
    _source_graph_verified(pending, candidate_root)
    leaves = observer._array(pending.get("leaf_migrations"))
    data_center_leaves = sorted(
        path.stem
        for path in (candidate_root / "apps/data_center/migrations").glob("*.py")
        if re.fullmatch(r"[0-9]{4}_.+", path.stem)
    )
    _require(
        pending.get("schema") == _SUMMARY_SCHEMA
        and observer._object(pending.get("database_identity")).get("database_name") == migrated_db
        and bool(leaves)
        and bool(data_center_leaves)
        and f"data_center.{data_center_leaves[-1]}" in leaves
        and type(pending.get("leaf_migration_count")) is int
        and pending.get("leaf_migration_count") == len(leaves)
        and pending.get("applied_leaf_migrations") == leaves
        and type(pending.get("pending_migration_count")) is int
        and pending["pending_migration_count"] == 0
        and pending.get("pending_migrations") == [],
        "OBSERVED_NATIVE_PENDING_MIGRATIONS",
    )
    boot = originals["legacy_readonly_boot"]
    old_summary = observer._object(boot.get("summary"))
    schema_check = observer._object(boot.get("old_orm_schema_check"))
    inventory = _orm_inventory(legacy.get("legacy_orm_inventory"))
    _require(
        observer._object(old_summary.get("database_identity")).get("system_identifier")
        == system_id,
        "OBSERVED_NATIVE_CLUSTER_IDENTITY_MISMATCH",
    )
    _require(
        boot.get("schema") == "ops.data02-legacy-native-old-boot.v1"
        and boot.get("source_commit") == LEGACY_SOURCE_COMMIT
        and boot.get("image_id") == LEGACY_IMAGE_ID
        and boot.get("runtime_source_origin") == "immutable_image_without_candidate_mount"
        and boot.get("database_read_only") is True
        and type(boot.get("provider_http_attempt_count")) is int
        and boot["provider_http_attempt_count"] == 0
        and observer._object(old_summary.get("database_identity")).get("database_name")
        == migrated_db
        and old_summary.get("native_numeric_columns_present") is False
        and _rows(old_summary) == legacy_rows
        and old_summary.get("member_fact_hash_pairs") == pairs,
        "OBSERVED_NATIVE_OLD_IMAGE_READ_UNVERIFIED",
    )
    _require(
        type(schema_check.get("managed_models_checked")) is int
        and schema_check["managed_models_checked"] == len(inventory)
        and schema_check.get("checked_inventory") == inventory
        and schema_check.get("missing_tables_or_columns") == [],
        "OBSERVED_NATIVE_OLD_ORM_SCHEMA_UNVERIFIED",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Check pinned isolated originals without touching Docker, HTTP or any database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify",))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        verify_compatibility(
            args.report,
            sha256=args.sha256,
            candidate_root=args.candidate_root,
            baseline_sha256=args.baseline_sha256,
        )
        print("OBSERVED_NATIVE_COMPATIBILITY_VERIFIED")
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("OBSERVED_NATIVE_COMPATIBILITY_BLOCKED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
