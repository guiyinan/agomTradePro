#!/usr/bin/env python
"""Full-repository governance consistency checks.

This check covers repo-wide gaps that are intentionally outside the
diff-only architecture guard: module shape, documentation counters, docs links,
misplaced AppConfig definitions, and known application-layer third-party debt.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "apps"
DOC_INDEX = REPO_ROOT / "docs" / "INDEX.md"
DEFAULT_BASELINE = REPO_ROOT / "governance" / "governance_baseline.json"

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


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "migrations" in path.parts:
            continue
        yield path


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def count_mcp_tools() -> int:
    count = 0
    roots = [REPO_ROOT / "sdk" / "agomtradepro_mcp"]
    for root in roots:
        if not root.exists():
            continue
        for path in iter_python_files(root):
            count += len(re.findall(r"@server\.tool\(", path.read_text(encoding="utf-8")))
    return count


def check_docs_consistency(baseline: dict) -> tuple[list[Violation], dict]:
    violations: list[Violation] = []
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

    baseline_doc = REPO_ROOT / "docs" / "governance" / "SYSTEM_BASELINE.md"
    if baseline_doc.exists() and "35/35" not in baseline_doc.read_text(encoding="utf-8"):
        violations.append(
            Violation(
                "module_coverage_doc_stale",
                rel(baseline_doc),
                "SYSTEM_BASELINE.md must contain current module coverage 35/35.",
            )
        )

    return violations, {
        "actual_mcp_tool_count": actual_count,
        "expected_mcp_tool_count": expected_count,
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
    for path in sorted(set(allowed) - set(actual)):
        # Debt was removed; keep this as a report hint but not a failure.
        pass

    return violations, actual


def build_report(baseline: dict) -> dict:
    sections = []
    violations: list[Violation] = []

    for name, checker in [
        ("docs_consistency", lambda: check_docs_consistency(baseline)),
        ("docs_links", check_docs_links),
        ("module_shape", lambda: check_module_shape(baseline)),
        ("misplaced_app_config", check_misplaced_app_config),
        ("singular_dto_files", check_singular_dto_files),
        (
            "application_third_party_imports",
            lambda: check_application_third_party_baseline(baseline),
        ),
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
