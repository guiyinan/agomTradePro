import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_governance_script():
    script_path = REPO_ROOT / "scripts" / "check_governance_consistency.py"
    module_name = "test_check_governance_consistency_script"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.guardrail
def test_guardrail_governance_consistency_has_no_regressions():
    baseline_path = REPO_ROOT / "governance" / "governance_baseline.json"
    expected_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_governance_consistency.py",
            "--baseline",
            str(baseline_path.relative_to(REPO_ROOT)),
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
    assert report["baseline_version"] == expected_baseline["version"]
    assert report["violation_count"] == 0
    docs_data = next(
        section["data"] for section in report["sections"] if section["name"] == "docs_consistency"
    )
    assert docs_data["actual_business_module_count"] == expected_baseline["business_module_count"]
    assert docs_data["expected_business_module_count"] == expected_baseline["business_module_count"]
    assert (
        docs_data["actual_static_test_function_count"]
        == expected_baseline["static_test_function_count"]
    )
    assert (
        docs_data["expected_static_test_function_count"]
        == expected_baseline["static_test_function_count"]
    )
    assert docs_data["core_version"] == "0.7.0"
    assert docs_data["pyproject_version"] == docs_data["core_version"]

    section_names = {section["name"] for section in report["sections"]}
    assert section_names == {
        "governance_baseline",
        "docs_consistency",
        "docs_links",
        "governance_docs",
        "module_shape",
        "misplaced_app_config",
        "singular_dto_files",
        "architecture_ruleset",
        "module_dependency_baseline",
        "ci_governance_wiring",
        "application_third_party_imports",
        "core_integration_debt",
        "core_management_command_debt",
        "large_python_files",
    }

    sections = {section["name"]: section for section in report["sections"]}
    governance_baseline = sections["governance_baseline"]["data"]
    assert governance_baseline["baseline_version"] == expected_baseline["version"]
    assert governance_baseline["missing_required_keys"] == []
    assert governance_baseline["module_shape_entry_count"] == expected_baseline[
        "business_module_count"
    ]

    governance_docs = sections["governance_docs"]["data"]
    assert governance_docs["required_token_count"] > 0
    assert governance_docs["missing_tokens"] == []

    architecture_ruleset = sections["architecture_ruleset"]["data"]
    assert architecture_ruleset["rules_version"] == "2026-06-30.v8"
    assert architecture_ruleset["boundary_rule_count"] > 0
    assert architecture_ruleset["audit_rule_count"] > 0
    assert architecture_ruleset["duplicate_rule_ids"] == []

    module_dependency_baseline = sections["module_dependency_baseline"]["data"]
    assert module_dependency_baseline["baseline_version"] == "2026-06-30.v1"
    assert module_dependency_baseline["module_count"] == expected_baseline[
        "business_module_count"
    ]
    assert module_dependency_baseline["outbound_budget_count"] == expected_baseline[
        "business_module_count"
    ]
    assert module_dependency_baseline["inbound_budget_count"] == expected_baseline[
        "business_module_count"
    ]

    ci_governance_wiring = sections["ci_governance_wiring"]["data"]
    assert ci_governance_wiring["architecture_workflow"] == (
        ".github/workflows/architecture-layer-guard.yml"
    )
    assert ci_governance_wiring["consistency_workflow"] == (
        ".github/workflows/consistency-check.yml"
    )
    assert ci_governance_wiring["architecture_required_token_count"] > 0
    assert ci_governance_wiring["consistency_required_token_count"] > 0

    core_integration_debt = sections["core_integration_debt"]["data"]
    assert (
        core_integration_debt["actual_infrastructure_import_count"]
        == expected_baseline["core_integration_app_infrastructure_import_count"]
    )
    assert (
        core_integration_debt["actual_orm_access_count"]
        == expected_baseline["core_integration_orm_access_count"]
    )

    core_management_command_debt = sections["core_management_command_debt"]["data"]
    assert (
        core_management_command_debt["actual_infrastructure_import_count"]
        == expected_baseline["core_management_command_app_infrastructure_import_count"]
    )
    assert (
        core_management_command_debt["actual_orm_access_count"]
        == expected_baseline["core_management_command_orm_access_count"]
    )

    large_files = sections["large_python_files"]["data"]
    assert large_files["line_limit"] == expected_baseline["python_file_non_empty_line_limit"]
    assert large_files["allowed_large_file_count"] == len(
        expected_baseline["allowed_large_python_files"]
    )


def test_large_python_file_baseline_detects_missing_growth_and_stale(monkeypatch):
    module = _load_governance_script()
    monkeypatch.setattr(
        module,
        "collect_large_python_files",
        lambda _limit: {
            "apps/new/application/use_cases.py": 1201,
            "apps/old/application/use_cases.py": 1301,
            "apps/stable/application/use_cases.py": 1250,
        },
    )

    violations, data = module.check_large_python_file_baseline(
        {
            "python_file_non_empty_line_limit": 1200,
            "allowed_large_python_files": {
                "apps/old/application/use_cases.py": 1300,
                "apps/stable/application/use_cases.py": 1250,
                "apps/resolved/application/use_cases.py": 1500,
            },
        }
    )

    assert data["line_limit"] == 1200
    assert data["large_file_count"] == 3
    assert {violation.code for violation in violations} == {
        "large_python_file_missing_baseline",
        "large_python_file_growth",
        "large_python_file_baseline_stale",
    }


def test_module_count_line_detection_requires_module_keyword():
    module = _load_governance_script()

    assert module.line_mentions_module_count("37 个业务模块", 37)
    assert module.line_mentions_module_count("37 business modules", 37)
    assert module.line_mentions_module_count("business_modules-37", 37)
    assert not module.line_mentions_module_count("2026-06-37 unrelated date", 37)


def test_test_count_line_detection_accepts_plain_and_comma_formats():
    module = _load_governance_script()

    assert module.line_mentions_test_count("静态测试函数数：5898", 5898)
    assert module.line_mentions_test_count("tests-5,898", 5898)
    assert module.line_mentions_test_count("5,898 static test functions", 5898)
    assert not module.line_mentions_test_count("5,898 modules", 5898)


def test_docs_consistency_detects_pyproject_version_mismatch(monkeypatch, tmp_path):
    module = _load_governance_script()
    monkeypatch.setattr(module, "load_core_version", lambda: "0.7.0")
    monkeypatch.setattr(module, "load_pyproject_version", lambda: "0.1.0")
    monkeypatch.setattr(module, "count_mcp_tools", lambda: 358)
    monkeypatch.setattr(module, "count_business_modules", lambda: 37)
    monkeypatch.setattr(module, "count_static_test_functions", lambda: 5898)

    violations, data = module.check_docs_consistency(
        {
            "mcp_tool_count": 358,
            "business_module_count": 37,
            "static_test_function_count": 5898,
        }
    )

    assert data["core_version"] == "0.7.0"
    assert data["pyproject_version"] == "0.1.0"
    assert any(
        violation.code == "version_pyproject_mismatch"
        and violation.path == "pyproject.toml"
        for violation in violations
    )

    invalid_rules = {
        "version": "bad-version",
        "boundary_rules": [
            {
                "id": "duplicate_rule",
                "description": "Blocks direct infrastructure access.",
                "rationale": "Keep layers separated.",
                "source_roots": ["apps"],
                "forbidden_import_patterns": [r"^apps\..*\.infrastructure"],
            },
            {
                "id": "duplicate_rule",
                "description": "",
                "rationale": "",
                "source_roots": ["apps"],
            },
        ],
        "audit_rules": [],
    }
    invalid_rules_path = tmp_path / "architecture_rules.json"
    invalid_rules_path.write_text(json.dumps(invalid_rules), encoding="utf-8")
    monkeypatch.setattr(module, "ARCHITECTURE_RULES", invalid_rules_path)

    rule_violations, rule_data = module.check_architecture_ruleset_health()

    assert rule_data["rules_version"] == "bad-version"
    assert {violation.code for violation in rule_violations} >= {
        "architecture_rules_version_invalid",
        "architecture_rule_group_empty",
        "architecture_rule_id_duplicate",
        "architecture_rule_metadata_missing",
        "architecture_rule_matcher_missing",
    }

    stale_guardrails_doc = tmp_path / "ARCHITECTURE_GUARDRAILS.md"
    stale_guardrails_doc.write_text("# Architecture Guardrails\n", encoding="utf-8")
    monkeypatch.setattr(module, "ARCHITECTURE_GUARDRAILS_DOC", stale_guardrails_doc)

    docs_violations, docs_data = module.check_governance_docs_current()

    assert docs_data["missing_tokens"]
    assert {violation.code for violation in docs_violations} == {
        "governance_guardrails_doc_stale"
    }

    invalid_baseline = {
        "version": "bad-version",
        "mcp_tool_count": -1,
        "business_module_count": True,
        "module_shape_minimums": {
            "account": 99,
            "unknown_app": 1,
        },
        "allowed_application_third_party_imports": {
            "apps/alpha/application/tasks.py": {
                "requests": 1,
            }
        },
        "python_file_non_empty_line_limit": 0,
        "allowed_large_python_files": {
            "README.md": "many",
        },
    }
    baseline_violations, baseline_data = module.check_governance_baseline_health(
        invalid_baseline
    )

    assert baseline_data["baseline_version"] == "bad-version"
    assert {violation.code for violation in baseline_violations} >= {
        "governance_baseline_required_key_missing",
        "governance_baseline_version_invalid",
        "governance_baseline_count_invalid",
        "governance_baseline_unknown_module",
        "governance_baseline_module_shape_score_invalid",
        "governance_baseline_module_shape_missing",
        "governance_baseline_application_import_value_invalid",
        "governance_baseline_large_file_limit_invalid",
        "governance_baseline_large_file_value_invalid",
    }

    invalid_allowlist = {
        "version": "bad-version",
        "description": "",
        "max_app_import_edges": 0,
        "max_outbound_modules_per_app": 99,
        "max_inbound_modules_per_app": 99,
        "max_outbound_modules_by_app": {
            "account": 1,
            "unknown_app": 1,
        },
        "max_inbound_modules_by_app": {
            "account": -1,
        },
        "allowed_bidirectional_pairs": [["account"], ["account", "unknown_app"]],
        "allowed_cycle_components": "not-a-list",
    }
    invalid_allowlist_path = tmp_path / "module_cycle_allowlist.json"
    invalid_allowlist_path.write_text(json.dumps(invalid_allowlist), encoding="utf-8")
    monkeypatch.setattr(module, "MODULE_CYCLE_ALLOWLIST", invalid_allowlist_path)

    dependency_violations, dependency_data = (
        module.check_module_dependency_baseline_health()
    )

    assert dependency_data["baseline_version"] == "bad-version"
    assert {violation.code for violation in dependency_violations} >= {
        "module_dependency_baseline_version_invalid",
        "module_dependency_baseline_description_missing",
        "module_dependency_budget_missing_module",
        "module_dependency_budget_unknown_module",
        "module_dependency_budget_value_invalid",
        "module_dependency_global_outbound_budget_mismatch",
        "module_dependency_global_inbound_budget_mismatch",
        "module_dependency_edge_budget_invalid",
        "module_dependency_allowlist_invalid",
        "module_dependency_allowlist_entry_invalid",
    }

    monkeypatch.setattr(
        module,
        "collect_core_integration_debt",
        lambda: {
            "infrastructure_import_count": 3,
            "orm_access_count": 1,
            "files": {},
        },
    )

    growth_violations, growth_data = module.check_core_integration_debt_baseline(
        {
            "core_integration_app_infrastructure_import_count": 2,
            "core_integration_orm_access_count": 0,
        }
    )
    assert growth_data["actual_infrastructure_import_count"] == 3
    assert {violation.code for violation in growth_violations} == {
        "core_integration_infrastructure_import_growth",
        "core_integration_orm_access_growth",
    }

    stale_violations, stale_data = module.check_core_integration_debt_baseline(
        {
            "core_integration_app_infrastructure_import_count": 4,
            "core_integration_orm_access_count": 2,
        }
    )
    assert stale_data["actual_orm_access_count"] == 1
    assert {violation.code for violation in stale_violations} == {
        "core_integration_infrastructure_import_baseline_stale",
        "core_integration_orm_access_baseline_stale",
    }

    monkeypatch.setattr(
        module,
        "collect_core_management_command_debt",
        lambda: {
            "infrastructure_import_count": 5,
            "orm_access_count": 4,
            "files": {},
        },
    )

    command_growth_violations, command_growth_data = (
        module.check_core_management_command_debt_baseline(
            {
                "core_management_command_app_infrastructure_import_count": 4,
                "core_management_command_orm_access_count": 3,
            }
        )
    )
    assert command_growth_data["actual_infrastructure_import_count"] == 5
    assert {violation.code for violation in command_growth_violations} == {
        "core_management_command_infrastructure_import_growth",
        "core_management_command_orm_access_growth",
    }

    command_stale_violations, command_stale_data = (
        module.check_core_management_command_debt_baseline(
            {
                "core_management_command_app_infrastructure_import_count": 6,
                "core_management_command_orm_access_count": 5,
            }
        )
    )
    assert command_stale_data["actual_orm_access_count"] == 4
    assert {violation.code for violation in command_stale_violations} == {
        "core_management_command_infrastructure_import_baseline_stale",
        "core_management_command_orm_access_baseline_stale",
    }

    bad_architecture_workflow = tmp_path / "architecture-layer-guard.yml"
    bad_architecture_workflow.write_text("name: Architecture Layer Guard\n", encoding="utf-8")
    bad_consistency_workflow = tmp_path / "consistency-check.yml"
    bad_consistency_workflow.write_text("name: Consistency Check\n", encoding="utf-8")
    monkeypatch.setattr(module, "ARCHITECTURE_WORKFLOW", bad_architecture_workflow)
    monkeypatch.setattr(module, "CONSISTENCY_WORKFLOW", bad_consistency_workflow)

    wiring_violations, wiring_data = module.check_ci_governance_wiring()

    assert wiring_data["architecture_workflow"].endswith("architecture-layer-guard.yml")
    assert wiring_data["consistency_workflow"].endswith("consistency-check.yml")
    assert {violation.code for violation in wiring_violations} == {
        "ci_governance_workflow_token_missing"
    }
