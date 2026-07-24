"""Regression tests for the test-tier inventory and coverage ratchet."""

from pathlib import Path

from scripts.check_coverage_ratchet import (
    CoverageTotals,
    find_scope_violations,
    find_violations,
    parse_coverage_xml,
)
from scripts.run_fast_tests import build_pytest_command
from scripts.test_tier_inventory import classify_test_file


def test_inventory_classifies_pure_domain_test_as_fast(tmp_path: Path) -> None:
    """A pure Domain test belongs to the no-database fast suite."""
    test_path = tmp_path / "tests" / "unit" / "test_rule.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from apps.signal.domain.rules import SignalRule\n"
        "def test_rule():\n"
        "    assert SignalRule is not None\n",
        encoding="utf-8",
    )

    result = classify_test_file(test_path, tmp_path)

    assert result.tier == "fast"
    assert result.database_dependent is False


def test_inventory_classifies_django_db_test_as_component(tmp_path: Path) -> None:
    """A database fixture keeps a test out of the Unit and fast tiers."""
    test_path = tmp_path / "tests" / "unit" / "test_repository.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_repository(db):\n" "    assert db is not None\n",
        encoding="utf-8",
    )

    result = classify_test_file(test_path, tmp_path)

    assert result.tier == "component"
    assert result.database_dependent is True
    assert result.reasons == ("fixture:db",)


def test_fast_command_always_loads_database_guard() -> None:
    """The fast runner must activate the collection-time database guard."""
    command = build_pytest_command(["tests/unit/domain/test_policy_rules.py"], ["-x"])

    assert command[-3:] == ["-p", "tests.support.fast_suite_guard", "-x"]
    assert "tests/unit/domain/test_policy_rules.py" in command


def test_coverage_ratchet_reports_repository_module_and_domain_failures() -> None:
    """Coverage failures remain attributable to the exact reporting scope."""
    baseline = {
        "coverage": {
            "repository_minimum": 80,
            "default_module_minimum": 70,
            "core_module_minimum": 80,
            "domain_module_minimum": 90,
            "require_branch_coverage": False,
            "core_modules": ["signal"],
        }
    }

    violations = find_violations(
        CoverageTotals(79, 100),
        {
            "signal": CoverageTotals(79, 100),
            "share": CoverageTotals(69, 100),
        },
        {"signal": CoverageTotals(89, 100)},
        baseline,
    )

    assert violations == [
        "repository 79.0% is below 80.0%",
        "module share 69.0% is below 70.0%",
        "module signal 79.0% is below 80.0%",
        "domain signal 89.0% is below 90.0%",
    ]


def test_coverage_parser_accepts_source_relative_and_repository_paths(
    tmp_path: Path,
) -> None:
    """Coverage XML may report paths relative to either ``apps`` or the repo."""
    report = tmp_path / "coverage.xml"
    report.write_text(
        """<?xml version="1.0"?>
<coverage lines-valid="3" lines-covered="2"
          branches-valid="2" branches-covered="1">
  <packages><package><classes>
    <class filename="alpha/domain/entities.py">
      <lines>
        <line number="1" hits="1" branch="true" condition-coverage="50% (1/2)"/>
        <line number="2" hits="0"/>
      </lines>
    </class>
    <class filename="apps/beta_gate/domain/services.py">
      <lines><line number="1" hits="1"/></lines>
    </class>
    <class filename="apps/beta_gate/domain/protocols.py">
      <lines><line number="1" hits="0"/></lines>
    </class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )

    repository, modules, domains = parse_coverage_xml(report)

    assert repository == CoverageTotals(
        covered=2,
        valid=3,
        branches_covered=1,
        branches_valid=2,
    )
    assert modules == {
        "alpha": CoverageTotals(
            covered=1,
            valid=2,
            branches_covered=1,
            branches_valid=2,
        ),
        "beta_gate": CoverageTotals(covered=1, valid=2),
    }
    assert domains == {
        "alpha": CoverageTotals(
            covered=1,
            valid=2,
            branches_covered=1,
            branches_valid=2,
        ),
        "beta_gate": CoverageTotals(covered=1, valid=1),
    }


def test_scope_ratchet_requires_reports_and_branch_measurement() -> None:
    """Every configured source scope must publish a branch-aware report."""
    baseline = {
        "coverage": {
            "require_branch_coverage": True,
            "required_scopes": ["apps", "core", "shared", "sdk"],
            "scope_minimums": {
                "apps": {"line": 80, "branch": 70},
                "core": {"line": 75, "branch": 60},
            },
        }
    }

    violations = find_scope_violations(
        {
            "apps": CoverageTotals(covered=79, valid=100),
            "core": CoverageTotals(
                covered=80,
                valid=100,
                branches_covered=0,
                branches_valid=0,
            ),
        },
        baseline,
    )

    assert violations == [
        "scope shared report is missing",
        "scope sdk report is missing",
        "scope apps line 79.0% is below 80.0%",
        "scope apps branch coverage was not collected",
        "scope core branch coverage was not collected",
    ]


def test_domain_branch_ratchet_supports_module_specific_floors() -> None:
    """Initial branch ratchets can rise per high-risk Domain without hiding others."""
    baseline = {
        "coverage": {
            "repository_minimum": 0,
            "default_module_minimum": 0,
            "core_module_minimum": 0,
            "domain_module_minimum": 0,
            "repository_branch_minimum": 0,
            "domain_branch_minimum": 0,
            "domain_branch_minimums": {"account": 80},
            "require_branch_coverage": True,
            "core_modules": [],
        }
    }

    violations = find_violations(
        CoverageTotals(
            covered=1,
            valid=1,
            branches_covered=1,
            branches_valid=2,
        ),
        {},
        {
            "account": CoverageTotals(
                covered=1,
                valid=1,
                branches_covered=3,
                branches_valid=4,
            ),
            "data_center": CoverageTotals(
                covered=1,
                valid=1,
                branches_covered=1,
                branches_valid=2,
            ),
        },
        baseline,
    )

    assert violations == ["domain branch account 75.0% is below 80.0%"]
