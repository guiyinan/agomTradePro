#!/usr/bin/env python
"""
Verify architecture boundary rules and generate a module ledger.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"
LAYER_NAMES = ("application", "domain", "infrastructure", "interface", "management")


@dataclass(frozen=True)
class ImportRecord:
    source_path: str
    source_module: str
    source_layer: str
    import_path: str
    target_module: Optional[str]
    lineno: int


def load_rules(rules_path: Path) -> dict:
    return json.loads(rules_path.read_text(encoding="utf-8"))


def iter_module_dirs(apps_root: Path) -> List[Path]:
    return sorted(
        path
        for path in apps_root.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )


def iter_python_files(module_dir: Path) -> Iterable[Path]:
    for path in sorted(module_dir.rglob("*.py")):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def detect_layer(path: Path) -> str:
    for part in path.parts:
        if part in LAYER_NAMES:
            return part
    return "other"


def extract_import_records(path: Path) -> List[ImportRecord]:
    records: List[ImportRecord] = []
    source_path = path.relative_to(REPO_ROOT).as_posix()
    parts = source_path.split("/")
    source_module = parts[1] if len(parts) > 1 else "unknown"
    source_layer = detect_layer(path.relative_to(REPO_ROOT))

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=source_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_path = alias.name
                target_module = import_path.split(".")[1] if import_path.startswith("apps.") else None
                records.append(
                    ImportRecord(
                        source_path=source_path,
                        source_module=source_module,
                        source_layer=source_layer,
                        import_path=import_path,
                        target_module=target_module,
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                continue
            import_path = node.module
            target_module = import_path.split(".")[1] if import_path.startswith("apps.") else None
            records.append(
                ImportRecord(
                    source_path=source_path,
                    source_module=source_module,
                    source_layer=source_layer,
                    import_path=import_path,
                    target_module=target_module,
                    lineno=node.lineno,
                )
            )
    return records


def collect_import_records(apps_root: Path) -> List[ImportRecord]:
    records: List[ImportRecord] = []
    for module_dir in iter_module_dirs(apps_root):
        for path in iter_python_files(module_dir):
            records.extend(extract_import_records(path))
    return records


def find_boundary_violations(records: List[ImportRecord], rules: List[dict]) -> List[dict]:
    violations: List[dict] = []
    for rule in rules:
        allowed_layers = set(rule.get("source_layers", []))
        for record in records:
            if record.source_module != rule["source_module"]:
                continue
            if "*" not in allowed_layers and record.source_layer not in allowed_layers:
                continue
            if any(record.import_path.startswith(prefix) for prefix in rule["forbidden_import_prefixes"]):
                violations.append(
                    {
                        "rule_id": rule["id"],
                        "source_path": record.source_path,
                        "source_module": record.source_module,
                        "source_layer": record.source_layer,
                        "lineno": record.lineno,
                        "import_path": record.import_path,
                        "description": rule["description"],
                        "rationale": rule.get("rationale", ""),
                    }
                )
    return sorted(violations, key=lambda item: (item["source_path"], item["lineno"], item["rule_id"]))


def build_module_summary(records: List[ImportRecord], module_metadata: Dict[str, dict]) -> List[dict]:
    module_names = [path.name for path in iter_module_dirs(APPS_ROOT)]
    outbound: Dict[str, set] = {name: set() for name in module_names}
    inbound: Dict[str, set] = {name: set() for name in module_names}

    for record in records:
        if not record.target_module or record.target_module == record.source_module:
            continue
        if record.target_module not in outbound:
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


def render_ledger_markdown(ruleset: dict, module_summary: List[dict], violations: List[dict]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Module Ledger",
        "",
        f"> Rules version: `{ruleset['version']}`",
        f"> Generated at: `{generated_at}`",
        f"> Boundary rules: `{len(ruleset['boundary_rules'])}`",
        f"> Violations: `{len(violations)}`",
        "",
        "## Boundary Baseline",
        "",
        "| Rule ID | Source | Layers | Forbidden Imports | Rationale |",
        "|---------|--------|--------|-------------------|-----------|",
    ]

    for rule in ruleset["boundary_rules"]:
        layers = ", ".join(rule["source_layers"])
        forbidden = ", ".join(rule["forbidden_import_prefixes"])
        rationale = rule.get("rationale", "")
        lines.append(
            f"| `{rule['id']}` | `{rule['source_module']}` | `{layers}` | `{forbidden}` | {rationale} |"
        )

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
        note_parts = [part for part in [outbound and f"out: {outbound}", inbound and f"in: {inbound}", note] if part]
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
    lines.append("")
    return "\n".join(lines)


def build_report(ruleset: dict, records: List[ImportRecord], violations: List[dict]) -> dict:
    module_summary = build_module_summary(records, ruleset.get("module_metadata", {}))
    return {
        "rules_version": ruleset["version"],
        "scanned_files": len({record.source_path for record in records}),
        "boundary_rule_count": len(ruleset["boundary_rules"]),
        "violation_count": len(violations),
        "violations": violations,
        "modules": module_summary,
    }


def print_text_report(report: dict) -> None:
    print(f"Architecture rules version: {report['rules_version']}")
    print(f"Scanned files: {report['scanned_files']}")
    print(f"Boundary rules: {report['boundary_rule_count']}")
    print(f"Violations: {report['violation_count']}")
    if report["violations"]:
        print("")
        print("Violations:")
        for violation in report["violations"]:
            print(
                f"- {violation['rule_id']}: {violation['source_path']}:{violation['lineno']} -> {violation['import_path']}"
            )


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
    args = parser.parse_args()

    rules_path = (REPO_ROOT / args.rules_file).resolve()
    ruleset = load_rules(rules_path)
    records = collect_import_records(APPS_ROOT)
    violations = find_boundary_violations(records, ruleset["boundary_rules"])
    report = build_report(ruleset, records, violations)

    if args.write_ledger:
        ledger_path = (REPO_ROOT / args.write_ledger).resolve()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            render_ledger_markdown(ruleset, report["modules"], violations),
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
