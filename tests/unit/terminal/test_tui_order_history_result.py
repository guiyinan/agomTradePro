"""Owner-safe TUI projections for paged simulated-order receipts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.terminal.application.tui_order_history_result import (
    project_tui_order_history_result,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)

_ORDERS = "simulated-trading.orders"
_FILLS = "simulated-trading.order-fills"
_RECEIPT_SCOPE_NOTE = "本页仅列已留存且完成单条核对的成交回执；空列表不能证明从未成交。"
_MEMBERSHIP_CUTOFF = "2026-10-29T01:00:00+08:00"
_READ_AT = "2026-10-29T01:05:00+08:00"
_RECORDED_AT = "2026-10-29T00:50:00+08:00"
_OCCURRED_AT = "2026-10-28T15:00:00+08:00"
_CURSOR = "opaque.cursor/with+=padding"


@pytest.mark.parametrize("valid", [True, False])
def test_workbench_envelope_keeps_history_scope_rejection(
    monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    """A successful transport cannot turn a mismatched owner page into success."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    action = deepcopy(
        next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ORDERS)
    )
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **kwargs: {
                "status_code": 200,
                "payload": _orders_page(account_id=12 if valid else 13),
            }
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"read"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": _ORDERS})
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})
    result = service.run_action(
        action_key=_ORDERS,
        params={"account_id": 12},
        user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=False),
    )
    assert result["outcome"] == ("success" if valid else "blocked")
    assert result["debug"]["raw_response"] is None
    if not valid:
        assert result["view_model"]["sections"] == []
        assert result["next_steps"] == []


def _order(**overrides: object) -> dict[str, object]:
    """Return one public order row with exact JSON decimal strings."""

    row: dict[str, object] = {
        "order_id": 91,
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "side": "buy",
        "status": "active",
        "quantity": "1.000000",
        "filled_quantity": "0.000000",
        "limit_price": "8.4500",
        "remaining_cash": "8.45",
        "remaining_shares": "1.000000",
        "reserved_at": _OCCURRED_AT,
    }
    row.update(overrides)
    return row


def _fill(**overrides: object) -> dict[str, object]:
    """Return one exact receipt-only row with its explicit time basis."""

    row: dict[str, object] = {
        "receipt_id": 501,
        "trade_id": 701,
        "order_id": 91,
        "fill_sequence": 1,
        "asset_code": "600000.SH",
        "side": "buy",
        "quantity": "0.000100",
        "price": "8.4500",
        "occurred_at": _OCCURRED_AT,
        "recorded_at": _RECORDED_AT,
        "observation_basis": "daily_interval_end",
        "verification_status": "single_receipt_verified",
    }
    row.update(overrides)
    return row


def _orders_page(
    *,
    account_id: object = 12,
    orders: object | None = None,
    has_more: object = False,
    next_cursor: object = None,
    **overrides: object,
) -> dict[str, object]:
    """Return one order page envelope."""

    response: dict[str, object] = {
        "success": True,
        "account_id": account_id,
        "orders": [_order()] if orders is None else orders,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "membership_cutoff": _MEMBERSHIP_CUTOFF,
        "read_at": _READ_AT,
    }
    response.update(overrides)
    return response


def _fills_page(
    *,
    account_id: object = 12,
    order_id: object = 91,
    fills: object | None = None,
    has_more: object = False,
    next_cursor: object = None,
    **overrides: object,
) -> dict[str, object]:
    """Return one receipt page envelope with the owner scope note."""

    response: dict[str, object] = {
        "success": True,
        "account_id": account_id,
        "order_id": order_id,
        "fills": [_fill()] if fills is None else fills,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "membership_cutoff": _MEMBERSHIP_CUTOFF,
        "read_at": _READ_AT,
        "receipt_scope_note": _RECEIPT_SCOPE_NOTE,
    }
    response.update(overrides)
    return response


def _section_rows(view: Mapping[str, object]) -> list[Mapping[str, object]]:
    sections = view.get("sections")
    assert isinstance(sections, list) and len(sections) == 1
    section = sections[0]
    assert isinstance(section, Mapping)
    rows = section.get("rows")
    assert isinstance(rows, list)
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _table_values(row: Mapping[str, object]) -> dict[str, object]:
    raw_fields = row.get("fields")
    assert isinstance(raw_fields, list)
    result: dict[str, object] = {}
    for raw in raw_fields:
        assert isinstance(raw, Mapping)
        key = raw.get("key")
        assert type(key) is str
        result[key] = raw.get("value")
    return result


def _visible_text(view: Mapping[str, object]) -> str:
    """Collect visible scalar copy, excluding action parameters sent internally."""

    values: list[str] = []
    for key in ("title", "status", "business_summary", "blocking_reason"):
        value = view.get(key)
        if isinstance(value, str):
            values.append(value)
    fields = view.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, Mapping):
                values.extend(str(field.get(key, "")) for key in ("label", "value"))
    for row in _section_rows(view):
        values.extend(str(value) for value in _table_values(row).values())
    return " ".join(values)


def test_orders_projection_keeps_exact_decimal_text_and_builds_scoped_steps() -> None:
    response = _orders_page(
        orders=[_order(quantity="0.000100", limit_price="8.450000")],
        has_more=True,
        next_cursor=_CURSOR,
        internal_key="must not appear",
        content_hash="must not appear",
    )

    view = project_tui_order_history_result(
        _ORDERS,
        response,
        http_status=200,
        requested_params={"account_id": "12", "limit": 5},
    )

    assert view["outcome"] == "success"
    rows = _section_rows(view)
    assert len(rows) == 1
    values = _table_values(rows[0])
    assert values["quantity"] == "0.000100"
    assert values["limit_price"] == "8.450000"
    assert values["side"] == "买入"
    assert values["status"] == "有效"
    steps = view["next_steps"]
    assert isinstance(steps, list) and len(steps) == 5
    assert steps[0] == {
        "label": "核对订单 91 的撮合决定",
        "action_key": "simulated-trading.order-decisions",
        "params": {"account_id": 12, "order_id": 91, "limit": 5},
    }
    assert steps[1] == {
        "label": "查看订单 91 的成交回执",
        "action_key": _FILLS,
        "params": {"account_id": 12, "order_id": 91, "limit": 5},
    }
    assert steps[2] == {
        "label": "撤销订单 91 当前剩余预留",
        "action_key": "simulated-trading.order-cancel",
        "params": {"account_id": 12, "order_id": 91},
    }
    assert steps[3] == {
        "label": "选择订单 91 的撮合交易日",
        "action_key": "simulated-trading.order-match",
        "params": {"account_id": 12, "order_id": 91},
    }
    assert steps[4] == {
        "label": "读取下一批订单",
        "action_key": _ORDERS,
        "params": {"account_id": 12, "limit": 5, "cursor": _CURSOR},
    }
    visible = _visible_text(view)
    assert _CURSOR not in visible
    assert "internal_key" not in visible
    assert "content_hash" not in visible


@pytest.mark.parametrize(
    ("status_code", "payload", "params"),
    [
        (403, _orders_page(), {"account_id": 12}),
        (200, _orders_page(account_id=13), {"account_id": 12}),
        (200, _orders_page(success=False), {"account_id": 12}),
        (200, _orders_page(has_more=True, next_cursor=None), {"account_id": 12}),
        (200, _orders_page(has_more=True, next_cursor="bad cursor"), {"account_id": 12}),
        (200, _orders_page(orders=[], has_more=True, next_cursor=_CURSOR), {"account_id": 12}),
        (200, _orders_page(has_more=False, next_cursor=_CURSOR), {"account_id": 12}),
        (200, _orders_page(account_id=True), {"account_id": 12}),
        (200, _orders_page(orders=[_order(quantity=1.0)]), {"account_id": 12}),
        (200, _orders_page(orders=[_order(quantity="NaN")]), {"account_id": 12}),
        (200, _orders_page(orders=[_order(reserved_at="2026-10-29T00:00:00")]), {"account_id": 12}),
    ],
    ids=[
        "forbidden-clears-facts",
        "foreign-account",
        "unsuccessful-envelope",
        "missing-opaque-cursor",
        "whitespace-cursor",
        "empty-page-with-continuation",
        "unexpected-cursor-at-end",
        "boolean-account-id",
        "binary-float-decimal",
        "nonfinite-decimal",
        "naive-order-time",
    ],
)
def test_bad_orders_scope_or_page_returns_no_rows_or_followups(
    status_code: int,
    payload: object,
    params: Mapping[str, object],
) -> None:
    view = project_tui_order_history_result(
        _ORDERS,
        payload,
        http_status=status_code,
        requested_params=params,
    )

    assert view["outcome"] == "blocked"
    assert view["sections"] == []
    assert view["next_steps"] == []


@pytest.mark.parametrize(
    ("basis", "event_time_label"),
    [
        ("daily_interval_end", "日线区间截止"),
        ("legacy_source_observed", "模拟成交时刻"),
    ],
)
def test_fills_projection_keeps_decimal_scale_and_distinguishes_time_basis(
    basis: str,
    event_time_label: str,
) -> None:
    response = _fills_page(
        fills=[_fill(observation_basis=basis, quantity="0.000100", price="8.450000")],
        has_more=True,
        next_cursor=_CURSOR,
        raw_payload={"hash": "private"},
    )

    view = project_tui_order_history_result(
        _FILLS,
        response,
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91, "limit": "7"},
    )

    rows = _section_rows(view)
    assert len(rows) == 1
    values = _table_values(rows[0])
    assert values["quantity"] == "0.000100"
    assert values["price"] == "8.450000"
    assert values["event_time_label"] == event_time_label
    assert values["occurred_at"] == _OCCURRED_AT
    assert values["recorded_at"] == _RECORDED_AT
    assert values["verification_status"] == "单条回执已核对"
    steps = view["next_steps"]
    assert steps == [
        {
            "label": "读取下一批回执",
            "action_key": _FILLS,
            "params": {
                "account_id": 12,
                "order_id": 91,
                "limit": 7,
                "cursor": _CURSOR,
            },
        }
    ]
    assert _RECEIPT_SCOPE_NOTE in str(view["business_summary"])
    assert not view.get("blocking_reason")
    assert "单条核对不等于完整成交链证明" in str(view["business_summary"])
    assert "源观察时间" not in _visible_text(view)
    assert _CURSOR not in _visible_text(view)


def test_empty_fills_does_not_claim_no_trade_and_does_not_invent_a_next_page() -> None:
    view = project_tui_order_history_result(
        _FILLS,
        _fills_page(fills=[]),
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91},
    )

    assert view["outcome"] == "success"
    assert view["status"] == "本页未读取到已留存回执"
    assert _RECEIPT_SCOPE_NOTE in str(view["business_summary"])
    assert not view.get("blocking_reason")
    assert _section_rows(view) == []
    assert view["next_steps"] == []
    visible = _visible_text(view)
    assert "空列表不能证明从未成交" in visible
    assert "没有发生" not in visible
    assert "未成交" not in visible.replace(_RECEIPT_SCOPE_NOTE, "")


@pytest.mark.parametrize(
    ("status_code", "response", "params"),
    [
        (403, _fills_page(), {"account_id": 12, "order_id": 91}),
        (404, _fills_page(), {"account_id": 12, "order_id": 91}),
        (200, _fills_page(order_id=92), {"account_id": 12, "order_id": 91}),
        (200, _fills_page(fills=[_fill(order_id=92)]), {"account_id": 12, "order_id": 91}),
        (200, _fills_page(receipt_scope_note=""), {"account_id": 12, "order_id": 91}),
        (
            200,
            _fills_page(fills=[_fill(observation_basis="unknown")]),
            {"account_id": 12, "order_id": 91},
        ),
        (
            200,
            _fills_page(fills=[_fill(verification_status="verified")]),
            {"account_id": 12, "order_id": 91},
        ),
        (
            200,
            _fills_page(membership_cutoff="2026-10-29T01:06:00+08:00"),
            {"account_id": 12, "order_id": 91},
        ),
    ],
    ids=[
        "forbidden-clears-facts",
        "not-found-clears-facts",
        "foreign-order-envelope",
        "foreign-order-row",
        "missing-owner-note",
        "unknown-time-basis",
        "unexpected-verification-scope",
        "future-membership-cutoff",
    ],
)
def test_bad_fill_scope_or_shape_returns_no_rows_or_followups(
    status_code: int,
    response: object,
    params: Mapping[str, object],
) -> None:
    view = project_tui_order_history_result(
        _FILLS,
        response,
        http_status=status_code,
        requested_params=params,
    )

    assert view["outcome"] == "blocked"
    assert view["sections"] == []
    assert view["next_steps"] == []


def test_order_history_runtime_actions_are_two_bounded_read_only_tasks() -> None:
    actions = {
        action["key"]: action
        for action in RUNTIME_SIMULATED_TRADING_ACTIONS
        if action.get("key") in {_ORDERS, _FILLS}
    }
    assert set(actions) == {_ORDERS, _FILLS}
    assert all(action["method"] == "GET" for action in actions.values())
    assert all(action["risk"] == "read" for action in actions.values())
    assert all(action["audience"] == "authenticated" for action in actions.values())
    assert all(action["raw_debug"] is False for action in actions.values())
    assert all(action["screen_key"] == "execution.accounts" for action in actions.values())
    assert all(action["task_group"] == "06 模拟交易记录" for action in actions.values())

    order_fields = {field["key"]: field for field in actions[_ORDERS]["fields"]}
    assert order_fields["account_id"]["binding"] == "path"
    assert order_fields["account_id"]["required"] is True
    assert order_fields["limit"]["default"] == 5
    assert order_fields["limit"]["max"] == 100
    assert order_fields["cursor"]["input_type"] == "hidden"
    assert order_fields["cursor"]["required"] is False

    fill_fields = {field["key"]: field for field in actions[_FILLS]["fields"]}
    assert fill_fields["account_id"]["binding"] == "path"
    assert fill_fields["order_id"]["binding"] == "path"
    assert fill_fields["order_id"]["value_type"] == "integer"
    assert fill_fields["order_id"]["required"] is True
    assert fill_fields["limit"]["default"] == 5
    assert fill_fields["limit"]["max"] == 100
    assert fill_fields["cursor"]["input_type"] == "hidden"


def test_malformed_payload_type_clears_results() -> None:
    for payload in (None, [], {1: "non-string key"}, "raw JSON"):
        view = project_tui_order_history_result(
            _ORDERS,
            payload,
            http_status=200,
            requested_params={"account_id": 12},
        )
        assert view["outcome"] == "blocked"
        assert view["sections"] == []
        assert view["next_steps"] == []


def test_non_mapping_row_cannot_be_partially_presented() -> None:
    view = project_tui_order_history_result(
        _ORDERS,
        _orders_page(orders=[_order(), "not a row"]),
        http_status=200,
        requested_params={"account_id": 12},
    )
    assert view["outcome"] == "blocked"
    assert view["sections"] == []
    assert view["next_steps"] == []


def test_next_page_cursor_is_not_displayed_but_is_carried_with_exact_scope() -> None:
    view = project_tui_order_history_result(
        _FILLS,
        _fills_page(has_more=True, next_cursor=_CURSOR),
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91, "limit": 9},
    )

    assert _visible_text(view).find(_CURSOR) == -1
    steps = view["next_steps"]
    assert isinstance(steps, list) and steps[0]["params"] == {
        "account_id": 12,
        "order_id": 91,
        "limit": 9,
        "cursor": _CURSOR,
    }
