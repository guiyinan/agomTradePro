"""User-facing projection contracts for previews without a configured strategy."""

from __future__ import annotations

from typing import cast

import pytest

from apps.terminal.application.tui_account_inspection_result import (
    project_account_inspection_result,
)


def _payload(
    *,
    selection_state: str | None,
    policy_applicability: str | None,
    target_mode: str | None = None,
) -> dict[str, object]:
    risk_context: dict[str, object] = {
        "strategy_id": None,
        "position_rule_id": None,
        "strategy_name": None,
        "strategy_version": None,
        "rule_name": None,
        "rule_version": None,
        "rule_effective_from": None,
        "rule_effective_until": None,
        "strategy_max_position_pct": None,
        "strategy_max_total_position_pct": None,
        "strategy_stop_loss_pct": None,
        "account_max_position_pct": "20.0000",
        "account_max_total_position_pct": "75.0000",
        "account_stop_loss_pct": "8.0000",
    }
    if selection_state is not None:
        risk_context["strategy_selection_state"] = selection_state
    if policy_applicability is not None:
        risk_context["strategy_policy_applicability"] = policy_applicability

    asset_items: list[dict[str, object]] = []
    if target_mode is not None:
        asset_items.append(
            {
                "scope": "asset",
                "asset_code": "600000.SH",
                "asset_name": "示例标的",
                "target_mode": target_mode,
                "action": "buy",
                "status": "ready",
                "reason_codes": [],
                "quantity_unit": "shares",
                "current_quantity": "0.000000",
                "target_quantity": "100.000000",
                "sellable_quantity": "0.000000",
                "suggested_quantity": "100.000000",
                "actionable_quantity": "100.000000",
                "remaining_quantity": "0.000000",
                "risk_rule_result": None,
                "risk_rule_reason_code": None,
                "risk_rule_entry_price_basis": "prospective_current_quote",
                "classification_evidence": None,
                "quantity_rule": None,
                "price_source": "test-provider",
                "price_observed_at": "2026-10-22T09:29:00+08:00",
                "price_as_of": None,
                "price_freshness": "realtime",
                "price_is_fallback": False,
                "identity": {
                    "purpose": "normal_simulated_current_reference",
                    "must_not_use_for_decision": True,
                    "must_not_execute": True,
                },
                "fee": None,
                "currency_unit": None,
            }
        )
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
                    "status": "ready",
                    "as_of": "2026-10-22T09:30:00+08:00",
                    "asset_items": asset_items,
                    "allocation_items": [],
                    "risk_context": risk_context,
                    "sell_before_buy": {
                        "required": False,
                        "sell_asset_codes": [],
                        "buy_asset_codes": [],
                        "sequence": "sell_then_buy",
                        "buy_requires_settled_sales": False,
                    },
                    "funding_status": "known",
                },
            }
        ],
    }


def _view(payload: dict[str, object]) -> dict[str, object]:
    result = project_account_inspection_result(payload, requested_account_id=8, http_status=200)
    return cast(dict[str, object], result)


def _risk_field_values(view: dict[str, object]) -> dict[str, str]:
    sections = cast(list[dict[str, object]], view["sections"])
    section = next(
        item for item in sections if item.get("key") == "selected_strategy_and_risk_limits"
    )
    fields = cast(list[dict[str, str]], section["fields"])
    return {field["key"]: field["value"] for field in fields}


def _risk_context(payload: dict[str, object]) -> dict[str, object]:
    reports = cast(list[dict[str, object]], payload["reports"])
    report = reports[0]
    plan = cast(dict[str, object], report["plan"])
    return cast(dict[str, object], plan["risk_context"])


def test_confirmed_absence_shows_manual_target_mode_and_keeps_account_caps() -> None:
    view = _view(
        _payload(
            selection_state="confirmed_unconfigured",
            policy_applicability="not_applicable",
            target_mode="user_target_difference",
        )
    )
    values = _risk_field_values(view)
    sections = cast(list[dict[str, object]], view["sections"])
    risk_section = next(
        item for item in sections if item.get("key") == "selected_strategy_and_risk_limits"
    )

    assert values["strategy_selection"] == "未配置；本次按你提供的目标估算差额"
    assert values["strategy_name"] == "未配置"
    assert values["strategy_max_position_pct"] == "不适用（未配置策略）"
    assert values["strategy_max_total_position_pct"] == "不适用（未配置策略）"
    assert values["strategy_stop_loss_pct"] == "不适用（未配置策略）"
    assert values["account_max_position_pct"] == "20.0000%"
    assert values["account_max_total_position_pct"] == "75.0000%"
    assert values["account_stop_loss_pct"] == "8.0000%"
    assert "只读预览" in str(risk_section["body"])
    assert "账户限制仍适用" in str(risk_section["body"])
    assert "来源限制和数量规则也仍适用" in str(risk_section["body"])


@pytest.mark.parametrize(
    ("selection_state", "policy_applicability"),
    [
        ("unavailable", "unknown"),
        ("configured", "unknown"),
        ("confirmed_unconfigured", "unknown"),
        ("confirmed_unconfigured", None),
    ],
)
def test_unknown_or_unavailable_policy_selection_blocks_projection(
    selection_state: str,
    policy_applicability: str | None,
) -> None:
    payload = _payload(
        selection_state=selection_state,
        policy_applicability=policy_applicability,
        target_mode="unavailable",
    )

    view = _view(payload)

    assert view["outcome"] == "blocked"
    assert "策略配置或规则适用性" in str(view["business_summary"])
    assert "未配置策略" not in str(view["business_summary"])


def test_configured_strategy_keeps_its_own_caps_separate_from_account_caps() -> None:
    payload = _payload(
        selection_state="configured",
        policy_applicability="applicable",
    )
    _risk_context(payload).update(
        {
            "strategy_name": "已配置策略",
            "strategy_max_position_pct": "40.0000",
            "strategy_max_total_position_pct": "80.0000",
            "strategy_stop_loss_pct": "10.0000",
        }
    )

    values = _risk_field_values(_view(payload))

    assert values["strategy_selection"] == "已配置"
    assert values["strategy_name"] == "已配置策略"
    assert values["strategy_max_position_pct"] == "40.0000%"
    assert values["account_max_position_pct"] == "20.0000%"


def test_confirmed_absence_rejects_non_null_strategy_limits() -> None:
    payload = _payload(
        selection_state="confirmed_unconfigured",
        policy_applicability="not_applicable",
        target_mode="user_target_difference",
    )
    _risk_context(payload)["strategy_max_position_pct"] = "100.0000"

    view = _view(payload)

    assert view["outcome"] == "blocked"
    assert "策略限制资料不一致" in str(view["business_summary"])


def test_confirmed_absence_without_explicit_target_does_not_claim_manual_estimate() -> None:
    view = _view(
        _payload(
            selection_state="confirmed_unconfigured",
            policy_applicability="not_applicable",
        )
    )
    values = _risk_field_values(view)
    sections = cast(list[dict[str, object]], view["sections"])
    risk_section = next(
        item for item in sections if item.get("key") == "selected_strategy_and_risk_limits"
    )

    assert values["strategy_selection"] == "未配置"
    assert values["strategy_max_position_pct"] == "未配置"
    assert values["strategy_max_total_position_pct"] == "未配置"
    assert values["strategy_stop_loss_pct"] == "未配置"
    assert "不适用" not in str(values)
    assert "按你提供的目标估算差额" not in str(risk_section["body"])


def test_confirmed_absence_rejects_rows_without_explicit_manual_target_mode() -> None:
    view = _view(
        _payload(
            selection_state="confirmed_unconfigured",
            policy_applicability="not_applicable",
            target_mode="unavailable",
        )
    )

    assert view["outcome"] == "blocked"
    assert "目标口径与未配置策略状态不匹配" in str(view["business_summary"])


def test_confirmed_absence_rejects_mixed_manual_and_unavailable_rows() -> None:
    payload = _payload(
        selection_state="confirmed_unconfigured",
        policy_applicability="not_applicable",
        target_mode="user_target_difference",
    )
    reports = cast(list[dict[str, object]], payload["reports"])
    plan = cast(dict[str, object], reports[0]["plan"])
    asset_items = cast(list[dict[str, object]], plan["asset_items"])
    asset_items.append({"target_mode": "unavailable"})

    view = _view(payload)

    assert view["outcome"] == "blocked"
    assert "目标口径与未配置策略状态不匹配" in str(view["business_summary"])


def test_legacy_payload_without_selection_contract_keeps_unknown_limits_unknown() -> None:
    payload = _payload(selection_state=None, policy_applicability=None)

    values = _risk_field_values(_view(payload))

    assert "strategy_selection" not in values
    assert values["strategy_max_position_pct"] == "未提供"
    assert values["account_max_position_pct"] == "20.0000%"
