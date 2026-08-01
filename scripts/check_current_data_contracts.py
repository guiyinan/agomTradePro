"""Validate current-data freshness evidence and reject timestamp laundering."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "governance" / "current_data_contracts.json"
HISTORICAL_NAME_TOKENS = frozenset(
    {
        "bar",
        "latest_bar",
        "historical",
        "historical_bar",
        "close",
        "recent_close",
        "nav",
        "fact",
        "quote",
        "snapshot",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "as_of",
        "trade_date",
        "freshness",
        "is_fallback",
        "observed_at",
    }
)
SOURCE_OBSERVATION_NAMES = frozenset(
    {
        "observed_at",
        "snapshot_at",
        "market_data_as_of",
    }
)


@dataclass(frozen=True)
class CurrentDataContractViolation:
    """One malformed contract or unsafe production timestamp pattern."""

    code: str
    message: str
    path: str = ""
    line: int | None = None


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _is_now_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) in {
        "timezone.now",
        "datetime.now",
    }


def _is_current_clock_call(node: ast.AST) -> bool:
    return _is_now_call(node) or (
        isinstance(node, ast.Call) and _call_name(node.func) == "date.today"
    )


def _none_checked_name(node: ast.AST) -> str | None:
    """Return a source-observation name tested against None."""

    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not isinstance(node.ops[0], (ast.Is, ast.Eq)):
        return None
    left, right = node.left, node.comparators[0]
    if isinstance(left, ast.Name) and isinstance(right, ast.Constant) and right.value is None:
        return left.id
    if isinstance(right, ast.Name) and isinstance(left, ast.Constant) and left.value is None:
        return right.id
    return None


def _expression_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _looks_historical(names: set[str]) -> bool:
    for name in names:
        normalized = name.lower()
        if normalized in HISTORICAL_NAME_TOKENS:
            return True
        if normalized.endswith(("_bar", "_close", "_nav", "_fact")):
            return True
    return False


def find_timestamp_laundering(
    tree: ast.AST,
    *,
    relative_path: str,
) -> list[CurrentDataContractViolation]:
    """Find request-time timestamps attached to historical observations."""

    violations: list[CurrentDataContractViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            checked_name = _none_checked_name(node.test)
            if checked_name in SOURCE_OBSERVATION_NAMES:
                for child in node.body:
                    if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                        continue
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    value = child.value
                    if value is None or not _is_current_clock_call(value):
                        continue
                    if any(
                        isinstance(target, ast.Name) and target.id == checked_name
                        for target in targets
                    ):
                        violations.append(
                            CurrentDataContractViolation(
                                "missing_observation_timestamp_laundering",
                                "missing source observation cannot be replaced with current time",
                                relative_path,
                                child.lineno,
                            )
                        )

        if isinstance(node, ast.Call) and _call_name(node.func).endswith("RealtimePrice"):
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            timestamp = keywords.get("timestamp")
            if timestamp is None or not _is_now_call(timestamp):
                continue
            provenance_names: set[str] = set()
            for key, value in keywords.items():
                if key != "timestamp":
                    provenance_names.update(_expression_names(value))
            if _looks_historical(provenance_names):
                violations.append(
                    CurrentDataContractViolation(
                        "historical_timestamp_laundering",
                        "RealtimePrice built from historical data cannot use request time",
                        relative_path,
                        node.lineno,
                    )
                )

        if isinstance(node, ast.Call) and _call_name(node.func).endswith("QuoteSnapshot"):
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            snapshot_at = keywords.get("snapshot_at")
            if snapshot_at is not None and _is_now_call(snapshot_at):
                violations.append(
                    CurrentDataContractViolation(
                        "quote_snapshot_timestamp_laundering",
                        "quote snapshot_at must preserve a source observation timestamp",
                        relative_path,
                        node.lineno,
                    )
                )

        if isinstance(node, ast.Dict):
            entries = {
                key.value: value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            timestamp = entries.get("timestamp")
            if timestamp is None or not _is_now_call(timestamp):
                continue
            if PROVENANCE_KEYS.intersection(entries):
                violations.append(
                    CurrentDataContractViolation(
                        "metadata_timestamp_laundering",
                        "metadata with source provenance cannot replace observation time with now",
                        relative_path,
                        node.lineno,
                    )
                )
    return violations


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _scan_production_timestamp_laundering(
    project_root: Path,
) -> list[CurrentDataContractViolation]:
    violations: list[CurrentDataContractViolation] = []
    apps_root = project_root / "apps"
    if not apps_root.is_dir():
        return [
            CurrentDataContractViolation(
                "apps_root_missing",
                "apps directory does not exist",
                "apps",
            )
        ]
    source_roots = [
        apps_root,
        project_root / "sdk" / "agomtradepro",
        project_root / "sdk" / "agomtradepro_mcp",
    ]
    source_paths = sorted(
        path
        for source_root in source_roots
        if source_root.is_dir()
        for path in source_root.rglob("*.py")
    )
    for path in source_paths:
        relative = path.relative_to(project_root).as_posix()
        if "/migrations/" in f"/{relative}/" or "/tests/" in f"/{relative}/":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as exc:
            violations.append(
                CurrentDataContractViolation(
                    "source_syntax_error",
                    str(exc),
                    relative,
                    exc.lineno,
                )
            )
            continue
        violations.extend(find_timestamp_laundering(tree, relative_path=relative))
    return violations


def _validate_contract(
    raw_contract: object,
    *,
    index: int,
    project_root: Path,
) -> tuple[str, list[CurrentDataContractViolation]]:
    fallback_id = f"contract:{index + 1:03d}"
    if not isinstance(raw_contract, Mapping):
        return fallback_id, [
            CurrentDataContractViolation("contract_invalid", "contract must be an object")
        ]
    contract_id = str(raw_contract.get("id") or fallback_id).strip()
    violations: list[CurrentDataContractViolation] = []
    source_files = raw_contract.get("source_files")
    if (
        not isinstance(source_files, list)
        or not source_files
        or not all(_is_non_empty_string(item) for item in source_files)
    ):
        violations.append(
            CurrentDataContractViolation(
                "source_files_invalid",
                f"{contract_id}: source_files must be a non-empty string list",
            )
        )
        source_files = []
    normalized_sources = {str(item) for item in source_files}
    for relative in normalized_sources:
        if not (project_root / relative).is_file():
            violations.append(
                CurrentDataContractViolation(
                    "source_file_missing",
                    f"{contract_id}: source file does not exist",
                    relative,
                )
            )

    markers = raw_contract.get("required_markers")
    if not isinstance(markers, Mapping) or not markers:
        violations.append(
            CurrentDataContractViolation(
                "required_markers_invalid",
                f"{contract_id}: required_markers must be a non-empty object",
            )
        )
    else:
        for raw_path, raw_markers in markers.items():
            relative = str(raw_path)
            if relative not in normalized_sources:
                violations.append(
                    CurrentDataContractViolation(
                        "marker_source_unregistered",
                        f"{contract_id}: marker source is not in source_files",
                        relative,
                    )
                )
                continue
            if (
                not isinstance(raw_markers, list)
                or not raw_markers
                or not all(_is_non_empty_string(item) for item in raw_markers)
            ):
                violations.append(
                    CurrentDataContractViolation(
                        "required_marker_invalid",
                        f"{contract_id}: markers must be a non-empty string list",
                        relative,
                    )
                )
                continue
            source_path = project_root / relative
            if not source_path.is_file():
                continue
            content = source_path.read_text(encoding="utf-8")
            for marker in raw_markers:
                if str(marker) not in content:
                    violations.append(
                        CurrentDataContractViolation(
                            "required_marker_missing",
                            f"{contract_id}: required marker is missing: {marker}",
                            relative,
                        )
                    )

    required_tests = raw_contract.get("required_tests")
    if not isinstance(required_tests, list) or not required_tests:
        violations.append(
            CurrentDataContractViolation(
                "required_tests_invalid",
                f"{contract_id}: required_tests must be a non-empty list",
            )
        )
    else:
        seen_cases: set[str] = set()
        for raw_test in required_tests:
            if not isinstance(raw_test, Mapping):
                violations.append(
                    CurrentDataContractViolation(
                        "required_test_invalid",
                        f"{contract_id}: test evidence must be an object",
                    )
                )
                continue
            case = str(raw_test.get("case") or "").strip()
            test_file = str(raw_test.get("test_file") or "").strip()
            test_function = str(raw_test.get("test_function") or "").strip()
            if not case or case in seen_cases:
                violations.append(
                    CurrentDataContractViolation(
                        "test_case_invalid",
                        f"{contract_id}: test case is empty or duplicated: {case}",
                        test_file,
                    )
                )
            seen_cases.add(case)
            path = project_root / test_file
            if not path.is_file():
                violations.append(
                    CurrentDataContractViolation(
                        "test_file_missing",
                        f"{contract_id}: test file does not exist",
                        test_file,
                    )
                )
                continue
            if not test_function or test_function not in _function_names(path):
                violations.append(
                    CurrentDataContractViolation(
                        "test_function_missing",
                        f"{contract_id}: test function not found: {test_function}",
                        test_file,
                    )
                )
    return contract_id, violations


def validate_current_data_contracts(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> list[CurrentDataContractViolation]:
    """Validate manifest evidence and scan production for timestamp laundering."""

    try:
        payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [CurrentDataContractViolation("manifest_unreadable", str(exc), str(manifest_path))]
    if not isinstance(payload, Mapping):
        return [CurrentDataContractViolation("manifest_invalid", "manifest must be an object")]

    violations: list[CurrentDataContractViolation] = []
    if payload.get("schema_version") != 1:
        violations.append(
            CurrentDataContractViolation("schema_version_invalid", "schema_version must equal 1")
        )
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        violations.append(
            CurrentDataContractViolation("contracts_invalid", "contracts must be a non-empty list")
        )
        return violations

    seen_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        contract_id, contract_violations = _validate_contract(
            contract,
            index=index,
            project_root=repo_root,
        )
        if contract_id in seen_ids:
            violations.append(
                CurrentDataContractViolation(
                    "contract_id_duplicate",
                    f"duplicate contract id: {contract_id}",
                )
            )
        seen_ids.add(contract_id)
        violations.extend(contract_violations)
    violations.extend(_scan_production_timestamp_laundering(repo_root))
    return violations


def main() -> int:
    """Run the current-data contract guard."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()
    violations = validate_current_data_contracts(args.manifest)
    if violations:
        for item in violations:
            location = item.path
            if item.line is not None:
                location = f"{location}:{item.line}"
            prefix = f"{location}: " if location else ""
            print(f"{prefix}{item.code}: {item.message}")
        print(f"Current-data freshness contracts failed: {len(violations)} violation(s)")
        return 1

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(f"Current-data freshness contracts OK: {len(payload['contracts'])} surface(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
