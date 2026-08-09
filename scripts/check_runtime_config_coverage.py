"""Validate runtime reads plus canonical definition and evidence contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "governance" / "data_center_architecture_inventory.json"
MANIFEST = ROOT / "governance" / "runtime_config_contracts.json"
CANONICAL_ONLY_STATUS = "canonical_only_fail_closed"


def _validate_locator(
    locator: object,
    *,
    repo_root: Path,
    kind: str,
) -> str | None:
    """Return a stable violation when a governed source locator is invalid."""

    raw_locator = str(locator or "").strip()
    if "::" not in raw_locator:
        return f"{kind}_locator_invalid:{raw_locator or '<empty>'}"
    relative_path, symbol = raw_locator.split("::", 1)
    relative_path = relative_path.strip().replace("\\", "/")
    symbol = symbol.strip()
    if not relative_path or not symbol:
        return f"{kind}_locator_invalid:{raw_locator}"
    path = (repo_root / relative_path).resolve()
    if not path.is_relative_to(repo_root.resolve()) or not path.is_file():
        return f"{kind}_path_missing:{raw_locator}"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return f"{kind}_path_unreadable:{raw_locator}"
    markers = [token for token in symbol.split(".") if token]
    if not markers or any(marker not in source for marker in markers):
        return f"{kind}_symbol_missing:{raw_locator}"
    if kind == "test":
        test_name = markers[-1]
        if not re.search(rf"\b(?:async\s+)?def\s+{re.escape(test_name)}\s*\(", source):
            return f"test_symbol_missing:{raw_locator}"
    return None


def validate_runtime_definition_contracts(
    manifest: dict[str, Any],
    *,
    repo_root: Path = ROOT,
) -> dict[str, int]:
    """Validate canonical runtime definitions and their executable evidence."""

    definitions = manifest.get("definitions")
    if not isinstance(definitions, list):
        raise ValueError("runtime config definitions must be a list")
    violations: list[str] = []
    canonical_count = 0
    materialization_count = 0
    locator_count = 0
    seen_keys: set[str] = set()
    for index, raw_definition in enumerate(definitions):
        if not isinstance(raw_definition, dict):
            violations.append(f"definition_invalid:{index}")
            continue
        config_key = str(raw_definition.get("config_key") or "").strip()
        if not config_key:
            violations.append(f"definition_key_missing:{index}")
            continue
        if config_key in seen_keys:
            violations.append(f"definition_key_duplicate:{config_key}")
        seen_keys.add(config_key)
        if str(raw_definition.get("migration_status") or "") != CANONICAL_ONLY_STATUS:
            continue
        canonical_count += 1
        if str(raw_definition.get("fallback") or "").strip() != "blocked":
            violations.append(f"canonical_fallback_not_blocked:{config_key}")

        materialization_required = raw_definition.get("materialization_required", False)
        if not isinstance(materialization_required, bool):
            violations.append(f"materialization_required_invalid:{config_key}")
        migration_path = str(raw_definition.get("materialization_migration") or "").strip()
        if materialization_required is True:
            materialization_count += 1
            if not migration_path:
                violations.append(f"materialization_migration_missing:{config_key}")
            else:
                migration = (repo_root / migration_path).resolve()
                if (
                    not migration.is_relative_to(repo_root.resolve())
                    or "migrations" not in migration.parts
                    or migration.suffix != ".py"
                    or not migration.is_file()
                ):
                    violations.append(
                        f"materialization_migration_invalid:{config_key}:{migration_path}"
                    )
        elif migration_path:
            migration = (repo_root / migration_path).resolve()
            if not migration.is_relative_to(repo_root.resolve()) or not migration.is_file():
                violations.append(
                    f"materialization_migration_invalid:{config_key}:{migration_path}"
                )

        for kind in ("consumer", "test"):
            field_name = "consumers" if kind == "consumer" else "tests"
            locators = raw_definition.get(field_name)
            if not isinstance(locators, list) or not locators:
                violations.append(f"canonical_{field_name}_missing:{config_key}")
                continue
            for locator in locators:
                locator_count += 1
                violation = _validate_locator(locator, repo_root=repo_root, kind=kind)
                if violation is not None:
                    violations.append(f"{config_key}:{violation}")

    if violations:
        raise ValueError("runtime definition contract mismatch: " + "; ".join(violations))
    return {
        "canonical_definition_count": canonical_count,
        "materialization_required_count": materialization_count,
        "locator_count": locator_count,
    }


def main() -> int:
    """Validate runtime-reference coverage against classification patterns."""

    try:
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"runtime config coverage manifest unreadable: {exc}") from exc
    references = inventory.get("runtime_parameter_references")
    rules = manifest.get("runtime_reference_classification")
    if not isinstance(references, list) or not isinstance(rules, list) or not rules:
        raise SystemExit("runtime config coverage requires references and classification rules")
    compiled: list[tuple[re.Pattern[str], str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise SystemExit("runtime reference classification must contain objects")
        pattern = str(rule.get("pattern") or "")
        classification = str(rule.get("classification") or "").strip()
        owner = str(rule.get("owner") or "").strip()
        if not pattern or not classification or not owner:
            raise SystemExit(
                "runtime reference classification requires pattern/classification/owner"
            )
        try:
            compiled.append((re.compile(pattern), classification))
        except re.error as exc:
            raise SystemExit(f"invalid runtime classification regex {pattern!r}: {exc}") from exc
    uncovered = [
        str(reference)
        for reference in references
        if not any(regex.search(str(reference)) for regex, _classification in compiled)
    ]
    if uncovered:
        raise SystemExit("unclassified runtime parameter references: " + "; ".join(uncovered))
    try:
        definition_report = validate_runtime_definition_contracts(manifest)
    except ValueError as exc:
        raise SystemExit(f"runtime definition contract failed: {exc}") from exc
    print(
        "Runtime config references classified: "
        f"{len(references)} ({sorted({classification for _, classification in compiled})}); "
        f"canonical definitions={definition_report['canonical_definition_count']}; "
        f"materialized={definition_report['materialization_required_count']}; "
        f"locators={definition_report['locator_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
