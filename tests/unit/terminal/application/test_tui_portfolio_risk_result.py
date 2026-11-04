"""User-facing projection contracts for read-only portfolio risk reports."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    validate_tui_metadata,
)
from apps.terminal.application.tui_portfolio_risk_result import project_portfolio_risk_result
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading_owner_actions import (
    build_portfolio_pressure_run_action,
    build_portfolio_risk_report_action,
)


def _report(*, outcome: str = "unknown") -> dict[str, object]:
    """Build one nonempty report carrying source clocks and explained unknowns."""

    return {
        "account_id": 42,
        "as_of": "2026-11-03T02:00:00+00:00",
        "outcome": outcome,
        "policy_version": "portfolio-policy-v7",
        "resource_snapshot_hash": "a" * 64,
        "checks": [
            {
                "dimension": "退出流动性",
                "status": "unknown",
                "reason_codes": ["liquidity_history_stale"],
                "summary": "历史成交覆盖不足且来源已过期，无法确认压力窗口中的可卖能力。",
                "details": {"window_days": 5, "coverage_fraction": "0.40"},
            }
        ],
        "sources": [
            {
                "source_id": "published-price-bars",
                "source_record_id": "publication-91:600000.SH",
                "raw_payload_sha256": "b" * 64,
                "observed_at": "2026-11-02T00:00:00+00:00",
                "observed_on": None,
                "observation_precision": "date",
                "available_at": "2026-11-02T01:00:00+00:00",
                "known_at": "2026-11-02T01:03:00+00:00",
                "cutoff": "2026-11-03T02:00:00+00:00",
                "valid_until": "2026-11-03T01:59:00+00:00",
                "purpose": "scenario_exit_pressure",
                "restrictions": ["historical_only", "not_execution_price"],
                "must_not_use_for_decision": False,
                "coverage_fraction": "0.40",
                "coverage_basis": "positions_with_source_bars",
            }
        ],
        "scope": "simulation_only",
        "must_not_execute": True,
    }


def test_projection_shows_unknown_reason_versions_and_actual_source_times() -> None:
    """Unknown business outcomes remain visible with source coverage and clocks."""

    view_model = project_portfolio_risk_result(_report(), http_status=200)

    assert view_model is not None
    assert view_model["outcome"] == "unknown"
    assert view_model["scope"] == "simulation_only"
    assert view_model["must_not_execute"] is True
    fields = view_model["fields"]
    assert isinstance(fields, list)
    rendered = "\n".join(str(item.get("value", "")) for item in fields if isinstance(item, dict))
    assert "关键风险数据未知" in rendered
    assert "portfolio-policy-v7" in rendered
    assert "历史成交覆盖不足且来源已过期" in rendered
    assert "数据覆盖比例：0.40" in rendered
    assert "情景退出压力核对" in rendered
    assert "2026-11-02T00:00:00+00:00" in rendered
    assert "2026-11-02T01:03:00+00:00" in rendered
    assert "2026-11-03T01:59:00+00:00" in rendered
    assert "仅历史数据" in rendered
    assert "publication-91" not in rendered
    assert "published-price-bars" not in rendered
    assert "b" * 64 not in rendered
    assert "a" * 64 not in rendered
    assert "liquidity_history_stale" not in rendered
    assert all(
        item.get("presentation") in {"metadata", "multiline"}
        for item in fields
        if isinstance(item, dict)
    )


def test_projection_keeps_http_errors_on_the_bounded_base_renderer() -> None:
    """Forbidden and unavailable responses are not mistaken for report outcomes."""

    assert project_portfolio_risk_result({"detail": "bounded"}, http_status=403) is None


def test_projection_displays_scenario_nav_and_fraction_with_explicit_units() -> None:
    """The public TUI result shows the saved hypothetical Scenario impact."""

    report = _report(outcome="partial")
    checks = report["checks"]
    assert isinstance(checks, list)
    checks.append(
        {
            "dimension": "exit_pressure",
            "status": "partial",
            "reason_codes": [],
            "summary": "情景影响是组合净值假设，不代表市场观察或已成交结果。",
            "details": {
                "scenario": {
                    "label": "两家银行同步行业下跌（测试假设）",
                    "revision_id": "scenario-revision-test-4",
                    "version": 4,
                    "content_sha256": "f" * 64,
                },
                "scenario_impact": {
                    "scope": "portfolio_snapshot_net_asset_value",
                    "scope_label": "全组合净值（含现金）",
                    "initial_value": "10000",
                    "final_value": "9290.000",
                    "value_unit": "CNY",
                    "total_return": "-0.071",
                    "total_return_unit": "fraction",
                    "scenario_result_hash": "c" * 64,
                    "hypothetical": True,
                    "market_observation": False,
                },
            },
        }
    )

    view_model = project_portfolio_risk_result(report, http_status=200)

    assert view_model is not None
    fields = view_model["fields"]
    assert isinstance(fields, list)
    rendered = "\n".join(str(item.get("value", "")) for item in fields if isinstance(item, dict))
    assert "情景名称：两家银行同步行业下跌（测试假设）" in rendered
    assert "scenario-revision-test-4" not in rendered
    assert "情景版本：4" in rendered
    assert "情景初始组合净值：10000" in rendered
    assert "影响范围：全组合净值（含现金）" in rendered
    assert "情景最终组合净值：9290.000" in rendered
    assert "组合金额单位：CNY" in rendered
    assert "情景组合回报比例：-0.071" in rendered
    assert "回报计量单位：fraction" in rendered
    assert "是否为假设情景：是" in rendered
    assert "是否为市场观察：否" in rendered
    assert "c" * 64 not in rendered


def test_projection_keeps_unknown_scenario_values_explicitly_unknown() -> None:
    """Unknown portfolio money units are not replaced with a default currency."""

    report = _report(outcome="unknown")
    checks = report["checks"]
    assert isinstance(checks, list)
    checks.append(
        {
            "dimension": "exit_pressure",
            "status": "unknown",
            "reason_codes": ["PORTFOLIO_MONEY_UNIT_UNKNOWN"],
            "summary": "组合金额单位未知，无法显示可比较的金额或回报比例。",
            "details": {
                "scenario_impact": {
                    "scope": "portfolio_snapshot_net_asset_value",
                    "scope_label": "全组合净值（含现金）",
                    "initial_value": None,
                    "final_value": None,
                    "value_unit": None,
                    "total_return": None,
                    "total_return_unit": None,
                    "scenario_result_hash": "d" * 64,
                    "hypothetical": True,
                    "market_observation": False,
                }
            },
        }
    )

    view_model = project_portfolio_risk_result(report, http_status=200)

    assert view_model is not None
    fields = view_model["fields"]
    assert isinstance(fields, list)
    rendered = "\n".join(str(item.get("value", "")) for item in fields if isinstance(item, dict))
    assert "情景初始组合净值：未知" in rendered
    assert "情景最终组合净值：未知" in rendered
    assert "组合金额单位：未知" in rendered
    assert "情景组合回报比例：未知" in rendered
    assert "回报计量单位：未知" in rendered


@pytest.mark.parametrize(
    "mode",
    [
        "policy_bounded_date_snapshot",
        "policy_bounded_timestamp_snapshot",
        "policy_bounded_close_snapshot_state",
        "policy_bounded_disclosed_report",
    ],
)
def test_simulation_deadline_does_not_replace_unknown_supplier_clocks(mode: str) -> None:
    """Users can see the bounded consumer permission and the unaltered source gaps."""

    report = _report(outcome="allowed")
    sources = report["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source["available_at"] = None
    source["valid_until"] = None
    source["clock_evidence_proof"] = {
        "scope": "simulation_only",
        "clock_evidence_mode": mode,
        "proven_available_at": "2026-11-03T13:59:36+00:00",
        "policy_acceptance_deadline": "2026-11-03T16:00:00+00:00",
        "original_body_sha256": "d" * 64,
        "http_status": 200,
        "report_period_end": "2026-09-30",
        "publication_on": "2026-10-27",
    }
    projected = project_portfolio_risk_result(report, http_status=200)
    assert projected is not None
    text = json.dumps(projected, ensure_ascii=False)
    assert "来源可用：未知" in text
    assert "来源有效至：未知" in text
    assert "本次模拟接纳至：2026-11-03T16:00:00+00:00" in text
    assert "不补写供应商发布或失效时间" in text
    assert "d" * 64 not in text
    assert "http_status" not in text
    if mode == "policy_bounded_disclosed_report":
        assert "披露持仓截至：2026-09-30" in text
        assert "发布日期：2026-10-27" in text
        assert "按披露期末计算报告年龄" in text
    if mode == "policy_bounded_close_snapshot_state":
        assert "交易所全日停牌状态仍未知" in text


def test_unknown_clock_proof_scope_cannot_be_presented_as_simulation_permission() -> None:
    """An unrecognized proof cannot acquire a reassuring consumer deadline label."""

    report = _report()
    sources = report["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source["clock_evidence_proof"] = {
        "scope": "live",
        "clock_evidence_mode": "policy_bounded_date_snapshot",
        "policy_acceptance_deadline": "2099-01-01T00:00:00+00:00",
    }
    projected = project_portfolio_risk_result(report, http_status=200)
    assert projected is not None
    text = json.dumps(projected, ensure_ascii=False)
    assert "模拟接纳依据：未知" in text
    assert "2099-01-01" not in text


def test_scope_mismatch_is_visible_as_non_executable_unknown() -> None:
    """A malformed safety boundary is never presented as an allowed report."""

    report = _report(outcome="allowed")
    report["scope"] = "live"

    view_model = project_portfolio_risk_result(report, http_status=200)

    assert view_model is not None
    assert view_model["status"] == "风险边界未知；不得据此执行"
    assert view_model["scope"] == "unknown"
    assert view_model["must_not_execute"] is True


def test_tui_actions_separate_read_only_report_from_confirmed_pressure_run() -> None:
    """The visible account task keeps reads and evidence writes as distinct actions."""

    report_action = build_portfolio_risk_report_action()
    pressure_action = build_portfolio_pressure_run_action()

    assert report_action["method"] == "GET"
    assert report_action["risk"] == "read"
    assert report_action["task_tier"] == "support"
    assert pressure_action["method"] == "POST"
    assert pressure_action["risk"] == "write"
    assert pressure_action["confirmation_required"] is True
    assert pressure_action["audit_required"] is True
    assert pressure_action["session_auth_required"] is True
    assert pressure_action["task_tier"] == "support"
    assert pressure_action["sequence"] == 789


def test_pressure_scenario_selector_metadata_compiles_as_account_scoped_lookup() -> None:
    """The published field is a user-facing selector whose value remains the exact revision ID."""

    action = build_portfolio_pressure_run_action()
    metadata = validate_tui_metadata(
        {
            "schema_version": "tui-metadata.v3",
            "version": "test",
            "default_screen": "execution.accounts",
            "groups": [{"key": "execution", "label": "模拟交易"}],
            "modules": [
                {
                    "key": "daily-decisions",
                    "label": "每日决策",
                    "group": "execution",
                    "summary": "查看模拟账户风险。",
                }
            ],
            "screens": [
                {
                    "key": "execution.accounts",
                    "label": "模拟账户",
                    "module_key": "daily-decisions",
                    "group": "execution",
                    "summary": "查看模拟账户风险和已审批压力情景。",
                    "view_type": "detail",
                    "default_action_key": action["key"],
                }
            ],
            "actions": [action],
        }
    )
    compiled_action = metadata["actions"][0]
    fields = {field["key"]: field for field in compiled_action["fields"]}
    scenario_field = fields["scenario_version_id"]

    schema_path = (
        Path(__file__).resolve().parents[4]
        / "config"
        / "tui"
        / "schema"
        / "tui_metadata.schema.v3.json"
    )
    from jsonschema import Draft202012Validator

    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(metadata)

    assert scenario_field["input_type"] == "select"
    assert scenario_field["presentation_semantic"] == "primary_selector"
    assert scenario_field["options"] == []
    assert scenario_field["options_lookup"] == "approved_portfolio_pressure_scenarios"
    assert scenario_field["required"] is True
    assert scenario_field["binding"] == "body"
    assert scenario_field["default"] == ""
    assert scenario_field["placeholder"] == "先选择模拟账户，再选择情景名称和业务版本"
    assert fields["account_id"]["binding"] == "path"
    assert compiled_action["endpoint"].endswith("/pressure-run/")


def test_pressure_scenario_lookup_metadata_cannot_point_to_another_endpoint_or_default() -> None:
    """The narrow lookup cannot become an arbitrary URL, static scenario, or latest alias."""

    action = build_portfolio_pressure_run_action()
    action["endpoint"] = "/api/unrelated/"
    payload = {
        "schema_version": "tui-metadata.v3",
        "version": "test",
        "default_screen": "execution.accounts",
        "groups": [{"key": "execution", "label": "模拟交易"}],
        "modules": [
            {
                "key": "daily-decisions",
                "label": "每日决策",
                "group": "execution",
                "summary": "查看模拟账户风险。",
            }
        ],
        "screens": [
            {
                "key": "execution.accounts",
                "label": "模拟账户",
                "module_key": "daily-decisions",
                "group": "execution",
                "summary": "查看模拟账户风险。",
                "view_type": "detail",
                "default_action_key": action["key"],
            }
        ],
        "actions": [action],
    }

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(deepcopy(payload))
