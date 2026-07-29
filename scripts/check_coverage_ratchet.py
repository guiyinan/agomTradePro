#!/usr/bin/env python
"""Enforce scope, module, Domain, line, and branch coverage thresholds."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN_NON_BEHAVIOR_FILES = frozenset(
    {
        "__init__.py",
        "interfaces.py",
        "protocols.py",
    }
)


@dataclass(frozen=True)
class CoverageTotals:
    """Covered and executable lines and branches for one reporting scope."""

    covered: int = 0
    valid: int = 0
    branches_covered: int = 0
    branches_valid: int = 0

    @property
    def percent(self) -> float:
        """Return line coverage as a percentage."""
        return 100.0 if self.valid == 0 else self.covered * 100.0 / self.valid

    @property
    def branch_percent(self) -> float:
        """Return branch coverage as a percentage."""
        return (
            100.0
            if self.branches_valid == 0
            else self.branches_covered * 100.0 / self.branches_valid
        )


def _merge(left: CoverageTotals, right: CoverageTotals) -> CoverageTotals:
    """Combine two disjoint coverage totals."""
    return CoverageTotals(
        covered=left.covered + right.covered,
        valid=left.valid + right.valid,
        branches_covered=left.branches_covered + right.branches_covered,
        branches_valid=left.branches_valid + right.branches_valid,
    )


BRANCH_COUNTS_PATTERN = re.compile(r"\((?P<covered>\d+)/(?P<valid>\d+)\)")


def _line_branch_totals(lines: Iterable[ET.Element]) -> tuple[int, int]:
    """Return covered and valid branch destinations from coverage.py line nodes."""
    covered = 0
    valid = 0
    for line in lines:
        condition_coverage = line.attrib.get("condition-coverage")
        if not condition_coverage:
            continue
        match = BRANCH_COUNTS_PATTERN.search(condition_coverage)
        if match is None:
            continue
        covered += int(match.group("covered"))
        valid += int(match.group("valid"))
    return covered, valid


def parse_coverage_xml(
    path: Path,
) -> tuple[CoverageTotals, dict[str, CoverageTotals], dict[str, CoverageTotals]]:
    """Parse coverage.py XML into repository, module, and Domain totals."""
    root = ET.parse(path).getroot()
    repository = CoverageTotals(
        covered=int(root.attrib["lines-covered"]),
        valid=int(root.attrib["lines-valid"]),
        branches_covered=int(root.attrib.get("branches-covered", "0")),
        branches_valid=int(root.attrib.get("branches-valid", "0")),
    )
    modules: dict[str, CoverageTotals] = defaultdict(CoverageTotals)
    domains: dict[str, CoverageTotals] = defaultdict(CoverageTotals)
    seen_files: set[str] = set()

    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename", "").replace("\\", "/")
        if filename in seen_files:
            continue
        seen_files.add(filename)
        parts = Path(filename).parts
        if parts and parts[0] == "apps":
            parts = parts[1:]
        if len(parts) < 2:
            continue
        module = parts[0]
        lines = class_node.findall("./lines/line")
        branches_covered, branches_valid = _line_branch_totals(lines)
        totals = CoverageTotals(
            covered=sum(1 for line in lines if int(line.attrib.get("hits", "0")) > 0),
            valid=len(lines),
            branches_covered=branches_covered,
            branches_valid=branches_valid,
        )
        modules[module] = _merge(modules[module], totals)
        if parts[1] == "domain" and parts[-1] not in DOMAIN_NON_BEHAVIOR_FILES:
            domains[module] = _merge(domains[module], totals)
    return repository, dict(modules), dict(domains)


def find_violations(
    repository: CoverageTotals,
    modules: dict[str, CoverageTotals],
    domains: dict[str, CoverageTotals],
    baseline: dict[str, object],
) -> list[str]:
    """Return all threshold violations in stable order."""
    config = baseline["coverage"]
    assert isinstance(config, dict)
    repository_minimum = float(config["repository_minimum"])
    default_module_minimum = float(config["default_module_minimum"])
    core_module_minimum = float(config["core_module_minimum"])
    module_minimums = {
        str(module): float(minimum) for module, minimum in config.get("module_minimums", {}).items()
    }
    domain_module_minimum = float(config["domain_module_minimum"])
    repository_branch_minimum = float(config.get("repository_branch_minimum", 0.0))
    domain_branch_minimum = float(config.get("domain_branch_minimum", 0.0))
    domain_branch_minimums = config.get("domain_branch_minimums", {})
    assert isinstance(domain_branch_minimums, dict)
    require_branch_coverage = bool(config.get("require_branch_coverage", False))
    core_modules = {str(item) for item in config["core_modules"]}

    violations: list[str] = []
    if repository.percent + 1e-9 < repository_minimum:
        violations.append(
            f"repository {repository.percent:.1f}% is below {repository_minimum:.1f}%"
        )
    if require_branch_coverage and repository.branches_valid == 0:
        violations.append("repository branch coverage was not collected")
    elif repository.branch_percent + 1e-9 < repository_branch_minimum:
        violations.append(
            "repository branch "
            f"{repository.branch_percent:.1f}% is below {repository_branch_minimum:.1f}%"
        )
    for module, totals in sorted(modules.items()):
        minimum = module_minimums.get(
            module,
            core_module_minimum if module in core_modules else default_module_minimum,
        )
        if totals.percent + 1e-9 < minimum:
            violations.append(f"module {module} {totals.percent:.1f}% is below {minimum:.1f}%")
    for module, totals in sorted(domains.items()):
        if totals.valid and totals.percent + 1e-9 < domain_module_minimum:
            violations.append(
                f"domain {module} {totals.percent:.1f}% is below {domain_module_minimum:.1f}%"
            )
        module_branch_minimum = float(domain_branch_minimums.get(module, domain_branch_minimum))
        if totals.branches_valid and totals.branch_percent + 1e-9 < module_branch_minimum:
            violations.append(
                "domain branch "
                f"{module} {totals.branch_percent:.1f}% is below "
                f"{module_branch_minimum:.1f}%"
            )
    return violations


def find_scope_violations(
    scopes: dict[str, CoverageTotals],
    baseline: dict[str, object],
) -> list[str]:
    """Return missing-report and scope-level line/branch threshold failures."""
    config = baseline["coverage"]
    assert isinstance(config, dict)
    required_scopes = [str(item) for item in config.get("required_scopes", [])]
    scope_minimums = config.get("scope_minimums", {})
    assert isinstance(scope_minimums, dict)
    require_branch_coverage = bool(config.get("require_branch_coverage", False))

    violations: list[str] = []
    for scope in required_scopes:
        if scope not in scopes:
            violations.append(f"scope {scope} report is missing")
    for scope, thresholds in sorted(scope_minimums.items()):
        if scope not in scopes:
            continue
        assert isinstance(thresholds, dict)
        totals = scopes[scope]
        line_minimum = float(thresholds.get("line", 0.0))
        branch_minimum = float(thresholds.get("branch", 0.0))
        if totals.percent + 1e-9 < line_minimum:
            violations.append(
                f"scope {scope} line {totals.percent:.1f}% is below {line_minimum:.1f}%"
            )
        if require_branch_coverage and totals.branches_valid == 0:
            violations.append(f"scope {scope} branch coverage was not collected")
        elif totals.branch_percent + 1e-9 < branch_minimum:
            violations.append(
                "scope "
                f"{scope} branch {totals.branch_percent:.1f}% is below "
                f"{branch_minimum:.1f}%"
            )
    return violations


def _print_table(label: str, totals: Iterable[tuple[str, CoverageTotals]]) -> None:
    """Print compact scope coverage rows."""
    print(label)
    for name, item in totals:
        print(
            f"  {name:28} line {item.percent:6.1f}% ({item.covered}/{item.valid}) "
            f"branch {item.branch_percent:6.1f}% "
            f"({item.branches_covered}/{item.branches_valid})"
        )


def _parse_scope_report(value: str) -> tuple[str, Path]:
    """Parse ``NAME=PATH`` CLI values."""
    scope, separator, path = value.partition("=")
    if not separator or not scope.strip() or not path.strip():
        raise argparse.ArgumentTypeError("scope reports must use NAME=PATH")
    return scope.strip(), Path(path.strip())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path, nargs="?")
    parser.add_argument(
        "--scope-report",
        action="append",
        type=_parse_scope_report,
        default=[],
        metavar="NAME=PATH",
        help="add a separately generated coverage XML report for one source scope",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=REPO_ROOT / "governance" / "testing_quality_baseline.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Check a coverage report against the configured ratchet."""
    args = parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    report_paths = dict(args.scope_report)
    if args.coverage_xml is not None:
        report_paths.setdefault("apps", args.coverage_xml)
    if not report_paths:
        raise SystemExit("at least one coverage XML or --scope-report is required")

    parsed_reports = {
        scope: parse_coverage_xml(path) for scope, path in sorted(report_paths.items())
    }
    primary_scope = "apps" if "apps" in parsed_reports else next(iter(parsed_reports))
    repository, modules, domains = parsed_reports[primary_scope]
    scope_totals = {scope: parsed[0] for scope, parsed in parsed_reports.items()}
    _print_table("Scopes:", sorted(scope_totals.items()))
    _print_table("Modules:", sorted(modules.items()))
    _print_table("Domains:", sorted(domains.items()))
    violations = find_violations(repository, modules, domains, baseline)
    violations.extend(find_scope_violations(scope_totals, baseline))
    for violation in violations:
        print(f"ERROR: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
