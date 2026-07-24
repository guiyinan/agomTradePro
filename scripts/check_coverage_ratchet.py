#!/usr/bin/env python
"""Enforce repository, module, and Domain coverage thresholds from one XML report."""

from __future__ import annotations

import argparse
import json
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
    """Covered and executable lines for one reporting scope."""

    covered: int = 0
    valid: int = 0

    @property
    def percent(self) -> float:
        """Return line coverage as a percentage."""
        return 100.0 if self.valid == 0 else self.covered * 100.0 / self.valid


def _merge(left: CoverageTotals, right: CoverageTotals) -> CoverageTotals:
    """Combine two disjoint coverage totals."""
    return CoverageTotals(left.covered + right.covered, left.valid + right.valid)


def parse_coverage_xml(
    path: Path,
) -> tuple[CoverageTotals, dict[str, CoverageTotals], dict[str, CoverageTotals]]:
    """Parse coverage.py XML into repository, module, and Domain totals."""
    root = ET.parse(path).getroot()
    repository = CoverageTotals(
        covered=int(root.attrib["lines-covered"]),
        valid=int(root.attrib["lines-valid"]),
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
        totals = CoverageTotals(
            covered=sum(1 for line in lines if int(line.attrib.get("hits", "0")) > 0),
            valid=len(lines),
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
    domain_module_minimum = float(config["domain_module_minimum"])
    core_modules = {str(item) for item in config["core_modules"]}

    violations: list[str] = []
    if repository.percent + 1e-9 < repository_minimum:
        violations.append(
            f"repository {repository.percent:.1f}% is below {repository_minimum:.1f}%"
        )
    for module, totals in sorted(modules.items()):
        minimum = core_module_minimum if module in core_modules else default_module_minimum
        if totals.percent + 1e-9 < minimum:
            violations.append(f"module {module} {totals.percent:.1f}% is below {minimum:.1f}%")
    for module, totals in sorted(domains.items()):
        if totals.valid and totals.percent + 1e-9 < domain_module_minimum:
            violations.append(
                f"domain {module} {totals.percent:.1f}% is below {domain_module_minimum:.1f}%"
            )
    return violations


def _print_table(label: str, totals: Iterable[tuple[str, CoverageTotals]]) -> None:
    """Print compact scope coverage rows."""
    print(label)
    for name, item in totals:
        print(f"  {name:28} {item.percent:6.1f}% ({item.covered}/{item.valid})")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path)
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
    repository, modules, domains = parse_coverage_xml(args.coverage_xml)
    print(f"Repository: {repository.percent:.1f}% ({repository.covered}/{repository.valid})")
    _print_table("Modules:", sorted(modules.items()))
    _print_table("Domains:", sorted(domains.items()))
    violations = find_violations(repository, modules, domains, baseline)
    for violation in violations:
        print(f"ERROR: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
