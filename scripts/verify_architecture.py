#!/usr/bin/env python
"""
Verify versioned architecture boundaries and generate structural audit reports.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from importlib.util import resolve_name
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"
DEFAULT_SCAN_ROOTS = ("apps", "core", "shared")
LAYER_NAMES = ("application", "domain", "infrastructure", "interface", "management")
MAX_TEXT_VIOLATIONS = 20


@dataclass(frozen=True)
class SourceFile:
    path: Path
    source_path: str
    source_root: str
    source_module: str
    source_layer: str
    module_path: str
    package: str
    text: str


@dataclass(frozen=True)
class ImportRecord:
    source_path: str
    source_root: str
    source_module: str
    source_layer: str
    import_path: str
    target_module: str | None
    lineno: int


@dataclass(frozen=True)
class LineRecord:
    source_path: str
    source_root: str
    source_module: str
    source_layer: str
    lineno: int
    line_text: str


def load_rules(rules_path: Path) -> dict:
    return json.loads(rules_path.read_text(encoding="utf-8"))


def iter_module_dirs(apps_root: Path) -> list[Path]:
    return sorted(
        path for path in apps_root.iterdir() if path.is_dir() and not path.name.startswith("__")
    )


def iter_python_files(root_path: Path) -> Iterable[Path]:
    for path in sorted(root_path.rglob("*.py")):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def detect_layer(path: Path) -> str:
    for part in path.parts:
        if part in LAYER_NAMES:
            return part
    return "other"


def build_source_file(path: Path) -> SourceFile:
    relative_path = path.relative_to(REPO_ROOT)
    source_path = relative_path.as_posix()
    source_root = relative_path.parts[0]
    if source_root == "apps" and len(relative_path.parts) > 1:
        source_module = relative_path.parts[1]
    else:
        source_module = source_root

    module_parts = list(relative_path.with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    module_path = ".".join(module_parts)
    if path.name == "__init__.py":
        package = module_path
    else:
        package = module_path.rpartition(".")[0]

    return SourceFile(
        path=path,
        source_path=source_path,
        source_root=source_root,
        source_module=source_module,
        source_layer=detect_layer(relative_path),
        module_path=module_path,
        package=package,
        text=path.read_text(encoding="utf-8"),
    )


def iter_source_files(source_roots: Sequence[str]) -> Iterable[SourceFile]:
    for root_name in source_roots:
        root_path = REPO_ROOT / root_name
        if not root_path.exists():
            continue
        for path in iter_python_files(root_path):
            yield build_source_file(path)


def resolve_import_path(
    source_file: SourceFile, module: str | None, level: int
) -> str | None:
    if level == 0:
        return module
    if not source_file.package:
        return None

    relative_name = "." * level
    if module:
        relative_name = f"{relative_name}{module}"

    try:
        return resolve_name(relative_name, source_file.package)
    except (ImportError, ValueError):
        return None


def build_target_module(import_path: str) -> str | None:
    if not import_path.startswith("apps."):
        return None
    parts = import_path.split(".")
    return parts[1] if len(parts) > 1 else None


def is_dynamic_import_call(node: ast.Call) -> bool:
    """Return True when a call imports a module by string literal."""

    if isinstance(node.func, ast.Attribute):
        return (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
        )
    if isinstance(node.func, ast.Name):
        return node.func.id == "__import__"
    return False


def resolve_dynamic_import_path(source_file: SourceFile, node: ast.Call) -> str | None:
    """Resolve importlib.import_module/__import__ string-literal module names."""

    if not node.args:
        return None
    first_arg = node.args[0]
    if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
        return None

    module_name = first_arg.value
    if module_name.startswith("."):
        level = len(module_name) - len(module_name.lstrip("."))
        relative_module = module_name[level:] or None
        return resolve_import_path(source_file, relative_module, level)
    return module_name


def extract_import_records(source_file: SourceFile) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    tree = ast.parse(source_file.text, filename=source_file.source_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    ImportRecord(
                        source_path=source_file.source_path,
                        source_root=source_file.source_root,
                        source_module=source_file.source_module,
                        source_layer=source_file.source_layer,
                        import_path=alias.name,
                        target_module=build_target_module(alias.name),
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            import_path = resolve_import_path(source_file, node.module, node.level)
            if not import_path:
                continue
            records.append(
                ImportRecord(
                    source_path=source_file.source_path,
                    source_root=source_file.source_root,
                    source_module=source_file.source_module,
                    source_layer=source_file.source_layer,
                    import_path=import_path,
                    target_module=build_target_module(import_path),
                    lineno=node.lineno,
                )
            )
        elif isinstance(node, ast.Call) and is_dynamic_import_call(node):
            import_path = resolve_dynamic_import_path(source_file, node)
            if not import_path:
                continue
            records.append(
                ImportRecord(
                    source_path=source_file.source_path,
                    source_root=source_file.source_root,
                    source_module=source_file.source_module,
                    source_layer=source_file.source_layer,
                    import_path=import_path,
                    target_module=build_target_module(import_path),
                    lineno=node.lineno,
                )
            )

    return records


def collect_import_records(source_files: Sequence[SourceFile]) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    for source_file in source_files:
        records.extend(extract_import_records(source_file))
    return records


def collect_line_records(source_files: Sequence[SourceFile]) -> list[LineRecord]:
    records: list[LineRecord] = []
    for source_file in source_files:
        for lineno, line_text in enumerate(source_file.text.splitlines(), start=1):
            stripped = line_text.strip()
            if not stripped or stripped.startswith("#"):
                continue
            records.append(
                LineRecord(
                    source_path=source_file.source_path,
                    source_root=source_file.source_root,
                    source_module=source_file.source_module,
                    source_layer=source_file.source_layer,
                    lineno=lineno,
                    line_text=line_text,
                )
            )
    return records


def rule_matches_record(record: ImportRecord | LineRecord, rule: dict) -> bool:
    source_roots = set(rule.get("source_roots", []))
    if source_roots and record.source_root not in source_roots:
        return False

    source_modules = set(rule.get("source_modules", []))
    source_module = rule.get("source_module")
    if source_module:
        source_modules.add(source_module)
    if source_modules and record.source_module not in source_modules:
        return False

    source_layers = set(rule.get("source_layers", []))
    if source_layers and "*" not in source_layers and record.source_layer not in source_layers:
        return False

    path_patterns = rule.get("path_patterns", [])
    if path_patterns and not any(
        re.search(pattern, record.source_path) for pattern in path_patterns
    ):
        return False

    exclude_path_patterns = rule.get("exclude_path_patterns", [])
    if exclude_path_patterns and any(
        re.search(pattern, record.source_path) for pattern in exclude_path_patterns
    ):
        return False

    return True


def find_import_violations(records: Sequence[ImportRecord], rules: Sequence[dict]) -> list[dict]:
    violations: list[dict] = []
    for rule in rules:
        prefixes = rule.get("forbidden_import_prefixes", [])
        patterns = rule.get("forbidden_import_patterns", [])
        forbid_cross_app_infra = bool(rule.get("forbid_cross_app_infrastructure_imports"))
        forbid_same_app_infra = bool(rule.get("forbid_same_app_infrastructure_imports"))
        if (
            not prefixes
            and not patterns
            and not forbid_cross_app_infra
            and not forbid_same_app_infra
        ):
            continue
        for record in records:
            if not rule_matches_record(record, rule):
                continue

            matched = next(
                (prefix for prefix in prefixes if record.import_path.startswith(prefix)),
                None,
            )
            if not matched:
                matched = next(
                    (pattern for pattern in patterns if re.search(pattern, record.import_path)),
                    None,
                )

            if not matched and forbid_cross_app_infra:
                match = re.match(r"^apps\.([^.]+)\.infrastructure(?:\.|$)", record.import_path)
                if match and match.group(1) != record.source_module:
                    matched = "apps.<other>.infrastructure"

            if not matched and forbid_same_app_infra:
                match = re.match(r"^apps\.([^.]+)\.infrastructure(?:\.|$)", record.import_path)
                if match and match.group(1) == record.source_module:
                    matched = "apps.<same>.infrastructure"

            if not matched:
                continue

            violations.append(
                {
                    "rule_id": rule["id"],
                    "source_path": record.source_path,
                    "source_root": record.source_root,
                    "source_module": record.source_module,
                    "source_layer": record.source_layer,
                    "lineno": record.lineno,
                    "kind": "import",
                    "import_path": record.import_path,
                    "matched_pattern": matched,
                    "description": rule["description"],
                    "rationale": rule.get("rationale", ""),
                }
            )

    return sorted(
        violations, key=lambda item: (item["source_path"], item["lineno"], item["rule_id"])
    )


def find_line_violations(records: Sequence[LineRecord], rules: Sequence[dict]) -> list[dict]:
    violations: list[dict] = []
    for rule in rules:
        patterns = rule.get("forbidden_line_patterns", [])
        if not patterns:
            continue
        for record in records:
            if not rule_matches_record(record, rule):
                continue

            matched = next(
                (pattern for pattern in patterns if re.search(pattern, record.line_text)),
                None,
            )
            if not matched:
                continue

            violations.append(
                {
                    "rule_id": rule["id"],
                    "source_path": record.source_path,
                    "source_root": record.source_root,
                    "source_module": record.source_module,
                    "source_layer": record.source_layer,
                    "lineno": record.lineno,
                    "kind": "line",
                    "line_text": record.line_text.strip(),
                    "matched_pattern": matched,
                    "description": rule["description"],
                    "rationale": rule.get("rationale", ""),
                }
            )

    return sorted(
        violations, key=lambda item: (item["source_path"], item["lineno"], item["rule_id"])
    )


def build_module_summary(
    records: list[ImportRecord], module_metadata: dict[str, dict]
) -> list[dict]:
    module_names = [path.name for path in iter_module_dirs(APPS_ROOT)]
    outbound: dict[str, set] = {name: set() for name in module_names}
    inbound: dict[str, set] = {name: set() for name in module_names}

    for record in records:
        if not record.target_module or record.target_module == record.source_module:
            continue
        if record.target_module not in outbound or record.source_module not in outbound:
            continue
        outbound[record.source_module].add(record.target_module)
        inbound[record.target_module].add(record.source_module)

    summaries = []
    for module_name in module_names:
        metadata = module_metadata.get(module_name, {})
        summaries.append(
            {
                "module": module_name,
                "role": metadata.get("role", ""),
                "patterns": metadata.get("patterns", []),
                "note": metadata.get("note", ""),
                "outbound_modules": sorted(outbound[module_name]),
                "inbound_modules": sorted(inbound[module_name]),
                "outbound_count": len(outbound[module_name]),
                "inbound_count": len(inbound[module_name]),
            }
        )
    return summaries


def build_top_counts(violations: Sequence[dict], key: str, label: str) -> list[dict]:
    counter = Counter(item[key] for item in violations)
    return [
        {label: name, "count": count}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def render_ledger_markdown(
    ruleset: dict,
    module_summary: list[dict],
    violations: list[dict],
    audit_report: dict | None = None,
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Module Ledger",
        "",
        f"> Rules version: `{ruleset['version']}`",
        f"> Generated at: `{generated_at}`",
        f"> Scan roots: `{', '.join(ruleset.get('source_roots', DEFAULT_SCAN_ROOTS))}`",
        f"> Boundary rules: `{len(ruleset['boundary_rules'])}`",
        f"> Violations: `{len(violations)}`",
        "",
        "## Boundary Baseline",
        "",
        "| Rule ID | Source | Layers | Forbidden Imports | Rationale |",
        "|---------|--------|--------|-------------------|-----------|",
    ]

    for rule in ruleset["boundary_rules"]:
        layers = ", ".join(rule.get("source_layers", []))
        forbidden = ", ".join(rule.get("forbidden_import_prefixes", []))
        rationale = rule.get("rationale", "")
        source = ", ".join(rule.get("source_modules", []) or [rule.get("source_module", "*")])
        lines.append(f"| `{rule['id']}` | `{source}` | `{layers}` | `{forbidden}` | {rationale} |")

    lines.extend(
        [
            "",
            "## Module Summary",
            "",
            "| Module | Role | Outbound | Inbound | Patterns | Note |",
            "|--------|------|----------|---------|----------|------|",
        ]
    )

    for summary in module_summary:
        patterns = ", ".join(summary["patterns"])
        note = summary["note"]
        outbound = ", ".join(summary["outbound_modules"][:8])
        inbound = ", ".join(summary["inbound_modules"][:8])
        if len(summary["outbound_modules"]) > 8:
            outbound = f"{outbound}, ..."
        if len(summary["inbound_modules"]) > 8:
            inbound = f"{inbound}, ..."
        note_parts = [
            part
            for part in [outbound and f"out: {outbound}", inbound and f"in: {inbound}", note]
            if part
        ]
        lines.append(
            f"| `{summary['module']}` | {summary['role']} | {summary['outbound_count']} | {summary['inbound_count']} | {patterns} | {'; '.join(note_parts)} |"
        )

    lines.extend(["", "## Violations", ""])
    if not violations:
        lines.append("No boundary violations detected.")
    else:
        for violation in violations:
            lines.append(
                f"- `{violation['rule_id']}`: `{violation['source_path']}:{violation['lineno']}` imports `{violation['import_path']}`"
            )

    if audit_report is not None:
        lines.extend(
            [
                "",
                "## Structural Audit",
                "",
                f"- Audit rules: `{audit_report['rule_count']}`",
                f"- Audit violations: `{audit_report['violation_count']}`",
                "",
                "### Top Rules",
                "",
                "| Rule ID | Count |",
                "|---------|-------|",
            ]
        )
        for item in audit_report["top_rules"][:10]:
            lines.append(f"| `{item['rule_id']}` | {item['count']} |")
        lines.extend(
            [
                "",
                "### Top Files",
                "",
                "| Path | Count |",
                "|------|-------|",
            ]
        )
        for item in audit_report["top_files"][:10]:
            lines.append(f"| `{item['source_path']}` | {item['count']} |")

    lines.append("")
    return "\n".join(lines)


def build_report(
    ruleset: dict,
    source_files: Sequence[SourceFile],
    import_records: list[ImportRecord],
    violations: list[dict],
    audit_violations: list[dict] | None = None,
) -> dict:
    module_summary = build_module_summary(import_records, ruleset.get("module_metadata", {}))
    report = {
        "rules_version": ruleset["version"],
        "scan_roots": list(ruleset.get("source_roots", DEFAULT_SCAN_ROOTS)),
        "scanned_files": len(source_files),
        "boundary_rule_count": len(ruleset["boundary_rules"]),
        "violation_count": len(violations),
        "violations": violations,
        "modules": module_summary,
    }
    if audit_violations is not None:
        report["audit"] = {
            "rule_count": len(ruleset.get("audit_rules", [])),
            "violation_count": len(audit_violations),
            "violations": audit_violations,
            "top_rules": build_top_counts(audit_violations, "rule_id", "rule_id"),
            "top_files": build_top_counts(audit_violations, "source_path", "source_path"),
        }
    return report


def print_violations(
    title: str, violations: Sequence[dict], limit: int = MAX_TEXT_VIOLATIONS
) -> None:
    print("")
    print(f"{title}:")
    for violation in list(violations)[:limit]:
        detail = violation.get("import_path") or violation.get("line_text", "")
        print(
            f"- {violation['rule_id']}: {violation['source_path']}:{violation['lineno']} -> {detail}"
        )
    remaining = len(violations) - min(len(violations), limit)
    if remaining > 0:
        print(f"... truncated {remaining} additional violations")


def print_text_report(report: dict) -> None:
    print(f"Architecture rules version: {report['rules_version']}")
    print(f"Scan roots: {', '.join(report['scan_roots'])}")
    print(f"Scanned files: {report['scanned_files']}")
    print(f"Boundary rules: {report['boundary_rule_count']}")
    print(f"Boundary violations: {report['violation_count']}")
    if report["violations"]:
        print_violations("Boundary violations", report["violations"])

    audit_report = report.get("audit")
    if audit_report is None:
        return

    print("")
    print(f"Audit rules: {audit_report['rule_count']}")
    print(f"Audit violations: {audit_report['violation_count']}")
    if audit_report["top_rules"]:
        print("Top audit rules:")
        for item in audit_report["top_rules"][:10]:
            print(f"- {item['rule_id']}: {item['count']}")
    if audit_report["violations"]:
        print_violations("Audit violations", audit_report["violations"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify architecture boundary rules.")
    parser.add_argument(
        "--rules-file",
        default="governance/architecture_rules.json",
        help="Path to the versioned architecture rules file.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--write-ledger",
        help="Write a generated module ledger markdown file to this path.",
    )
    parser.add_argument(
        "--write-report",
        help="Write a JSON report to this path.",
    )
    parser.add_argument(
        "--include-audit",
        action="store_true",
        help="Include report-only structural audit rules in the output.",
    )
    parser.add_argument(
        "--fail-on-audit-violations",
        action="store_true",
        help="Treat audit violations as hard failures in addition to boundary violations.",
    )
    args = parser.parse_args()

    rules_path = (REPO_ROOT / args.rules_file).resolve()
    ruleset = load_rules(rules_path)
    source_roots = tuple(ruleset.get("source_roots", DEFAULT_SCAN_ROOTS))
    source_files = list(iter_source_files(source_roots))
    import_records = collect_import_records(source_files)
    boundary_violations = find_import_violations(import_records, ruleset["boundary_rules"])

    audit_violations: list[dict] | None = None
    if args.include_audit:
        line_records = collect_line_records(source_files)
        audit_rules = ruleset.get("audit_rules", [])
        audit_violations = sorted(
            [
                *find_import_violations(import_records, audit_rules),
                *find_line_violations(line_records, audit_rules),
            ],
            key=lambda item: (item["source_path"], item["lineno"], item["rule_id"], item["kind"]),
        )

    report = build_report(
        ruleset, source_files, import_records, boundary_violations, audit_violations
    )

    if args.write_report:
        report_path = (REPO_ROOT / args.write_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_ledger:
        ledger_path = (REPO_ROOT / args.write_ledger).resolve()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            render_ledger_markdown(
                ruleset,
                report["modules"],
                boundary_violations,
                report.get("audit"),
            ),
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    has_boundary_violations = bool(boundary_violations)
    has_audit_violations = bool(audit_violations)
    if has_boundary_violations or (args.fail_on_audit_violations and has_audit_violations):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
