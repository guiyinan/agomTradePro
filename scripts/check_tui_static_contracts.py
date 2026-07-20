"""Validate declarative source contracts for the TUI workbench assets."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = (
    PROJECT_ROOT / "config" / "tui" / "contracts" / "tui_static_source_contracts.json"
)
SUPPORTED_RELATIONS = frozenset({"contains", "not_contains"})


@dataclass(frozen=True)
class TuiStaticContractViolation:
    """Describe one failed or malformed static source rule."""

    rule_id: str
    message: str


def load_contract_payload(path: Path = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    """Load the versioned TUI static contract payload."""

    return json.loads(path.read_text(encoding="utf-8"))


def load_contract_sources(
    payload: Mapping[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict[str, str], list[TuiStaticContractViolation]]:
    """Load and concatenate every source declared by the contract payload."""

    sources: dict[str, str] = {}
    violations: list[TuiStaticContractViolation] = []
    source_specs = payload.get("sources")
    if not isinstance(source_specs, Mapping):
        return {}, [TuiStaticContractViolation("contract:sources", "sources must be an object")]

    for source_key, source_spec in source_specs.items():
        rule_id = f"source:{source_key}"
        if not isinstance(source_key, str) or not source_key.strip():
            violations.append(TuiStaticContractViolation(rule_id, "source key is empty"))
            continue
        if not isinstance(source_spec, Mapping):
            violations.append(TuiStaticContractViolation(rule_id, "source spec must be an object"))
            continue
        paths = source_spec.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(item, str) for item in paths)
        ):
            violations.append(
                TuiStaticContractViolation(rule_id, "paths must be a non-empty string list")
            )
            continue

        contents: list[str] = []
        for relative_path in paths:
            source_path = project_root / relative_path
            if not source_path.is_file():
                violations.append(
                    TuiStaticContractViolation(
                        rule_id,
                        f"source file does not exist: {relative_path}",
                    )
                )
                continue
            contents.append(source_path.read_text(encoding="utf-8"))
        sources[source_key] = "\n\n".join(contents)
    return sources, violations


def evaluate_contract_rules(
    sources: Mapping[str, str],
    rules: Sequence[Mapping[str, Any]],
) -> list[TuiStaticContractViolation]:
    """Evaluate required and forbidden string rules against loaded sources."""

    violations: list[TuiStaticContractViolation] = []
    seen_rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        fallback_id = f"rule:{index + 1:03d}"
        if not isinstance(rule, Mapping):
            violations.append(TuiStaticContractViolation(fallback_id, "rule must be an object"))
            continue

        rule_id = str(rule.get("id") or fallback_id).strip()
        source_key = str(rule.get("source") or "").strip()
        relation = str(rule.get("relation") or "").strip()
        value = rule.get("value")
        if rule_id in seen_rule_ids:
            violations.append(TuiStaticContractViolation(rule_id, "duplicate rule id"))
            continue
        seen_rule_ids.add(rule_id)
        if source_key not in sources:
            violations.append(
                TuiStaticContractViolation(rule_id, f"unknown source: {source_key or '<empty>'}")
            )
            continue
        if relation not in SUPPORTED_RELATIONS:
            violations.append(
                TuiStaticContractViolation(
                    rule_id, f"unsupported relation: {relation or '<empty>'}"
                )
            )
            continue
        if not isinstance(value, str) or not value:
            violations.append(
                TuiStaticContractViolation(rule_id, "value must be a non-empty string")
            )
            continue

        present = value in sources[source_key]
        if relation == "contains" and not present:
            violations.append(TuiStaticContractViolation(rule_id, "required text is missing"))
        elif relation == "not_contains" and present:
            violations.append(TuiStaticContractViolation(rule_id, "forbidden text is present"))
    return violations


def check_tui_static_contracts(
    path: Path = DEFAULT_CONTRACT_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[TuiStaticContractViolation]:
    """Load and validate the complete TUI static source contract."""

    payload = load_contract_payload(path)
    sources, violations = load_contract_sources(payload, project_root=project_root)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return [*violations, TuiStaticContractViolation("contract:rules", "rules must be a list")]
    return [*violations, *evaluate_contract_rules(sources, rules)]


def main() -> int:
    """Run the TUI static contract check as a command-line guard."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    args = parser.parse_args()
    violations = check_tui_static_contracts(args.contract)
    if violations:
        for violation in violations:
            print(f"{violation.rule_id}: {violation.message}")
        print(f"TUI static source contracts failed: {len(violations)} violation(s)")
        return 1

    payload = load_contract_payload(args.contract)
    print(
        "TUI static source contracts OK: "
        f"{len(payload.get('rules', []))} rule(s), {len(payload.get('sources', {}))} source(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
