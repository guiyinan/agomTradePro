import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "governance/architecture_rules.json"


def load_architecture_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


@pytest.mark.guardrail
def test_guardrail_architecture_boundaries_have_no_violations():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_architecture.py",
            "--rules-file",
            "governance/architecture_rules.json",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    report = json.loads(result.stdout)
    ruleset = load_architecture_rules()
    assert report["rules_version"] == ruleset["version"]
    assert report["scan_roots"] == ruleset["source_roots"]
    assert report["violation_count"] == 0
    rule_ids = {rule["id"] for rule in ruleset["boundary_rules"]}

    assert "regime_runtime_no_macro_impl_imports" in rule_ids
    assert "events_no_direct_downstream_models_or_handlers" in rule_ids
    assert "account_interface_no_simulated_trading_orm_imports" in rule_ids
    assert "apps_application_no_cross_app_infrastructure_imports" in rule_ids


@pytest.mark.guardrail
def test_guardrail_architecture_audit_report_can_be_generated(tmp_path):
    report_path = tmp_path / "architecture-audit.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_architecture.py",
            "--rules-file",
            "governance/architecture_rules.json",
            "--format",
            "text",
            "--include-audit",
            "--fail-on-audit-violations",
            "--write-report",
            str(report_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ruleset = load_architecture_rules()
    assert report["rules_version"] == ruleset["version"]
    assert report["scan_roots"] == ruleset["source_roots"]
    assert report["violation_count"] == 0
    assert "audit" in report
    assert report["audit"]["rule_count"] == len(ruleset["audit_rules"])
    assert report["audit"]["violation_count"] == 0

    audit_rule_ids = {rule["id"] for rule in ruleset["audit_rules"]}
    assert "core_application_no_cross_app_infrastructure_access" in audit_rule_ids
    assert "shared_no_apps_dependencies" in audit_rule_ids
    assert "apps_application_no_pandas_numpy_imports" in audit_rule_ids
    assert "apps_application_no_transaction_or_get_model" in audit_rule_ids
    assert "apps_no_app_root_model_shim_imports_outside_admin" in audit_rule_ids
    assert "apps_domain_no_external_runtime_imports" in audit_rule_ids
    assert "no_retired_shared_business_compat_imports" in audit_rule_ids
    assert "apps_no_misplaced_app_config" in audit_rule_ids
    assert (
        "apps_application_no_same_app_infrastructure_imports_except_repository_provider"
        in audit_rule_ids
    )
    assert "apps_domain_no_application_or_infrastructure_imports" in audit_rule_ids


@pytest.mark.guardrail
def test_guardrail_module_ledger_can_be_generated(tmp_path):
    ledger_path = tmp_path / "module-ledger.md"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_architecture.py",
            "--rules-file",
            "governance/architecture_rules.json",
            "--write-ledger",
            str(ledger_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    content = ledger_path.read_text(encoding="utf-8")
    assert "# Module Ledger" in content
    assert "regime_runtime_no_macro_impl_imports" in content
    assert "`regime`" in content
    assert "No boundary violations detected." in content


@pytest.mark.guardrail
def test_guardrail_module_cycles_have_no_regressions():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_module_cycles.py",
            "--allowlist-file",
            "governance/module_cycle_allowlist.json",
            "--fail-on-cycles",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout or result.stderr
    report = json.loads(result.stdout)
    assert report["bidirectional_pair_count"] == 0
    assert report["cycle_component_count"] == 0
    assert report["edge_count"] <= report["max_app_import_edges"]
    assert report["edge_budget_exceeded"] is False
    assert report["edge_budget_stale"] is False
    assert report["observed_max_outbound_modules"] <= report["max_outbound_modules_per_app"]
    assert report["outbound_budget_stale"] is False
    assert report["outbound_budget_exceeded"] == []
    assert report["observed_max_inbound_modules"] <= report["max_inbound_modules_per_app"]
    assert report["inbound_budget_stale"] is False
    assert report["inbound_budget_exceeded"] == []
    assert len(report["max_outbound_modules_by_app"]) == report["module_count"]
    assert report["outbound_app_budget_exceeded"] == []
    assert report["outbound_app_budget_stale"] == []
    assert report["outbound_app_budget_missing"] == []
    assert len(report["max_inbound_modules_by_app"]) == report["module_count"]
    assert report["inbound_app_budget_exceeded"] == []
    assert report["inbound_app_budget_stale"] == []
    assert report["inbound_app_budget_missing"] == []
    assert report["unexpected_pairs"] == []
    assert report["unexpected_cycle_components"] == []
