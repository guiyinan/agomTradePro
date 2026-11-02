"""Owner-safe TUI metadata and projections for local simulated order entry."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_metadata_continuation_validation import (
    _validate_result_continuations,
)
from apps.terminal.application.tui_order_history_result import (
    order_operation_confirmation_message,
)
from apps.terminal.application.tui_owner_order_submission_result import (
    project_tui_owner_order_submission_result,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_information_architecture import (
    load_tui_information_architecture,
)
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_OWNER_ORDER_ENTRY_ACTIONS,
    RUNTIME_OWNER_ORDER_ENTRY_SCREEN,
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
_PREVIEW = "simulated-trading.order-preview"
_CONFIRM = "simulated-trading.order-confirm"
_READBACK = "simulated-trading.order-by-key"
_ORDER_LIST = "simulated-trading.order-entry-orders"
_ORDER_KEY = "owner-order:test-locator"
_PRIVATE_TOKEN = "private-preview-token"


def _clock_values() -> dict[str, str]:
    """Build internally consistent aware source and confirmation clocks."""

    now = datetime.now(UTC)
    return {
        "observed_at": (now - timedelta(seconds=2)).isoformat(),
        "available_at": (now - timedelta(seconds=1)).isoformat(),
        "qualified_at": now.isoformat(),
        "valid_until": (now + timedelta(minutes=20)).isoformat(),
        "confirmation_expires_at": (now + timedelta(minutes=10)).isoformat(),
    }


def _requested_params(
    side: str = "buy",
    *,
    market_purpose: str = "local_simulation_only",
    limit_price: str = "8.45",
) -> dict[str, object]:
    """Return one ordinary owner order intent with exact decimal strings."""

    return {
        "account_id": 42,
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "side": side,
        "quantity": "100",
        "limit_price": limit_price,
        "market_purpose": market_purpose,
    }


def _preview_payload(side: str = "buy") -> dict[str, object]:
    """Return one safe local-simulation preview with explicit source clocks."""

    clocks = _clock_values()
    order: dict[str, object] = {
        "idempotency_key": _ORDER_KEY,
        "security_id": 9001,
        "side": side,
        "quantity": "100.000000",
        "limit_price": "8.450000",
        "notional": "845.000000",
        "fee_estimate": "0.250000",
        "fee_budget": None,
        "cash_reserved": "845.25" if side == "buy" else "0",
        "shares_reserved": "0" if side == "buy" else "100",
        "available_cash": "9154.75" if side == "buy" else None,
        "available_shares": None if side == "buy" else "0",
        "withdrawable_cash": None,
        "status": "active",
    }
    payload: dict[str, object] = {
        "success": True,
        "outcome": "success",
        "read_only": True,
        "account_id": 42,
        "execution_submitted": False,
        "purpose": "local_simulation_only",
        "market_purpose": "local_simulation_only",
        "message": "请核对数量、费用和预留后确认",
        "replayed": False,
        "order": order,
        "market": {
            "market_source_id": "sina.a_share.local_simulation",
            "market_observed_at": clocks["observed_at"],
            "market_available_at": clocks["available_at"],
            "market_valid_until": clocks["valid_until"],
            "security_state": "TRADING",
            "session_state": "OPEN",
            "reference_price": "8.430000",
            "lower_limit_price": "7.600000",
            "upper_limit_price": "9.300000",
            "price_boundary_mode": "LIMITED",
        },
        "market_notice": "新浪报告状态；价界按明确配置推导，仅用于本地模拟",
        "continuation_expires_at": clocks["confirmation_expires_at"],
    }
    return payload


def _field_values(view_model: Mapping[str, object]) -> dict[str, object]:
    """Index projected scalar fields by stable key for focused assertions."""

    fields = view_model.get("fields")
    assert isinstance(fields, list)
    return {
        str(field["key"]): field["value"]
        for field in fields
        if isinstance(field, dict) and "key" in field and "value" in field
    }


def _close_snapshot_preview_payload() -> dict[str, object]:
    """Build one fully qualified after-close preview bound to the exact source price."""

    payload = _preview_payload()
    clocks = _clock_values()
    order = payload["order"]
    market = payload["market"]
    assert isinstance(order, dict) and isinstance(market, dict)
    order.update(
        {
            "limit_price": "8.430000",
            "notional": "843.000000",
            "cash_reserved": "843.25",
            "available_cash": "9156.75",
        }
    )
    market.update(
        {
            "market_session": "CLOSED",
            "trade_date": datetime.fromisoformat(clocks["observed_at"])
            .astimezone(ZoneInfo("Asia/Shanghai"))
            .date()
            .isoformat(),
            "market_valid_until": clocks["valid_until"],
            "session_state": "CLOSED",
            "lower_limit_price": "8.430000",
            "upper_limit_price": "8.430000",
            "snapshot_kind": "vendor_last_quote_after_close_not_official_close",
            "price_rule": "exact_vendor_last_after_close.v1",
        }
    )
    payload.update(
        {
            "purpose": "close_snapshot_simulation",
            "market_purpose": "close_snapshot_simulation",
            "market_qualification": {
                "decision_scope": "close_snapshot_simulation",
                "qualified_at": clocks["qualified_at"],
                "freshness": "close_snapshot",
                "reliability": "vendor_reported_close_snapshot",
                "must_not_use_for_decision": True,
                "must_not_execute": True,
                "local_simulation_qualified": True,
                "blocking_reasons": [],
                "market_available_at_basis": (
                    "local_response_completed_at_not_vendor_published_at"
                ),
            },
            "market_notice": "使用新浪供应商盘后末笔报价进行本地模拟；该报价不是官方收盘价。",
        }
    )
    return payload


def _reservation_payload(
    *,
    readback: bool,
    replayed: bool,
    market_purpose: str | None = None,
) -> dict[str, object]:
    """Return a persisted owner reservation response without any fill receipt."""

    order = _preview_payload()["order"]
    assert isinstance(order, dict)
    if readback:
        for key in (
            "notional",
            "fee_budget",
            "available_cash",
            "available_shares",
            "withdrawable_cash",
        ):
            order.pop(key, None)
        order["filled_quantity"] = "0.000000"
        order["reserved_at"] = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "success": True,
        "outcome": "success",
        "read_only": readback,
        "account_id": 42,
        "order_key": _ORDER_KEY,
        "execution_submitted": False,
        "purpose": "local_simulation_only",
        "message": "订单已预留，尚未成交；可在订单历史继续操作",
        "replayed": replayed,
        "order_id": 810,
        "order": deepcopy(order),
    }
    if market_purpose is not None:
        payload["purpose"] = market_purpose
        payload["market_purpose"] = market_purpose
    return payload


def _stop_loss_payload(*, sell_count: int = 1, buy_count: int = 0) -> dict[str, object]:
    """Return a bounded stop-loss-only HTTP result with no broker receipt claim."""

    outcome = "success" if sell_count + buy_count else "noop"
    account = {
        "account_id": 42,
        "outcome": outcome,
        "success": True,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "confirmed_trade_count": buy_count + sell_count,
        "stored": buy_count + sell_count,
        "counts_unavailable": False,
        "reason_code": None,
        "issues": [],
    }
    return {
        "success": True,
        "outcome": outcome,
        "trade_date": "2026-10-16",
        "market_purpose": "close_snapshot_simulation",
        "execution_scope": "account_stop_loss_only",
        "market_notice": "供应商收盘后末笔报价并非官方收盘价；仅用于本地模拟。",
        "requested": 1,
        "total_accounts": 1,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "confirmed_trade_count": buy_count + sell_count,
        "stored": buy_count + sell_count,
        "counts_unavailable": False,
        "accounts": [account],
    }


def test_order_entry_ia_and_continuation_bind_original_owner_scope() -> None:
    """Keep the new task separate while preserving its exact account and order scope."""

    registry = load_tui_information_architecture()
    screens = {
        screen["key"]: screen
        for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }
    account_screen = screens["execution.accounts"]
    account_nav = next(
        panel
        for panel in account_screen["dashboard_panels"]
        if panel["key"] == "simulated-order-entry"
    )
    order_screen = screens["simulated-trading.order-entry"]
    actions = {action["key"]: action for action in RUNTIME_OWNER_ORDER_ENTRY_ACTIONS}

    assert account_nav["target_screen"] == "simulated-trading.order-entry"
    assert account_screen["default_action_key"] != _PREVIEW
    assert order_screen["audience"] == "authenticated"
    assert order_screen["entry_mode"] == "dashboard"
    assert order_screen["default_action_key"] == _PREVIEW
    assert order_screen["user_experience"]["primary_task"]
    assert order_screen["user_experience"]["primary_outcome"]
    assert {
        panel["user_priority"] for panel in RUNTIME_OWNER_ORDER_ENTRY_SCREEN["dashboard_panels"]
    } >= {"p0"}
    assert actions[_PREVIEW]["method"] == "POST"
    assert actions[_PREVIEW]["risk"] == "read"
    assert actions[_PREVIEW]["effect"] == "read"
    assert actions[_PREVIEW]["confirmation_required"] is False
    preview_account_field = next(
        field for field in actions[_PREVIEW]["fields"] if field["key"] == "account_id"
    )
    assert preview_account_field["binding"] == "path"
    assert preview_account_field["input_type"] == "number"
    assert preview_account_field["value_type"] == "integer"
    assert preview_account_field.get("presentation_semantic") is None
    preview_fields = {field["key"]: field for field in actions[_PREVIEW]["fields"]}
    for decimal_field in ("quantity", "limit_price", "fee_budget"):
        assert preview_fields[decimal_field]["input_type"] == "text"
        assert preview_fields[decimal_field]["value_type"] == "string"
    purpose_field = preview_fields["market_purpose"]
    assert purpose_field["input_type"] == "select"
    assert purpose_field["value_type"] == "string"
    assert purpose_field["required"] is True
    assert purpose_field["default"] == "local_simulation_only"
    assert purpose_field["options"] == [
        {"value": "local_simulation_only", "label": "盘中模拟（仅限本地）"},
        {
            "value": "close_snapshot_simulation",
            "label": "收盘快照模拟（非官方收盘价）",
        },
    ]
    intent_panel = next(
        panel
        for panel in RUNTIME_OWNER_ORDER_ENTRY_SCREEN["dashboard_panels"]
        if panel["key"] == "order-entry-intent"
    )
    assert intent_panel["action_key"] == _PREVIEW
    order_list_panel = next(
        panel
        for panel in RUNTIME_OWNER_ORDER_ENTRY_SCREEN["dashboard_panels"]
        if panel["key"] == "order-entry-order-list"
    )
    assert order_list_panel["action_key"] == _ORDER_LIST
    order_list_account_field = next(
        field for field in actions[_ORDER_LIST]["fields"] if field["key"] == "account_id"
    )
    assert order_list_account_field["input_type"] == "number"
    assert order_list_account_field.get("presentation_semantic") is None
    assert actions[_CONFIRM]["endpoint"].endswith("/orders/by-key/<str:order_key>/confirm/")
    assert actions[_READBACK]["method"] == "GET"
    assert actions[_READBACK]["endpoint"].endswith("/orders/by-key/<str:order_key>/")
    confirm_fields = {field["key"]: field for field in actions[_CONFIRM]["fields"]}
    readback_fields = {field["key"]: field for field in actions[_READBACK]["fields"]}
    assert "market_purpose" not in confirm_fields
    assert set(readback_fields) == {"account_id", "order_key"}
    descriptor = actions[_PREVIEW]["result_continuation"]
    assert descriptor == {
        "target_action_key": _CONFIRM,
        "field_map": {
            "account_id": "account_id",
            "order_key": "order_key",
            "preview_token": "preview_token",
        },
        "reuse_source_idempotency_key": True,
        "readback_action_key": _READBACK,
    }
    _validate_result_continuations(
        actions=list(RUNTIME_OWNER_ORDER_ENTRY_ACTIONS),
        screens=[],
        action_by_key=actions,
    )

    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)
    runtime_payload = repository._normalize_runtime_payload(
        validate_tui_metadata(json.loads(PUBLISHED_PATH.read_text(encoding="utf-8")))
    )
    runtime_metadata = runtime_payload
    validate_tui_metadata(runtime_metadata)

    normalized_actions = {
        action["key"]: action
        for action in runtime_metadata.get("actions", [])
        if isinstance(action, dict)
    }
    stop_loss = normalized_actions["simulated-trading.account-stop-loss-check"]
    stop_loss_fields = {field["key"]: field for field in stop_loss["fields"]}
    assert stop_loss["endpoint"] == "/api/simulated-trading/auto-trading/run/"
    assert stop_loss["method"] == "POST"
    assert stop_loss["risk"] == "write"
    assert stop_loss["effect"] == "execute"
    assert stop_loss["confirmation_required"] is True
    assert stop_loss["audit_required"] is True
    assert stop_loss["session_auth_required"] is True
    assert stop_loss_fields["trade_date"]["required"] is True
    assert stop_loss_fields["account_ids"]["required"] is True
    assert stop_loss_fields["account_ids"]["value_type"] == "list"
    assert stop_loss_fields["market_purpose"]["default"] == "local_simulation_only"
    assert stop_loss_fields["execution_scope"]["input_type"] == "hidden"
    assert stop_loss_fields["execution_scope"]["default"] == "account_stop_loss_only"
    assert stop_loss_fields["confirmed"]["input_type"] == "hidden"
    assert stop_loss_fields["confirmed"]["default"] is True
    assert "不会开启自动交易" in stop_loss["description"]
    assert "不会运行策略或买入" in stop_loss["description"]

    account_screen = screens["execution.accounts"]
    assert any(
        panel.get("action_key") == "simulated-trading.account-stop-loss-check"
        for panel in account_screen["dashboard_panels"]
        if isinstance(panel, dict)
    )


def test_owner_account_id_is_an_explicit_nonsecret_form_input() -> None:
    """Require a visible owner-account identifier without labeling it as a secret."""

    actions = {action["key"]: action for action in RUNTIME_OWNER_ORDER_ENTRY_ACTIONS}
    for action_key in (_PREVIEW, _ORDER_LIST):
        account_field = next(
            field for field in actions[action_key]["fields"] if field["key"] == "account_id"
        )
        assert account_field["required"] is True
        assert account_field["min"] == 1
        assert account_field["input_type"] == "number"
        assert account_field.get("presentation_semantic") is None


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_preview_projection_shows_source_clocks_and_reservations_without_private_keys(
    side: str,
) -> None:
    """Render both directions with exact market provenance and no continuation secret."""

    payload = _preview_payload(side)
    view = project_tui_owner_order_submission_result(
        _PREVIEW,
        payload,
        http_status=200,
        requested_params=_requested_params(side),
    )
    fields = _field_values(view)
    market = payload["market"]
    assert isinstance(market, dict)

    assert view["outcome"] == "success"
    assert fields["market_observed_at"] == market["market_observed_at"]
    assert fields["market_valid_until"] == market["market_valid_until"]
    assert fields["continuation_expires_at"] == payload["continuation_expires_at"]
    assert fields["market_source_id"] == "sina.a_share.local_simulation"
    assert fields["price_boundary_mode"] == "LIMITED"
    assert fields["cash_reserved"] == ("845.25" if side == "buy" else "0")
    assert fields["shares_reserved"] == ("0" if side == "buy" else "100")
    assert "不会提交券商" in str(view["business_summary"])
    assert _PRIVATE_TOKEN not in repr(view)
    assert _ORDER_KEY not in repr(view)
    assert view["next_steps"] == [
        {
            "label": "查看本人模拟订单",
            "action_key": _ORDER_LIST,
            "params": {"account_id": 42, "limit": 5},
        }
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda market: market.update(security_state="UNKNOWN"),
        lambda market: market.update(session_state="UNKNOWN"),
        lambda market: market.update(price_boundary_mode="UNKNOWN"),
        lambda market: market.update(
            market_available_at=market["market_observed_at"],
            market_observed_at=market["market_valid_until"],
        ),
        lambda market: market.update(lower_limit_price=None),
    ],
)
def test_preview_projection_fails_closed_when_source_state_or_clock_is_unqualified(
    mutation: Any,
) -> None:
    """Malformed, unknown, and unqualified source evidence cannot produce a confirm view."""

    payload = _preview_payload()
    market = payload["market"]
    assert isinstance(market, dict)
    mutation(market)
    view = project_tui_owner_order_submission_result(
        _PREVIEW,
        payload,
        http_status=200,
        requested_params=_requested_params(),
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["next_steps"] == []
    assert "可确认预览" in str(view["business_summary"])


def test_close_snapshot_preview_shows_original_clocks_and_exact_nonofficial_price_rule() -> None:
    """Keep a close snapshot distinct from fresh quotes and bind the order to its exact price."""

    payload = _close_snapshot_preview_payload()
    params = _requested_params(
        market_purpose="close_snapshot_simulation",
        limit_price="8.43",
    )
    view = project_tui_owner_order_submission_result(
        _PREVIEW,
        payload,
        http_status=200,
        requested_params=params,
    )
    fields = _field_values(view)

    assert view["outcome"] == "success"
    assert fields["market_purpose"] == "收盘快照模拟（非官方收盘价）"
    assert fields["trade_date"] == payload["market"]["trade_date"]
    assert payload["market"]["market_session"] == "CLOSED"
    assert fields["security_state"] == "TRADING"
    assert fields["session_state"] == "已收市"
    assert fields["snapshot_kind"] == "供应商收盘后末笔报价；不是官方收盘价"
    assert fields["price_rule"] == "仅限供应商末笔快照价"
    assert fields["reference_price"] == fields["limit_price"] == "8.430000"
    assert fields["freshness"] == "收盘快照（非实时、非新鲜报价）"
    assert fields["reliability"] == "供应商报告的收盘后末笔快照"
    assert fields["must_not_use_for_decision"] == "不得用于投资决策"
    assert fields["must_not_execute"] == "不得提交外部执行"
    assert fields["local_simulation_qualified"] == "已通过；仅限本地模拟"
    assert fields["market_available_at_basis"] == ("本地完整响应接收时间；不是供应商发布时间")
    assert fields["market_observed_at"] == payload["market"]["market_observed_at"]
    assert fields["market_available_at"] == payload["market"]["market_available_at"]
    assert "非官方收盘价" in str(view["business_summary"])
    assert "限价仅按该快照价" in str(view["business_summary"])
    assert "当前不是实时新鲜行情" in str(view["business_summary"])
    assert "不会提交券商" in str(view["business_summary"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["market"].update(snapshot_kind="official_close"),
        lambda payload: payload["market"].update(price_rule="last_price_within_limits"),
        lambda payload: payload["market"].update(session_state="OPEN"),
        lambda payload: payload["market"].update(trade_date="2026-01-01"),
        lambda payload: payload["market_qualification"].update(local_simulation_qualified=False),
        lambda payload: payload["market_qualification"].update(must_not_execute=False),
        lambda payload: payload["market_qualification"].update(blocking_reasons=["blocked"]),
    ],
)
def test_close_snapshot_preview_fails_closed_on_provenance_or_qualification_mismatch(
    mutation: Any,
) -> None:
    """A source, date, time, or purpose mismatch must not become a confirmable preview."""

    payload = _close_snapshot_preview_payload()
    mutation(payload)
    view = project_tui_owner_order_submission_result(
        _PREVIEW,
        payload,
        http_status=200,
        requested_params=_requested_params(
            market_purpose="close_snapshot_simulation",
            limit_price="8.43",
        ),
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["next_steps"] == []


def test_close_snapshot_preview_rejects_limit_price_other_than_exact_snapshot() -> None:
    """An exchange-range price cannot replace the explicitly qualified exact snapshot price."""

    view = project_tui_owner_order_submission_result(
        _PREVIEW,
        _close_snapshot_preview_payload(),
        http_status=200,
        requested_params=_requested_params(
            market_purpose="close_snapshot_simulation",
            limit_price="8.44",
        ),
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["next_steps"] == []


def test_confirm_and_readback_report_reserved_not_filled() -> None:
    """Only the exact persisted order identity can be reported as reserved."""

    params: dict[str, object] = {
        "account_id": 42,
        "order_key": _ORDER_KEY,
        "preview_token": _PRIVATE_TOKEN,
    }
    confirmed = project_tui_owner_order_submission_result(
        _CONFIRM,
        _reservation_payload(readback=False, replayed=False),
        http_status=200,
        requested_params=params,
    )
    readback = project_tui_owner_order_submission_result(
        _READBACK,
        _reservation_payload(readback=True, replayed=True),
        http_status=200,
        requested_params=params,
    )

    assert confirmed["outcome"] == "success"
    assert confirmed["status"] == "已预留，尚未成交"
    assert "尚未成交" in str(confirmed["business_summary"])
    assert "不会提交券商订单" in str(order_operation_confirmation_message(_CONFIRM, params))
    assert any(
        step.get("screen_key") == "execution.accounts"
        and step.get("action_key") == "simulated-trading.orders"
        for step in confirmed["next_steps"]
        if isinstance(step, dict)
    )
    assert readback["outcome"] == "success"
    assert "此前" not in str(confirmed["business_summary"])
    assert "未重新读取行情" in str(readback["business_summary"])
    assert _PRIVATE_TOKEN not in repr(confirmed)
    assert _PRIVATE_TOKEN not in repr(readback)
    assert _ORDER_KEY not in repr(confirmed)
    assert _ORDER_KEY not in repr(readback)


def test_close_snapshot_confirm_and_readback_use_durable_double_purpose() -> None:
    """Reject conflicting purpose echoes and trust only a matching durable response."""

    params: dict[str, object] = {
        "account_id": 42,
        "order_key": _ORDER_KEY,
        "preview_token": _PRIVATE_TOKEN,
        "market_purpose": "close_snapshot_simulation",
    }
    confirmed = project_tui_owner_order_submission_result(
        _CONFIRM,
        _reservation_payload(
            readback=False,
            replayed=False,
            market_purpose="close_snapshot_simulation",
        ),
        http_status=200,
        requested_params={
            "account_id": 42,
            "order_key": _ORDER_KEY,
            "preview_token": _PRIVATE_TOKEN,
        },
    )
    readback = project_tui_owner_order_submission_result(
        _READBACK,
        _reservation_payload(
            readback=True,
            replayed=True,
            market_purpose="close_snapshot_simulation",
        ),
        http_status=200,
        requested_params={"account_id": 42, "order_key": _ORDER_KEY},
    )

    assert confirmed["outcome"] == "success"
    assert readback["outcome"] == "success"
    assert _field_values(confirmed)["market_purpose"] == "收盘快照模拟（非官方收盘价）"
    assert _field_values(readback)["market_purpose"] == "收盘快照模拟（非官方收盘价）"
    assert "非官方收盘价" in str(confirmed["business_summary"])
    assert "非官方收盘价" in str(readback["business_summary"])
    assert "尚未成交" in str(confirmed["business_summary"])
    assert _PRIVATE_TOKEN not in repr(confirmed)
    assert _ORDER_KEY not in repr(confirmed)

    mismatched = _reservation_payload(
        readback=False,
        replayed=False,
        market_purpose="local_simulation_only",
    )
    mismatched["market_purpose"] = "close_snapshot_simulation"
    rejected = project_tui_owner_order_submission_result(
        _CONFIRM,
        mismatched,
        http_status=200,
        requested_params=params,
    )
    mismatched_readback = _reservation_payload(
        readback=True,
        replayed=True,
        market_purpose="close_snapshot_simulation",
    )
    mismatched_readback["market_purpose"] = "local_simulation_only"
    rejected_readback = project_tui_owner_order_submission_result(
        _READBACK,
        mismatched_readback,
        http_status=200,
        requested_params={"account_id": 42, "order_key": _ORDER_KEY},
    )
    assert rejected["outcome"] == "blocked"
    assert rejected["fields"] == []
    assert rejected_readback["outcome"] == "blocked"
    assert rejected_readback["fields"] == []


def test_legacy_local_reservation_projection_still_accepts_original_single_purpose() -> None:
    """Keep old local-only receipts readable when they predate a duplicate purpose echo."""

    view = project_tui_owner_order_submission_result(
        _CONFIRM,
        _reservation_payload(readback=False, replayed=False),
        http_status=200,
        requested_params={
            "account_id": 42,
            "order_key": _ORDER_KEY,
            "preview_token": _PRIVATE_TOKEN,
            "market_purpose": "local_simulation_only",
        },
    )
    assert view["outcome"] == "success"
    assert "market_purpose" not in _field_values(view)


def test_replayed_confirmation_reports_existing_terminal_state_without_second_order() -> None:
    """A repeated token can resolve to the original completed order without new writes."""

    payload = _reservation_payload(readback=False, replayed=True)
    order = payload["order"]
    assert isinstance(order, dict)
    order["status"] = "completed"
    view = project_tui_owner_order_submission_result(
        _CONFIRM,
        payload,
        http_status=200,
        requested_params={
            "account_id": 42,
            "order_key": _ORDER_KEY,
            "preview_token": _PRIVATE_TOKEN,
        },
    )

    assert view["outcome"] == "success"
    assert view["status"] == "已读取原订单：已完成"
    assert "没有创建第二笔订单" in str(view["business_summary"])
    assert "订单尚未成交" not in str(view["business_summary"])


def test_close_snapshot_stop_loss_result_displays_only_scope_and_verified_counts() -> None:
    """Show nonofficial simulation purpose and typed sell counts without fabricating a receipt."""

    params = {
        "trade_date": "2026-10-16",
        "account_ids": [42],
        "market_purpose": "close_snapshot_simulation",
        "execution_scope": "account_stop_loss_only",
        "confirmed": True,
    }
    action = next(
        item
        for item in RUNTIME_SIMULATED_TRADING_ACTIONS
        if item["key"] == "simulated-trading.account-stop-loss-check"
    )
    view = project_tui_owner_order_submission_result(
        "simulated-trading.account-stop-loss-check",
        _stop_loss_payload(),
        http_status=200,
        requested_params=params,
    )
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(execute=lambda **kwargs: {}),
    )
    routed_view = service._custom_view_model(
        action,
        _stop_loss_payload(),
        200,
        request_params=params,
    )
    fields = _field_values(view)

    assert action["confirmation_required"] is True
    assert routed_view == view
    assert view["outcome"] == "success"
    assert fields["market_purpose"] == "收盘快照模拟（非官方供应商末笔报价）"
    assert fields["execution_scope"] == "仅检查所选账户止损；不运行策略或买入"
    assert fields["sell_count"] == "1"
    assert fields["stored_count"] == "1"
    assert "非官方供应商末笔报价" in str(view["business_summary"])
    assert "不会开启自动交易" in str(view["business_summary"])
    assert "券商成交" in str(view["business_summary"])
    assert "market_observed_at" not in fields
    assert "receipt_id" not in fields
    sections = view["sections"]
    assert isinstance(sections, list) and len(sections) == 1
    assert sections[0]["rows"] == [
        {
            "account_id": 42,
            "outcome": "完成",
            "sell_count": 1,
            "reason_code": "无",
            "issues": "无",
        }
    ]


def test_account_stop_loss_projection_rejects_buy_counts_and_scope_mismatch() -> None:
    """A result that reports a buy or a different execution scope is never shown as valid."""

    params = {
        "trade_date": "2026-10-16",
        "account_ids": [42],
        "market_purpose": "close_snapshot_simulation",
        "execution_scope": "account_stop_loss_only",
        "confirmed": True,
    }
    buy_payload = _stop_loss_payload(sell_count=0, buy_count=1)
    buy_view = project_tui_owner_order_submission_result(
        "simulated-trading.account-stop-loss-check",
        buy_payload,
        http_status=200,
        requested_params=params,
    )
    mismatched_scope = _stop_loss_payload()
    mismatched_scope["execution_scope"] = "daily_simulation"
    scope_view = project_tui_owner_order_submission_result(
        "simulated-trading.account-stop-loss-check",
        mismatched_scope,
        http_status=200,
        requested_params=params,
    )

    for view in (buy_view, scope_view):
        assert view["outcome"] == "blocked"
        assert view["fields"] == []
        assert view["sections"] == []
        assert view["business_summary"]


def test_indeterminate_confirmation_offers_only_original_order_readback() -> None:
    """A lost confirmation stays unresolved and never suggests a fresh preview."""

    view = project_tui_owner_order_submission_result(
        _CONFIRM,
        {"success": False, "outcome": "unknown", "effects_indeterminate": True},
        http_status=503,
        requested_params={
            "account_id": 42,
            "order_key": _ORDER_KEY,
            "preview_token": _PRIVATE_TOKEN,
        },
    )

    assert view["outcome"] == "blocked"
    assert view["next_steps"] == [
        {
            "label": "只读核对同一原订单",
            "action_key": _READBACK,
            "params": {"account_id": 42, "order_key": _ORDER_KEY},
        }
    ]
    assert "不要重新预览" in str(view["business_summary"])
    assert _PRIVATE_TOKEN not in repr(view)
    assert _PREVIEW not in repr(view)


def test_unknown_readback_is_not_presented_as_proof_that_order_never_existed() -> None:
    """A missing keyed readback does not turn an ambiguous original request into no-op."""

    view = project_tui_owner_order_submission_result(
        _READBACK,
        {"success": False, "outcome": "blocked"},
        http_status=404,
        requested_params={"account_id": 42, "order_key": _ORDER_KEY},
    )

    assert view["outcome"] == "blocked"
    assert "不表示原请求未提交" in str(view["business_summary"])
    assert view["next_steps"] == []


def test_tui_workbench_strips_preview_secret_and_rejects_scope_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real TUI action boundary hides the signed preview token and binds its order key."""

    clocks = _clock_values()
    payload = _preview_payload()
    payload["continuation"] = {
        "action_key": _CONFIRM,
        "input": {
            "account_id": "42",
            "order_key": _ORDER_KEY,
            "preview_token": _PRIVATE_TOKEN,
        },
        "expires_at": clocks["confirmation_expires_at"],
    }
    action = deepcopy(
        next(item for item in RUNTIME_OWNER_ORDER_ENTRY_ACTIONS if item["key"] == _PREVIEW)
    )
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **kwargs: {"status_code": 200, "payload": deepcopy(payload)}
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"read", "write"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": _PREVIEW})
    monkeypatch.setattr(
        service,
        "_metadata",
        lambda: {"actions": list(RUNTIME_OWNER_ORDER_ENTRY_ACTIONS), "screens": []},
    )
    user = SimpleNamespace(pk=7, is_authenticated=True, is_active=True, is_staff=False)
    result = service.run_action(
        action_key=_PREVIEW,
        params=_requested_params(),
        idempotency_key="preview-request-42",
        user=user,
    )

    assert result["outcome"] == "success"
    assert result["debug"]["raw_response"] is None
    assert _PRIVATE_TOKEN not in repr(result["view_model"])
    assert _ORDER_KEY not in repr(result["view_model"])
    assert _PRIVATE_TOKEN not in repr(result["next_steps"])

    mismatched = deepcopy(payload)
    continuation = mismatched["continuation"]
    assert isinstance(continuation, dict)
    continuation_input = continuation["input"]
    assert isinstance(continuation_input, dict)
    continuation_input["order_key"] = "owner-order:other-account"
    service.action_executor.execute = lambda **kwargs: {
        "status_code": 200,
        "payload": mismatched,
    }
    rejected = service.run_action(
        action_key=_PREVIEW,
        params=_requested_params(),
        idempotency_key="preview-request-43",
        user=user,
    )
    assert rejected["outcome"] == "failed"
    assert rejected["error_code"] == "tui_result_continuation_invalid"
    assert _PRIVATE_TOKEN not in repr(rejected["view_model"])
