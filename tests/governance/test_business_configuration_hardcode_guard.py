"""Executable evidence for the repository Business Configuration Guard."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.check_business_configuration_hardcodes import (
    DEFAULT_MANIFEST,
    RULE_ALLOCATION_MATRIX,
    RULE_DECISION_THRESHOLD,
    RULE_DEFAULT_PRINCIPAL,
    RULE_HISTORICAL_SCENARIO_CATALOG,
    RULE_POLICY_MULTIPLIER,
    RULE_STATIC_FALLBACK,
    BusinessConfigurationFinding,
    evaluate_business_configuration_guard,
    scan_source,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "business_configuration_hardcode_guard"


def _scan_fixture(filename: str) -> list[BusinessConfigurationFinding]:
    """Return AST findings for one mutation-style source fixture."""

    path = FIXTURE_ROOT / filename
    return scan_source(
        path.read_text(encoding="utf-8"),
        relative_path=f"tests/governance/fixtures/{filename}",
    )


def test_repository_business_configuration_full_scan_is_green() -> None:
    """The authoritative repository scan permits only exact, unexpired migration items."""

    report = evaluate_business_configuration_guard(as_of=date(2026, 8, 5))

    assert report.scanned_files > 0
    assert report.violations == ()
    assert report.findings == report.accepted_findings


@pytest.mark.parametrize(
    ("filename", "expected_rules"),
    [
        (
            "negative_historical_scenarios.py",
            {RULE_HISTORICAL_SCENARIO_CATALOG},
        ),
        ("negative_allocation_matrix.py", {RULE_ALLOCATION_MATRIX}),
        ("negative_policy_multiplier.py", {RULE_POLICY_MULTIPLIER}),
        ("negative_static_fallback.py", {RULE_STATIC_FALLBACK}),
        (
            "negative_threshold_and_principal.py",
            {RULE_DECISION_THRESHOLD, RULE_DEFAULT_PRINCIPAL},
        ),
    ],
)
def test_negative_fixtures_are_rejected(
    filename: str,
    expected_rules: set[str],
) -> None:
    """Reintroducing each legacy business-configuration shape stays detectable."""

    findings = _scan_fixture(filename)

    assert {item.rule_id for item in findings} == expected_rules
    assert {item.classification for item in findings} == {"mutable_business_configuration"}


@pytest.mark.parametrize(
    "filename",
    [
        "positive_repository_configuration.py",
        "positive_domain_invariants.py",
    ],
)
def test_repository_ports_enums_schemas_and_unit_invariants_are_allowed(
    filename: str,
) -> None:
    """Typed repository reads and stable invariants are not mutable configuration."""

    assert _scan_fixture(filename) == []


def test_manifest_declares_all_four_configuration_classifications() -> None:
    """The machine contract distinguishes mutable settings from valid constants."""

    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    assert set(payload["classifications"]) == {
        "mutable_business_configuration",
        "domain_invariant",
        "schema_or_protocol_constant",
        "test_fixture",
    }
    assert payload["scan"]["authoritative_mode"] == "full"
    assert all(
        contract["runtime_fallback_policy"] == "forbidden" for contract in payload["contracts"]
    )


def test_temporary_exception_is_bound_to_exact_ast_fingerprint() -> None:
    """Editing an excepted legacy block creates both a new finding and stale exception."""

    with TemporaryDirectory(prefix=".business-config-guard-", dir=Path.cwd()) as raw_tmp:
        tmp_path = Path(raw_tmp)
        source_path = tmp_path / "apps" / "example" / "application" / "config.py"
        source_path.parent.mkdir(parents=True)
        source = (FIXTURE_ROOT / "negative_policy_multiplier.py").read_text(encoding="utf-8")
        source_path.write_text(source, encoding="utf-8")
        finding = scan_source(
            source,
            relative_path="apps/example/application/config.py",
        )[0]

        payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        payload["scan"]["roots"] = ["apps"]
        payload["scan"]["include_patterns"] = ["apps/*/application/*.py"]
        payload["temporary_exceptions"] = [
            {
                "rule_id": finding.rule_id,
                "path": finding.path,
                "symbol": finding.symbol,
                "ast_fingerprint": finding.ast_fingerprint,
                "owner": "strategy",
                "reason": "focused test of exact migration exception matching",
                "expires_on": "2026-08-31",
                "replacement_plan": "remove the fixture",
            }
        ]
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        accepted = evaluate_business_configuration_guard(
            manifest,
            repo_root=tmp_path,
            as_of=date(2026, 8, 5),
        )
        assert accepted.violations == ()
        assert accepted.accepted_findings == accepted.findings

        source_path.write_text(source.replace("0.3", "0.2"), encoding="utf-8")
        changed = evaluate_business_configuration_guard(
            manifest,
            repo_root=tmp_path,
            as_of=date(2026, 8, 5),
        )

        assert {item.code for item in changed.violations} == {
            "mutable_business_configuration",
            "stale_or_changed_exception",
        }
