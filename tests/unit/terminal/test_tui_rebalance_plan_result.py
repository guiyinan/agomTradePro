"""Contract tests for safe rebalance-plan presentation and progress binding."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.terminal.application.tui_rebalance_plan_quantity_details import (
    project_plan_quantity_detail_fields,
)
from apps.terminal.application.tui_rebalance_plan_result import (
    project_rebalance_plan_result,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_rebalance_plan import (
    RUNTIME_REBALANCE_PLAN_ACTIONS,
)

_REVISION_HASH = "a" * 64
_ORDER_HASH = "b" * 64
_BINDING_HASH = "c" * 64


def _preparation_evidence(
    *,
    suggested_quantity: str = "200",
    requested_quantity: int = 200,
    fractional_remainder: str = "0",
    ordinal: int = 0,
    asset_code: str = "600000.SH",
    security_id: str = "private-security-id",
    side: str = "sell",
) -> str:
    evidence = {
        "schema": "ash08.plan_preparation.v1",
        "decision_snapshot": {
            "id": "decision-1",
            "content_hash": _ORDER_HASH,
            "payload": {
                "prepared_risk": {
                    "order_policy_members": [
                        {
                            "ordinal": ordinal,
                            "asset_code": asset_code,
                            "security_id": security_id,
                            "side": side,
                            "target_quantity_derivation": {
                                "basis": "theoretical_target_difference",
                                "suggested_quantity": suggested_quantity,
                                "requested_whole_share_quantity": requested_quantity,
                                "fractional_remainder": fractional_remainder,
                                "rounding_rule": "floor_to_whole_share",
                            },
                        }
                    ]
                }
            },
        },
    }
    return json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plan() -> dict[str, object]:
    return {
        "identity": {
            "plan_id": "internal-plan-17",
            "family_id": "internal-family-8",
            "root_plan_id": "internal-root-4",
            "version": 2,
            "parent_plan_id": "internal-plan-12",
            "parent_version": 1,
            "parent_revision_hash": _REVISION_HASH,
            "account_id": 9,
            "owner_user_id": 37,
            "transition_plan_hash": _ORDER_HASH,
            "revision_hash": _REVISION_HASH,
            "recorded_at": "2026-11-05T08:00:00+08:00",
            "valid_until": "2026-11-05T12:00:00+08:00",
        },
        "transition_plan": {"target": "synthetic test fixture"},
        "basis": {
            "account": {"account_id": 9, "owner_user_id": 37, "requested_by_user_id": 37},
            "money_unit": "CNY",
            "portfolio_snapshot": {
                "id": "internal-snapshot-1",
                "content_hash": _ORDER_HASH,
                "as_of": "2026-11-05T07:59:00+08:00",
                "source_evidence_hash": _ORDER_HASH,
            },
            "decision": {"id": "decision-1", "content_hash": _ORDER_HASH},
            "preparation_evidence_json": _preparation_evidence(),
            "target": {
                "id": "target-1",
                "content_hash": _ORDER_HASH,
                "selection_id": "selection-1",
                "selection_hash": _ORDER_HASH,
            },
            "planning_policy": {
                "kind": "planning",
                "status": "qualified",
                "reference_id": "planning-policy",
                "version": "policy-v2",
                "content_hash": _ORDER_HASH,
                "effective_at": "2026-11-05T07:00:00+08:00",
                "known_at": "2026-11-05T07:00:00+08:00",
                "valid_until": "2026-11-05T12:00:00+08:00",
                "reason_code": None,
            },
            "risk": {
                "report_content_hash": _ORDER_HASH,
                "binding_hash": _ORDER_HASH,
                "outcome": "allowed",
                "must_not_use_for_decision": False,
            },
            "fee_policy": {
                "kind": "fee",
                "status": "qualified",
                "reference_id": "fee-policy",
                "version": "fee-v2",
                "content_hash": _ORDER_HASH,
                "effective_at": "2026-11-05T07:00:00+08:00",
                "known_at": "2026-11-05T07:00:00+08:00",
                "valid_until": "2026-11-05T12:00:00+08:00",
                "reason_code": None,
            },
            "quantity_rule": {
                "kind": "quantity",
                "status": "qualified",
                "reference_id": "q",
                "version": "1",
                "content_hash": _ORDER_HASH,
                "effective_at": "2026-11-05T07:00:00+08:00",
                "known_at": "2026-11-05T07:00:00+08:00",
                "valid_until": "2026-11-05T12:00:00+08:00",
                "reason_code": None,
            },
            "settlement_rule": {
                "kind": "settlement",
                "status": "qualified",
                "reference_id": "s",
                "version": "1",
                "content_hash": _ORDER_HASH,
                "effective_at": "2026-11-05T07:00:00+08:00",
                "known_at": "2026-11-05T07:00:00+08:00",
                "valid_until": "2026-11-05T12:00:00+08:00",
                "reason_code": None,
            },
            "execution_calendar": {
                "kind": "calendar",
                "status": "qualified",
                "reference_id": "c",
                "version": "1",
                "content_hash": _ORDER_HASH,
                "effective_at": "2026-11-05T07:00:00+08:00",
                "known_at": "2026-11-05T07:00:00+08:00",
                "valid_until": "2026-11-05T12:00:00+08:00",
                "reason_code": None,
            },
            "source_bindings": [
                {
                    "kind": "industry_membership",
                    "asset_code": "600000.SH",
                    "security_id": "private-security-id",
                    "source_id": "private-source-id",
                    "source_record_id": "private-record-id",
                    "manifest_sha256": _ORDER_HASH,
                    "body_sha256": _ORDER_HASH,
                    "observation_precision": "date",
                    "observed_at": None,
                    "observed_on": "2026-11-04",
                    "available_at": None,
                    "known_at": "2026-11-05T07:50:00+08:00",
                    "decision_cutoff": "2026-11-05T08:00:00+08:00",
                    "decision_date_cutoff": "2026-11-05",
                    "source_valid_until": None,
                    "admission_until": "2026-11-05T23:59:59+08:00",
                    "qualification_proof_hash": _ORDER_HASH,
                    "source_purpose": "industry-risk",
                    "requested_purpose": "risk",
                    "allowed_purposes": ["risk"],
                    "restrictions": ["simulation_only"],
                    "coverage_status": "full",
                    "qualified": True,
                    "reason_codes": [],
                }
            ],
            "current_positions": [
                {
                    "asset_code": "600000.SH",
                    "security_id": "private-security-id",
                    "quantity": "1000",
                    "available_quantity": "800",
                    "target_weight": None,
                    "target_quantity": None,
                    "reference_price": "13.5",
                    "market_value": "13500",
                    "quantity_unit": "share",
                    "money_unit": "CNY",
                    "source_binding_hashes": [_ORDER_HASH],
                }
            ],
            "target_positions": [
                {
                    "asset_code": "600000.SH",
                    "security_id": "private-security-id",
                    "quantity": None,
                    "available_quantity": None,
                    "target_weight": "0.5",
                    "target_quantity": "800",
                    "reference_price": "13.5",
                    "market_value": "10800",
                    "quantity_unit": "share",
                    "money_unit": "CNY",
                    "source_binding_hashes": [_ORDER_HASH],
                }
            ],
            "business_date": "2026-11-05",
            "execution_session": "2026-11-06",
            "prepared_at": "2026-11-05T08:00:00+08:00",
            "valid_until": "2026-11-05T12:00:00+08:00",
        },
        "orders": [
            {
                "ordinal": 0,
                "order_content_hash": _ORDER_HASH,
                "plan_order_binding_id": _BINDING_HASH,
                "asset_code": "600000.SH",
                "security_id": "private-security-id",
                "asset_type": "equity",
                "classification_content_hash": _ORDER_HASH,
                "side": "sell",
                "requested_quantity": 200,
                "approved_quantity": 200,
                "unapproved_quantity": 0,
                "quantity_unit": "share",
                "money_unit": "CNY",
                "reference_price": "13.5",
                "reference_price_is_executable_limit": False,
                "estimated_fee": "2.00",
                "estimated_fee_is_actual_fee": False,
                "approved_limit_price": None,
                "status": "approved",
                "reason_codes": [],
            }
        ],
        "status": "approved",
        "automatic_submission": False,
    }


def _progress(*, revision_hash: str = _REVISION_HASH) -> dict[str, object]:
    return {
        "plan_identity": {
            "plan_id": "internal-plan-17",
            "family_id": "internal-family-8",
            "root_plan_id": "internal-root-4",
            "version": 2,
            "revision_hash": revision_hash,
            "valid_until": "2026-11-05T12:00:00+08:00",
        },
        "orders": [
            {
                "order": {
                    "ordinal": 0,
                    "plan_order_binding_id": _BINDING_HASH,
                    "order_content_hash": _ORDER_HASH,
                    "asset_code": "600000.SH",
                    "security_id": "private-security-id",
                    "asset_type": "equity",
                    "classification_content_hash": _ORDER_HASH,
                    "side": "sell",
                    "approved_quantity": 200,
                    "quantity_unit": "share",
                    "money_unit": "CNY",
                },
                "progress": {
                    "outcome": "unknown",
                    "filled_quantity": "0",
                    "in_flight_quantity": "0",
                    "released_quantity": "0",
                    "unreserved_remaining_quantity": None,
                    "reason_codes": ["SYNTHETIC_UNKNOWN"],
                },
                "attempts": [],
                "can_preview": False,
                "can_cancel": False,
                "can_recover": False,
                "requires_successor": False,
            }
        ],
        "account_reconciliation": {
            "read_at": "2026-11-05T08:10:00+08:00",
            "cash_available": None,
            "money_unit": "CNY",
            "positions": [
                {
                    "asset_code": "600000.SH",
                    "security_id": "private-security-id",
                    "quantity": "1000",
                    "available_quantity": "800",
                    "quantity_unit": "share",
                }
            ],
            "active_buy_cash_reserved": "0.00",
            "active_sell_quantity_reserved": "0",
            "actual_fees_paid": None,
            "fees_complete": False,
            "reason_codes": ["SYNTHETIC_UNKNOWN"],
        },
    }


def _envelope(*, revision_hash: str = _REVISION_HASH) -> dict[str, object]:
    return {
        "success": True,
        "account_id": 9,
        "plan": _plan(),
        "review": None,
        "progress": _progress(revision_hash=revision_hash),
        "capabilities": {
            "read_only": False,
            "can_request_review": False,
            "can_create_successor": False,
            "can_preview_order": True,
        },
    }


def _saved_order(envelope: dict[str, object]) -> dict[str, object]:
    plan = envelope["plan"]
    assert isinstance(plan, dict)
    orders = plan["orders"]
    assert isinstance(orders, list) and isinstance(orders[0], dict)
    return orders[0]


def _saved_basis(envelope: dict[str, object]) -> dict[str, object]:
    plan = envelope["plan"]
    assert isinstance(plan, dict)
    basis = plan["basis"]
    assert isinstance(basis, dict)
    return basis


def _detail_result(envelope: dict[str, object]) -> dict[str, object]:
    return project_rebalance_plan_result(
        "rebalance-plan.read",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )


def _detail_values(envelope: dict[str, object]) -> dict[str, str]:
    result = _detail_result(envelope)
    return {field["key"]: field["value"] for field in result["fields"]}


def _replace_evidence(envelope: dict[str, object], evidence: object) -> None:
    _saved_basis(envelope)["preparation_evidence_json"] = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def test_exact_progress_shows_unknown_without_zero_filling_or_exposing_internal_ids() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.read",
        _envelope(),
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    rendered = str(result)
    values = {field["key"]: field["value"] for field in result["fields"]}
    labels = {field["key"]: field["label"] for field in result["fields"]}
    assert result["must_not_execute"] is True
    assert result["outcome"] == "风险检查通过；订单仍须逐项按当前事实重新核对"
    assert values["execution_permission"] == "未启用；计划不会自动提交或成交"
    assert values["source_1_observed"] == "2026-11-04"
    assert values["source_1_valid_until"] == "未提供；保持未知"
    assert values["source_1_policy_deadline"] == "2026-11-05T23:59:59+08:00"
    assert values["source_1_available"] == "未提供；保持未知"
    assert values["saved_money_unit"] == "CNY"
    assert values["saved_position_1"] == "1000 share"
    assert values["target_position_1"] == "800 share"
    assert values["order_1_approved"] == "200 share"
    assert values["cash_available"] == "未知"
    assert values["progress_1_remaining"] == "未知"
    assert values["order_1_fee"] == "2.00 CNY"
    assert labels["order_1_fee"] == "计划费用估算（非成交费用）"
    assert values["actual_fees_paid"] == "未知"
    assert values["fees_complete"] == "否"
    assert "internal-plan-17" not in rendered
    assert "private-source-id" not in rendered
    assert "private-security-id" not in rendered
    assert _BINDING_HASH not in rendered
    assert _REVISION_HASH not in rendered


def test_unreviewed_plan_copy_distinguishes_saved_targets_from_staff_approval() -> None:
    for status, expected_status in (
        ("DRAFT", "待核对"),
        ("APPROVAL_PENDING", "等待独立复核"),
    ):
        envelope = _envelope()
        plan = envelope["plan"]
        assert isinstance(plan, dict)
        plan["status"] = status
        orders = plan["orders"]
        assert isinstance(orders, list) and isinstance(orders[0], dict)
        orders[0]["status"] = "draft"

        result = project_rebalance_plan_result(
            "rebalance-plan.read",
            envelope,
            requested_params={
                "account_id": 9,
                "plan_id": "internal-plan-17",
                "plan_version": 2,
                "revision_hash": _REVISION_HASH,
            },
            http_status=200,
        )
        fields = result["fields"]
        labels = {field["key"]: field["label"] for field in fields}
        values = {field["key"]: field["value"] for field in fields}

        assert values["plan_status"] == expected_status
        assert values["order_1_status"] == "待核对"
        assert values["execution_permission"] == "未启用；计划不会自动提交或成交"
        assert labels["order_1_approved"] == "第 1 项 600000.SH 卖出本版本办理上限"
        assert labels["order_1_unapproved"] == "尚未纳入办理量"
        assert labels["order_1_approved_limit"] == "本版本计划限价"
        assert "本版本计划目标" in result["next_steps"][0]
        assert "批准目标" not in result["next_steps"][0]


def test_readonly_exact_revision_keeps_progress_visible_but_suppresses_write_capabilities() -> None:
    envelope = _envelope()
    envelope["capabilities"] = {
        "read_only": True,
        "can_request_review": True,
        "can_create_successor": True,
        "can_preview_order": True,
    }
    progress = envelope["progress"]
    progress["orders"][0]["can_preview"] = True
    progress["orders"][0]["can_cancel"] = True
    progress["orders"][0]["requires_successor"] = True

    result = project_rebalance_plan_result(
        "rebalance-plan.read",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    values = {field["key"]: field["value"] for field in result["fields"]}
    assert values["progress_1_filled"] == "0 share"
    assert values["progress_1_can_reserve"] == "否"
    assert not any("服务器允许" in step for step in result["next_steps"])
    assert not any("可继续单笔订单预览" in step for step in result["next_steps"])
    assert not any("原订单入口单独申请撤销" in step for step in result["next_steps"])

    grid = project_rebalance_plan_result(
        "rebalance-plan.orders",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )
    assert grid["rows"][0]["capability_label"] == "当前不能继续预览"
    assert not any("申请撤销" in step for step in grid["next_steps"])
    assert any("只读时可在 TUI“本人模拟下单”任务查看" in step for step in grid["next_steps"])


def test_progress_with_different_revision_is_discarded_and_status_does_not_grant_action() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.read",
        _envelope(revision_hash="c" * 64),
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    values = {field["key"]: field["value"] for field in result["fields"]}
    assert values["progress"] == "暂不可核实；请重新读取对账。"
    assert not any("可继续单笔订单预览" in step for step in result["next_steps"])
    assert result["must_not_execute"] is True


def test_exact_read_response_cannot_replace_the_selected_plan_revision() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.read",
        _envelope(),
        requested_params={
            "account_id": 9,
            "plan_id": "another-plan",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    assert result["outcome"] == "unknown"
    assert result["title"] == "调仓计划暂不可展示"
    assert result["must_not_execute"] is True


def test_order_grid_keeps_pins_hidden_and_shows_fill_hold_and_unreserved_separately() -> None:
    envelope = _envelope()
    progress = envelope["progress"]
    progress["orders"][0]["can_preview"] = True
    progress["orders"][0]["progress"]["filled_quantity"] = "25"
    progress["orders"][0]["progress"]["in_flight_quantity"] = "50"
    progress["orders"][0]["progress"]["released_quantity"] = "10"
    progress["orders"][0]["progress"]["unreserved_remaining_quantity"] = "125"
    result = project_rebalance_plan_result(
        "rebalance-plan.orders",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    assert result["kind"] == "datagrid"
    assert result["rows"][0]["filled_label"] == "25 share"
    assert result["rows"][0]["in_flight_label"] == "50 share"
    assert result["rows"][0]["released_label"] == "10 share"
    assert result["rows"][0]["remaining_label"] == "125 share"
    assert result["rows"][0]["price_label"] == "13.5 CNY"
    assert result["rows"][0]["limit_label"] == "计划未设限价；本次仍须明确输入"
    assert result["rows"][0]["capability_label"] == "可进入当前单笔预览"
    assert result["rows"][0]["order_ordinal"] == 0
    assert result["must_not_execute"] is True
    visible_values = [row[column["key"]] for column in result["columns"] for row in result["rows"]]
    rendered = str(visible_values)
    assert "internal-plan-17" not in rendered
    assert _REVISION_HASH not in rendered
    assert "order_content_hash" in result["debug_hidden_fields"]
    assert not any(column["key"] == "order_content_hash" for column in result["columns"])
    assert _BINDING_HASH not in rendered
    assert "private-security-id" not in rendered


def test_order_grid_routes_saved_order_lifecycle_to_existing_owner_task() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.orders",
        _envelope(),
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
        },
        http_status=200,
    )

    next_steps = result["next_steps"]
    assert any("本人模拟下单”任务" in step for step in next_steps)
    assert any("逐单处理" in step and "成交回执" in step for step in next_steps)
    assert any("计划不会自动撤销、撮合或成交" in step for step in next_steps)


def _preview_envelope(*, revision_hash: str = _REVISION_HASH) -> dict[str, object]:
    plan = _plan()
    identity = plan["identity"]
    order = plan["orders"][0]
    binding: dict[str, object] = {
        "plan_id": identity["plan_id"],
        "family_id": identity["family_id"],
        "root_plan_id": identity["root_plan_id"],
        "plan_version": identity["version"],
        "revision_hash": revision_hash,
        "order_ordinal": 0,
        "plan_order_binding_id": order["plan_order_binding_id"],
        "order_content_hash": order["order_content_hash"],
        "account_id": 9,
        "owner_user_id": 37,
        "action_attempt_key": "private-attempt-key",
        "asset_code": order["asset_code"],
        "security_id": order["security_id"],
        "asset_type": order["asset_type"],
        "classification_content_hash": order["classification_content_hash"],
        "side": order["side"],
        "approved_quantity": order["approved_quantity"],
        "approved_limit_price": None,
        "quantity_unit": "share",
        "money_unit": "CNY",
        "plan_expires_at": identity["valid_until"],
        "reference_price_is_executable_limit": False,
        "estimated_fee_is_actual_fee": False,
    }
    return {
        "success": True,
        "account_id": 9,
        "plan": plan,
        "review": None,
        "progress": _progress(),
        "capabilities": {"read_only": False, "can_preview_order": True},
        "preview": {
            "binding": binding,
            "revision_recorded_at": identity["recorded_at"],
            "preview": {
                "success": True,
                "outcome": "success",
                "read_only": True,
                "account_id": 9,
                "execution_submitted": False,
                "purpose": "close_snapshot_simulation",
                "market_purpose": "close_snapshot_simulation",
                "market_notice": "盘后来源仅供受限模拟使用。",
                "order": {
                    "idempotency_key": "private-order-key",
                    "security_id": "private-security-id",
                    "side": "sell",
                    "quantity": "100",
                    "limit_price": "13.40",
                    "fee_estimate": "1.20",
                    "fee_budget": None,
                    "cash_reserved": "0",
                    "shares_reserved": "100",
                    "available_cash": None,
                    "available_shares": "700",
                    "withdrawable_cash": None,
                    "status": "preview",
                },
                "market": {
                    "market_observed_at": "2026-11-04T15:00:00+08:00",
                    "market_available_at": "2026-11-04T15:00:05+08:00",
                    "market_valid_until": None,
                    "market_session": "closed",
                    "trade_date": "2026-11-04",
                    "security_state": "trading_at_quote_time",
                    "price_boundary_mode": "policy_bound",
                },
            },
        },
        "continuation": {
            "action_key": "simulated-trading.order-confirm",
            "input": {
                "account_id": "9",
                "order_key": "private-order-key",
                "preview_token": "secret-preview-token",
            },
            "expires_at": "2026-11-05T08:30:00+08:00",
        },
    }


def test_plan_order_preview_displays_only_exact_single_order_preview_and_never_token() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.preview-order",
        _preview_envelope(),
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
            "order_ordinal": 0,
            "order_content_hash": _ORDER_HASH,
            "plan_order_binding_id": _BINDING_HASH,
            "quantity": "100",
            "limit_price": "13.40",
        },
        http_status=200,
    )

    fields = {field["key"]: field["value"] for field in result["fields"]}
    assert result["read_only"] is True
    assert result["must_not_execute"] is True
    assert fields["requested_quantity"] == "100 share"
    assert fields["requested_limit"] == "13.40 CNY"
    assert fields["fee_estimate"] == "1.20 CNY"
    assert fields["fee_budget"] == "未知"
    assert fields["available_cash"] == "未知"
    assert fields["market_observed_at"] == "2026-11-04T15:00:00+08:00"
    assert fields["market_valid_until"] == "未提供；保持未知"
    rendered = str(result)
    assert "secret-preview-token" not in rendered
    assert "private-order-key" not in rendered
    assert "private-attempt-key" not in rendered
    assert "internal-plan-17" not in rendered
    assert _REVISION_HASH not in rendered


def test_workbench_binds_the_ordinary_preview_to_its_same_screen_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 11, 4, 7, 5, tzinfo=UTC)
    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench_execution.timezone.now", lambda: now
    )
    upstream = _preview_envelope()
    upstream["continuation"]["expires_at"] = "2026-11-04T07:06:00+00:00"
    executor = Mock()
    executor.execute.return_value = {"status_code": 200, "payload": upstream}
    service = TuiWorkbenchService(metadata_repository=Mock(), action_executor=executor)
    monkeypatch.setattr(
        service,
        "_metadata",
        lambda: {"actions": list(RUNTIME_REBALANCE_PLAN_ACTIONS), "screens": []},
    )

    result = service.run_action(
        action_key="rebalance-plan.preview-order",
        params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
            "order_ordinal": 0,
            "order_content_hash": _ORDER_HASH,
            "plan_order_binding_id": _BINDING_HASH,
            "quantity": "100",
            "limit_price": "13.40",
        },
        user=SimpleNamespace(is_authenticated=True, is_staff=False, is_superuser=False),
    )

    assert result["response"]["status_code"] == 200
    assert result["continuation"]["action_key"] == "rebalance-plan.order-confirm"
    assert result["continuation"]["input"] == upstream["continuation"]["input"]
    assert any(field["key"] == "requested_quantity" for field in result["view_model"]["fields"])
    assert "secret-preview-token" not in json.dumps(
        {key: value for key, value in result.items() if key != "continuation"}
    )


def test_readonly_scope_cannot_render_a_preview_even_if_order_facts_claim_ready() -> None:
    envelope = _preview_envelope()
    envelope["capabilities"] = {"read_only": True, "can_preview_order": True}
    result = project_rebalance_plan_result(
        "rebalance-plan.preview-order",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
            "order_ordinal": 0,
            "order_content_hash": _ORDER_HASH,
            "plan_order_binding_id": _BINDING_HASH,
            "quantity": "100",
            "limit_price": "13.40",
        },
        http_status=200,
    )

    assert result["status"] == "需要重新读取"
    assert result["must_not_execute"] is True


def test_plan_order_preview_rejects_a_binding_for_another_revision() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.preview-order",
        _preview_envelope(revision_hash="d" * 64),
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
            "order_ordinal": 0,
            "order_content_hash": _ORDER_HASH,
            "plan_order_binding_id": _BINDING_HASH,
            "quantity": "100",
            "limit_price": "13.40",
        },
        http_status=200,
    )

    assert result["status"] == "需要重新读取"
    assert result["must_not_execute"] is True


def test_plan_order_preview_rejects_a_continuation_for_another_attempt() -> None:
    envelope = _preview_envelope()
    envelope["continuation"]["input"]["order_key"] = "different-order-key"
    result = project_rebalance_plan_result(
        "rebalance-plan.preview-order",
        envelope,
        requested_params={
            "account_id": 9,
            "plan_id": "internal-plan-17",
            "plan_version": 2,
            "revision_hash": _REVISION_HASH,
            "order_ordinal": 0,
            "order_content_hash": _ORDER_HASH,
            "plan_order_binding_id": _BINDING_HASH,
            "quantity": "100",
            "limit_price": "13.40",
        },
        http_status=200,
    )

    assert result["status"] == "需要重新读取"
    assert result["must_not_execute"] is True


def test_empty_list_keeps_create_next_step_and_never_invents_progress() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.list",
        {"success": True, "account_id": 9, "plans": []},
        requested_params={"account_id": 9},
        http_status=200,
    )

    assert result["rows"] == []
    assert result["empty_message"] == "当前账户还没有已保存的调仓计划。"
    assert "生成新计划" in result["business_summary"]
    assert result["read_only"] is True


def test_account_summary_discloses_missing_money_unit_and_valuation_time() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.account-detail",
        {
            "success": True,
            "account": {
                "account_id": 9,
                "account_name": "本人模拟账户",
                "current_cash": "25000.00",
                "cash_known": True,
                "cash_reconciliation_status": "unknown",
                "current_market_value": "60000.00",
                "total_value": None,
            },
        },
        requested_params={"account_id": 9},
        http_status=200,
    )

    values = {field["key"]: field["value"] for field in result["fields"]}
    assert values["current_cash"] == "25000.00 单位未提供"
    assert values["current_market_value"] == "60000.00 单位未提供"
    assert values["valuation_time"] == "账户摘要未提供；不标为实时行情"
    assert values["cash_reconciliation"] == "未知或未完整核对"
    assert result["must_not_execute"] is True


def test_account_row_projector_hides_account_id_and_auto_execution_flag() -> None:
    result = project_rebalance_plan_result(
        "rebalance-plan.accounts",
        {
            "success": True,
            "count": 1,
            "accounts": [
                {
                    "account_id": 9,
                    "account_name": "模拟账户 A",
                    "current_cash": "25000.00",
                    "cash_known": True,
                    "current_market_value": None,
                    "auto_trading_enabled": False,
                    "cash_reconciliation_status": "unknown",
                }
            ],
        },
        requested_params=None,
        http_status=200,
    )

    assert result["rows"][0]["account_id"] == 9
    assert "account_id" in result["debug_hidden_fields"]
    visible_values = [result["rows"][0][column["key"]] for column in result["columns"]]
    assert "9" not in str(visible_values)
    assert result["rows"][0]["progress_label"] == "未知"
    assert "auto_trading_enabled" not in str(result)


def test_saved_plan_shows_exact_fraction_even_when_unapproved_whole_quantity_is_zero() -> None:
    envelope = _envelope()
    order = _saved_order(envelope)
    order.update(
        {
            "requested_quantity": 101,
            "approved_quantity": 101,
            "unapproved_quantity": 0,
            "reason_codes": [],
        }
    )
    progress = envelope["progress"]
    assert isinstance(progress, dict)
    progress_orders = progress["orders"]
    assert isinstance(progress_orders, list) and isinstance(progress_orders[0], dict)
    progress_order = progress_orders[0]["order"]
    assert isinstance(progress_order, dict)
    progress_order["approved_quantity"] = 101
    _replace_evidence(
        envelope,
        json.loads(
            _preparation_evidence(
                suggested_quantity="101.949",
                requested_quantity=101,
                fractional_remainder="0.949",
            )
        ),
    )

    values = _detail_values(envelope)
    assert values["order_1_theoretical_quantity"] == "101.949 share"
    assert values["order_1_whole_share_request"] == "101 share"
    assert values["order_1_fractional_remainder"] == "0.949 share"
    assert values["order_1_unapproved"] == "0 share"
    assert "不表示目标已完成" in values["order_1_quantity_rounding"]
    assert values["execution_permission"] == "未启用；计划不会自动提交或成交"


@pytest.mark.parametrize(
    ("side", "reason_code", "reason_label"),
    (
        (
            "sell",
            "SELL_QUANTITY_STEP_ROUNDED_DOWN",
            "卖出数量按交易步长向下取整，仍有差量未覆盖",
        ),
        (
            "buy",
            "BUY_QUANTITY_STEP_ROUNDED_DOWN",
            "买入数量按交易步长向下取整，仍有差量未覆盖",
        ),
    ),
)
def test_saved_plan_explains_whole_share_step_rounding(
    side: str, reason_code: str, reason_label: str
) -> None:
    envelope = _envelope()
    order = _saved_order(envelope)
    order.update(
        {
            "side": side,
            "requested_quantity": 101,
            "approved_quantity": 100,
            "unapproved_quantity": 1,
            "reason_codes": [reason_code],
        }
    )
    progress = envelope["progress"]
    assert isinstance(progress, dict)
    progress_orders = progress["orders"]
    assert isinstance(progress_orders, list) and isinstance(progress_orders[0], dict)
    progress_order = progress_orders[0]["order"]
    assert isinstance(progress_order, dict)
    progress_order.update({"side": side, "approved_quantity": 100})
    _replace_evidence(
        envelope,
        json.loads(
            _preparation_evidence(
                suggested_quantity="101.949",
                requested_quantity=101,
                fractional_remainder="0.949",
                side=side,
            )
        ),
    )

    values = _detail_values(envelope)
    assert values["order_1_whole_share_request"] == "101 share"
    assert values["order_1_unapproved"] == "1 share"
    assert reason_label in values["order_1_quantity_rounding"]
    assert "尚有 1 share 整股未办理量" in values["order_1_quantity_rounding"]


@pytest.mark.parametrize(
    "invalid_case",
    (
        "duplicate_ordinal",
        "wrong_asset",
        "wrong_security",
        "wrong_side",
        "missing_ordinal",
        "wrong_decision_binding",
        "matching_empty_decision_id",
        "matching_empty_decision_hash",
        "requested_mismatch",
        "nonfinite_suggested",
        "negative_suggested",
        "nonfinite_remainder",
        "remainder_at_least_one",
        "remainder_arithmetic_mismatch",
        "missing_derivation",
    ),
)
def test_saved_plan_hides_derivation_when_evidence_is_not_exact_and_consistent(
    invalid_case: str,
) -> None:
    envelope = _envelope()
    evidence = json.loads(
        _preparation_evidence(
            suggested_quantity="200.75",
            requested_quantity=200,
            fractional_remainder="0.75",
        )
    )
    snapshot = evidence["decision_snapshot"]
    payload = snapshot["payload"]
    members = payload["prepared_risk"]["order_policy_members"]
    member = members[0]
    derivation = member["target_quantity_derivation"]
    if invalid_case == "duplicate_ordinal":
        members.append(member.copy())
    elif invalid_case == "wrong_asset":
        member["asset_code"] = "601398.SH"
    elif invalid_case == "wrong_security":
        member["security_id"] = "another-security"
    elif invalid_case == "wrong_side":
        member["side"] = "buy"
    elif invalid_case == "missing_ordinal":
        member["ordinal"] = 1
    elif invalid_case == "wrong_decision_binding":
        snapshot["content_hash"] = "d" * 64
    elif invalid_case == "matching_empty_decision_id":
        _saved_basis(envelope)["decision"]["id"] = None
        snapshot["id"] = None
    elif invalid_case == "matching_empty_decision_hash":
        _saved_basis(envelope)["decision"]["content_hash"] = None
        snapshot["content_hash"] = None
    elif invalid_case == "requested_mismatch":
        derivation["requested_whole_share_quantity"] = 199
    elif invalid_case == "nonfinite_suggested":
        derivation["suggested_quantity"] = "NaN"
    elif invalid_case == "negative_suggested":
        derivation["suggested_quantity"] = "-1"
    elif invalid_case == "nonfinite_remainder":
        derivation["fractional_remainder"] = "Infinity"
    elif invalid_case == "remainder_at_least_one":
        derivation["fractional_remainder"] = "1"
    elif invalid_case == "remainder_arithmetic_mismatch":
        derivation["fractional_remainder"] = "0.74"
    else:
        derivation.clear()
    _replace_evidence(envelope, evidence)

    values = _detail_values(envelope)
    assert values["order_1_quantity_derivation"] == ("未知；本版本没有可匹配的取整证据。")
    assert "order_1_theoretical_quantity" not in values
    assert "order_1_fractional_remainder" not in values


def test_saved_plan_without_preparation_evidence_keeps_legacy_unknown_behavior() -> None:
    envelope = _envelope()
    _saved_basis(envelope).pop("preparation_evidence_json")

    values = _detail_values(envelope)

    assert values["order_1_quantity_derivation"] == ("未知；本版本没有可匹配的取整证据。")
    assert "order_1_theoretical_quantity" not in values


def test_quantity_evidence_binds_the_order_ordinal_not_its_display_position() -> None:
    envelope = _envelope()
    plan = envelope["plan"]
    order = _saved_order(envelope)
    basis = _saved_basis(envelope)
    order["ordinal"] = 7
    evidence = json.loads(
        _preparation_evidence(
            ordinal=7,
            suggested_quantity="200.75",
            requested_quantity=200,
            fractional_remainder="0.75",
        )
    )
    snapshot = evidence["decision_snapshot"]
    members = snapshot["payload"]["prepared_risk"]["order_policy_members"]
    members.insert(
        0,
        {
            "ordinal": 0,
            "asset_code": "another-asset",
            "security_id": "another-security",
            "side": "buy",
            "target_quantity_derivation": {},
        },
    )
    basis["preparation_evidence_json"] = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    fields = project_plan_quantity_detail_fields(plan, order, field_index=1)
    values = {field["key"]: field["value"] for field in fields}

    assert values["order_1_theoretical_quantity"] == "200.75 share"
    assert values["order_1_whole_share_request"] == "200 share"
    assert values["order_1_fractional_remainder"] == "0.75 share"


@pytest.mark.parametrize("identity_key", ("ordinal", "asset_code", "security_id", "side"))
def test_matching_empty_order_identity_is_unknown(identity_key: str) -> None:
    envelope = _envelope()
    plan = envelope["plan"]
    order = _saved_order(envelope)
    basis = _saved_basis(envelope)
    order[identity_key] = None
    evidence = json.loads(
        _preparation_evidence(
            suggested_quantity="200.75",
            requested_quantity=200,
            fractional_remainder="0.75",
        )
    )
    member = evidence["decision_snapshot"]["payload"]["prepared_risk"]["order_policy_members"][0]
    member[identity_key] = None
    basis["preparation_evidence_json"] = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    fields = project_plan_quantity_detail_fields(plan, order, field_index=1)
    values = {field["key"]: field["value"] for field in fields}

    assert values["order_1_quantity_derivation"] == ("未知；本版本没有可匹配的取整证据。")


@pytest.mark.parametrize(
    "reason",
    (
        "TRANSITION_PLAN_EVENT_REVIEW_REQUIRED",
        "TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE",
        "TRANSITION_PLAN_EVENT_REVIEW_BLOCKED",
    ),
)
def test_current_event_block_is_visible_without_exposing_internal_reason(reason: str) -> None:
    envelope = _envelope()
    envelope["review"] = {"event_review_blocking_reason": reason}
    envelope["capabilities"] = {
        "read_only": False,
        "can_preview_order": False,
        "can_request_review": False,
        "can_create_successor": True,
    }
    original = json.dumps(envelope["plan"], sort_keys=True)
    result = _detail_result(envelope)
    assert (
        result["blocking_reason"]
        == "当前公告需重新核对，旧计划暂不能继续预览；请按当前事实生成后继版本。"
    )
    assert reason not in str(result)
    assert "风险检查通过" not in str(result["outcome"])
    assert json.dumps(envelope["plan"], sort_keys=True) == original
    assert not any("至少一项可继续" in item for item in result["next_steps"])
