"""Keep parallel versioned source families tied to explicit retirement gates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "governance" / "versioned_surface_retirement.json"
DEFAULT_ACTIVE_PLAN = ROOT / "governance" / "active_plan_registry.json"
VERSION_TOKEN = re.compile(r"_v(?P<version>[0-9]+)(?=_|\.py$)")
ALLOWED_FAMILY_STATES = {"blocked_retirement", "read_compatibility"}


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _tokens(value: object, *, field: str, violations: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        violations.append(f"{field}_invalid")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            violations.append(f"{field}_item_invalid:{index}")
            continue
        result.append(item)
    if len(result) != len(set(result)):
        violations.append(f"{field}_duplicate")
    return result


def _versions(value: object, *, field: str, violations: list[str]) -> list[int]:
    if not isinstance(value, list):
        violations.append(f"{field}_invalid")
        return []
    result: list[int] = []
    for index, item in enumerate(value):
        if type(item) is not int or item <= 0:
            violations.append(f"{field}_item_invalid:{index}")
            continue
        result.append(item)
    if result != sorted(set(result)):
        violations.append(f"{field}_not_sorted_unique")
    return result


def discover_multi_version_groups(repository_root: Path = ROOT) -> dict[str, list[int]]:
    """Return exact non-migration Python module groups with parallel version tokens."""

    groups: dict[str, set[int]] = {}
    for source_root in (repository_root / "apps", repository_root / "core"):
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(repository_root).as_posix()
            if "/migrations/" in relative or "/__pycache__/" in relative:
                continue
            versions = {int(match.group("version")) for match in VERSION_TOKEN.finditer(relative)}
            if not versions:
                continue
            normalized = VERSION_TOKEN.sub("_v#", relative)
            groups.setdefault(normalized, set()).update(versions)
    return {
        group: sorted(versions) for group, versions in sorted(groups.items()) if len(versions) > 1
    }


def _active_unit_statuses(payload: dict[str, Any], violations: list[str]) -> dict[str, str]:
    backlog = payload.get("closure_backlog")
    if not isinstance(backlog, dict) or not isinstance(backlog.get("units"), list):
        violations.append("active_plan_units_invalid")
        return {}
    statuses: dict[str, str] = {}
    for index, item in enumerate(backlog["units"]):
        if not isinstance(item, dict):
            violations.append(f"active_plan_unit_invalid:{index}")
            continue
        unit_id = item.get("id")
        status = item.get("status")
        if not isinstance(unit_id, str) or not isinstance(status, str):
            violations.append(f"active_plan_unit_identity_invalid:{index}")
            continue
        if unit_id in statuses:
            violations.append(f"active_plan_unit_duplicate:{unit_id}")
        statuses[unit_id] = status
    return statuses


def _check_blockers(
    *,
    owner_id: str,
    raw_blockers: object,
    statuses: dict[str, str],
    violations: list[str],
) -> list[str]:
    blockers = _tokens(raw_blockers, field=f"{owner_id}.blocked_by", violations=violations)
    missing = sorted(set(blockers) - set(statuses))
    violations.extend(f"{owner_id}.blocker_unknown:{unit_id}" for unit_id in missing)
    known = [unit_id for unit_id in blockers if unit_id in statuses]
    if known and all(statuses[unit_id] == "completed" for unit_id in known):
        violations.append(f"{owner_id}.retirement_review_due")
    return blockers


def validate(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    active_plan_path: Path = DEFAULT_ACTIVE_PLAN,
    repository_root: Path = ROOT,
) -> tuple[list[str], dict[str, Any]]:
    """Return lifecycle violations and a deterministic inventory summary."""

    manifest = _load_object(manifest_path)
    active_plan = _load_object(active_plan_path)
    violations: list[str] = []
    statuses = _active_unit_statuses(active_plan, violations)
    discovered = discover_multi_version_groups(repository_root)

    if manifest.get("schema_version") != "2026-09-22.v1":
        violations.append("schema_version_invalid")
    if manifest.get("owner") != "architecture-governance":
        violations.append("manifest_owner_invalid")
    if manifest.get("scope") != (
        "apps/**/*.py and core/**/*.py excluding migrations; _vN module tokens"
    ):
        violations.append("scope_invalid")

    families_raw = manifest.get("families")
    if not isinstance(families_raw, list) or not families_raw:
        violations.append("families_invalid")
        families_raw = []
    registered: dict[str, list[int]] = {}
    family_ids: set[str] = set()
    multi_writer_family_count = 0
    for index, raw_family in enumerate(families_raw):
        if not isinstance(raw_family, dict):
            violations.append(f"family_invalid:{index}")
            continue
        family_id = raw_family.get("id")
        if not isinstance(family_id, str) or not family_id.strip():
            violations.append(f"family_id_invalid:{index}")
            continue
        if family_id in family_ids:
            violations.append(f"family_id_duplicate:{family_id}")
        family_ids.add(family_id)
        if not isinstance(raw_family.get("owner"), str) or not raw_family["owner"].strip():
            violations.append(f"{family_id}.owner_invalid")
        state = raw_family.get("state")
        if state not in ALLOWED_FAMILY_STATES:
            violations.append(f"{family_id}.state_invalid:{state}")
        preferred = raw_family.get("preferred_current_version")
        if type(preferred) is not int or preferred <= 0:
            violations.append(f"{family_id}.preferred_current_version_invalid")
        write_versions = _versions(
            raw_family.get("write_surface_versions"),
            field=f"{family_id}.write_surface_versions",
            violations=violations,
        )
        read_versions = _versions(
            raw_family.get("retained_read_versions"),
            field=f"{family_id}.retained_read_versions",
            violations=violations,
        )
        if len(write_versions) > 1:
            multi_writer_family_count += 1
            if state != "blocked_retirement":
                violations.append(f"{family_id}.multi_writer_state_invalid")
        if preferred not in set(write_versions) | set(read_versions):
            violations.append(f"{family_id}.preferred_version_uncovered")
        _check_blockers(
            owner_id=family_id,
            raw_blockers=raw_family.get("blocked_by"),
            statuses=statuses,
            violations=violations,
        )
        _tokens(
            raw_family.get("retirement_gate"),
            field=f"{family_id}.retirement_gate",
            violations=violations,
        )
        evidence_paths = _tokens(
            raw_family.get("evidence"),
            field=f"{family_id}.evidence",
            violations=violations,
        )
        for path_text in evidence_paths:
            if not (repository_root / path_text).is_file():
                violations.append(f"{family_id}.evidence_missing:{path_text}")

        module_groups = raw_family.get("module_groups")
        if not isinstance(module_groups, dict) or not module_groups:
            violations.append(f"{family_id}.module_groups_invalid")
            continue
        family_observed_versions: set[int] = set()
        for group, raw_versions in module_groups.items():
            if not isinstance(group, str) or "_v#" not in group:
                violations.append(f"{family_id}.module_group_invalid:{group}")
                continue
            versions = _versions(
                raw_versions,
                field=f"{family_id}.module_groups.{group}",
                violations=violations,
            )
            if len(versions) < 2:
                violations.append(f"{family_id}.module_group_not_parallel:{group}")
            family_observed_versions.update(versions)
            if group in registered:
                violations.append(f"module_group_duplicate:{group}")
            registered[group] = versions
        unclassified_versions = sorted(
            family_observed_versions - set(write_versions) - set(read_versions)
        )
        if unclassified_versions:
            violations.append(f"{family_id}.versions_unclassified:{unclassified_versions}")

    for group in sorted(set(discovered) - set(registered)):
        violations.append(f"unregistered_multi_version_group:{group}")
    for group in sorted(set(registered) - set(discovered)):
        violations.append(f"stale_multi_version_group:{group}")
    for group in sorted(set(discovered) & set(registered)):
        if discovered[group] != registered[group]:
            violations.append(
                f"module_group_versions_changed:{group}:"
                f"expected={registered[group]}:actual={discovered[group]}"
            )

    linked_raw = manifest.get("linked_retirement_gates")
    if not isinstance(linked_raw, list) or not linked_raw:
        violations.append("linked_retirement_gates_invalid")
        linked_raw = []
    linked_ids: set[str] = set()
    for index, raw_gate in enumerate(linked_raw):
        if not isinstance(raw_gate, dict):
            violations.append(f"linked_gate_invalid:{index}")
            continue
        gate_id = raw_gate.get("id")
        if not isinstance(gate_id, str) or not gate_id.strip():
            violations.append(f"linked_gate_id_invalid:{index}")
            continue
        if gate_id in linked_ids:
            violations.append(f"linked_gate_id_duplicate:{gate_id}")
        linked_ids.add(gate_id)
        if not isinstance(raw_gate.get("owner"), str) or not raw_gate["owner"].strip():
            violations.append(f"{gate_id}.owner_invalid")
        blockers = _check_blockers(
            owner_id=gate_id,
            raw_blockers=raw_gate.get("blocked_by"),
            statuses=statuses,
            violations=violations,
        )
        deletion_allowed = raw_gate.get("deletion_allowed")
        if type(deletion_allowed) is not bool:
            violations.append(f"{gate_id}.deletion_allowed_invalid")
        if any(statuses.get(unit_id) != "completed" for unit_id in blockers):
            if deletion_allowed is not False:
                violations.append(f"{gate_id}.blocked_deletion_must_be_false")
        guard_command = raw_gate.get("guard_command")
        if not isinstance(guard_command, str) or not guard_command.strip():
            violations.append(f"{gate_id}.guard_command_invalid")
        _tokens(
            raw_gate.get("retirement_gate"),
            field=f"{gate_id}.retirement_gate",
            violations=violations,
        )

    summary = {
        "schema_version": manifest.get("schema_version"),
        "family_count": len(family_ids),
        "multi_writer_family_count": multi_writer_family_count,
        "discovered_module_group_count": len(discovered),
        "linked_retirement_gate_count": len(linked_ids),
        "violation_count": len(set(violations)),
    }
    return sorted(set(violations)), summary


def main() -> int:
    """Fail closed on an unregistered or newly unblocked version family."""

    try:
        violations, summary = validate()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"versioned surface retirement guard failed: {exc}") from exc
    if violations:
        raise SystemExit("Versioned surface retirement violations: " + "; ".join(violations))
    linked_gate_count = summary["linked_retirement_gate_count"]
    linked_gate_label = "gate" if linked_gate_count == 1 else "gates"
    print(
        "Versioned surface retirement: "
        f"{summary['family_count']} families, "
        f"{summary['multi_writer_family_count']} multi-writer, "
        f"{summary['discovered_module_group_count']} module groups, "
        f"{linked_gate_count} linked {linked_gate_label}, 0 violations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
