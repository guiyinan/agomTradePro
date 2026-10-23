"""Bind displayed temporary-target results to the exact submitted request."""

from apps.terminal.application.tui_account_inspection_result import (
    project_account_inspection_result,
)
from apps.terminal.application.tui_temporary_target_result import (
    project_temporary_target_context,
)


def _payload(target_weights: dict[str, str], residual_cash_weight: str) -> dict[str, object]:
    """Build one response envelope carrying a temporary-target audit marker."""

    return {
        "reports": [
            {
                "checks": [
                    {
                        "scope": "temporary_target_entry",
                        "source": "user_entered_temporary",
                        "target_weights": target_weights,
                        "residual_cash_weight": residual_cash_weight,
                    }
                ]
            }
        ]
    }


def _view_model() -> dict[str, object]:
    """Return an empty successful-view envelope for focused binding checks."""

    return {"kind": "message", "sections": [], "fields": []}


def _detail_view_model() -> dict[str, object]:
    """Return safe projected inputs needed to build the five primary facts."""

    return {
        "kind": "detail",
        "fields": [
            {"key": "report_id", "label": "生成记录编号", "value": "31"},
            {"key": "inspection_date", "label": "生成日期", "value": "2026-10-22"},
            {
                "key": "as_of",
                "label": "预览时点",
                "value": "2026-10-22T09:30:00+08:00",
            },
            {"key": "plan_status", "label": "预览状态", "value": "预览已生成"},
            {"key": "submission", "label": "交易提交状态", "value": "未提交"},
            {"key": "currency", "label": "汇总现金与费用币种", "value": "本次未提供"},
            {"key": "risk_falsification", "label": "风险证伪条件", "value": "本次响应未提供"},
        ],
        "sections": [
            {
                "key": "asset_quantity_plan",
                "rows": [
                    {
                        "fields": [
                            {"key": "asset_code", "label": "证券代码", "value": "600000.SH"},
                            {"key": "asset", "label": "标的", "value": "浦发银行"},
                            {"key": "direction", "label": "方向", "value": "建议增加"},
                            {"key": "current", "label": "当前数量", "value": "0"},
                            {"key": "sellable", "label": "可卖数量", "value": "0"},
                            {"key": "target", "label": "目标数量", "value": "100"},
                            {"key": "suggested", "label": "理论差量", "value": "100"},
                            {"key": "actionable", "label": "规则后建议", "value": "100"},
                            {"key": "unit", "label": "数量单位", "value": "股（来源单位）"},
                            {"key": "status", "label": "状态与限制", "value": "可核对"},
                        ]
                    }
                ],
            },
            {
                "key": "asset_source_times",
                "fields": [
                    {
                        "key": "observed_at",
                        "label": "浦发银行来源观测时间",
                        "value": "2026-10-22T09:29:00+08:00",
                    }
                ],
            },
            {
                "key": "cash_and_cost_estimates",
                "fields": [
                    {
                        "key": "financial_snapshot_read_at",
                        "label": "账户资料读取时间",
                        "value": "09:30",
                    },
                    {"key": "available_cash_before", "label": "当前可用现金", "value": "8000.00"},
                    {"key": "estimated_sell_fees", "label": "卖出费用估算", "value": "0.00"},
                    {"key": "estimated_buy_fees", "label": "买入费用估算", "value": "1.00"},
                    {
                        "key": "projected_cash_after_buys",
                        "label": "估算买入后余额",
                        "value": "7999.00",
                    },
                ],
            },
            {
                "key": "selected_strategy_and_risk_limits",
                "fields": [
                    {
                        "key": "strategy_selection",
                        "label": "策略配置状态",
                        "value": "未配置；本次按你提供的目标估算差额",
                    },
                    {"key": "account_max_position_pct", "label": "账户单标的上限", "value": "20%"},
                    {
                        "key": "account_max_total_position_pct",
                        "label": "账户总持仓上限",
                        "value": "95%",
                    },
                    {"key": "account_stop_loss_pct", "label": "账户止损", "value": "未提供"},
                    {
                        "key": "strategy_max_position_pct",
                        "label": "策略单标的上限",
                        "value": "不适用（未配置策略）",
                    },
                    {
                        "key": "strategy_max_total_position_pct",
                        "label": "策略总持仓上限",
                        "value": "不适用（未配置策略）",
                    },
                    {
                        "key": "strategy_stop_loss_pct",
                        "label": "策略止损",
                        "value": "不适用（未配置策略）",
                    },
                ],
            },
        ],
    }


def test_bound_manual_target_weights_are_promoted_without_exposing_internal_state() -> None:
    """Promote percentages only after the request and audit marker match exactly."""

    result = project_temporary_target_context(
        _detail_view_model(),
        _payload({"600000.SH": "0.1"}, "0.9"),
        {"temporary_target_weights": "600000.SH,10"},
    )

    fields = result["fields"]
    assert [field["key"] for field in fields[:5]] == [
        "p0_scope_time",
        "p0_target_cash",
        "p0_fees_cash",
        "p0_first_asset",
        "p0_applicable_limits",
    ]
    target_summary = fields[1]["value"]
    assert target_summary == "600000.SH 目标比例 10%；未分配目标现金 90%"
    assert "confirmed_unconfigured" not in str(result)
    assert "not_applicable" not in str(result)
    assert "未配置；本次按你提供的目标估算差额" in fields[4]["value"]
    assert "账户单标的 20%" in fields[4]["value"]
    assert [field["key"] for field in fields[5:]] == [
        "report_id",
        "inspection_date",
        "as_of",
        "plan_status",
        "submission",
        "currency",
        "risk_falsification",
    ]


def test_bound_target_does_not_add_primary_fields_to_blocked_base_detail() -> None:
    """A valid target marker cannot turn a rejected base result into a preview."""

    base_view = project_account_inspection_result(
        {
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
                        "execution_submitted": True,
                    },
                }
            ],
        },
        requested_account_id=8,
        http_status=200,
    )
    assert base_view["kind"] == "detail"
    assert base_view["outcome"] == "blocked"
    assert base_view["fields"] == []

    result = project_temporary_target_context(
        base_view,
        _payload({"600000.SH": "0.1"}, "0.9"),
        {"temporary_target_weights": "600000.SH,10"},
    )

    assert result["kind"] == "detail"
    assert result["outcome"] == "blocked"
    assert result["fields"] == []
    assert result["business_summary"] == base_view["business_summary"]
    sections = result["sections"]
    assert isinstance(sections, list)
    assert any(section.get("key") == "temporary_target_context" for section in sections)


def test_temporary_target_result_rejects_a_different_valid_security_map() -> None:
    """A valid but different target map must not be presented as this request."""

    result = project_temporary_target_context(
        _view_model(),
        _payload({"000001.SZ": "0.8"}, "0.2"),
        {"temporary_target_weights": "600000.SH,90"},
    )

    assert result["outcome"] == "blocked"
    assert result["sections"] == []
    assert not any(field["key"].startswith("p0_") for field in result["fields"])


def test_temporary_target_result_rejects_cash_text_not_bound_to_request() -> None:
    """A numerically equal but noncanonical cash string must fail closed."""

    result = project_temporary_target_context(
        _view_model(),
        _payload({"600000.SH": "0.9"}, "0.10"),
        {"temporary_target_weights": "600000.SH,90"},
    )

    assert result["outcome"] == "blocked"
    assert result["sections"] == []
    assert not any(field["key"].startswith("p0_") for field in result["fields"])
