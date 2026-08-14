#!/usr/bin/env python
"""Validate the active plan registry and prevent plan-index drift."""

from __future__ import annotations

import argparse
import json
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
        return RegistryReport("unknown", 0, 0, 0, 0, 0, 0, 1, (violation,))

    expected_root_keys = {"version", "updated_at", "workstreams", "review_queue"}
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

    ordered_violations = tuple(
        sorted(violations, key=lambda item: (item.code, item.path, item.message))
    )
    return RegistryReport(
        version=version,
        workstream_count=len(workstreams),
        primary_plan_count=primary_count,
        supporting_document_count=supporting_count,
        review_queue_count=len(review_queue),
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
            f"review={report.review_queue_count} paths={report.active_path_count} "
            f"violations={report.violation_count}"
        )
        for violation in report.violations:
            print(f"[{violation.code}] {violation.path}: {violation.message}")
    return 1 if report.violation_count else 0


if __name__ == "__main__":
    sys.exit(main())
