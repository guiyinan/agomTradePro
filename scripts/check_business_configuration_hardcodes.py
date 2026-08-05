#!/usr/bin/env python
"""Reject mutable business configuration embedded in production Python code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST: Final = REPO_ROOT / "governance" / "business_configuration_contracts.json"

MUTABLE_CLASSIFICATION: Final = "mutable_business_configuration"
REQUIRED_CLASSIFICATIONS: Final = frozenset(
    {
        MUTABLE_CLASSIFICATION,
        "domain_invariant",
        "schema_or_protocol_constant",
        "test_fixture",
    }
)
RULE_HISTORICAL_SCENARIO_CATALOG: Final = "historical_scenario_catalog"
RULE_ALLOCATION_MATRIX: Final = "allocation_policy_matrix"
RULE_POLICY_MULTIPLIER: Final = "policy_adjustment_multiplier"
RULE_DECISION_THRESHOLD: Final = "decision_recommendation_threshold"
RULE_DEFAULT_PRINCIPAL: Final = "default_portfolio_principal"
RULE_STATIC_FALLBACK: Final = "static_business_configuration_fallback"
KNOWN_RULES: Final = frozenset(
    {
        RULE_HISTORICAL_SCENARIO_CATALOG,
        RULE_ALLOCATION_MATRIX,
        RULE_POLICY_MULTIPLIER,
        RULE_DECISION_THRESHOLD,
        RULE_DEFAULT_PRINCIPAL,
        RULE_STATIC_FALLBACK,
    }
)

BUSINESS_CONFIGURATION_NAME_TOKENS: Final = frozenset(
    {
        "allocation",
        "catalog",
        "config",
        "matrix",
        "policy",
        "scenario",
        "threshold",
        "universe",
        "weight",
    }
)
REPOSITORY_CALL_TOKENS: Final = frozenset(
    {
        "active",
        "config",
        "load",
        "list",
        "policy",
        "provider",
        "repo",
        "repository",
        "scenario",
    }
)
RECOMMENDATION_FUNCTION_TOKENS: Final = frozenset(
    {"advice", "recommendation", "recommend", "suggestion", "suggest"}
)
DECISION_METRIC_TOKENS: Final = frozenset(
    {
        "drawdown",
        "loss",
        "max_drawdown",
        "position",
        "total_return",
        "volatility",
        "weight",
    }
)
PRINCIPAL_TARGETS: Final = frozenset(
    {
        "default_principal",
        "initial_capital",
        "initial_value",
        "portfolio_principal",
    }
)


@dataclass(frozen=True)
class BusinessConfigurationFinding:
    """One AST finding representing mutable production business configuration."""

    rule_id: str
    classification: str
    path: str
    line: int
    symbol: str
    message: str
    ast_fingerprint: str

    @property
    def exception_key(self) -> tuple[str, str, str, str]:
        """Return the exact key required by a temporary migration exception."""

        return (self.rule_id, self.path, self.symbol, self.ast_fingerprint)


@dataclass(frozen=True)
class GuardViolation:
    """One manifest, source, or unapproved hard-code violation."""

    code: str
    message: str
    path: str = ""
    line: int | None = None


@dataclass(frozen=True)
class BusinessConfigurationGuardReport:
    """Full-scan result, including exact time-bound migration exceptions."""

    scanned_files: int
    findings: tuple[BusinessConfigurationFinding, ...]
    accepted_findings: tuple[BusinessConfigurationFinding, ...]
    violations: tuple[GuardViolation, ...]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _normalized_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _tokens_match(tokens: Iterable[str], candidates: Iterable[str]) -> bool:
    """Match singular/plural and descriptive suffixes without broad substring scans."""

    return any(
        token == candidate or token.startswith(candidate)
        for token in tokens
        for candidate in candidates
    )


def _numeric_literal(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = _numeric_literal(node.operand)
        if value is None:
            return None
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call) and _call_name(node.func).split(".")[-1] == "Decimal":
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
            return None
        try:
            return float(node.args[0].value)
        except (TypeError, ValueError):
            return None
    return None


def _fingerprint(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dict_string_keys(node: ast.Dict) -> set[str]:
    return {
        str(key.value)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _is_date_constructor(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if _call_name(node.func).split(".")[-1] not in {"date", "datetime"}:
        return False
    return len(node.args) >= 3 and all(_numeric_literal(item) is not None for item in node.args[:3])


def _has_historical_window(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        keyword_names = {item.arg for item in child.keywords if item.arg}
        if {"start_date", "end_date"}.issubset(keyword_names):
            return True
    if isinstance(node, ast.Dict):
        keys = _dict_string_keys(node)
        if {"start_date", "end_date"}.issubset(keys):
            return True
    return False


def _historical_window_count(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            keyword_names = {item.arg for item in child.keywords if item.arg}
            if {"start_date", "end_date"}.issubset(keyword_names):
                count += 1
        elif isinstance(child, ast.Dict):
            keys = _dict_string_keys(child)
            if {"start_date", "end_date"}.issubset(keys):
                count += 1
    return count


def _is_historical_scenario_catalog(target: str, value: ast.AST) -> bool:
    if not isinstance(value, ast.Dict | ast.List | ast.Tuple):
        return False
    if not _tokens_match(_normalized_tokens(target), {"scenario"}):
        return False
    if _historical_window_count(value) < 2:
        return False
    return sum(1 for item in ast.walk(value) if _is_date_constructor(item)) >= 2 or any(
        _has_historical_window(item) for item in ast.iter_child_nodes(value)
    )


def _allocation_call_count(node: ast.AST) -> int:
    required = {"cash", "commodity", "equity", "fixed_income"}
    count = 0
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        keyword_names = {item.arg for item in child.keywords if item.arg}
        if required.issubset(keyword_names):
            count += 1
    return count


def _is_four_by_four_allocation_matrix(value: ast.AST) -> bool:
    if not isinstance(value, ast.Dict) or len(value.values) < 4:
        return False
    nested_rows = [item for item in value.values if isinstance(item, ast.Dict)]
    return (
        len(nested_rows) >= 4
        and all(len(row.values) >= 4 for row in nested_rows[:4])
        and _allocation_call_count(value) >= 16
    )


def _policy_key(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr.upper()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.upper()
    return ""


def _is_policy_multiplier_catalog(target: str, value: ast.AST) -> bool:
    if not isinstance(value, ast.Dict) or len(value.values) < 2:
        return False
    target_tokens = _normalized_tokens(target)
    keys = [_policy_key(item) for item in value.keys]
    if not all(re.fullmatch(r"P\d+", item) for item in keys):
        return False
    numbers = [_numeric_literal(item) for item in value.values]
    if any(item is None for item in numbers):
        return False
    normalized_numbers = [float(item) for item in numbers if item is not None]
    if len(set(normalized_numbers)) < 2 or not all(0 <= item <= 2 for item in normalized_numbers):
        return False
    return bool(
        {"policy", "multiplier", "adjustment", "factor", "equity"}.intersection(target_tokens)
    )


def _assignment_parts(node: ast.Assign | ast.AnnAssign) -> tuple[list[ast.AST], ast.AST | None]:
    if isinstance(node, ast.Assign):
        return list(node.targets), node.value
    return [node.target], node.value


def _looks_like_business_config_name(name: str) -> bool:
    return _tokens_match(_normalized_tokens(name), BUSINESS_CONFIGURATION_NAME_TOKENS)


def _collect_static_configuration_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()

    def collect_from_body(body: Sequence[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                collect_from_body(node.body)
                continue
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            targets, value = _assignment_parts(node)
            if value is None or not isinstance(value, ast.Dict | ast.List | ast.Tuple | ast.Set):
                continue
            for target_node in targets:
                name = _target_name(target_node)
                if name and _looks_like_business_config_name(name):
                    names.add(name)

    if isinstance(tree, ast.Module):
        collect_from_body(tree.body)
    return names


def _has_repository_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        call_tokens = _normalized_tokens(_call_name(child.func))
        if call_tokens.intersection(REPOSITORY_CALL_TOKENS) and (
            {"repo", "repository", "provider"}.intersection(call_tokens)
            or {"active", "config", "list", "load", "policy", "scenario"}.intersection(call_tokens)
        ):
            return True
    return False


def _is_static_business_expression(node: ast.AST, static_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        upper = node.id.upper()
        return node.id in static_names or (
            upper.startswith(
                ("BUILTIN_", "DEFAULT_", "FALLBACK_", "HARDCODED_", "LEGACY_", "STATIC_")
            )
            and _looks_like_business_config_name(node.id)
        )
    if isinstance(node, ast.Attribute):
        upper = node.attr.upper()
        return node.attr in static_names or (
            upper.startswith(
                ("BUILTIN_", "DEFAULT_", "FALLBACK_", "HARDCODED_", "LEGACY_", "STATIC_")
            )
            and _looks_like_business_config_name(node.attr)
        )
    if isinstance(node, ast.Dict | ast.List | ast.Tuple | ast.Set):
        if not list(ast.iter_child_nodes(node)):
            return False
        return (
            _has_historical_window(node)
            or _is_four_by_four_allocation_matrix(node)
            or _is_policy_multiplier_catalog("policy_multiplier", node)
        )
    return False


def _static_fallback_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    static_names: set[str],
) -> list[ast.AST]:
    findings: list[ast.AST] = []
    function_has_repository_call = _has_repository_call(function)
    for node in ast.walk(function):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if (
                len(node.values) >= 2
                and _has_repository_call(node.values[0])
                and any(
                    _is_static_business_expression(item, static_names) for item in node.values[1:]
                )
            ):
                findings.append(node)
        elif isinstance(node, ast.If) and function_has_repository_call:
            branch_nodes: Iterable[ast.AST] = (*node.body, *node.orelse)
            for branch_node in branch_nodes:
                if isinstance(branch_node, ast.Return) and branch_node.value is not None:
                    if _is_static_business_expression(branch_node.value, static_names):
                        findings.append(branch_node)
                elif isinstance(branch_node, ast.Assign | ast.AnnAssign):
                    _targets, value = _assignment_parts(branch_node)
                    if value is not None and _is_static_business_expression(value, static_names):
                        findings.append(branch_node)
        elif isinstance(node, ast.Try):
            if not _has_repository_call(ast.Module(body=node.body, type_ignores=[])):
                continue
            for handler in node.handlers:
                for handler_node in handler.body:
                    if isinstance(handler_node, ast.Return) and handler_node.value is not None:
                        if _is_static_business_expression(handler_node.value, static_names):
                            findings.append(handler_node)
    unique: dict[tuple[int, int], ast.AST] = {}
    for node in findings:
        unique[(node.lineno, node.col_offset)] = node
    return list(unique.values())


def _recommendation_thresholds(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Compare]:
    function_tokens = _normalized_tokens(function.name)
    if not _tokens_match(function_tokens, RECOMMENDATION_FUNCTION_TOKENS):
        return []
    matches: list[ast.Compare] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        expression_names = {
            item.id.lower() for item in ast.walk(node) if isinstance(item, ast.Name)
        }
        if not any(token in name for name in expression_names for token in DECISION_METRIC_TOKENS):
            continue
        literals = [
            value
            for value in (_numeric_literal(item) for item in node.comparators)
            if value is not None
        ]
        if any(value not in {0.0, 1.0, -1.0} for value in literals):
            matches.append(node)
    return matches


class _BusinessConfigurationVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str, static_names: set[str]) -> None:
        self.relative_path = relative_path
        self.static_names = static_names
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.findings: list[BusinessConfigurationFinding] = []

    def _symbol(self, leaf: str) -> str:
        return ".".join((*self.class_stack, *self.function_stack, leaf))

    def _append(self, *, rule_id: str, node: ast.AST, symbol: str, message: str) -> None:
        self.findings.append(
            BusinessConfigurationFinding(
                rule_id=rule_id,
                classification=MUTABLE_CLASSIFICATION,
                path=self.relative_path,
                line=node.lineno,
                symbol=symbol,
                message=message,
                ast_fingerprint=_fingerprint(node),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        threshold_nodes = _recommendation_thresholds(node)
        if threshold_nodes:
            rendered = ", ".join(str(item.lineno) for item in threshold_nodes)
            self._append(
                rule_id=RULE_DECISION_THRESHOLD,
                node=node,
                symbol=self._symbol("thresholds"),
                message=f"decision recommendation thresholds are embedded on lines {rendered}",
            )
        for fallback in _static_fallback_nodes(node, self.static_names):
            self._append(
                rule_id=RULE_STATIC_FALLBACK,
                node=fallback,
                symbol=self._symbol("fallback"),
                message="repository/provider failure falls back to static business configuration",
            )
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_assignment(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets, value = _assignment_parts(node)
        if value is not None:
            for target_node in targets:
                target = _target_name(target_node)
                if not target:
                    continue
                symbol = self._symbol(target)
                if _is_historical_scenario_catalog(target, value):
                    self._append(
                        rule_id=RULE_HISTORICAL_SCENARIO_CATALOG,
                        node=node,
                        symbol=symbol,
                        message="historical scenario windows form a static runtime catalog",
                    )
                if _is_four_by_four_allocation_matrix(value):
                    self._append(
                        rule_id=RULE_ALLOCATION_MATRIX,
                        node=node,
                        symbol=symbol,
                        message=(
                            "4x4 asset weights and expected metrics form a static allocation policy"
                        ),
                    )
                if _is_policy_multiplier_catalog(target, value):
                    self._append(
                        rule_id=RULE_POLICY_MULTIPLIER,
                        node=node,
                        symbol=symbol,
                        message="Policy levels map to static allocation adjustment multipliers",
                    )
                principal = _numeric_literal(value)
                context = " ".join((self.relative_path, *self.class_stack, *self.function_stack))
                if (
                    target.lower() in PRINCIPAL_TARGETS
                    and principal is not None
                    and abs(principal) >= 1_000
                    and {"scenario", "stress"}.intersection(_normalized_tokens(context))
                ):
                    self._append(
                        rule_id=RULE_DEFAULT_PRINCIPAL,
                        node=node,
                        symbol=symbol,
                        message="stress-test portfolio principal is a production literal",
                    )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._visit_assignment(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_assignment(node)


def scan_source(source: str, *, relative_path: str) -> list[BusinessConfigurationFinding]:
    """Parse and classify mutable business configuration in one Python source."""

    tree = ast.parse(source, filename=relative_path)
    visitor = _BusinessConfigurationVisitor(
        relative_path=relative_path,
        static_names=_collect_static_configuration_names(tree),
    )
    visitor.visit(tree)
    unique: dict[tuple[str, str, str, str], BusinessConfigurationFinding] = {}
    for finding in visitor.findings:
        unique[finding.exception_key] = finding
    return sorted(
        unique.values(), key=lambda item: (item.path, item.line, item.rule_id, item.symbol)
    )


def _load_manifest(path: Path) -> tuple[Mapping[str, object] | None, list[GuardViolation]]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [GuardViolation("manifest_unreadable", str(exc), str(path))]
    if not isinstance(payload, Mapping):
        return None, [
            GuardViolation("manifest_invalid", "manifest root must be an object", str(path))
        ]
    return payload, []


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object) -> list[str] | None:
    if (
        not isinstance(value, list)
        or not value
        or not all(_non_empty_string(item) for item in value)
    ):
        return None
    return [str(item) for item in value]


def _validate_manifest(payload: Mapping[str, object]) -> list[GuardViolation]:
    violations: list[GuardViolation] = []
    if payload.get("schema_version") != 1:
        violations.append(GuardViolation("schema_version_invalid", "schema_version must equal 1"))

    classifications = payload.get("classifications")
    if not isinstance(classifications, Mapping):
        violations.append(
            GuardViolation("classifications_invalid", "classifications must be an object")
        )
    else:
        missing = sorted(REQUIRED_CLASSIFICATIONS - {str(item) for item in classifications})
        if missing:
            violations.append(
                GuardViolation(
                    "classification_missing",
                    f"required classifications are missing: {', '.join(missing)}",
                )
            )

    scan = payload.get("scan")
    if not isinstance(scan, Mapping):
        violations.append(GuardViolation("scan_invalid", "scan must be an object"))
    else:
        roots = _string_list(scan.get("roots"))
        patterns = _string_list(scan.get("include_patterns"))
        excluded = _string_list(scan.get("excluded_segments"))
        if roots is None:
            violations.append(GuardViolation("scan_roots_invalid", "scan.roots is invalid"))
        if patterns is None:
            violations.append(
                GuardViolation("scan_patterns_invalid", "scan.include_patterns is invalid")
            )
        if excluded is None:
            violations.append(
                GuardViolation("scan_exclusions_invalid", "scan.excluded_segments is invalid")
            )
        if scan.get("authoritative_mode") != "full":
            violations.append(
                GuardViolation(
                    "authoritative_mode_invalid",
                    "scan.authoritative_mode must be full; delta cannot authorize the gate",
                )
            )

    contracts = payload.get("contracts")
    covered_rules: set[str] = set()
    seen_ids: set[str] = set()
    required_contract_fields = (
        "canonical_owner",
        "classification",
        "initialization",
        "migration_status",
        "persistence",
        "read_port",
        "version_policy",
    )
    if not isinstance(contracts, list) or not contracts:
        violations.append(GuardViolation("contracts_invalid", "contracts must be a non-empty list"))
    else:
        for index, raw_contract in enumerate(contracts):
            label = f"contracts[{index}]"
            if not isinstance(raw_contract, Mapping):
                violations.append(GuardViolation("contract_invalid", f"{label} must be an object"))
                continue
            contract_id = raw_contract.get("id")
            if not _non_empty_string(contract_id) or str(contract_id) in seen_ids:
                violations.append(
                    GuardViolation("contract_id_invalid", f"{label}.id is missing or duplicated")
                )
            else:
                seen_ids.add(str(contract_id))
            for field in required_contract_fields:
                if not _non_empty_string(raw_contract.get(field)):
                    violations.append(
                        GuardViolation("contract_field_invalid", f"{label}.{field} is required")
                    )
            if raw_contract.get("classification") != MUTABLE_CLASSIFICATION:
                violations.append(
                    GuardViolation(
                        "contract_classification_invalid",
                        f"{label}.classification must be {MUTABLE_CLASSIFICATION}",
                    )
                )
            if raw_contract.get("runtime_fallback_policy") != "forbidden":
                violations.append(
                    GuardViolation(
                        "fallback_policy_invalid",
                        f"{label}.runtime_fallback_policy must be forbidden",
                    )
                )
            rules = _string_list(raw_contract.get("covered_rules"))
            if rules is None:
                violations.append(
                    GuardViolation("covered_rules_invalid", f"{label}.covered_rules is invalid")
                )
            else:
                unknown = sorted(set(rules) - KNOWN_RULES)
                if unknown:
                    violations.append(
                        GuardViolation(
                            "covered_rule_unknown",
                            f"{label} contains unknown rules: {', '.join(unknown)}",
                        )
                    )
                covered_rules.update(rules)
    missing_rules = sorted(KNOWN_RULES - covered_rules)
    if missing_rules:
        violations.append(
            GuardViolation(
                "rule_contract_missing",
                f"guard rules lack a business contract: {', '.join(missing_rules)}",
            )
        )

    invariants = payload.get("allowed_invariants")
    if not isinstance(invariants, list) or not invariants:
        violations.append(
            GuardViolation("allowed_invariants_invalid", "allowed_invariants must be non-empty")
        )
    else:
        for index, raw_invariant in enumerate(invariants):
            label = f"allowed_invariants[{index}]"
            if not isinstance(raw_invariant, Mapping):
                violations.append(GuardViolation("invariant_invalid", f"{label} must be an object"))
                continue
            classification = raw_invariant.get("classification")
            if classification not in {"domain_invariant", "schema_or_protocol_constant"}:
                violations.append(
                    GuardViolation(
                        "invariant_classification_invalid",
                        f"{label} has an unsupported classification",
                    )
                )
            for field in ("id", "matcher", "owner", "rationale"):
                if not _non_empty_string(raw_invariant.get(field)):
                    violations.append(
                        GuardViolation("invariant_field_invalid", f"{label}.{field} is required")
                    )
    return violations


def _source_paths(
    payload: Mapping[str, object],
    *,
    repo_root: Path,
) -> tuple[list[Path], list[GuardViolation]]:
    scan = payload.get("scan")
    if not isinstance(scan, Mapping):
        return [], []
    roots = _string_list(scan.get("roots")) or []
    patterns = _string_list(scan.get("include_patterns")) or []
    excluded = set(_string_list(scan.get("excluded_segments")) or [])
    paths: set[Path] = set()
    violations: list[GuardViolation] = []
    for relative_root in roots:
        root = repo_root / relative_root
        if not root.is_dir():
            violations.append(
                GuardViolation(
                    "scan_root_missing", "configured scan root does not exist", relative_root
                )
            )
            continue
        for path in root.rglob("*.py"):
            relative = path.relative_to(repo_root).as_posix()
            if excluded.intersection(path.relative_to(repo_root).parts):
                continue
            if any(fnmatch(relative, pattern) for pattern in patterns):
                paths.add(path)
    return sorted(paths), violations


def _exception_records(
    payload: Mapping[str, object],
    *,
    as_of: date,
) -> tuple[dict[tuple[str, str, str, str], Mapping[str, object]], list[GuardViolation]]:
    raw_exceptions = payload.get("temporary_exceptions")
    if not isinstance(raw_exceptions, list):
        return {}, [
            GuardViolation("temporary_exceptions_invalid", "temporary_exceptions must be a list")
        ]
    records: dict[tuple[str, str, str, str], Mapping[str, object]] = {}
    violations: list[GuardViolation] = []
    required = (
        "ast_fingerprint",
        "expires_on",
        "owner",
        "path",
        "reason",
        "replacement_plan",
        "rule_id",
        "symbol",
    )
    for index, raw_exception in enumerate(raw_exceptions):
        label = f"temporary_exceptions[{index}]"
        if not isinstance(raw_exception, Mapping):
            violations.append(GuardViolation("exception_invalid", f"{label} must be an object"))
            continue
        missing = [field for field in required if not _non_empty_string(raw_exception.get(field))]
        if missing:
            violations.append(
                GuardViolation(
                    "exception_field_invalid",
                    f"{label} is missing: {', '.join(missing)}",
                )
            )
            continue
        rule_id = str(raw_exception["rule_id"])
        if rule_id not in KNOWN_RULES:
            violations.append(
                GuardViolation("exception_rule_unknown", f"{label} has unknown rule {rule_id}")
            )
        try:
            expires_on = date.fromisoformat(str(raw_exception["expires_on"]))
        except ValueError:
            violations.append(
                GuardViolation("exception_expiry_invalid", f"{label}.expires_on is not ISO date")
            )
            continue
        if expires_on < as_of:
            violations.append(
                GuardViolation(
                    "exception_expired",
                    f"{label} expired on {expires_on.isoformat()}",
                    str(raw_exception["path"]),
                )
            )
        fingerprint = str(raw_exception["ast_fingerprint"])
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            violations.append(
                GuardViolation(
                    "exception_fingerprint_invalid",
                    f"{label}.ast_fingerprint must be SHA-256 hex",
                )
            )
            continue
        key = (
            rule_id,
            str(raw_exception["path"]),
            str(raw_exception["symbol"]),
            fingerprint,
        )
        if key in records:
            violations.append(
                GuardViolation("exception_duplicate", f"{label} duplicates an earlier exception")
            )
        records[key] = raw_exception
    return records, violations


def evaluate_business_configuration_guard(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    repo_root: Path = REPO_ROOT,
    as_of: date | None = None,
) -> BusinessConfigurationGuardReport:
    """Run the authoritative full scan and apply only exact, expiring exceptions."""

    payload, violations = _load_manifest(manifest_path)
    if payload is None:
        return BusinessConfigurationGuardReport(0, (), (), tuple(violations))
    violations.extend(_validate_manifest(payload))
    paths, path_violations = _source_paths(payload, repo_root=repo_root)
    violations.extend(path_violations)

    findings: list[BusinessConfigurationFinding] = []
    for path in paths:
        relative = path.relative_to(repo_root).as_posix()
        try:
            findings.extend(scan_source(path.read_text(encoding="utf-8"), relative_path=relative))
        except (OSError, UnicodeError, SyntaxError) as exc:
            line = exc.lineno if isinstance(exc, SyntaxError) else None
            violations.append(GuardViolation("source_unreadable", str(exc), relative, line))

    exceptions, exception_violations = _exception_records(
        payload,
        as_of=as_of or date.today(),
    )
    violations.extend(exception_violations)
    accepted: list[BusinessConfigurationFinding] = []
    matched_exception_keys: set[tuple[str, str, str, str]] = set()
    for finding in findings:
        if finding.exception_key in exceptions:
            accepted.append(finding)
            matched_exception_keys.add(finding.exception_key)
            continue
        violations.append(
            GuardViolation(
                "mutable_business_configuration",
                f"[{finding.rule_id}] {finding.symbol}: {finding.message}",
                finding.path,
                finding.line,
            )
        )
    for key, raw_exception in exceptions.items():
        if key not in matched_exception_keys:
            violations.append(
                GuardViolation(
                    "stale_or_changed_exception",
                    "temporary exception no longer matches an exact AST finding; remove or re-review it",
                    str(raw_exception["path"]),
                )
            )

    return BusinessConfigurationGuardReport(
        scanned_files=len(paths),
        findings=tuple(
            sorted(findings, key=lambda item: (item.path, item.line, item.rule_id, item.symbol))
        ),
        accepted_findings=tuple(
            sorted(accepted, key=lambda item: (item.path, item.line, item.rule_id, item.symbol))
        ),
        violations=tuple(violations),
    )


def _print_report(report: BusinessConfigurationGuardReport) -> None:
    for finding in report.accepted_findings:
        print(
            f"ACCEPTED-UNTIL-EXPIRY {finding.path}:{finding.line}: "
            f"[{finding.rule_id}] {finding.symbol} ({finding.ast_fingerprint[:12]})"
        )
    for violation in report.violations:
        location = violation.path
        if violation.line is not None:
            location = f"{location}:{violation.line}"
        prefix = f"{location}: " if location else ""
        print(f"{prefix}[{violation.code}] {violation.message}")


def main() -> int:
    """Run the Business Configuration Guard in authoritative full-scan mode."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--mode",
        choices=("full",),
        default="full",
        help="Only full is authoritative; delta output must never authorize this gate.",
    )
    args = parser.parse_args()
    report = evaluate_business_configuration_guard(args.manifest)
    _print_report(report)
    if report.violations:
        print(
            "Business Configuration Guard failed: "
            f"{len(report.violations)} violation(s), {report.scanned_files} file(s) scanned"
        )
        return 1
    print(
        "Business Configuration Guard OK: "
        f"{report.scanned_files} file(s) scanned, "
        f"{len(report.findings)} mutable finding(s), "
        f"{len(report.accepted_findings)} exact time-bound exception(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
