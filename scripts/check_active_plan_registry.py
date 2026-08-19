#!/usr/bin/env python
"""Validate the active plan registry and prevent plan-index drift."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import cast

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "governance" / "active_plan_registry.json"
DEFAULT_INDEX = REPO_ROOT / "docs" / "plans" / "README.md"
ACTIVE_PLAN_ROOT = REPO_ROOT / "docs" / "plans"
ACTIVE_SUFFIXES = {".md", ".csv"}
ALLOWED_PRIORITIES = {"P0", "P0/P1", "P1", "P2"}
ALLOWED_STATUSES = {
    "active",
    "production_validation",
    "external_validation",
    "blocked_external",
}
ALLOWED_ROLES = {"primary", "supporting", "evidence", "matrix"}
ALLOWED_EXECUTION_MODES = {"repository", "production", "external", "governance"}
ALLOWED_UNIT_STATUSES = {
    "active",
    "completed",
    "planned",
    "waiting_dependency",
    "awaiting_production",
    "blocked_external",
}
UNCHECKED_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+\[ \]", re.MULTILINE)


@dataclass(frozen=True)
class Violation:
    """One stable plan-registry validation failure."""

    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RegistryReport:
    """Machine-readable summary of the active-plan registry."""

    version: str
    workstream_count: int
    primary_plan_count: int
    supporting_document_count: int
    review_queue_count: int
    closure_unit_count: int
    registered_path_count: int
    active_path_count: int
    violation_count: int
    violations: tuple[Violation, ...]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_normalized_active_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    pure = PurePosixPath(value)
    return (
        value == pure.as_posix()
        and pure.is_relative_to(PurePosixPath("docs/plans"))
        and ".." not in pure.parts
        and pure.suffix in ACTIVE_SUFFIXES
        and value != "docs/plans/README.md"
    )


def collect_active_plan_paths(repository_root: Path) -> set[str]:
    """Return every governed artifact physically present in ``docs/plans``."""

    plan_root = repository_root / "docs" / "plans"
    return {
        _relative(path, repository_root)
        for path in plan_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in ACTIVE_SUFFIXES
        and path != plan_root / "README.md"
    }


def _load_registry(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registry root must be a JSON object")
    return cast(dict[str, object], payload)


def _dependency_cycle(unit_dependencies: dict[str, tuple[str, ...]]) -> bool:
    """Return whether canonical closure-unit dependencies contain a cycle."""

    pending = {unit_id: set(dependencies) for unit_id, dependencies in unit_dependencies.items()}
    while pending:
        ready = {unit_id for unit_id, dependencies in pending.items() if not dependencies}
        if not ready:
            return True
        pending = {
            unit_id: dependencies - ready
            for unit_id, dependencies in pending.items()
            if unit_id not in ready
        }
    return False


def evaluate_registry(
    repository_root: Path,
    registry_path: Path,
    index_path: Path,
) -> RegistryReport:
    """Evaluate structure, coverage, ownership and human-index wiring."""

    violations: list[Violation] = []
    try:
        registry = _load_registry(registry_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        violation = Violation("registry_unreadable", str(registry_path), str(exc))
        return RegistryReport("unknown", 0, 0, 0, 0, 0, 0, 0, 1, (violation,))

    expected_root_keys = {
        "version",
        "updated_at",
        "workstreams",
        "review_queue",
        "closure_backlog",
    }
    if set(registry) != expected_root_keys:
        violations.append(
            Violation(
                "registry_root_keys",
                _relative(registry_path, repository_root),
                f"expected exact keys {sorted(expected_root_keys)}, got {sorted(registry)}",
            )
        )

    version = registry.get("version")
    if not isinstance(version, str) or not version:
        violations.append(
            Violation(
                "registry_version",
                _relative(registry_path, repository_root),
                "version must be a non-empty string",
            )
        )
        version = "unknown"

    updated_at_value = registry.get("updated_at")
    try:
        updated_at = date.fromisoformat(cast(str, updated_at_value))
    except (TypeError, ValueError):
        violations.append(
            Violation(
                "registry_updated_at",
                _relative(registry_path, repository_root),
                "updated_at must be an ISO date",
            )
        )
        updated_at = date.min

    workstreams_value = registry.get("workstreams")
    review_queue_value = registry.get("review_queue")
    workstreams = workstreams_value if isinstance(workstreams_value, list) else []
    review_queue = review_queue_value if isinstance(review_queue_value, list) else []
    if not isinstance(workstreams_value, list):
        violations.append(
            Violation("workstreams_type", "workstreams", "workstreams must be a list")
        )
    if not isinstance(review_queue_value, list):
        violations.append(
            Violation("review_queue_type", "review_queue", "review_queue must be a list")
        )

    registered_paths: list[str] = []
    workstream_ids: list[str] = []
    primary_paths_by_workstream: dict[str, list[str]] = {}
    primary_count = 0
    supporting_count = 0
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    expected_workstream_keys = {
        "id",
        "title",
        "category",
        "priority",
        "owner",
        "status",
        "next_gate",
        "documents",
    }
    expected_document_keys = {"path", "role"}
    for position, raw_workstream in enumerate(workstreams):
        location = f"workstreams[{position}]"
        if not isinstance(raw_workstream, dict):
            violations.append(
                Violation("workstream_type", location, "workstream must be an object")
            )
            continue
        workstream = cast(dict[str, object], raw_workstream)
        if set(workstream) != expected_workstream_keys:
            violations.append(
                Violation(
                    "workstream_keys",
                    location,
                    f"expected exact keys {sorted(expected_workstream_keys)}",
                )
            )
        workstream_id = workstream.get("id")
        if not isinstance(workstream_id, str) or not workstream_id:
            violations.append(Violation("workstream_id", location, "id must be a non-empty string"))
        else:
            workstream_ids.append(workstream_id)
            primary_paths_by_workstream.setdefault(workstream_id, [])
            if f"`{workstream_id}`" not in index_text:
                violations.append(
                    Violation(
                        "workstream_missing_from_index",
                        workstream_id,
                        "workstream ID is absent from docs/plans/README.md",
                    )
                )
        for key in ("title", "category", "owner", "next_gate"):
            if not isinstance(workstream.get(key), str) or not workstream.get(key):
                violations.append(
                    Violation(f"workstream_{key}", location, f"{key} must be a non-empty string")
                )
        if workstream.get("priority") not in ALLOWED_PRIORITIES:
            violations.append(
                Violation(
                    "workstream_priority", location, "priority is outside the closed contract"
                )
            )
        if workstream.get("status") not in ALLOWED_STATUSES:
            violations.append(
                Violation("workstream_status", location, "status is outside the closed contract")
            )
        documents_value = workstream.get("documents")
        documents = documents_value if isinstance(documents_value, list) else []
        if not documents:
            violations.append(
                Violation(
                    "workstream_documents", location, "workstream must own at least one document"
                )
            )
        local_primary_count = 0
        for document_position, raw_document in enumerate(documents):
            document_location = f"{location}.documents[{document_position}]"
            if not isinstance(raw_document, dict):
                violations.append(
                    Violation("document_type", document_location, "document must be an object")
                )
                continue
            document = cast(dict[str, object], raw_document)
            if set(document) != expected_document_keys:
                violations.append(
                    Violation(
                        "document_keys", document_location, "document keys must be path and role"
                    )
                )
            path_value = document.get("path")
            role = document.get("role")
            if not _is_normalized_active_path(path_value):
                violations.append(
                    Violation(
                        "document_path",
                        document_location,
                        "path must be a normalized active plan path",
                    )
                )
            else:
                registered_paths.append(cast(str, path_value))
            if role not in ALLOWED_ROLES:
                violations.append(
                    Violation(
                        "document_role", document_location, "role is outside the closed contract"
                    )
                )
            elif role == "primary":
                local_primary_count += 1
                primary_count += 1
                if isinstance(workstream_id, str) and isinstance(path_value, str):
                    primary_paths_by_workstream.setdefault(workstream_id, []).append(path_value)
            else:
                supporting_count += 1
        if local_primary_count == 0:
            violations.append(
                Violation(
                    "workstream_primary", location, "workstream must own at least one primary plan"
                )
            )

    if len(workstream_ids) != len(set(workstream_ids)):
        violations.append(
            Violation("duplicate_workstream_id", "workstreams", "workstream IDs must be unique")
        )

    expected_review_keys = {"path", "owner", "status", "review_by", "disposition"}
    for position, raw_review in enumerate(review_queue):
        location = f"review_queue[{position}]"
        if not isinstance(raw_review, dict):
            violations.append(Violation("review_type", location, "review entry must be an object"))
            continue
        review = cast(dict[str, object], raw_review)
        if set(review) != expected_review_keys:
            violations.append(
                Violation(
                    "review_keys", location, f"expected exact keys {sorted(expected_review_keys)}"
                )
            )
        path_value = review.get("path")
        if not _is_normalized_active_path(path_value):
            violations.append(
                Violation("review_path", location, "path must be a normalized active plan path")
            )
        else:
            registered_paths.append(cast(str, path_value))
        for key in ("owner", "disposition"):
            if not isinstance(review.get(key), str) or not review.get(key):
                violations.append(
                    Violation(f"review_{key}", location, f"{key} must be a non-empty string")
                )
        if review.get("status") != "review_required":
            violations.append(
                Violation(
                    "review_status", location, "review queue entries must use review_required"
                )
            )
        try:
            review_by = date.fromisoformat(cast(str, review.get("review_by")))
            if review_by < updated_at:
                violations.append(
                    Violation(
                        "review_deadline_past",
                        location,
                        "review_by cannot predate registry updated_at",
                    )
                )
        except (TypeError, ValueError):
            violations.append(
                Violation("review_deadline", location, "review_by must be an ISO date")
            )

    closure_backlog_value = registry.get("closure_backlog")
    closure_backlog = (
        cast(dict[str, object], closure_backlog_value)
        if isinstance(closure_backlog_value, dict)
        else {}
    )
    if not isinstance(closure_backlog_value, dict):
        violations.append(
            Violation(
                "closure_backlog_type",
                "closure_backlog",
                "closure_backlog must be an object",
            )
        )
    expected_backlog_keys = {
        "version",
        "legacy_unchecked_count",
        "legacy_unchecked_by_workstream",
        "legacy_sources",
        "waves",
        "units",
    }
    if set(closure_backlog) != expected_backlog_keys:
        violations.append(
            Violation(
                "closure_backlog_keys",
                "closure_backlog",
                f"expected exact keys {sorted(expected_backlog_keys)}",
            )
        )
    if not isinstance(closure_backlog.get("version"), str) or not closure_backlog.get("version"):
        violations.append(
            Violation(
                "closure_backlog_version",
                "closure_backlog.version",
                "version must be a non-empty string",
            )
        )

    legacy_counts_value = closure_backlog.get("legacy_unchecked_by_workstream")
    legacy_counts = (
        cast(dict[str, object], legacy_counts_value)
        if isinstance(legacy_counts_value, dict)
        else {}
    )
    if set(legacy_counts) != set(workstream_ids):
        violations.append(
            Violation(
                "legacy_count_workstreams",
                "closure_backlog.legacy_unchecked_by_workstream",
                "legacy checkbox counts must cover every workstream exactly once",
            )
        )
    actual_legacy_total = 0
    actual_unchecked_by_primary_path: dict[str, int] = {}
    primary_path_owners = {
        primary_path: workstream_id
        for workstream_id, primary_paths in primary_paths_by_workstream.items()
        for primary_path in primary_paths
    }
    for workstream_id in workstream_ids:
        actual_count = 0
        for primary_path in primary_paths_by_workstream.get(workstream_id, []):
            source_path = repository_root / primary_path
            path_count = 0
            if source_path.is_file():
                try:
                    path_count = len(
                        UNCHECKED_ITEM_PATTERN.findall(source_path.read_text(encoding="utf-8"))
                    )
                except (OSError, UnicodeError) as exc:
                    violations.append(Violation("primary_plan_unreadable", primary_path, str(exc)))
            actual_unchecked_by_primary_path[primary_path] = path_count
            actual_count += path_count
        actual_legacy_total += actual_count
        declared_count = legacy_counts.get(workstream_id)
        if not isinstance(declared_count, int) or isinstance(declared_count, bool):
            violations.append(
                Violation(
                    "legacy_count_type",
                    f"closure_backlog.legacy_unchecked_by_workstream.{workstream_id}",
                    "legacy checkbox count must be an integer",
                )
            )
        elif declared_count != actual_count:
            violations.append(
                Violation(
                    "legacy_count_drift",
                    workstream_id,
                    f"declared {declared_count}, found {actual_count} unchecked primary-plan items",
                )
            )
    declared_legacy_total = closure_backlog.get("legacy_unchecked_count")
    if (
        not isinstance(declared_legacy_total, int)
        or isinstance(declared_legacy_total, bool)
        or declared_legacy_total != actual_legacy_total
    ):
        violations.append(
            Violation(
                "legacy_total_drift",
                "closure_backlog.legacy_unchecked_count",
                f"declared {declared_legacy_total!r}, found {actual_legacy_total}",
            )
        )

    waves_value = closure_backlog.get("waves")
    waves = waves_value if isinstance(waves_value, list) else []
    if not isinstance(waves_value, list) or not waves:
        violations.append(
            Violation("closure_waves", "closure_backlog.waves", "waves must be a non-empty list")
        )
    wave_ids: list[int] = []
    for position, raw_wave in enumerate(waves):
        location = f"closure_backlog.waves[{position}]"
        if not isinstance(raw_wave, dict):
            violations.append(Violation("closure_wave_type", location, "wave must be an object"))
            continue
        wave = cast(dict[str, object], raw_wave)
        if set(wave) != {"id", "title", "rule"}:
            violations.append(
                Violation("closure_wave_keys", location, "wave keys must be id, title and rule")
            )
        wave_id = wave.get("id")
        if not isinstance(wave_id, int) or isinstance(wave_id, bool) or wave_id < 0:
            violations.append(
                Violation("closure_wave_id", location, "wave id must be a non-negative integer")
            )
        else:
            wave_ids.append(wave_id)
        for key in ("title", "rule"):
            if not isinstance(wave.get(key), str) or not wave.get(key):
                violations.append(
                    Violation(f"closure_wave_{key}", location, f"{key} must be non-empty")
                )
    if len(wave_ids) != len(set(wave_ids)):
        violations.append(
            Violation("duplicate_closure_wave", "closure_backlog.waves", "wave IDs must be unique")
        )
    if wave_ids and sorted(wave_ids) != list(range(min(wave_ids), max(wave_ids) + 1)):
        violations.append(
            Violation(
                "closure_wave_sequence",
                "closure_backlog.waves",
                "wave IDs must form a contiguous sequence",
            )
        )

    units_value = closure_backlog.get("units")
    units = units_value if isinstance(units_value, list) else []
    if not isinstance(units_value, list) or not units:
        violations.append(
            Violation("closure_units", "closure_backlog.units", "units must be a non-empty list")
        )
    expected_unit_keys = {
        "id",
        "workstream_id",
        "wave",
        "priority",
        "execution_mode",
        "status",
        "title",
        "depends_on",
        "exit_gate",
    }
    expected_evidence_collection_keys = {
        "auto_collect",
        "authorization_required",
        "human_or_external_required",
    }
    unit_ids: list[str] = []
    unit_workstreams: list[str] = []
    unit_workstream_by_id: dict[str, str] = {}
    unit_waves: dict[str, int] = {}
    unit_dependencies: dict[str, tuple[str, ...]] = {}
    allowed_unit_workstreams = set(workstream_ids) | {"review-queue"}
    for position, raw_unit in enumerate(units):
        location = f"closure_backlog.units[{position}]"
        if not isinstance(raw_unit, dict):
            violations.append(Violation("closure_unit_type", location, "unit must be an object"))
            continue
        unit = cast(dict[str, object], raw_unit)
        execution_mode = unit.get("execution_mode")
        unit_keys = expected_unit_keys | (
            {"evidence_collection"} if execution_mode in {"production", "external"} else set()
        )
        if set(unit) != unit_keys:
            violations.append(
                Violation(
                    "closure_unit_keys",
                    location,
                    f"expected exact keys {sorted(unit_keys)}",
                )
            )
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not re.fullmatch(r"[A-Z]+-\d{2}", unit_id):
            violations.append(
                Violation("closure_unit_id", location, "id must match the canonical PREFIX-NN form")
            )
            continue
        unit_ids.append(unit_id)
        workstream_id = unit.get("workstream_id")
        if workstream_id not in allowed_unit_workstreams:
            violations.append(
                Violation(
                    "closure_unit_workstream",
                    unit_id,
                    "workstream_id must reference a registered workstream or review-queue",
                )
            )
        elif isinstance(workstream_id, str):
            unit_workstreams.append(workstream_id)
            unit_workstream_by_id[unit_id] = workstream_id
        wave_value = unit.get("wave")
        if (
            not isinstance(wave_value, int)
            or isinstance(wave_value, bool)
            or wave_value not in wave_ids
        ):
            violations.append(
                Violation("closure_unit_wave", unit_id, "wave must reference a registered wave")
            )
        else:
            unit_waves[unit_id] = wave_value
        if unit.get("priority") not in ALLOWED_PRIORITIES:
            violations.append(
                Violation("closure_unit_priority", unit_id, "priority is outside the contract")
            )
        if execution_mode not in ALLOWED_EXECUTION_MODES:
            violations.append(
                Violation(
                    "closure_unit_execution_mode",
                    unit_id,
                    "execution_mode is outside the contract",
                )
            )
        evidence_collection_value = unit.get("evidence_collection")
        if execution_mode in {"production", "external"}:
            evidence_collection = (
                cast(dict[str, object], evidence_collection_value)
                if isinstance(evidence_collection_value, dict)
                else {}
            )
            if not isinstance(evidence_collection_value, dict):
                violations.append(
                    Violation(
                        "closure_unit_evidence_collection",
                        unit_id,
                        "production and external units require an evidence_collection object",
                    )
                )
            elif set(evidence_collection) != expected_evidence_collection_keys:
                violations.append(
                    Violation(
                        "closure_unit_evidence_collection_keys",
                        unit_id,
                        "evidence_collection keys must be auto_collect, "
                        "authorization_required and human_or_external_required",
                    )
                )
            for evidence_key in expected_evidence_collection_keys:
                raw_evidence_items = evidence_collection.get(evidence_key)
                if not isinstance(raw_evidence_items, list) or any(
                    not isinstance(item, str) or not item.strip() for item in raw_evidence_items
                ):
                    violations.append(
                        Violation(
                            "closure_unit_evidence_collection_items",
                            unit_id,
                            f"evidence_collection.{evidence_key} must be a list of non-empty strings",
                        )
                    )
            auto_collect = evidence_collection.get("auto_collect")
            if isinstance(auto_collect, list) and not auto_collect:
                violations.append(
                    Violation(
                        "closure_unit_auto_collection_empty",
                        unit_id,
                        "production and external units must identify evidence the agent can collect automatically",
                    )
                )
        status = unit.get("status")
        if status not in ALLOWED_UNIT_STATUSES:
            violations.append(
                Violation("closure_unit_status", unit_id, "status is outside the contract")
            )
        for key in ("title", "exit_gate"):
            if not isinstance(unit.get(key), str) or not unit.get(key):
                violations.append(
                    Violation(f"closure_unit_{key}", unit_id, f"{key} must be non-empty")
                )
        dependencies_value = unit.get("depends_on")
        dependency_values: list[object] = (
            dependencies_value if isinstance(dependencies_value, list) else []
        )
        dependency_ids = [
            dependency for dependency in dependency_values if isinstance(dependency, str)
        ]
        if not isinstance(dependencies_value, list) or len(dependency_ids) != len(
            dependency_values
        ):
            violations.append(
                Violation(
                    "closure_unit_dependencies",
                    unit_id,
                    "depends_on must be a list of unit IDs",
                )
            )
        elif len(dependency_ids) != len(set(dependency_ids)):
            violations.append(
                Violation(
                    "duplicate_closure_dependency",
                    unit_id,
                    "depends_on entries must be unique",
                )
            )
        else:
            unit_dependencies[unit_id] = tuple(dependency_ids)
        if status == "waiting_dependency" and not dependency_values:
            violations.append(
                Violation(
                    "closure_wait_without_dependency",
                    unit_id,
                    "waiting_dependency requires at least one dependency",
                )
            )

    if len(unit_ids) != len(set(unit_ids)):
        violations.append(
            Violation("duplicate_closure_unit", "closure_backlog.units", "unit IDs must be unique")
        )
    missing_unit_workstreams = set(workstream_ids) - set(unit_workstreams)
    for workstream_id in sorted(missing_unit_workstreams):
        violations.append(
            Violation(
                "workstream_without_closure_unit",
                workstream_id,
                "every active workstream must own a canonical closure unit",
            )
        )
    if unit_workstreams.count("review-queue") != 1:
        violations.append(
            Violation(
                "review_queue_closure_unit",
                "review-queue",
                "the review queue must have exactly one deduplicated closure unit",
            )
        )
    known_unit_ids = set(unit_ids)
    legacy_sources_value = closure_backlog.get("legacy_sources")
    legacy_sources = legacy_sources_value if isinstance(legacy_sources_value, list) else []
    if not isinstance(legacy_sources_value, list):
        violations.append(
            Violation(
                "legacy_sources_type",
                "closure_backlog.legacy_sources",
                "legacy_sources must be a list",
            )
        )
    declared_legacy_source_paths: list[str] = []
    for position, raw_source in enumerate(legacy_sources):
        location = f"closure_backlog.legacy_sources[{position}]"
        if not isinstance(raw_source, dict):
            violations.append(
                Violation("legacy_source_type", location, "legacy source must be an object")
            )
            continue
        source = cast(dict[str, object], raw_source)
        if set(source) != {"path", "unchecked_count", "closure_unit_ids"}:
            violations.append(
                Violation(
                    "legacy_source_keys",
                    location,
                    "legacy source keys must be path, unchecked_count and closure_unit_ids",
                )
            )
        path_value = source.get("path")
        if not isinstance(path_value, str) or path_value not in primary_path_owners:
            violations.append(
                Violation(
                    "legacy_source_path",
                    location,
                    "path must reference a registered primary plan",
                )
            )
            continue
        declared_legacy_source_paths.append(path_value)
        actual_count = actual_unchecked_by_primary_path.get(path_value, 0)
        unchecked_count = source.get("unchecked_count")
        if (
            not isinstance(unchecked_count, int)
            or isinstance(unchecked_count, bool)
            or unchecked_count != actual_count
        ):
            violations.append(
                Violation(
                    "legacy_source_count_drift",
                    path_value,
                    f"declared {unchecked_count!r}, found {actual_count}",
                )
            )
        closure_unit_ids_value = source.get("closure_unit_ids")
        closure_unit_ids: list[object] = (
            closure_unit_ids_value if isinstance(closure_unit_ids_value, list) else []
        )
        if (
            not isinstance(closure_unit_ids_value, list)
            or not closure_unit_ids
            or any(not isinstance(unit_id, str) for unit_id in closure_unit_ids)
            or len(closure_unit_ids) != len(set(cast(list[str], closure_unit_ids)))
        ):
            violations.append(
                Violation(
                    "legacy_source_units",
                    path_value,
                    "closure_unit_ids must be a non-empty unique list of unit IDs",
                )
            )
            continue
        source_workstream = primary_path_owners[path_value]
        for closure_unit_id in cast(list[str], closure_unit_ids):
            if closure_unit_id not in known_unit_ids:
                violations.append(
                    Violation(
                        "legacy_source_unknown_unit",
                        path_value,
                        f"closure unit {closure_unit_id!r} is not registered",
                    )
                )
            elif unit_workstream_by_id.get(closure_unit_id) != source_workstream:
                violations.append(
                    Violation(
                        "legacy_source_cross_workstream",
                        path_value,
                        f"closure unit {closure_unit_id!r} belongs to another workstream",
                    )
                )
    if len(declared_legacy_source_paths) != len(set(declared_legacy_source_paths)):
        violations.append(
            Violation(
                "duplicate_legacy_source",
                "closure_backlog.legacy_sources",
                "legacy source paths must be unique",
            )
        )
    actual_nonzero_source_paths = {
        path for path, count in actual_unchecked_by_primary_path.items() if count > 0
    }
    if set(declared_legacy_source_paths) != actual_nonzero_source_paths:
        violations.append(
            Violation(
                "legacy_source_coverage",
                "closure_backlog.legacy_sources",
                "every primary plan with unchecked items must be mapped exactly once",
            )
        )

    for unit_id, dependencies in unit_dependencies.items():
        for dependency in dependencies:
            if dependency not in known_unit_ids:
                violations.append(
                    Violation(
                        "unknown_closure_dependency",
                        unit_id,
                        f"dependency {dependency!r} is not a canonical unit",
                    )
                )
            elif dependency == unit_id:
                violations.append(
                    Violation("self_closure_dependency", unit_id, "unit cannot depend on itself")
                )
            elif unit_waves.get(dependency, 0) > unit_waves.get(unit_id, 0):
                violations.append(
                    Violation(
                        "future_wave_dependency",
                        unit_id,
                        f"dependency {dependency!r} belongs to a later wave",
                    )
                )
    if unit_dependencies and _dependency_cycle(unit_dependencies):
        violations.append(
            Violation(
                "closure_dependency_cycle",
                "closure_backlog.units",
                "canonical closure-unit dependencies must be acyclic",
            )
        )

    duplicates = sorted({path for path in registered_paths if registered_paths.count(path) > 1})
    for path in duplicates:
        violations.append(
            Violation("duplicate_path", path, "active artifact is registered more than once")
        )

    registered_set = set(registered_paths)
    active_set = collect_active_plan_paths(repository_root)
    for path in sorted(active_set - registered_set):
        violations.append(
            Violation(
                "unregistered_active_path", path, "active plan artifact is absent from the registry"
            )
        )
    for path in sorted(registered_set - active_set):
        violations.append(
            Violation(
                "stale_registered_path",
                path,
                "registered plan artifact does not exist under docs/plans",
            )
        )

    if "governance/active_plan_registry.json" not in index_text:
        violations.append(
            Violation(
                "registry_missing_from_index",
                "docs/plans/README.md",
                "human index must link the machine registry",
            )
        )
    if "closure_backlog" not in index_text:
        violations.append(
            Violation(
                "closure_backlog_missing_from_index",
                "docs/plans/README.md",
                "human index must identify the canonical closure backlog",
            )
        )

    ordered_violations = tuple(
        sorted(violations, key=lambda item: (item.code, item.path, item.message))
    )
    return RegistryReport(
        version=version,
        workstream_count=len(workstreams),
        primary_plan_count=primary_count,
        supporting_document_count=supporting_count,
        review_queue_count=len(review_queue),
        closure_unit_count=len(units),
        registered_path_count=len(registered_set),
        active_path_count=len(active_set),
        violation_count=len(ordered_violations),
        violations=ordered_violations,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main() -> int:
    """Run the active-plan registry check."""

    args = _build_parser().parse_args()
    registry_path = args.registry if args.registry.is_absolute() else REPO_ROOT / args.registry
    index_path = args.index if args.index.is_absolute() else REPO_ROOT / args.index
    report = evaluate_registry(REPO_ROOT, registry_path, index_path)
    if args.format == "json":
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(
            "active-plan-registry "
            f"version={report.version} workstreams={report.workstream_count} "
            f"primary={report.primary_plan_count} support={report.supporting_document_count} "
            f"review={report.review_queue_count} units={report.closure_unit_count} "
            f"paths={report.active_path_count} "
            f"violations={report.violation_count}"
        )
        for violation in report.violations:
            print(f"[{violation.code}] {violation.path}: {violation.message}")
    return 1 if report.violation_count else 0


if __name__ == "__main__":
    sys.exit(main())
