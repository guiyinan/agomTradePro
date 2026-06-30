#!/usr/bin/env python
"""Full-repository governance consistency checks.

This check covers repo-wide gaps that are intentionally outside the
diff-only architecture guard: module shape, documentation counters, docs links,
misplaced AppConfig definitions, known application-layer third-party debt, and
production file-size growth.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"
DOC_INDEX = REPO_ROOT / "docs" / "INDEX.md"
ARCHITECTURE_GUARDRAILS_DOC = REPO_ROOT / "docs" / "governance" / "ARCHITECTURE_GUARDRAILS.md"
DEFAULT_BASELINE = REPO_ROOT / "governance" / "governance_baseline.json"
ARCHITECTURE_RULES = REPO_ROOT / "governance" / "architecture_rules.json"
MODULE_CYCLE_ALLOWLIST = REPO_ROOT / "governance" / "module_cycle_allowlist.json"
ARCHITECTURE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "architecture-layer-guard.yml"
CONSISTENCY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "consistency-check.yml"
PRODUCTION_PYTHON_ROOTS = ("apps", "core", "shared")
RULE_SELECTOR_KEYS = (
    "source_roots",
    "source_module",
    "source_modules",
    "source_layers",
    "path_patterns",
)
RULE_MATCHER_KEYS = (
    "forbidden_import_prefixes",
    "forbidden_import_patterns",
    "forbidden_line_patterns",
    "forbid_cross_app_infrastructure_imports",
    "forbid_same_app_infrastructure_imports",
)
GOVERNANCE_BASELINE_REQUIRED_KEYS = (
    "version",
    "mcp_tool_count",
    "business_module_count",
    "static_test_function_count",
    "module_shape_minimums",
    "allowed_application_third_party_imports",
    "core_integration_app_infrastructure_import_count",
    "core_integration_orm_access_count",
    "core_management_command_app_infrastructure_import_count",
    "core_management_command_orm_access_count",
    "python_file_non_empty_line_limit",
    "allowed_large_python_files",
)

REQUIRED_MODULE_FILES = (
    "domain/entities.py",
    "domain/rules.py",
    "domain/services.py",
    "application/use_cases.py",
    "application/dtos.py",
    "infrastructure/models.py",
    "infrastructure/repositories.py",
    "interface/views.py",
    "interface/serializers.py",
    "interface/urls.py",
    "interface/api_urls.py",
)

MCP_COUNT_DOCS = (
    "README.md",
    "README_EN.md",
    "AGENTS.md",
    "docs/INDEX.md",
    "docs/governance/SYSTEM_BASELINE.md",
    "docs/SYSTEM_SPECIFICATION.md",
    "docs/mcp/mcp_guide.md",
)

MODULE_COUNT_DOCS = (
    "README.md",
    "README_EN.md",
    "AGENTS.md",
    "docs/INDEX.md",
    "docs/VERSION.md",
    "docs/governance/SYSTEM_BASELINE.md",
    "docs/SYSTEM_SPECIFICATION.md",
)

VERSION_DOCS = (
    "AGENTS.md",
    "docs/INDEX.md",
    "docs/VERSION.md",
    "docs/governance/SYSTEM_BASELINE.md",
    "docs/SYSTEM_SPECIFICATION.md",
)

TEST_COUNT_DOCS = (
    "README.md",
    "README_EN.md",
    "AGENTS.md",
    "docs/INDEX.md",
    "docs/governance/SYSTEM_BASELINE.md",
    "docs/SYSTEM_SPECIFICATION.md",
)

GOVERNANCE_DOC_REQUIRED_TOKENS = (
    "governance_baseline",
    "architecture_ruleset",
    "module_dependency_baseline",
    "ci_governance_wiring",
    "core_integration_debt",
    "core_management_command_debt",
    "check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles",
    "verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit --fail-on-audit-violations",
    "check_governance_consistency.py --baseline governance/governance_baseline.json --format text",
)


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict:
        payload = {"code": self.code, "path": self.path, "message": self.message}
        if self.line is not None:
            payload["line"] = self.line
        return payload


def load_baseline(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_core_version() -> str:
    tree = ast.parse((REPO_ROOT / "core" / "version.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise RuntimeError("core/version.py does not define __version__")


def load_pyproject_version() -> str:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload.get("project", {}).get("version", ""))


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "migrations" in path.parts:
            continue
        yield path


def is_production_python_file(path: Path) -> bool:
    """Return True for production Python files governed by complexity checks."""

    if "__pycache__" in path.parts or "migrations" in path.parts or "tests" in path.parts:
        return False
    return not path.name.startswith("test_")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def display_path(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.as_posix()


def count_non_empty_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def count_mcp_tools() -> int:
    count = 0
    roots = [REPO_ROOT / "sdk" / "agomtradepro_mcp"]
    for root in roots:
        if not root.exists():
            continue
        for path in iter_python_files(root):
            count += len(re.findall(r"@server\.tool\(", path.read_text(encoding="utf-8")))
    return count


def count_business_modules() -> int:
    return len(
        [
            path
            for path in APPS_ROOT.iterdir()
            if path.is_dir() and not path.name.startswith("__")
        ]
    )


def count_static_test_functions() -> int:
    count = 0
    for root in (REPO_ROOT / "tests", REPO_ROOT / "apps"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("test_*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel(path))
            except SyntaxError:
                continue
            count += sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
    return count


def count_tokens(count: int) -> set[str]:
    return {str(count), f"{count:,}"}


def line_mentions_module_count(line: str, count: int) -> bool:
    lowered = line.lower()
    has_module_keyword = (
        "业务模块" in line
        or "business module" in lowered
        or "business_modules" in lowered
    )
    return has_module_keyword and str(count) in line


def line_mentions_test_count(line: str, count: int) -> bool:
    lowered = line.lower()
    has_test_keyword = "测试" in line or "test" in lowered
    return has_test_keyword and any(token in line for token in count_tokens(count))


def check_docs_consistency(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    core_version = load_core_version()
    pyproject_version = load_pyproject_version()
    if pyproject_version != core_version:
        violations.append(
            Violation(
                "version_pyproject_mismatch",
                "pyproject.toml",
                f"pyproject project.version is {pyproject_version}, core/version.py is {core_version}.",
            )
        )

    for doc in VERSION_DOCS:
        path = REPO_ROOT / doc
        if not path.exists():
            violations.append(
                Violation("version_doc_missing", doc, "Expected version doc is missing.")
            )
            continue
        if core_version not in path.read_text(encoding="utf-8"):
            violations.append(
                Violation(
                    "version_doc_stale",
                    doc,
                    f"Document does not contain current core version {core_version}.",
                )
            )

    actual_count = count_mcp_tools()
    expected_count = int(baseline["mcp_tool_count"])
    if actual_count != expected_count:
        violations.append(
            Violation(
                "mcp_count_baseline_mismatch",
                "sdk/agomtradepro_mcp",
                f"Actual MCP tool count is {actual_count}, baseline is {expected_count}.",
            )
        )

    expected_text = str(actual_count)
    for doc in MCP_COUNT_DOCS:
        path = REPO_ROOT / doc
        if not path.exists():
            violations.append(
                Violation("mcp_count_doc_missing", doc, "Expected MCP count doc is missing.")
            )
            continue
        text = path.read_text(encoding="utf-8")
        if expected_text not in text:
            violations.append(
                Violation(
                    "mcp_count_doc_stale",
                    doc,
                    f"Document does not contain current MCP tool count {expected_text}.",
                )
            )

    actual_module_count = count_business_modules()
    expected_module_count = int(baseline["business_module_count"])
    if actual_module_count != expected_module_count:
        violations.append(
            Violation(
                "module_count_baseline_mismatch",
                "apps",
                f"Actual business module count is {actual_module_count}, baseline is {expected_module_count}.",
            )
        )

    for doc in MODULE_COUNT_DOCS:
        path = REPO_ROOT / doc
        if not path.exists():
            violations.append(
                Violation("module_count_doc_missing", doc, "Expected module count doc is missing.")
            )
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if not any(line_mentions_module_count(line, actual_module_count) for line in lines):
            violations.append(
                Violation(
                    "module_count_doc_stale",
                    doc,
                    f"Document has no current module-count line for {actual_module_count} business modules.",
                )
            )
        if doc == "docs/governance/SYSTEM_BASELINE.md" and (
            f"{actual_module_count}/{actual_module_count}" not in "\n".join(lines)
        ):
            violations.append(
                Violation(
                    "module_coverage_doc_stale",
                    doc,
                    f"SYSTEM_BASELINE.md must contain current module coverage {actual_module_count}/{actual_module_count}.",
                )
            )

    actual_test_count = count_static_test_functions()
    expected_test_count = int(baseline["static_test_function_count"])
    if actual_test_count != expected_test_count:
        violations.append(
            Violation(
                "static_test_count_baseline_mismatch",
                "tests",
                f"Actual static test function count is {actual_test_count}, baseline is {expected_test_count}.",
            )
        )

    for doc in TEST_COUNT_DOCS:
        path = REPO_ROOT / doc
        if not path.exists():
            violations.append(
                Violation("test_count_doc_missing", doc, "Expected test count doc is missing.")
            )
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if not any(line_mentions_test_count(line, actual_test_count) for line in lines):
            violations.append(
                Violation(
                    "test_count_doc_stale",
                    doc,
                    f"Document has no current test-count line for {actual_test_count} static test functions.",
                )
            )

    return violations, {
        "actual_mcp_tool_count": actual_count,
        "expected_mcp_tool_count": expected_count,
        "actual_business_module_count": actual_module_count,
        "expected_business_module_count": expected_module_count,
        "actual_static_test_function_count": actual_test_count,
        "expected_static_test_function_count": expected_test_count,
        "core_version": core_version,
        "pyproject_version": pyproject_version,
    }


def check_docs_links() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    checked = 0
    if not DOC_INDEX.exists():
        return [Violation("docs_index_missing", rel(DOC_INDEX), "docs/INDEX.md is missing.")], {
            "checked": 0
        }

    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for line_no, line in enumerate(DOC_INDEX.read_text(encoding="utf-8").splitlines(), start=1):
        for match in link_re.finditer(line):
            target = match.group(1)
            if re.match(r"^(https?:|mailto:|#|/)", target):
                continue
            clean_target = target.split("#", 1)[0]
            if not clean_target.strip():
                continue
            checked += 1
            resolved = (DOC_INDEX.parent / clean_target).resolve()
            try:
                resolved.relative_to(REPO_ROOT)
            except ValueError:
                violations.append(
                    Violation(
                        "docs_index_link_escapes_repo",
                        rel(DOC_INDEX),
                        f"Link escapes repo: {target}",
                        line_no,
                    )
                )
                continue
            if not resolved.exists():
                violations.append(
                    Violation(
                        "docs_index_dead_link",
                        rel(DOC_INDEX),
                        f"Dead link target: {target}",
                        line_no,
                    )
                )
    return violations, {"checked_links": checked}


def check_governance_docs_current() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    path_label = display_path(ARCHITECTURE_GUARDRAILS_DOC)
    if not ARCHITECTURE_GUARDRAILS_DOC.exists():
        return [
            Violation(
                "governance_guardrails_doc_missing",
                path_label,
                "Architecture guardrails documentation is missing.",
            )
        ], {"required_token_count": len(GOVERNANCE_DOC_REQUIRED_TOKENS)}

    text = ARCHITECTURE_GUARDRAILS_DOC.read_text(encoding="utf-8")
    missing_tokens = [
        token for token in GOVERNANCE_DOC_REQUIRED_TOKENS if token not in text
    ]
    for token in missing_tokens:
        violations.append(
            Violation(
                "governance_guardrails_doc_stale",
                path_label,
                f"Architecture guardrails documentation is missing required token: {token}",
            )
        )
    return violations, {
        "required_token_count": len(GOVERNANCE_DOC_REQUIRED_TOKENS),
        "missing_tokens": missing_tokens,
    }


def check_governance_baseline_health(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    path_label = display_path(DEFAULT_BASELINE)
    missing_keys = [
        key for key in GOVERNANCE_BASELINE_REQUIRED_KEYS if key not in baseline
    ]
    for key in missing_keys:
        violations.append(
            Violation(
                "governance_baseline_required_key_missing",
                path_label,
                f"Governance baseline is missing required key {key}.",
            )
        )

    version = str(baseline.get("version", ""))
    if not re.match(r"^\d{4}-\d{2}-\d{2}\.v\d+$", version):
        violations.append(
            Violation(
                "governance_baseline_version_invalid",
                path_label,
                f"Governance baseline version {version!r} must match YYYY-MM-DD.vN.",
            )
        )

    for key in (
        "mcp_tool_count",
        "business_module_count",
        "static_test_function_count",
        "core_integration_app_infrastructure_import_count",
        "core_integration_orm_access_count",
        "core_management_command_app_infrastructure_import_count",
        "core_management_command_orm_access_count",
    ):
        if key in baseline and not is_non_negative_int(baseline[key]):
            violations.append(
                Violation(
                    "governance_baseline_count_invalid",
                    path_label,
                    f"{key} must be a non-negative integer.",
                )
            )

    module_names = current_module_names()
    shape_minimums = baseline.get("module_shape_minimums", {})
    if not isinstance(shape_minimums, dict):
        violations.append(
            Violation(
                "governance_baseline_module_shape_invalid",
                path_label,
                "module_shape_minimums must be a JSON object keyed by app module name.",
            )
        )
        shape_minimums = {}
    else:
        for module_name, score in sorted(shape_minimums.items()):
            if module_name not in module_names:
                violations.append(
                    Violation(
                        "governance_baseline_unknown_module",
                        path_label,
                        f"module_shape_minimums references unknown module {module_name}.",
                    )
                )
            if not is_non_negative_int(score) or int(score) > len(REQUIRED_MODULE_FILES):
                violations.append(
                    Violation(
                        "governance_baseline_module_shape_score_invalid",
                        path_label,
                        f"module_shape_minimums.{module_name} must be between 0 and {len(REQUIRED_MODULE_FILES)}.",
                    )
                )
        for module_name in sorted(module_names - set(shape_minimums)):
            violations.append(
                Violation(
                    "governance_baseline_module_shape_missing",
                    path_label,
                    f"module_shape_minimums is missing module {module_name}.",
                )
            )

    allowed_imports = baseline.get("allowed_application_third_party_imports", {})
    if not isinstance(allowed_imports, dict):
        violations.append(
            Violation(
                "governance_baseline_application_imports_invalid",
                path_label,
                "allowed_application_third_party_imports must be a JSON object.",
            )
        )
    else:
        for source_path, package_counts in sorted(allowed_imports.items()):
            if not isinstance(package_counts, dict):
                violations.append(
                    Violation(
                        "governance_baseline_application_imports_invalid",
                        path_label,
                        f"allowed_application_third_party_imports.{source_path} must be a JSON object.",
                    )
                )
                continue
            for package_name, count in sorted(package_counts.items()):
                if package_name not in {"pandas", "numpy"} or not is_non_negative_int(count):
                    violations.append(
                        Violation(
                            "governance_baseline_application_import_value_invalid",
                            path_label,
                            f"allowed_application_third_party_imports.{source_path}.{package_name} must be a non-negative pandas/numpy count.",
                        )
                    )

    line_limit = baseline.get("python_file_non_empty_line_limit")
    if not is_non_negative_int(line_limit) or int(line_limit or 0) == 0:
        violations.append(
            Violation(
                "governance_baseline_large_file_limit_invalid",
                path_label,
                "python_file_non_empty_line_limit must be a positive integer.",
            )
        )

    allowed_large_files = baseline.get("allowed_large_python_files", {})
    if not isinstance(allowed_large_files, dict):
        violations.append(
            Violation(
                "governance_baseline_large_files_invalid",
                path_label,
                "allowed_large_python_files must be a JSON object keyed by production Python path.",
            )
        )
    else:
        for source_path, line_count in sorted(allowed_large_files.items()):
            if not source_path.endswith(".py") or not is_non_negative_int(line_count):
                violations.append(
                    Violation(
                        "governance_baseline_large_file_value_invalid",
                        path_label,
                        f"allowed_large_python_files.{source_path} must map a Python file path to a non-negative integer.",
                    )
                )

    return violations, {
        "baseline_version": version,
        "required_key_count": len(GOVERNANCE_BASELINE_REQUIRED_KEYS),
        "missing_required_keys": missing_keys,
        "module_shape_entry_count": len(shape_minimums),
        "allowed_application_import_file_count": len(allowed_imports)
        if isinstance(allowed_imports, dict)
        else 0,
        "allowed_large_file_count": len(allowed_large_files)
        if isinstance(allowed_large_files, dict)
        else 0,
    }


def module_shape() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for module_dir in sorted(
        path for path in APPS_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")
    ):
        missing = [item for item in REQUIRED_MODULE_FILES if not (module_dir / item).exists()]
        result[module_dir.name] = {
            "score": len(REQUIRED_MODULE_FILES) - len(missing),
            "missing": missing,
        }
    return result


def check_module_shape(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    actual = module_shape()
    minimums = baseline["module_shape_minimums"]

    for module_name in sorted(set(actual) - set(minimums)):
        violations.append(
            Violation(
                "module_shape_missing_baseline",
                f"apps/{module_name}",
                "New app module is missing a module-shape baseline entry.",
            )
        )
    for module_name in sorted(set(minimums) - set(actual)):
        violations.append(
            Violation(
                "module_shape_baseline_orphan",
                f"apps/{module_name}",
                "Module-shape baseline references a missing app module.",
            )
        )

    for module_name, expected_score in sorted(minimums.items()):
        if module_name not in actual:
            continue
        score = actual[module_name]["score"]
        if score < expected_score:
            missing = ", ".join(actual[module_name]["missing"])
            violations.append(
                Violation(
                    "module_shape_regression",
                    f"apps/{module_name}",
                    f"Module shape score regressed from {expected_score}/11 to {score}/11. Missing: {missing}",
                )
            )

    return violations, actual


def check_misplaced_app_config() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    for path in iter_python_files(APPS_ROOT):
        relative = rel(path)
        if re.match(r"apps/[^/]+/apps\.py$", relative):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"^\s*from\s+django\.apps\s+import\s+AppConfig\b", line) or re.search(
                r"class\s+\w+Config\(AppConfig\)", line
            ):
                violations.append(
                    Violation(
                        "misplaced_app_config",
                        relative,
                        "Django AppConfig definitions/imports must live in app-root apps.py only.",
                        line_no,
                    )
                )
    return violations, {"violation_count": len(violations)}


def check_singular_dto_files() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    for path in sorted(APPS_ROOT.glob("*/application/dto.py")):
        violations.append(
            Violation(
                "singular_dto_filename",
                rel(path),
                "Use application/dtos.py, not application/dto.py.",
            )
        )
    return violations, {"violation_count": len(violations)}


def rule_has_non_empty_key(rule: dict, keys: tuple[str, ...]) -> bool:
    return any(bool(rule.get(key)) for key in keys)


def check_architecture_ruleset_health() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    payload = json.loads(ARCHITECTURE_RULES.read_text(encoding="utf-8"))
    version = str(payload.get("version", ""))
    if not re.match(r"^\d{4}-\d{2}-\d{2}\.v\d+$", version):
        violations.append(
            Violation(
                "architecture_rules_version_invalid",
                rel(ARCHITECTURE_RULES),
                f"Architecture rules version {version!r} must match YYYY-MM-DD.vN.",
            )
        )

    rule_groups = {
        "boundary_rules": payload.get("boundary_rules", []),
        "audit_rules": payload.get("audit_rules", []),
    }
    rule_ids: list[str] = []
    for group_name, rules in rule_groups.items():
        if not isinstance(rules, list) or not rules:
            violations.append(
                Violation(
                    "architecture_rule_group_empty",
                    rel(ARCHITECTURE_RULES),
                    f"{group_name} must be a non-empty list.",
                )
            )
            continue
        for index, rule in enumerate(rules):
            rule_path = f"{rel(ARCHITECTURE_RULES)}#{group_name}[{index}]"
            if not isinstance(rule, dict):
                violations.append(
                    Violation(
                        "architecture_rule_invalid",
                        rule_path,
                        "Architecture rule entries must be JSON objects.",
                    )
                )
                continue
            rule_id = str(rule.get("id", "")).strip()
            rule_ids.append(rule_id)
            if not re.match(r"^[a-z][a-z0-9_]*$", rule_id):
                violations.append(
                    Violation(
                        "architecture_rule_id_invalid",
                        rule_path,
                        f"Architecture rule id {rule_id!r} must be snake_case.",
                    )
                )
            for required_key in ("description", "rationale"):
                if not str(rule.get(required_key, "")).strip():
                    violations.append(
                        Violation(
                            "architecture_rule_metadata_missing",
                            rule_path,
                            f"Architecture rule {rule_id or '<missing>'} is missing {required_key}.",
                        )
                    )
            if not rule_has_non_empty_key(rule, RULE_SELECTOR_KEYS):
                violations.append(
                    Violation(
                        "architecture_rule_selector_missing",
                        rule_path,
                        f"Architecture rule {rule_id or '<missing>'} has no source selector.",
                    )
                )
            if not rule_has_non_empty_key(rule, RULE_MATCHER_KEYS):
                violations.append(
                    Violation(
                        "architecture_rule_matcher_missing",
                        rule_path,
                        f"Architecture rule {rule_id or '<missing>'} has no forbidden matcher.",
                    )
                )

    duplicates = sorted(
        rule_id for rule_id, count in Counter(rule_ids).items() if rule_id and count > 1
    )
    for rule_id in duplicates:
        violations.append(
            Violation(
                "architecture_rule_id_duplicate",
                rel(ARCHITECTURE_RULES),
                f"Architecture rule id {rule_id!r} is duplicated.",
            )
        )

    return violations, {
        "rules_version": version,
        "boundary_rule_count": len(rule_groups["boundary_rules"]),
        "audit_rule_count": len(rule_groups["audit_rules"]),
        "duplicate_rule_ids": duplicates,
    }


def current_module_names() -> set[str]:
    return {
        path.name
        for path in APPS_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }


def is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_budget_map(
    *,
    name: str,
    payload: dict,
    module_names: set[str],
    violations: list[Violation],
) -> dict[str, int]:
    path_label = display_path(MODULE_CYCLE_ALLOWLIST)
    raw_map = payload.get(name)
    if not isinstance(raw_map, dict):
        violations.append(
            Violation(
                "module_dependency_budget_map_invalid",
                path_label,
                f"{name} must be a JSON object keyed by app module name.",
            )
        )
        return {}

    budgets: dict[str, int] = {}
    for module_name, value in sorted(raw_map.items()):
        if not is_non_negative_int(value):
            violations.append(
                Violation(
                    "module_dependency_budget_value_invalid",
                    path_label,
                    f"{name}.{module_name} must be a non-negative integer.",
                )
            )
            continue
        budgets[str(module_name)] = int(value)

    missing = sorted(module_names - set(budgets))
    extra = sorted(set(budgets) - module_names)
    for module_name in missing:
        violations.append(
            Violation(
                "module_dependency_budget_missing_module",
                path_label,
                f"{name} is missing module {module_name}.",
            )
        )
    for module_name in extra:
        violations.append(
            Violation(
                "module_dependency_budget_unknown_module",
                path_label,
                f"{name} references unknown module {module_name}.",
            )
        )
    return budgets


def check_module_dependency_baseline_health() -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    path_label = display_path(MODULE_CYCLE_ALLOWLIST)
    payload = json.loads(MODULE_CYCLE_ALLOWLIST.read_text(encoding="utf-8"))
    version = str(payload.get("version", ""))
    if not re.match(r"^\d{4}-\d{2}-\d{2}\.v\d+$", version):
        violations.append(
            Violation(
                "module_dependency_baseline_version_invalid",
                path_label,
                f"Module dependency baseline version {version!r} must match YYYY-MM-DD.vN.",
            )
        )
    if not str(payload.get("description", "")).strip():
        violations.append(
            Violation(
                "module_dependency_baseline_description_missing",
                path_label,
                "Module dependency baseline must include a description.",
            )
        )

    module_names = current_module_names()
    outbound_budgets = check_budget_map(
        name="max_outbound_modules_by_app",
        payload=payload,
        module_names=module_names,
        violations=violations,
    )
    inbound_budgets = check_budget_map(
        name="max_inbound_modules_by_app",
        payload=payload,
        module_names=module_names,
        violations=violations,
    )

    max_outbound = payload.get("max_outbound_modules_per_app")
    observed_outbound_budget = max(outbound_budgets.values(), default=0)
    if not is_non_negative_int(max_outbound) or int(max_outbound) != observed_outbound_budget:
        violations.append(
            Violation(
                "module_dependency_global_outbound_budget_mismatch",
                path_label,
                f"max_outbound_modules_per_app must equal max per-app outbound budget {observed_outbound_budget}.",
            )
        )

    max_inbound = payload.get("max_inbound_modules_per_app")
    observed_inbound_budget = max(inbound_budgets.values(), default=0)
    if not is_non_negative_int(max_inbound) or int(max_inbound) != observed_inbound_budget:
        violations.append(
            Violation(
                "module_dependency_global_inbound_budget_mismatch",
                path_label,
                f"max_inbound_modules_per_app must equal max per-app inbound budget {observed_inbound_budget}.",
            )
        )

    max_edges = payload.get("max_app_import_edges")
    if not is_non_negative_int(max_edges) or int(max_edges) < observed_outbound_budget:
        violations.append(
            Violation(
                "module_dependency_edge_budget_invalid",
                path_label,
                "max_app_import_edges must be a non-negative integer and at least the largest per-app outbound budget.",
            )
        )

    for field_name, exact_length, minimum_length in (
        ("allowed_bidirectional_pairs", 2, 2),
        ("allowed_cycle_components", None, 2),
    ):
        entries = payload.get(field_name)
        if not isinstance(entries, list):
            violations.append(
                Violation(
                    "module_dependency_allowlist_invalid",
                    path_label,
                    f"{field_name} must be a list.",
                )
            )
            continue
        for entry in entries:
            has_valid_length = (
                len(entry) == exact_length
                if exact_length is not None and isinstance(entry, list)
                else isinstance(entry, list) and len(entry) >= minimum_length
            )
            if (
                not isinstance(entry, list)
                or not has_valid_length
                or any(not isinstance(item, str) for item in entry)
                or len(set(entry)) != len(entry)
                or any(item not in module_names for item in entry)
            ):
                violations.append(
                    Violation(
                        "module_dependency_allowlist_entry_invalid",
                        path_label,
                        f"{field_name} entry {entry!r} must reference existing distinct modules.",
                    )
                )

    return violations, {
        "baseline_version": version,
        "module_count": len(module_names),
        "outbound_budget_count": len(outbound_budgets),
        "inbound_budget_count": len(inbound_budgets),
        "max_outbound_modules_per_app": max_outbound,
        "max_inbound_modules_per_app": max_inbound,
        "max_app_import_edges": max_edges,
    }


def check_text_tokens(path: Path, required_tokens: tuple[str, ...]) -> list[Violation]:
    path_label = display_path(path)
    if not path.exists():
        return [
            Violation(
                "ci_governance_workflow_missing",
                path_label,
                "Required governance workflow file is missing.",
            )
        ]
    text = path.read_text(encoding="utf-8")
    return [
        Violation(
            "ci_governance_workflow_token_missing",
            path_label,
            f"Workflow must contain required governance command token: {token}",
        )
        for token in required_tokens
        if token not in text
    ]


def check_ci_governance_wiring() -> tuple[list[Violation], dict]:
    architecture_tokens = (
        "scripts/check_architecture_delta.py",
        "--include-audit",
        "--fail-on-audit-violations",
        "scripts/verify_architecture.py",
        "scripts/check_module_cycles.py",
        "--allowlist-file governance/module_cycle_allowlist.json",
        "--fail-on-cycles",
    )
    consistency_tokens = (
        "scripts/check_governance_consistency.py",
        "--baseline governance/governance_baseline.json",
        "--write-report reports/consistency/governance-consistency.json",
    )
    violations = [
        *check_text_tokens(ARCHITECTURE_WORKFLOW, architecture_tokens),
        *check_text_tokens(CONSISTENCY_WORKFLOW, consistency_tokens),
    ]
    return violations, {
        "architecture_workflow": display_path(ARCHITECTURE_WORKFLOW),
        "consistency_workflow": display_path(CONSISTENCY_WORKFLOW),
        "architecture_required_token_count": len(architecture_tokens),
        "consistency_required_token_count": len(consistency_tokens),
    }


def collect_application_third_party_imports() -> dict[str, dict[str, int]]:
    result: dict[str, Counter] = {}
    for path in iter_python_files(APPS_ROOT):
        relative = rel(path)
        if "/application/" not in relative:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError:
            continue
        counter: Counter = Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in {"pandas", "numpy"}:
                        counter[root] += 1
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in {"pandas", "numpy"}:
                    counter[root] += 1
        if counter:
            result[relative] = dict(counter)
    return result


def check_application_third_party_baseline(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    actual = collect_application_third_party_imports()
    allowed = baseline.get("allowed_application_third_party_imports", {})

    for path, imports in sorted(actual.items()):
        allowed_imports = allowed.get(path, {})
        for package, count in sorted(imports.items()):
            allowed_count = int(allowed_imports.get(package, 0))
            if count > allowed_count:
                violations.append(
                    Violation(
                        "application_third_party_import_regression",
                        path,
                        f"{package} imports increased from allowed {allowed_count} to {count}.",
                    )
                )
    for _path in sorted(set(allowed) - set(actual)):
        pass

    return violations, actual


def collect_app_infrastructure_orm_debt(root: Path) -> dict[str, object]:
    infrastructure_import_count = 0
    orm_access_count = 0
    files: dict[str, dict[str, int]] = {}
    if not root.exists():
        return {
            "infrastructure_import_count": 0,
            "orm_access_count": 0,
            "files": files,
        }

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = rel(path)
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            continue

        file_infrastructure_imports = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("apps.") and ".infrastructure" in alias.name:
                        file_infrastructure_imports += 1
            elif isinstance(node, ast.ImportFrom) and node.module:
                if (
                    node.level == 0
                    and node.module.startswith("apps.")
                    and ".infrastructure" in node.module
                ):
                    file_infrastructure_imports += 1

        file_orm_accesses = 0
        for line_text in text.splitlines():
            stripped = line_text.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if (
                "._default_manager" in line_text
                or ".objects." in line_text
                or ".objects(" in line_text
                or "apps.get_model(" in line_text
            ):
                file_orm_accesses += 1

        if file_infrastructure_imports or file_orm_accesses:
            files[relative] = {
                "infrastructure_imports": file_infrastructure_imports,
                "orm_accesses": file_orm_accesses,
            }
        infrastructure_import_count += file_infrastructure_imports
        orm_access_count += file_orm_accesses

    return {
        "infrastructure_import_count": infrastructure_import_count,
        "orm_access_count": orm_access_count,
        "files": files,
    }


def collect_core_integration_debt() -> dict[str, object]:
    return collect_app_infrastructure_orm_debt(REPO_ROOT / "core" / "integration")


def collect_core_management_command_debt() -> dict[str, object]:
    return collect_app_infrastructure_orm_debt(
        REPO_ROOT / "core" / "management" / "commands"
    )


def check_debt_baseline(
    *,
    baseline: dict,
    actual: dict[str, object],
    path_label: str,
    baseline_infrastructure_import_key: str,
    baseline_orm_access_key: str,
    violation_prefix: str,
    display_name: str,
) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    actual_infrastructure_imports = int(actual["infrastructure_import_count"])
    actual_orm_accesses = int(actual["orm_access_count"])
    expected_infrastructure_imports = int(
        baseline.get(baseline_infrastructure_import_key, 0)
    )
    expected_orm_accesses = int(baseline.get(baseline_orm_access_key, 0))

    if actual_infrastructure_imports > expected_infrastructure_imports:
        violations.append(
            Violation(
                f"{violation_prefix}_infrastructure_import_growth",
                path_label,
                f"{display_name} app infrastructure imports grew from {expected_infrastructure_imports} to {actual_infrastructure_imports}.",
            )
        )
    elif actual_infrastructure_imports < expected_infrastructure_imports:
        violations.append(
            Violation(
                f"{violation_prefix}_infrastructure_import_baseline_stale",
                path_label,
                f"{display_name} app infrastructure imports fell from {expected_infrastructure_imports} to {actual_infrastructure_imports}; tighten governance_baseline.json.",
            )
        )

    if actual_orm_accesses > expected_orm_accesses:
        violations.append(
            Violation(
                f"{violation_prefix}_orm_access_growth",
                path_label,
                f"{display_name} ORM access lines grew from {expected_orm_accesses} to {actual_orm_accesses}.",
            )
        )
    elif actual_orm_accesses < expected_orm_accesses:
        violations.append(
            Violation(
                f"{violation_prefix}_orm_access_baseline_stale",
                path_label,
                f"{display_name} ORM access lines fell from {expected_orm_accesses} to {actual_orm_accesses}; tighten governance_baseline.json.",
            )
        )

    return violations, {
        "actual_infrastructure_import_count": actual_infrastructure_imports,
        "expected_infrastructure_import_count": expected_infrastructure_imports,
        "actual_orm_access_count": actual_orm_accesses,
        "expected_orm_access_count": expected_orm_accesses,
        "files": actual["files"],
    }


def check_core_integration_debt_baseline(baseline: dict) -> tuple[list[Violation], dict]:
    return check_debt_baseline(
        baseline=baseline,
        actual=collect_core_integration_debt(),
        path_label="core/integration",
        baseline_infrastructure_import_key="core_integration_app_infrastructure_import_count",
        baseline_orm_access_key="core_integration_orm_access_count",
        violation_prefix="core_integration",
        display_name="core/integration",
    )


def check_core_management_command_debt_baseline(
    baseline: dict,
) -> tuple[list[Violation], dict]:
    return check_debt_baseline(
        baseline=baseline,
        actual=collect_core_management_command_debt(),
        path_label="core/management/commands",
        baseline_infrastructure_import_key="core_management_command_app_infrastructure_import_count",
        baseline_orm_access_key="core_management_command_orm_access_count",
        violation_prefix="core_management_command",
        display_name="core/management/commands",
    )


def collect_large_python_files(limit: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for root_name in PRODUCTION_PYTHON_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if not is_production_python_file(path):
                continue
            line_count = count_non_empty_lines(path)
            if line_count > limit:
                result[rel(path)] = line_count
    return result


def check_large_python_file_baseline(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
    limit = int(baseline.get("python_file_non_empty_line_limit", 1200))
    actual = collect_large_python_files(limit)
    allowed = {
        str(path): int(line_count)
        for path, line_count in baseline.get("allowed_large_python_files", {}).items()
    }

    for path, line_count in sorted(actual.items()):
        allowed_count = allowed.get(path)
        if allowed_count is None:
            violations.append(
                Violation(
                    "large_python_file_missing_baseline",
                    path,
                    f"Production Python file has {line_count} non-empty lines, above limit {limit}.",
                )
            )
        elif line_count > allowed_count:
            violations.append(
                Violation(
                    "large_python_file_growth",
                    path,
                    f"Production Python file grew from allowed {allowed_count} to {line_count} non-empty lines.",
                )
            )

    for path, allowed_count in sorted(allowed.items()):
        actual_count = actual.get(path)
        if actual_count is None:
            violations.append(
                Violation(
                    "large_python_file_baseline_stale",
                    path,
                    f"Baseline allows {allowed_count} non-empty lines, but file is now at or below limit {limit} or missing.",
                )
            )

    return violations, {
        "line_limit": limit,
        "large_file_count": len(actual),
        "large_files": actual,
        "allowed_large_file_count": len(allowed),
    }


def build_report(baseline: dict) -> dict:
    sections = []
    violations: list[Violation] = []

    for name, checker in [
        ("governance_baseline", lambda: check_governance_baseline_health(baseline)),
        ("docs_consistency", lambda: check_docs_consistency(baseline)),
        ("docs_links", check_docs_links),
        ("governance_docs", check_governance_docs_current),
        ("module_shape", lambda: check_module_shape(baseline)),
        ("misplaced_app_config", check_misplaced_app_config),
        ("singular_dto_files", check_singular_dto_files),
        ("architecture_ruleset", check_architecture_ruleset_health),
        ("module_dependency_baseline", check_module_dependency_baseline_health),
        ("ci_governance_wiring", check_ci_governance_wiring),
        (
            "application_third_party_imports",
            lambda: check_application_third_party_baseline(baseline),
        ),
        ("core_integration_debt", lambda: check_core_integration_debt_baseline(baseline)),
        (
            "core_management_command_debt",
            lambda: check_core_management_command_debt_baseline(baseline),
        ),
        ("large_python_files", lambda: check_large_python_file_baseline(baseline)),
    ]:
        section_violations, data = checker()
        violations.extend(section_violations)
        sections.append(
            {
                "name": name,
                "violation_count": len(section_violations),
                "data": data,
                "violations": [item.to_dict() for item in section_violations],
            }
        )

    return {
        "baseline_version": baseline["version"],
        "violation_count": len(violations),
        "sections": sections,
        "violations": [item.to_dict() for item in violations],
    }


def print_text_report(report: dict) -> None:
    print(f"Governance baseline version: {report['baseline_version']}")
    print(f"Governance violations: {report['violation_count']}")
    for section in report["sections"]:
        print(f"- {section['name']}: {section['violation_count']} violation(s)")
    if report["violations"]:
        print("")
        print("Violations:")
        for violation in report["violations"][:50]:
            location = violation["path"]
            if "line" in violation:
                location = f"{location}:{violation['line']}"
            print(f"- {violation['code']}: {location} - {violation['message']}")
        remaining = len(report["violations"]) - 50
        if remaining > 0:
            print(f"... truncated {remaining} additional violations")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check full-repository governance consistency.")
    parser.add_argument(
        "--baseline", default=str(DEFAULT_BASELINE), help="Governance baseline JSON path."
    )
    parser.add_argument("--write-report", help="Write JSON report to the given path.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    baseline = load_baseline(
        (REPO_ROOT / args.baseline).resolve()
        if not Path(args.baseline).is_absolute()
        else Path(args.baseline)
    )
    report = build_report(baseline)

    if args.write_report:
        report_path = (REPO_ROOT / args.write_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    return 1 if report["violation_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
