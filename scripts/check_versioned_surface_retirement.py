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
NO_SUFFIX_VERSION = re.compile(r"^(?P<prefix>.*)_v(?P<version>[0-9]+)(?P<suffix>.*)\.py$")
ALLOWED_FAMILY_STATES = {"blocked_retirement", "read_compatibility"}
ALLOWED_LEGACY_SURFACE_STATES = {"blocked_retirement", "compatibility_only"}
ALLOWED_PATH_ROLES = {
    "compatibility_entrypoint",
    "preferred_entrypoint",
    "reader",
    "reader_writer",
    "schema",
    "writer",
}
REQUIRED_RETIREMENT_EVIDENCE = frozenset(
    {
        "zero_runtime_callers",
        "production_row_inventory",
        "backup_restore",
        "historical_hash_replay",
    }
)


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


def discover_no_suffix_version_groups(repository_root: Path = ROOT) -> dict[str, list[int]]:
    """Return groups where an unnumbered Python module coexists with numbered modules."""

    groups: dict[str, set[int]] = {}
    for source_root in (repository_root / "apps", repository_root / "core"):
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(repository_root)
            if "migrations" in relative.parts or "__pycache__" in relative.parts:
                continue
            match = NO_SUFFIX_VERSION.match(path.name)
            if match is None:
                continue
            unnumbered = path.with_name(f"{match.group('prefix')}{match.group('suffix')}.py")
            if not unnumbered.is_file():
                continue
            group = unnumbered.relative_to(repository_root).as_posix()[:-3] + "{_v#}.py"
            groups.setdefault(group, {1}).add(int(match.group("version")))
    return {group: sorted(versions) for group, versions in sorted(groups.items())}


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


def _check_retirement_evidence(
    *, owner_id: str, raw_evidence: object, repository_root: Path, violations: list[str]
) -> int:
    """Validate machine-readable retirement proof slots without inventing receipts."""

    if not isinstance(raw_evidence, dict):
        violations.append(f"{owner_id}.retirement_evidence_invalid")
        return 0
    keys = frozenset(raw_evidence)
    if keys != REQUIRED_RETIREMENT_EVIDENCE:
        violations.append(f"{owner_id}.retirement_evidence_keys_invalid")
    pending_count = 0
    for evidence_key in sorted(REQUIRED_RETIREMENT_EVIDENCE):
        raw_item = raw_evidence.get(evidence_key)
        if not isinstance(raw_item, dict) or frozenset(raw_item) != {"status", "artifact"}:
            violations.append(f"{owner_id}.{evidence_key}_invalid")
            continue
        status = raw_item.get("status")
        artifact = raw_item.get("artifact")
        if status == "pending":
            pending_count += 1
            if artifact is not None:
                violations.append(f"{owner_id}.{evidence_key}_pending_artifact_must_be_null")
        elif status == "verified":
            if not isinstance(artifact, str) or not artifact.strip():
                violations.append(f"{owner_id}.{evidence_key}_verified_artifact_invalid")
            elif not (repository_root / artifact).is_file():
                violations.append(f"{owner_id}.{evidence_key}_artifact_missing:{artifact}")
        else:
            violations.append(f"{owner_id}.{evidence_key}_status_invalid:{status}")
    return pending_count


def _check_tracked_paths(
    *,
    owner_id: str,
    raw_paths: object,
    versions: list[int],
    preferred_version: object,
    active_default_version: object,
    repository_root: Path,
    violations: list[str],
) -> set[str]:
    """Validate explicit no-suffix, runtime-schema, and entrypoint contracts."""

    if not isinstance(raw_paths, list) or not raw_paths:
        violations.append(f"{owner_id}.tracked_paths_invalid")
        return set()
    observed_versions: set[int] = set()
    observed_paths: set[str] = set()
    preferred_entrypoint_versions: set[int] = set()
    active_entrypoint_versions: set[int] = set()
    for index, raw_path in enumerate(raw_paths):
        if not isinstance(raw_path, dict):
            violations.append(f"{owner_id}.tracked_path_invalid:{index}")
            continue
        if frozenset(raw_path) != {"path", "versions", "role", "markers"}:
            violations.append(f"{owner_id}.tracked_path_keys_invalid:{index}")
            continue
        path_text = raw_path.get("path")
        role = raw_path.get("role")
        if not isinstance(path_text, str) or not path_text.strip():
            violations.append(f"{owner_id}.tracked_path_name_invalid:{index}")
            continue
        if path_text in observed_paths:
            violations.append(f"{owner_id}.tracked_path_duplicate:{path_text}")
        observed_paths.add(path_text)
        path_versions = _versions(
            raw_path.get("versions"),
            field=f"{owner_id}.tracked_paths.{path_text}.versions",
            violations=violations,
        )
        unknown_versions = sorted(set(path_versions) - set(versions))
        if unknown_versions:
            violations.append(
                f"{owner_id}.tracked_path_versions_invalid:{path_text}:{unknown_versions}"
            )
        observed_versions.update(set(path_versions) & set(versions))
        if role not in ALLOWED_PATH_ROLES:
            violations.append(f"{owner_id}.tracked_path_role_invalid:{path_text}")
        if role == "preferred_entrypoint":
            preferred_entrypoint_versions.update(path_versions)
        if role in {"compatibility_entrypoint", "preferred_entrypoint"}:
            active_entrypoint_versions.update(path_versions)
        markers = _tokens(
            raw_path.get("markers"),
            field=f"{owner_id}.tracked_paths.{path_text}.markers",
            violations=violations,
        )
        source_path = repository_root / path_text
        if not source_path.is_file():
            violations.append(f"{owner_id}.tracked_path_missing:{path_text}")
            continue
        source_text = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source_text:
                violations.append(f"{owner_id}.tracked_marker_missing:{path_text}:{marker}")
    missing_versions = sorted(set(versions) - observed_versions)
    if missing_versions:
        violations.append(f"{owner_id}.tracked_versions_missing:{missing_versions}")
    if preferred_version not in preferred_entrypoint_versions:
        violations.append(f"{owner_id}.preferred_entrypoint_missing:{preferred_version}")
    if active_default_version not in active_entrypoint_versions:
        violations.append(f"{owner_id}.active_default_entrypoint_missing:{active_default_version}")
    return observed_paths


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
    discovered_no_suffix = discover_no_suffix_version_groups(repository_root)

    if manifest.get("schema_version") != "2026-09-22.v2":
        violations.append("schema_version_invalid")
    if manifest.get("owner") != "architecture-governance":
        violations.append("manifest_owner_invalid")
    if manifest.get("scope") != (
        "apps/**/*.py and core/**/*.py excluding migrations; _vN module groups plus "
        "explicit no-suffix, runtime-schema and composition-route legacy surfaces"
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

    legacy_raw = manifest.get("legacy_surfaces")
    if not isinstance(legacy_raw, list) or not legacy_raw:
        violations.append("legacy_surfaces_invalid")
        legacy_raw = []
    legacy_ids: set[str] = set()
    legacy_versions: dict[str, list[int]] = {}
    legacy_paths: set[str] = set()
    pending_retirement_evidence_count = 0
    for index, raw_surface in enumerate(legacy_raw):
        if not isinstance(raw_surface, dict):
            violations.append(f"legacy_surface_invalid:{index}")
            continue
        surface_id = raw_surface.get("id")
        if not isinstance(surface_id, str) or not surface_id.strip():
            violations.append(f"legacy_surface_id_invalid:{index}")
            continue
        if surface_id in legacy_ids:
            violations.append(f"legacy_surface_id_duplicate:{surface_id}")
        legacy_ids.add(surface_id)
        if not isinstance(raw_surface.get("owner"), str) or not raw_surface["owner"].strip():
            violations.append(f"{surface_id}.owner_invalid")
        state = raw_surface.get("state")
        if state not in ALLOWED_LEGACY_SURFACE_STATES:
            violations.append(f"{surface_id}.state_invalid:{state}")
        versions = _versions(
            raw_surface.get("versions"),
            field=f"{surface_id}.versions",
            violations=violations,
        )
        legacy_versions[surface_id] = versions
        if len(versions) < 2:
            violations.append(f"{surface_id}.versions_not_parallel")
        preferred = raw_surface.get("preferred_current_version")
        active_default = raw_surface.get("active_default_version")
        if type(preferred) is not int or preferred not in versions:
            violations.append(f"{surface_id}.preferred_current_version_invalid")
        if type(active_default) is not int or active_default not in versions:
            violations.append(f"{surface_id}.active_default_version_invalid")
        write_versions = _versions(
            raw_surface.get("write_surface_versions"),
            field=f"{surface_id}.write_surface_versions",
            violations=violations,
        )
        read_versions = _versions(
            raw_surface.get("retained_read_versions"),
            field=f"{surface_id}.retained_read_versions",
            violations=violations,
        )
        versions_set = set(versions)
        unknown_classified = sorted((set(write_versions) | set(read_versions)) - versions_set)
        if unknown_classified:
            violations.append(f"{surface_id}.classified_versions_unknown:{unknown_classified}")
        unclassified = sorted(set(versions) - set(write_versions) - set(read_versions))
        if unclassified:
            violations.append(f"{surface_id}.versions_unclassified:{unclassified}")
        blockers = _check_blockers(
            owner_id=surface_id,
            raw_blockers=raw_surface.get("blocked_by"),
            statuses=statuses,
            violations=violations,
        )
        if active_default != preferred and not blockers:
            violations.append(f"{surface_id}.nonpreferred_default_without_blocker")
        _tokens(
            raw_surface.get("retirement_gate"),
            field=f"{surface_id}.retirement_gate",
            violations=violations,
        )
        surface_paths = _check_tracked_paths(
            owner_id=surface_id,
            raw_paths=raw_surface.get("tracked_paths"),
            versions=versions,
            preferred_version=preferred,
            active_default_version=active_default,
            repository_root=repository_root,
            violations=violations,
        )
        duplicates = sorted(legacy_paths & surface_paths)
        violations.extend(f"legacy_tracked_path_duplicate:{path}" for path in duplicates)
        legacy_paths.update(surface_paths)
        pending_retirement_evidence_count += _check_retirement_evidence(
            owner_id=surface_id,
            raw_evidence=raw_surface.get("retirement_evidence"),
            repository_root=repository_root,
            violations=violations,
        )

    no_suffix_raw = manifest.get("no_suffix_module_groups")
    if not isinstance(no_suffix_raw, dict) or not no_suffix_raw:
        violations.append("no_suffix_module_groups_invalid")
        no_suffix_raw = {}
    registered_no_suffix: dict[str, list[int]] = {}
    for group, raw_group in no_suffix_raw.items():
        if not isinstance(group, str) or "{_v#}" not in group:
            violations.append(f"no_suffix_module_group_invalid:{group}")
            continue
        if not isinstance(raw_group, dict) or frozenset(raw_group) != {
            "versions",
            "legacy_surface_id",
        }:
            violations.append(f"no_suffix_module_group_contract_invalid:{group}")
            continue
        group_versions = _versions(
            raw_group.get("versions"),
            field=f"no_suffix_module_groups.{group}.versions",
            violations=violations,
        )
        surface_id = raw_group.get("legacy_surface_id")
        if surface_id not in legacy_ids:
            violations.append(f"no_suffix_module_group_surface_unknown:{group}:{surface_id}")
        elif not set(group_versions).issubset(set(legacy_versions[surface_id])):
            violations.append(f"no_suffix_module_group_versions_uncovered:{group}:{surface_id}")
        registered_no_suffix[group] = group_versions
    for group in sorted(set(discovered_no_suffix) - set(registered_no_suffix)):
        violations.append(f"unregistered_no_suffix_version_group:{group}")
    for group in sorted(set(registered_no_suffix) - set(discovered_no_suffix)):
        violations.append(f"stale_no_suffix_version_group:{group}")
    for group in sorted(set(discovered_no_suffix) & set(registered_no_suffix)):
        if discovered_no_suffix[group] != registered_no_suffix[group]:
            violations.append(
                f"no_suffix_group_versions_changed:{group}:"
                f"expected={registered_no_suffix[group]}:actual={discovered_no_suffix[group]}"
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
        "discovered_no_suffix_group_count": len(discovered_no_suffix),
        "legacy_surface_count": len(legacy_ids),
        "pending_retirement_evidence_count": pending_retirement_evidence_count,
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
        f"{summary['discovered_no_suffix_group_count']} no-suffix groups, "
        f"{summary['legacy_surface_count']} explicit legacy surfaces, "
        f"{summary['pending_retirement_evidence_count']} pending retirement proofs, "
        f"{linked_gate_count} linked {linked_gate_label}, 0 violations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
