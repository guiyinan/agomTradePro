"""Contracts for the owner-scoped account inspection task preview."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from apps.terminal.application.tui_account_inspection_result import (
    project_account_inspection_result,
)
from apps.terminal.application.tui_task_scope_contracts import (
    TuiTaskScopeError,
    validate_task_action_scope,
)
from apps.terminal.application.tui_temporary_target_result import (
    project_temporary_target_context,
)
from apps.terminal.application.tui_workbench_catalog import TuiWorkbenchCatalogMixin
from apps.terminal.infrastructure.tui_metadata_runtime_injection_task_focus import (
    RUNTIME_TASK_FOCUS_ACTIONS,
    RUNTIME_TASK_FOCUS_SCREENS,
)


class _AccountOptionCatalog(TuiWorkbenchCatalogMixin):
    """Provide deterministic owned-account options for the metadata projection test."""

    def __init__(self, options: list[dict[str, Any]]) -> None:
        self.options = options

    def _account_options_for_user(self, user: Any | None) -> list[dict[str, Any]]:
        return list(self.options)


def _preview_payload() -> dict[str, Any]:
    return {
        "success": True,
        "count": 1,
        "reports": [
            {
                "report_id": 31,
                "account_id": 8,
                "inspection_date": "2026-10-22",
                "plan": {
                    "plan_kind": "rebalance_preview",
                    "read_only": True,
                    "execution_submitted": False,
                    "status": "partial",
                    "as_of": "2026-10-22T09:30:00+08:00",
                    "financial_snapshot_read_at": "2026-10-22T09:30:01+08:00",
                    "cash_before": "8000.00",
                    "reserved_cash": "3000.00",
                    "available_cash_before": "5000.00",
                    "currency_unit": None,
                    "projected_cash_after_sells": "7000.00",
                    "estimated_sell_gross": "2000.00",
                    "estimated_sell_fees": "2.30",
                    "estimated_sell_net": "1997.70",
                    "estimated_buy_gross": "3000.00",
                    "estimated_buy_fees": "3.45",
                    "estimated_buy_total": "3003.45",
                    "projected_cash_after_buys": "3994.25",
                    "funding_status": "known",
                    "sell_before_buy": {
                        "required": True,
                        "sell_asset_codes": ["600001.SH"],
                        "buy_asset_codes": ["000001.SZ"],
                        "sequence": "sell_then_buy",
                        "buy_requires_settled_sales": True,
                    },
                    "risk_context": {
                        "strategy_id": 23,
                        "position_rule_id": 91,
                        "strategy_name": "稳健策略",
                        "strategy_version": 3,
                        "rule_name": "账户风险限制",
                        "rule_version": None,
                        "rule_effective_from": None,
                        "rule_effective_until": None,
                        "max_position_pct": "100.0000",
                        "max_total_position_pct": "100.0000",
                        "stop_loss_pct": "10.0000",
                        "strategy_max_position_pct": "100.0000",
                        "strategy_max_total_position_pct": "100.0000",
                        "strategy_stop_loss_pct": "10.0000",
                        "account_max_position_pct": "20.0000",
                        "account_max_total_position_pct": "75.0000",
                        "account_stop_loss_pct": "8.0000",
                    },
                    "asset_items": [
                        {
                            "scope": "asset",
                            "asset_code": "600001.SH",
                            "asset_name": "示例标的",
                            "action": "sell",
                            "status": "partial",
                            "currency_unit": None,
                            "quantity_unit": "shares",
                            "current_quantity": "10.000000",
                            "target_quantity": "6.000000",
                            "sellable_quantity": "2.000000",
                            "suggested_quantity": "4.000000",
                            "actionable_quantity": "2.000000",
                            "remaining_quantity": "2.000000",
                            "risk_rule_result": None,
                            "risk_rule_reason_code": None,
                            "risk_rule_entry_price_basis": "position_cost_basis",
                            "classification_evidence": None,
                            "quantity_rule": {
                                "rule_id": "ashare-rule-001",
                                "rule_version": "v7",
                                "content_hash": "a" * 64,
                                "market": "CN",
                                "board": "MAIN",
                                "price_tick": "0.01",
                                "buy": {
                                    "minimum": "100",
                                    "step": "100",
                                    "maximum": "1000000",
                                },
                                "sell": {
                                    "minimum": "100",
                                    "step": "100",
                                    "maximum": "1000000",
                                },
                                "sell_odd_lot_mode": "SELL_ODD_REMAINDER_ONCE",
                                "bundle": {
                                    "bundle_id": "settlement-bundle-004",
                                    "bundle_version": "v4",
                                    "content_hash": "b" * 64,
                                    "latest_source_observed_at": "2026-10-22T09:18:00+08:00",
                                    "source_available_at": "2026-10-22T09:19:00+08:00",
                                    "effective_from": "2026-10-22T09:00:00+08:00",
                                    "valid_until": "2026-10-23T09:00:00+08:00",
                                },
                                "execution_rule": {
                                    "source_observed_at": "2026-10-22T09:20:00+08:00",
                                    "source_available_at": "2026-10-22T09:21:00+08:00",
                                    "effective_from": "2026-10-22T09:10:00+08:00",
                                    "valid_until": "2026-10-22T16:00:00+08:00",
                                },
                            },
                            "price_source": "quote-provider-internal",
                            "price_observed_at": "2026-10-22T09:29:00+08:00",
                            "price_as_of": "2026-10-22",
                            "price_freshness": "realtime",
                            "identity": {
                                "security_id": "secret-security-id",
                                "identity_hash": "secret-identity-hash",
                                "purpose": "normal_simulated_current_reference",
                                "must_not_use_for_decision": False,
                                "must_not_execute": True,
                            },
                            "fee": {
                                "policy_id": "secret-policy-id",
                                "policy_version": "secret-policy-version",
                                "content_hash": "secret-fee-hash",
                                "transaction_case": {"internal": "secret-case"},
                                "commission": "1.00",
                                "transfer_fee": "0.10",
                                "stamp_duty": "0.20",
                                "slippage": "0.30",
                                "total": "1.60",
                            },
                            "reason_codes": ["SELLABLE_QUANTITY_PARTIAL"],
                        }
                    ],
                    "allocation_items": [
                        {
                            "scope": "asset_class",
                            "asset_name": "权益类",
                            "action": "buy",
                            "status": "amount_only",
                            "suggested_amount": "1000.00",
                            "currency_unit": None,
                            "reason_codes": [],
                        }
                    ],
                },
            }
        ],
    }


def test_task_metadata_is_one_confirmed_owner_scoped_preview_action() -> None:
    action = next(
        item for item in RUNTIME_TASK_FOCUS_ACTIONS if item["key"] == "account-inspection.run"
    )
    screen = next(
        item for item in RUNTIME_TASK_FOCUS_SCREENS if item["key"] == "task.account-inspection"
    )
    screen_actions = [
        item for item in RUNTIME_TASK_FOCUS_ACTIONS if item["screen_key"] == screen["key"]
    ]
    fields = {field["key"]: field for field in action["fields"]}

    assert action["endpoint"] == "/api/account/accounts/<int:account_id>/inspections/run/"
    assert action["method"] == "POST"
    assert action["risk"] == "write"
    assert action["confirmation_required"] is True
    assert action["audit_required"] is True
    assert action["submit_label"] == "生成调仓预览"
    assert action["raw_debug"] is False
    assert screen_actions == [action]
    assert set(fields) == {"account_id", "temporary_target_weights"}
    assert fields["account_id"]["binding"] == "path"
    assert fields["account_id"]["required"] is True
    assert fields["account_id"]["input_type"] == "select"
    assert fields["account_id"]["options"] == [{"value": "", "label": "请选择本人账户"}]
    assert fields["temporary_target_weights"]["binding"] == "body"
    assert fields["temporary_target_weights"]["required"] is False
    assert fields["temporary_target_weights"]["input_type"] == "textarea"
    assert fields["temporary_target_weights"]["value_type"] == "string"
    assert "auto_create_proposal" not in action
    assert "task.account-inspection" == screen["key"]

    ia_path = Path("config/tui/ia/tui_information_architecture.v1.json")
    ia = json.loads(ia_path.read_text(encoding="utf-8"))
    screen_ia = next(item for item in ia["runtime_screens"] if item["key"] == screen["key"])
    task_mode = next(mode for mode in ia["experience"]["modes"] if mode["key"] == "task")
    entry = next(item for item in task_mode["entries"] if item["screen_key"] == screen["key"])
    assert entry["label"] == "账户调仓预览"
    assert entry["description"] == "为本人选定账户生成并核对只读调仓预览。"
    assert screen_ia["summary"] == "选择本人账户，生成并核对只读调仓预览。"
    user_copy = str(
        {
            "primary_task": screen_ia["user_experience"]["primary_task"],
            "primary_outcome": screen_ia["user_experience"]["primary_outcome"],
            "next_step_hint": screen_ia["user_experience"]["next_step_hint"],
            "decision_output": screen_ia["business_context"]["decision_output"],
        }
    )
    assert "巡检" not in user_copy
    assert "接口" not in user_copy
    assert "HTTP" not in user_copy
    assert len(screen_ia["dashboard_panels"]) == 1
    assert screen_ia["dashboard_panels"][0]["user_priority"] == "p0"


def test_account_selector_options_are_owned_and_empty_state_has_no_free_id_input() -> None:
    options = [{"value": 8, "label": "本人模拟账户"}]
    action = {"method": "POST"}
    field = {
        "key": "account_id",
        "label": "选择本人账户",
        "input_type": "select",
        "value_type": "integer",
        "required": True,
        "default": "",
        "options": [{"value": "", "label": "请选择本人账户"}],
    }

    _AccountOptionCatalog(options)._decorate_dynamic_field_options(
        field, action=action, user=object()
    )
    assert field["input_type"] == "select"
    assert field["options"] == [
        {"value": "", "label": "请选择本人账户"},
        {"value": 8, "label": "本人模拟账户"},
    ]

    empty_field = {
        "key": "account_id",
        "label": "选择本人账户",
        "input_type": "select",
        "value_type": "integer",
        "required": True,
        "default": "",
        "options": [{"value": "", "label": "请选择本人账户"}],
    }
    _AccountOptionCatalog([])._decorate_dynamic_field_options(
        empty_field, action=action, user=object()
    )
    assert empty_field["input_type"] == "select"
    assert empty_field["options"] == [{"value": "", "label": "请选择本人账户"}]


def test_account_inspection_scope_normalizes_only_the_owned_account() -> None:
    scope = validate_task_action_scope("account-inspection.run", {"account_id": "8"})

    assert scope is not None
    assert scope.to_params() == {"account_id": 8}


def test_account_inspection_scope_preserves_declared_temporary_target_text() -> None:
    target_text = "600000.SH,0\n000001.SZ,90.000001"
    scope = validate_task_action_scope(
        "account-inspection.run",
        {"account_id": "8", "temporary_target_weights": target_text},
    )

    assert scope is not None
    assert dict(scope.params) == {"account_id": 8}
    assert scope.temporary_target_weights == target_text
    assert scope.to_params() == {
        "account_id": 8,
        "temporary_target_weights": target_text,
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"account_id": True},
        {"account_id": 8, "user_id": 1},
        {"account_id": 8, "auto_create_proposal": True},
        {"account_id": 8, "inspection_date": "2026-10-22"},
        {"account_id": 8, "strategy_id": 13},
        {"account_id": 8, "temporary_target_weights": {"600000.SH": 0.5}},
        {"account_id": 8, "temporary_target_weights": "x" * 2049},
    ],
)
def test_account_inspection_scope_rejects_unowned_or_undeclared_inputs(
    params: dict[str, object],
) -> None:
    with pytest.raises(TuiTaskScopeError):
        validate_task_action_scope("account-inspection.run", params)


def test_temporary_target_context_displays_source_and_exact_residual_cash() -> None:
    payload = {
        "reports": [
            {
                "checks": [
                    {
                        "scope": "temporary_target_entry",
                        "source": "user_entered_temporary",
                        "target_weights": {"600000.SH": "0.90000001"},
                        "residual_cash_weight": "0.09999999",
                    }
                ]
            }
        ]
    }
    view = project_temporary_target_context(
        {"kind": "detail", "sections": [], "fields": []},
        payload,
        {"temporary_target_weights": "600000.SH,90.000001"},
    )

    context = next(
        section for section in view["sections"] if section["key"] == "temporary_target_context"
    )
    values = {field["key"]: field["value"] for field in context["fields"]}
    assert values["target_source"] == "用户本次填写；未保存为策略配置或自动交易规则"
    assert values["residual_cash_weight"] == "9.999999%"
    target = next(field for field in context["fields"] if field["label"] == "600000.SH 目标比例")
    assert target["value"] == "90.000001%"


def test_temporary_target_context_hides_plan_when_audit_marker_is_missing() -> None:
    view = project_temporary_target_context(
        {
            "kind": "detail",
            "title": "原始计划标题",
            "sections": [{"key": "private_plan"}],
            "fields": [{"key": "private_plan"}],
            "raw_hint": "只保留通用提示",
        },
        {"reports": [{"checks": []}]},
        {"temporary_target_weights": "600000.SH,90"},
    )

    assert view["kind"] == "message"
    assert view["outcome"] == "blocked"
    assert view["sections"] == []
    assert view["fields"] == []
    assert "private_plan" not in str(view)


def test_preview_keeps_asset_quantities_and_class_amounts_in_separate_tables() -> None:
    view = project_account_inspection_result(
        _preview_payload(), requested_account_id=8, http_status=200
    )

    assert view["kind"] == "detail"
    assert view["outcome"] == "success"
    assert "尚未提交交易" in str(view["business_summary"])
    submission = next(field for field in view["fields"] if field["key"] == "submission")
    assert submission["value"] == "未提交"
    assert "SELLABLE_QUANTITY_PARTIAL" not in str(view)
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    amount_section = next(
        section for section in view["sections"] if section["key"] == "allocation_amount_guidance"
    )
    quantity_values = {
        field["key"]: field["value"] for field in quantity_section["rows"][0]["fields"]
    }
    assert quantity_values["current"] == "10.000000"
    assert quantity_values["target"] == "6.000000"
    assert quantity_values["suggested"] == "4.000000"
    assert quantity_values["actionable"] == "2.000000"
    assert quantity_values["remaining"] == "2.000000"
    assert quantity_values["sellable"] == "2.000000"
    assert [column["key"] for column in quantity_section["columns"]] == [
        "asset",
        "direction",
        "current",
        "target",
        "suggested",
        "actionable",
        "remaining",
        "sellable",
        "unit",
        "status",
    ]
    assert "1000.00（币种待确认）" == amount_section["rows"][0]["fields"][2]["value"]
    assert amount_section["columns"][2]["label"] == "建议金额"
    assert quantity_values["unit"] == "股（来源单位）"
    assert "接口" not in str(view)
    assert "HTTP" not in str(view)


def test_preview_places_compact_primary_facts_before_complete_metadata() -> None:
    view = project_account_inspection_result(
        _preview_payload(), requested_account_id=8, http_status=200
    )

    fields = view["fields"]
    assert [field["key"] for field in fields[:5]] == [
        "p0_scope_time",
        "p0_target_cash",
        "p0_fees_cash",
        "p0_first_asset",
        "p0_applicable_limits",
    ]
    assert fields[0]["label"] == "用途与时点"
    assert "只读预览，未提交交易" in fields[0]["value"]
    assert "2026-10-22T09:29:00+08:00" in fields[0]["value"]
    assert "本次未提供" in fields[2]["value"]
    assert "600001.SH（示例标的）" in fields[3]["value"]
    assert "当前 10.000000" in fields[3]["value"]
    assert "规则后建议 2.000000" in fields[3]["value"]
    assert "账户单标的 20.0000%" in fields[4]["value"]
    assert [field["key"] for field in fields[5:]] == [
        "report_id",
        "inspection_date",
        "as_of",
        "plan_status",
        "submission",
        "currency",
        "risk_falsification",
    ]
    assert "next_steps" not in view


def test_blocked_preview_does_not_project_inert_next_steps() -> None:
    view = project_account_inspection_result({}, requested_account_id=8, http_status=200)

    assert view["outcome"] == "blocked"
    assert "next_steps" not in view


def test_primary_asset_summary_keeps_all_fifty_rows_available() -> None:
    payload = _preview_payload()
    plan = payload["reports"][0]["plan"]
    item = plan["asset_items"][0]
    plan["asset_items"] = [
        {**deepcopy(item), "asset_code": f"{index:06d}.SH"} for index in range(1, 51)
    ]

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)

    primary = {field["key"]: field for field in view["fields"][:5]}
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    assert len(quantity_section["rows"]) == 50
    assert "另有49项见完整数量建议" in primary["p0_first_asset"]["value"]
    assert "000001.SH" in primary["p0_first_asset"]["value"]


def test_preview_displays_supplied_cost_cash_and_dependency_estimates_safely() -> None:
    view = project_account_inspection_result(
        _preview_payload(), requested_account_id=8, http_status=200
    )
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    cash_section = next(
        section for section in view["sections"] if section["key"] == "cash_and_cost_estimates"
    )
    risk_section = next(
        section
        for section in view["sections"]
        if section["key"] == "selected_strategy_and_risk_limits"
    )
    dependency_section = next(
        section for section in view["sections"] if section["key"] == "sell_then_buy_dependency"
    )
    quantity_rule_section = next(
        section for section in view["sections"] if section["key"] == "quantity_rule_evidence"
    )

    fee_row = fee_section["rows"][0]
    fee_text = fee_row["fields"][1]["value"]
    assert "佣金 1.00" in fee_text
    assert "过户费 0.10" in fee_text
    assert "印花税 0.20" in fee_text
    assert "滑点估算 0.30" in fee_text
    assert "费用合计 1.60" in fee_text
    assert "币种未提供" in fee_text
    assert "secret-policy-id" not in str(view)
    assert "secret-policy-version" not in str(view)
    assert "secret-fee-hash" not in str(view)
    assert "secret-case" not in str(view)
    identity_text = next(
        field["value"] for field in fee_row["fields"] if field["key"] == "identity"
    )
    assert "本次身份用途：普通模拟当前名录参考；仅限本地模拟用途" in identity_text
    assert "上游来源原始标记：不可用于通用决策：否；禁止执行：是" in identity_text
    assert "不适用于历史、自动或实盘用途" in str(fee_section["body"])
    source_text = fee_row["fields"][2]["value"]
    assert "行情来源：quote-provider-internal" in source_text
    assert "观测时间：2026-10-22T09:29:00+08:00" in source_text
    assert "参考日期：2026-10-22" in source_text
    assert "时效：实时行情" in source_text
    assert "备用来源：未提供" in source_text
    assert "可卖数量不足以覆盖建议差量" in fee_row["fields"][4]["value"]
    assert "secret-security-id" not in str(view)
    assert "secret-identity-hash" not in str(view)

    cash_values = {field["key"]: field for field in cash_section["fields"]}
    assert cash_values["financial_snapshot_read_at"]["value"] == "2026-10-22T09:30:01+08:00"
    assert "账户资料读取时间" in cash_values["financial_snapshot_read_at"]["label"]
    assert "币种" not in cash_values["financial_snapshot_read_at"]["label"]
    assert cash_values["cash_before"]["value"] == "8000.00"
    assert "账户账面现金" in cash_values["cash_before"]["label"]
    assert cash_values["reserved_cash"]["value"] == "3000.00"
    assert "所有活动委托预留现金" in cash_values["reserved_cash"]["label"]
    assert cash_values["available_cash_before"]["value"] == "5000.00"
    assert "当前可用现金" in cash_values["available_cash_before"]["label"]
    assert cash_values["projected_cash_after_sells"]["value"] == "7000.00"
    assert "尚未释放" in cash_values["projected_cash_after_sells"]["label"]
    assert "不代表当前可用现金" in cash_values["projected_cash_after_sells"]["label"]
    assert cash_values["estimated_sell_fees"]["value"] == "2.30"
    assert cash_values["projected_cash_after_buys"]["value"] == "3994.25"
    assert cash_values["funding_status"]["value"] == "估算资金资料完整（仍需核对）"
    assert all(
        "币种未提供" in field["label"]
        for field in cash_values.values()
        if field["key"] not in {"funding_status", "financial_snapshot_read_at"}
    )

    risk_values = {field["key"]: field["value"] for field in risk_section["fields"]}
    assert risk_values["strategy_name"] == "稳健策略"
    assert risk_values["strategy_version"] == "3"
    assert risk_values["rule_name"] == "账户风险限制"
    assert risk_values["rule_version"] == "未提供"
    assert risk_values["account_max_position_pct"] == "20.0000%"
    assert risk_values["strategy_max_position_pct"] == "100.0000%"
    assert risk_values["account_max_total_position_pct"] == "75.0000%"
    assert risk_values["strategy_max_total_position_pct"] == "100.0000%"
    assert risk_values["account_stop_loss_pct"] == "8.0000%"
    assert risk_values["strategy_stop_loss_pct"] == "10.0000%"
    assert "0–100%" in str(risk_section["fields"])
    assert "口径待确认" not in str(risk_section)
    assert risk_values["falsification"] == "本次响应未提供"
    assert "23" not in str(risk_values)
    assert "91" not in str(risk_values)

    dependency_values = {field["key"]: field["value"] for field in dependency_section["fields"]}
    assert dependency_values["sequence"] == "先卖出，再核对买入资金；未发生交易"
    assert dependency_values["sell_assets"] == "600001.SH"
    assert dependency_values["buy_assets"] == "000001.SZ"
    assert dependency_values["buy_requires_settled_sales"] == (
        "是；卖出资金完成交收前，买入数量暂不确认"
    )

    rule_fields = {
        field["key"]: field["value"] for field in quantity_rule_section["rows"][0]["fields"]
    }
    assert "基础规则编号 ashare-rule-001" in rule_fields["identity"]
    assert "v7" in rule_fields["identity"]
    assert "a" * 64 in rule_fields["identity"]
    assert "市场 CN；板块 MAIN；价格变动单位 0.01" in rule_fields["identity"]
    assert "来源组合编号 settlement-bundle-004" in rule_fields["identity"]
    assert "b" * 64 in rule_fields["identity"]
    assert "最小值 100；步长 100；上限 1000000" == rule_fields["buy"]
    assert "零碎处理：允许一次性卖出尾数" in rule_fields["sell"]
    assert "基础规则观测时间 2026-10-22T09:20:00+08:00" in rule_fields["source_window"]
    assert "基础规则有效至 2026-10-22T16:00:00+08:00" in rule_fields["source_window"]
    assert "组合来源最新观测 2026-10-22T09:18:00+08:00" in rule_fields["source_window"]
    assert "组合有效至 2026-10-23T09:00:00+08:00" in rule_fields["source_window"]
    assert "secret-security-id" not in str(quantity_rule_section)

    missing_bundle_clock_payload = _preview_payload()
    missing_bundle_clock_rule = missing_bundle_clock_payload["reports"][0]["plan"]["asset_items"][
        0
    ]["quantity_rule"]
    missing_bundle_clock_rule["bundle"]["valid_until"] = None
    missing_bundle_clock_view = project_account_inspection_result(
        missing_bundle_clock_payload, requested_account_id=8, http_status=200
    )
    missing_bundle_clock_section = next(
        section
        for section in missing_bundle_clock_view["sections"]
        if section["key"] == "quantity_rule_evidence"
    )
    missing_bundle_clock_values = {
        field["key"]: field["value"] for field in missing_bundle_clock_section["rows"][0]["fields"]
    }
    assert (
        "基础规则有效至 2026-10-22T16:00:00+08:00" in missing_bundle_clock_values["source_window"]
    )
    assert "组合有效至 未提供" in missing_bundle_clock_values["source_window"]

    provenance_section = next(
        section for section in view["sections"] if section["key"] == "asset_source_times"
    )
    provenance_values = {field["key"]: field["value"] for field in provenance_section["fields"]}
    assert provenance_values["classification"] == "本次分类未提供"
    assert "本次规则结果已返回" not in provenance_values["risk_basis"]
    assert "所需依据为已有持仓成本" in provenance_values["risk_basis"]
    assert "风险规则评价未完成" in provenance_values["risk_basis"]


def test_account_and_strategy_risk_limits_keep_missing_values_unknown() -> None:
    payload = _preview_payload()
    context = payload["reports"][0]["plan"]["risk_context"]
    context["account_max_position_pct"] = None
    context.pop("account_max_total_position_pct")
    context["account_stop_loss_pct"] = None
    context["strategy_max_position_pct"] = None
    context.pop("strategy_max_total_position_pct")
    context["strategy_stop_loss_pct"] = None

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    risk_section = next(
        section
        for section in view["sections"]
        if section["key"] == "selected_strategy_and_risk_limits"
    )
    values = {field["key"]: field["value"] for field in risk_section["fields"]}

    for key in (
        "account_max_position_pct",
        "account_max_total_position_pct",
        "account_stop_loss_pct",
        "strategy_max_position_pct",
        "strategy_max_total_position_pct",
        "strategy_stop_loss_pct",
    ):
        assert values[key] == "未提供"
    assert "账户设置的单标的持仓上限（0–100%）" in str(risk_section["fields"])
    assert "选定策略的单标的持仓上限（0–100%）" in str(risk_section["fields"])


def test_zero_account_percentage_is_preserved_as_a_supplied_value() -> None:
    payload = _preview_payload()
    payload["reports"][0]["plan"]["risk_context"]["account_max_position_pct"] = "0.0000"

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    risk_section = next(
        section
        for section in view["sections"]
        if section["key"] == "selected_strategy_and_risk_limits"
    )
    values = {field["key"]: field["value"] for field in risk_section["fields"]}

    assert values["account_max_position_pct"] == "0.0000%"


@pytest.mark.parametrize(
    ("reason_code", "expected_label"),
    [
        ("ACCOUNT_MAX_POSITION_LIMIT_UNKNOWN", "账户单标的持仓上限未提供"),
        ("ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED", "超过账户设置的单标的持仓上限"),
        ("ACCOUNT_MAX_TOTAL_POSITION_LIMIT_UNKNOWN", "账户总持仓上限或估值资料不全"),
        ("ACCOUNT_MAX_TOTAL_POSITION_LIMIT_EXCEEDED", "超过账户设置的总持仓上限"),
        ("ACCOUNT_STOP_LOSS_EVIDENCE_UNKNOWN", "账户止损核对所需行情或持仓成本资料不足"),
        ("ACCOUNT_STOP_LOSS_TRIGGERED", "账户止损限制已触发"),
        ("STRATEGY_MAX_POSITION_LIMIT_UNKNOWN", "选定策略的单标的持仓上限未提供"),
        ("STRATEGY_MAX_POSITION_LIMIT_EXCEEDED", "超过选定策略的单标的持仓上限"),
        ("STRATEGY_MAX_TOTAL_POSITION_LIMIT_UNKNOWN", "选定策略总持仓上限或估值资料不全"),
        ("STRATEGY_MAX_TOTAL_POSITION_LIMIT_EXCEEDED", "超过选定策略的总持仓上限"),
        ("STRATEGY_STOP_LOSS_EVIDENCE_UNKNOWN", "策略止损核对所需行情或持仓成本资料不足"),
        ("STRATEGY_STOP_LOSS_TRIGGERED", "选定策略的止损限制已触发"),
        ("STRATEGY_RULE_CONTEXT_UNKNOWN", "策略风险规则所需数据不完整"),
        ("ASSET_TYPE_CLASSIFICATION_UNAVAILABLE", "标的模拟资产分类资料不可用"),
        ("STRATEGY_RULE_EVALUATION_UNAVAILABLE", "策略风险规则评估未完成"),
    ],
)
def test_risk_and_classification_reasons_use_specific_safe_labels(
    reason_code: str, expected_label: str
) -> None:
    payload = _preview_payload()
    payload["reports"][0]["plan"]["asset_items"][0]["reason_codes"] = [reason_code]

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    reason_value = fee_section["rows"][0]["fields"][4]["value"]

    assert expected_label in reason_value
    assert reason_code not in reason_value


def test_missing_fee_currency_and_identity_remain_explicitly_unknown() -> None:
    payload = _preview_payload()
    plan = payload["reports"][0]["plan"]
    plan["financial_snapshot_read_at"] = None
    plan["cash_before"] = None
    plan["reserved_cash"] = None
    plan["available_cash_before"] = None
    plan["asset_items"][0]["fee"] = None
    plan["asset_items"][0]["identity"] = None
    plan["asset_items"][0]["currency_unit"] = None
    plan["allocation_items"][0]["currency_unit"] = None

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    amount_section = next(
        section for section in view["sections"] if section["key"] == "allocation_amount_guidance"
    )
    assert fee_section["rows"][0]["fields"][1]["value"] == "费用资料未提供"
    assert fee_section["rows"][0]["fields"][1]["label"] == "费用估算（币种未提供）"
    identity_text = next(
        field["value"] for field in fee_section["rows"][0]["fields"] if field["key"] == "identity"
    )
    assert "本次身份用途：用途未确认" in identity_text
    assert "不可用于通用决策：未知；禁止执行：未知" in identity_text
    assert amount_section["rows"][0]["fields"][2]["value"] == "1000.00（币种待确认）"
    cash_section = next(
        section for section in view["sections"] if section["key"] == "cash_and_cost_estimates"
    )
    cash_values = {field["key"]: field["value"] for field in cash_section["fields"]}
    assert cash_values["financial_snapshot_read_at"] == "未提供"
    assert cash_values["cash_before"] == "未提供"
    assert cash_values["reserved_cash"] == "未提供"
    assert cash_values["available_cash_before"] == "未提供"
    assert next(field["value"] for field in view["fields"] if field["key"] == "currency") == (
        "本次未提供"
    )


def test_unsettled_sale_dependency_withholds_current_buy_quantity() -> None:
    payload = _preview_payload()
    plan = payload["reports"][0]["plan"]
    plan["status"] = "conditional"
    plan["funding_status"] = "conditional"
    buy_item = dict(plan["asset_items"][0])
    buy_item.update(
        {
            "asset_code": "000001.SZ",
            "asset_name": "待交收买入标的",
            "action": "buy",
            "status": "conditional",
            "current_quantity": "0.000000",
            "target_quantity": "4.000000",
            "suggested_quantity": "4.000000",
            "actionable_quantity": None,
            "remaining_quantity": "4.000000",
            "sellable_quantity": None,
            "reason_codes": ["BUY_DEPENDS_ON_SETTLED_SALES"],
        }
    )
    plan["asset_items"].append(buy_item)

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    buy_values = {field["key"]: field["value"] for field in quantity_section["rows"][1]["fields"]}
    assert view["status"] == "等待资金交收后确认"
    assert "卖出资金完成交收后重新核对" in str(view["business_summary"])
    assert buy_values["target"] == "4.000000"
    assert buy_values["suggested"] == "4.000000"
    assert buy_values["actionable"] == "待卖出资金完成交收后确认"
    assert "附条件" in buy_values["status"]
    assert "买入数量需等待卖出资金完成交收后重新核对" in buy_values["status"]
    cash_section = next(
        section for section in view["sections"] if section["key"] == "cash_and_cost_estimates"
    )
    funding = next(field for field in cash_section["fields"] if field["key"] == "funding_status")
    assert funding["value"] == "等待卖出资金完成交收后复核"


def test_cash_only_buy_remains_ready_and_keeps_unknown_currency_unknown() -> None:
    payload = _preview_payload()
    plan = payload["reports"][0]["plan"]
    plan["status"] = "ready"
    plan["funding_status"] = "known"
    plan["sell_before_buy"] = {
        "required": False,
        "sell_asset_codes": [],
        "buy_asset_codes": [],
        "sequence": "sell_then_buy",
        "buy_requires_settled_sales": False,
    }
    item = plan["asset_items"][0]
    item.update(
        {
            "action": "buy",
            "status": "ready",
            "current_quantity": "0.000000",
            "target_quantity": "4.000000",
            "suggested_quantity": "4.000000",
            "actionable_quantity": "4.000000",
            "remaining_quantity": "0.000000",
            "sellable_quantity": None,
            "risk_rule_entry_price_basis": "prospective_current_quote",
            "risk_rule_reason_code": None,
            "risk_rule_result": {
                "should_buy": True,
                "should_sell": False,
                "buy_price": "10.00",
                "sell_price": "8.00",
                "stop_loss_price": "7.00",
                "take_profit_price": "12.00",
                "position_size": "5.000000",
                "risk_reward_ratio": "2.00",
            },
            "classification_evidence": {
                "content_hash": "secret-classification-hash",
                "read_at": "2026-10-22T09:28:00+08:00",
                "simulated_asset_type": "equity",
                "purpose": "normal_simulated_current_reference",
                "must_not_use_for_decision": False,
                "must_not_execute": True,
                "evidence": {
                    "selector_id": "secret-selector-id",
                    "source_id": "secret-source-id",
                    "mapping_id": "secret-mapping-id",
                    "raw": "do-not-display",
                },
            },
        }
    )

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    quantity_values = {
        field["key"]: field["value"] for field in quantity_section["rows"][0]["fields"]
    }
    provenance_section = next(
        section for section in view["sections"] if section["key"] == "asset_source_times"
    )
    provenance_values = {field["key"]: field["value"] for field in provenance_section["fields"]}

    assert view["outcome"] == "success"
    assert quantity_values["current"] == "0.000000"
    assert quantity_values["target"] == "4.000000"
    assert quantity_values["actionable"] == "4.000000"
    assert "拟用当前参考报价作为入场价依据" in provenance_values["risk_basis"]
    assert "不是持仓成本" in provenance_values["risk_basis"]
    assert "本次规则结果已返回" in provenance_values["risk_basis"]
    assert "0.000000" not in provenance_values["risk_basis"]
    assert "币种未提供" in str(view)
    assert " 元" not in str(view)
    assert "类型 equity" in provenance_values["classification"]
    assert "普通模拟当前名录参考；仅限本地模拟用途" in provenance_values["classification"]
    assert "2026-10-22T09:28:00+08:00" in provenance_values["classification"]
    assert "不可用于通用决策 否；禁止执行 是" in provenance_values["classification"]
    assert "secret-classification-hash" not in str(view)
    assert "secret-selector-id" not in str(view)
    assert "secret-source-id" not in str(view)
    assert "secret-mapping-id" not in str(view)

    item["risk_rule_result"] = None
    item["risk_rule_reason_code"] = "STRATEGY_RULE_EVALUATION_UNAVAILABLE"
    item["reason_codes"] = ["STRATEGY_RULE_EVALUATION_UNAVAILABLE"]
    item["status"] = "partial"
    plan["status"] = "partial"
    pending_view = project_account_inspection_result(
        payload, requested_account_id=8, http_status=200
    )
    pending_provenance = next(
        section for section in pending_view["sections"] if section["key"] == "asset_source_times"
    )
    pending_values = {field["key"]: field["value"] for field in pending_provenance["fields"]}
    assert "拟用当前参考报价作为入场价依据" in pending_values["risk_basis"]
    assert "风险规则评价未完成" in pending_values["risk_basis"]
    assert "本次规则结果已返回" not in pending_values["risk_basis"]


def test_exact_local_simulated_purpose_preserves_preview_when_source_flag_is_true() -> None:
    payload = _preview_payload()
    identity = payload["reports"][0]["plan"]["asset_items"][0]["identity"]
    identity["must_not_use_for_decision"] = True

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    quantity_values = {
        field["key"]: field["value"] for field in quantity_section["rows"][0]["fields"]
    }
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    identity_text = next(
        field["value"] for field in fee_section["rows"][0]["fields"] if field["key"] == "identity"
    )

    assert view["outcome"] == "success"
    assert quantity_values["target"] == "6.000000"
    assert quantity_values["suggested"] == "4.000000"
    assert quantity_values["actionable"] == "2.000000"
    assert "本次身份用途：普通模拟当前名录参考；仅限本地模拟用途" in identity_text
    assert "上游来源原始标记：不可用于通用决策：是；禁止执行：是" in identity_text


@pytest.mark.parametrize(
    "purpose", [None, "historical_reference", "normal_simulated_other_purpose"]
)
def test_unknown_identity_purpose_hides_plan_quantities_but_keeps_facts(
    purpose: str | None,
) -> None:
    payload = _preview_payload()
    item = payload["reports"][0]["plan"]["asset_items"][0]
    identity = item["identity"]
    if purpose is None:
        identity.pop("purpose")
    else:
        identity["purpose"] = purpose
    identity["must_not_use_for_decision"] = True

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    quantity_values = {
        field["key"]: field["value"] for field in quantity_section["rows"][0]["fields"]
    }
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    identity_text = next(
        field["value"] for field in fee_section["rows"][0]["fields"] if field["key"] == "identity"
    )

    assert quantity_values["current"] == "10.000000"
    assert quantity_values["sellable"] == "2.000000"
    assert quantity_values["target"] == "用途未确认"
    assert quantity_values["suggested"] == "用途未确认"
    assert quantity_values["actionable"] == "用途未确认"
    assert quantity_values["remaining"] == "用途未确认"
    assert "用途未确认，未展示目标与建议数量" in quantity_values["status"]
    assert "本次身份用途：用途未确认" in identity_text
    assert "上游来源原始标记：不可用于通用决策：是；禁止执行：是" in identity_text

    buy_payload = _preview_payload()
    buy_plan = buy_payload["reports"][0]["plan"]
    buy_plan["status"] = "conditional"
    buy_item = buy_plan["asset_items"][0]
    buy_item.update(
        {
            "asset_code": "000001.SZ",
            "asset_name": "待交收买入标的",
            "action": "buy",
            "status": "conditional",
            "identity": {"must_not_use_for_decision": True, "must_not_execute": False},
            "reason_codes": ["BUY_DEPENDS_ON_SETTLED_SALES"],
        }
    )
    buy_view = project_account_inspection_result(
        buy_payload, requested_account_id=8, http_status=200
    )
    buy_section = next(
        section for section in buy_view["sections"] if section["key"] == "asset_quantity_plan"
    )
    buy_values = {field["key"]: field["value"] for field in buy_section["rows"][0]["fields"]}
    assert buy_values["actionable"] == ("用途未确认；并且待卖出资金完成交收后确认")
    assert buy_values["target"] == "用途未确认"


def test_malformed_quantity_rule_evidence_is_not_exposed_or_inferred() -> None:
    payload = _preview_payload()
    item = payload["reports"][0]["plan"]["asset_items"][0]
    item["target_quantity"] = None
    item["quantity_rule"] = {
        "rule_id": "https://example.invalid/?token=private-value",
        "rule_version": "v7",
        "content_hash": "not-a-hash",
        "bundle": {
            "bundle_id": "secret-bundle-id",
            "bundle_version": None,
            "content_hash": None,
            "latest_source_observed_at": "not-a-timestamp",
            "source_available_at": None,
            "effective_from": None,
            "valid_until": None,
        },
        "execution_rule": {
            "source_observed_at": "not-a-timestamp",
            "source_available_at": None,
            "effective_from": None,
            "valid_until": None,
        },
        "buy": {"minimum": "private-value", "step": None, "maximum": "1000000"},
        "sell": None,
        "sell_odd_lot_mode": "UNRECOGNIZED",
    }

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    rule_section = next(
        section for section in view["sections"] if section["key"] == "quantity_rule_evidence"
    )
    values = {field["key"]: field["value"] for field in rule_section["rows"][0]["fields"]}
    quantity_section = next(
        section for section in view["sections"] if section["key"] == "asset_quantity_plan"
    )
    quantity_values = {
        field["key"]: field["value"] for field in quantity_section["rows"][0]["fields"]
    }
    assert quantity_values["target"] == "未提供"
    assert "格式未确认" in values["identity"]
    assert "https://example.invalid" not in str(view)
    assert "secret-bundle-id" not in str(view)
    assert "private-value" not in str(view)
    assert "口径待确认" in values["sell"]
    assert "基础规则观测时间 格式未确认" in values["source_window"]
    assert "最小值 格式未确认" in values["buy"]
    assert "数量限制格式未确认" not in values["sell"]

    missing_payload = _preview_payload()
    missing_payload["reports"][0]["plan"]["asset_items"][0]["quantity_rule"] = None
    missing_view = project_account_inspection_result(
        missing_payload, requested_account_id=8, http_status=200
    )
    missing_section = next(
        section
        for section in missing_view["sections"]
        if section["key"] == "quantity_rule_evidence"
    )
    assert "未提供" in str(missing_section)


def test_price_source_shows_only_safe_provider_code_and_source_clock() -> None:
    payload = _preview_payload()
    payload["reports"][0]["plan"]["asset_items"][0][
        "price_source"
    ] = "https://user:secret@example.test/quote?api_key=private-token"

    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    fee_section = next(
        section for section in view["sections"] if section["key"] == "asset_cost_identity_review"
    )
    source_text = fee_section["rows"][0]["fields"][2]["value"]

    assert "行情来源名称未提供或格式未确认" in source_text
    assert "观测时间：2026-10-22T09:29:00+08:00" in source_text
    assert "时效：实时行情" in source_text
    assert "example.test" not in str(view)
    assert "secret" not in str(view)
    assert "api_key" not in str(view)
    assert "private-token" not in str(view)


@pytest.mark.parametrize("http_status", [403, 404])
def test_denied_or_missing_account_clears_old_preview_without_raw_error(
    http_status: int,
) -> None:
    view = project_account_inspection_result(
        {"success": False, "error": "private raw detail"},
        requested_account_id=8,
        http_status=http_status,
    )

    assert view["outcome"] == "blocked"
    assert "private raw detail" not in str(view)
    assert "本次未展示旧结果" in view["business_summary"]
    assert view["fields"] == []
    assert view["empty_message"] == "本次没有可展示的预览明细。"
    assert view["sections"][0]["key"] == "blocked"
    assert "private raw detail" not in str(view["sections"])


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "count": 0, "reports": []},
        {"success": True, "count": 1, "reports": [{"report_id": 1, "account_id": 9}]},
        {
            **_preview_payload(),
            "reports": [
                {
                    **_preview_payload()["reports"][0],
                    "plan": {
                        **_preview_payload()["reports"][0]["plan"],
                        "execution_submitted": True,
                    },
                }
            ],
        },
        {
            **_preview_payload(),
            "reports": [
                {
                    **_preview_payload()["reports"][0],
                    "plan": {
                        **_preview_payload()["reports"][0]["plan"],
                        "status": "new-unreviewed-state",
                    },
                }
            ],
        },
    ],
)
def test_missing_unknown_or_non_preview_payload_is_blocked(payload: dict[str, Any]) -> None:
    view = project_account_inspection_result(payload, requested_account_id=8, http_status=200)

    assert view["outcome"] == "blocked"
    assert "没有展示旧结果" in str(view)
