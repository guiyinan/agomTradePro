"""Owner-facing durable decision state, without inferring a missing posting."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.terminal.application.tui_order_history_result import project_tui_order_history_result
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)
from tests.unit.terminal.test_tui_order_history_result import _orders_page

ACTION = "simulated-trading.order-decisions"
APPLY_ACTION = "simulated-trading.order-decision-apply"
CANCEL_ACTION = "simulated-trading.order-cancel"
NOTE = "仅核对已保存的撮合决定及原成交回执；缺少回执表示入账尚未确认，不能据此重新撮合或释放预留。"


def _page() -> dict[str, object]:
    return {
        "success": True,
        "account_id": 12,
        "order_id": 91,
        "decisions": [
            {
                "decision_id": 801,
                "order_id": 91,
                "session_date": "2026-10-28",
                "outcome": "matched",
                "matched_quantity": "100.000000",
                "matched_price": "8.4500",
                "recorded_at": "2026-10-29T00:40:00+08:00",
                "occurred_at": "2026-10-28T15:00:00+08:00",
                "posting_state": "unconfirmed",
                "receipt_id": None,
                "trade_id": None,
            }
        ],
        "has_more": False,
        "next_cursor": None,
        "membership_cutoff": "2026-10-29T01:00:00+08:00",
        "read_at": "2026-10-29T01:05:00+08:00",
        "decision_scope_note": NOTE,
    }


def _project(payload: object, status: int = 200) -> dict[str, object]:
    return project_tui_order_history_result(
        ACTION,
        payload,
        http_status=status,
        requested_params={"account_id": 12, "order_id": 91, "limit": 5},
    )


def test_decision_task_and_order_followup_are_explicit_reads() -> None:
    action = next((a for a in RUNTIME_SIMULATED_TRADING_ACTIONS if a["key"] == ACTION), None)
    assert action is not None
    assert (action["method"], action["risk"], action["screen_key"]) == (
        "GET",
        "read",
        "execution.accounts",
    )
    assert action["raw_debug"] is False
    view = project_tui_order_history_result(
        "simulated-trading.orders",
        _orders_page(),
        http_status=200,
        requested_params={"account_id": 12, "limit": 5},
    )
    assert any(step["action_key"] == ACTION for step in view["next_steps"])


def test_unconfirmed_match_offers_exact_saved_decision_apply_only() -> None:
    view = _project(_page())
    apply_steps = [step for step in view["next_steps"] if step["action_key"] == APPLY_ACTION]
    assert apply_steps == [
        {
            "label": "按原撮合决定 801 恢复入账",
            "action_key": APPLY_ACTION,
            "params": {"account_id": 12, "order_id": 91, "decision_id": 801},
        }
    ]
    applied = _page()
    applied["decisions"][0].update(posting_state="applied", receipt_id=501, trade_id=701)
    assert not [
        step for step in _project(applied)["next_steps"] if step["action_key"] == APPLY_ACTION
    ]
    no_match = _page()
    no_match["decisions"][0].update(
        outcome="no_match",
        posting_state="not_applicable",
        matched_quantity="0",
        matched_price=None,
        occurred_at=None,
    )
    assert not [
        step for step in _project(no_match)["next_steps"] if step["action_key"] == APPLY_ACTION
    ]


def test_active_order_offers_cancel_for_exact_order_and_current_reserve() -> None:
    view = project_tui_order_history_result(
        "simulated-trading.orders",
        _orders_page(),
        http_status=200,
        requested_params={"account_id": 12, "limit": 5},
    )
    cancel_steps = [step for step in view["next_steps"] if step["action_key"] == CANCEL_ACTION]
    assert cancel_steps == [
        {
            "label": "撤销订单 91 当前剩余预留",
            "action_key": CANCEL_ACTION,
            "params": {"account_id": 12, "order_id": 91},
        }
    ]
    page = _orders_page()
    page["orders"][0].update(status="completed")
    terminal = project_tui_order_history_result(
        "simulated-trading.orders",
        page,
        http_status=200,
        requested_params={"account_id": 12, "limit": 5},
    )
    assert not [step for step in terminal["next_steps"] if step["action_key"] == CANCEL_ACTION]


@pytest.mark.parametrize("valid_scope", [True, False])
def test_workbench_preserves_decision_scope_and_blocks_debug_leakage(
    monkeypatch: pytest.MonkeyPatch, valid_scope: bool
) -> None:
    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    action = deepcopy(next(a for a in RUNTIME_SIMULATED_TRADING_ACTIONS if a["key"] == ACTION))
    payload = _page()
    if not valid_scope:
        payload["account_id"] = 13
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **kwargs: {"status_code": 200, "payload": payload}
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"read"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": ACTION})
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})
    result = service.run_action(
        action_key=ACTION,
        params={"account_id": 12, "order_id": 91, "limit": 5},
        user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=False),
    )
    assert result["outcome"] == ("success" if valid_scope else "blocked")
    assert result["debug"]["raw_response"] is None
    if not valid_scope:
        assert result["view_model"]["sections"] == []
        assert result["next_steps"] == []


@pytest.mark.parametrize("state", ["unconfirmed", "applied", "not_applicable"])
def test_decision_outcomes_keep_exact_values_and_distinct_posting_state(state: str) -> None:
    payload = _page()
    row = payload["decisions"][0]
    row["posting_state"] = state
    if state == "applied":
        row.update(receipt_id=501, trade_id=701)
    elif state == "not_applicable":
        row.update(outcome="no_match", matched_quantity="0", matched_price=None, occurred_at=None)
    view = _project(payload)
    assert view["outcome"] == "success"
    assert NOTE in view["business_summary"]
    fields = {f["key"]: f["value"] for f in view["sections"][0]["rows"][0]["fields"]}
    assert fields["matched_quantity"] == row["matched_quantity"]
    assert fields["recorded_at"] == row["recorded_at"]
    assert (
        fields["posting_state"]
        == {
            "unconfirmed": "入账尚未确认",
            "applied": "已核对原成交回执",
            "not_applicable": "本次未撮合成交",
        }[state]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"posting_state": "applied"},
        {"receipt_id": 501},
        {"order_id": 92},
        {"matched_quantity": 100.0},
        {"matched_price": "NaN"},
        {"outcome": "blocked"},
        {"recorded_at": "2026-10-30T00:00:00+08:00"},
        {"session_date": "2026-10-28T00:00:00"},
        {"posting_state": "not_applicable"},
        {"occurred_at": None},
    ],
)
def test_inconsistent_decision_rows_clear_all_prior_facts(change: dict[str, object]) -> None:
    payload = deepcopy(_page())
    payload["decisions"][0].update(change)
    view = _project(payload)
    assert view["outcome"] == "blocked"
    assert view["sections"] == []
    assert view["next_steps"] == []


def test_empty_and_paged_decisions_do_not_claim_no_unresolved_events() -> None:
    payload = _page()
    payload.update(has_more=True, next_cursor="opaque.cursor")
    view = _project(payload)
    assert view["outcome"] == "success"
    step = next(s for s in view["next_steps"] if s["action_key"] == ACTION)
    assert step["params"] == {
        "account_id": 12,
        "order_id": 91,
        "limit": 5,
        "cursor": "opaque.cursor",
    }
    payload.update(decisions=[], has_more=False, next_cursor=None)
    view = _project(payload)
    assert view["outcome"] == "success"
    assert "不能" in view["business_summary"]
    assert view["sections"][0]["rows"] == []


@pytest.mark.parametrize("status", [403, 404, 409, 503])
def test_failed_decision_reads_never_keep_previous_facts(status: int) -> None:
    view = _project(_page(), status)
    assert view["outcome"] == "blocked"
    assert view["sections"] == []


def _apply_result(**overrides: object) -> dict[str, object]:
    fees: dict[str, object] = {
        "commission": "0.010000",
        "transfer_fee": "0.001000",
        "stamp_duty": "0.000000",
        "slippage": "0.020000",
        "total_fee": "0.031000",
    }
    result: dict[str, object] = {
        "success": True,
        "account_id": 12,
        "order_id": 91,
        "decision_id": 801,
        "trade_id": 701,
        "fill_sequence": 2,
        "asset_code": "600000.SH",
        "side": "buy",
        "quantity": "100.000000",
        "price": "8.450000",
        "gross_amount": "845.000000",
        "incremental_fees": fees,
        "occurred_at": "2026-10-28T15:00:00+08:00",
        "status": "applied",
        "replayed": False,
        "operation_key": "private-operation-key",
        "source_reference": {"hash": "private-source-hash"},
        "receipt_id": 501,
        "recorded_at": "2026-10-29T00:50:00+08:00",
        "observation_basis": "daily_interval_end",
    }
    result.update(overrides)
    return result


def _cancel_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "success": True,
        "account_id": 12,
        "order_id": 91,
        "status": "cancelled",
        "released_cash": "845.000000",
        "released_shares": "0.000000",
        "remaining_cash": "0.000000",
        "remaining_shares": "0.000000",
    }
    result.update(overrides)
    return result


def test_apply_projection_uses_original_decision_and_exact_public_economics() -> None:
    view = project_tui_order_history_result(
        APPLY_ACTION,
        _apply_result(),
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91, "decision_id": 801},
    )

    assert view["outcome"] == "success"
    assert view["title"] == "恢复原撮合决定"
    fields = {field["key"]: field["value"] for field in view["fields"]}
    assert fields["account_id"] == "12"
    assert fields["order_id"] == "91"
    assert fields["decision_id"] == "801"
    assert fields["trade_id"] == "701"
    assert fields["fill_sequence"] == "2"
    assert fields["quantity"] == "100.000000"
    assert fields["price"] == "8.450000"
    assert fields["gross_amount"] == "845.000000"
    assert fields["commission"] == "0.010000"
    assert fields["transfer_fee"] == "0.001000"
    assert fields["stamp_duty"] == "0.000000"
    assert fields["slippage"] == "0.020000"
    assert fields["total_fee"] == "0.031000"
    assert fields["occurred_at"] == "2026-10-28T15:00:00+08:00"
    assert fields["replayed"] == "否"
    visible = str(view["business_summary"]) + repr(view["fields"])
    assert "原撮合决定" in str(view["business_summary"])
    assert "receipt_id" not in visible and "source" not in visible and "hash" not in visible
    assert any(step["action_key"] == "simulated-trading.order-fills" for step in view["next_steps"])


def test_apply_replay_is_reported_without_claiming_a_second_fill() -> None:
    view = project_tui_order_history_result(
        APPLY_ACTION,
        _apply_result(replayed=True),
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91, "decision_id": 801},
    )

    fields = {field["key"]: field["value"] for field in view["fields"]}
    assert view["outcome"] == "success"
    assert fields["replayed"] == "是"
    assert "原样核对" in str(view["business_summary"])
    assert "再次成交" not in str(view["business_summary"])


@pytest.mark.parametrize(
    ("terminal_status", "visible_status"),
    [("cancelled", "已撤销"), ("completed", "已完成")],
)
def test_cancel_projection_labels_cumulative_release_and_terminal_state(
    terminal_status: str,
    visible_status: str,
) -> None:
    view = project_tui_order_history_result(
        CANCEL_ACTION,
        _cancel_result(status=terminal_status),
        http_status=200,
        requested_params={"account_id": 12, "order_id": 91},
    )

    assert view["outcome"] == "success"
    assert view["title"] == "撤销订单剩余预留"
    fields = {field["key"]: field["value"] for field in view["fields"]}
    assert fields["status"] == visible_status
    assert fields["released_cash"] == "845.000000"
    assert fields["released_shares"] == "0.000000"
    assert fields["remaining_cash"] == "0.000000"
    assert fields["remaining_shares"] == "0.000000"
    summary = str(view["business_summary"])
    assert "累计释放" in summary
    assert "本次释放" not in summary


@pytest.mark.parametrize(
    ("action", "payload", "params"),
    [
        (
            APPLY_ACTION,
            _apply_result(order_id=92),
            {"account_id": 12, "order_id": 91, "decision_id": 801},
        ),
        (
            APPLY_ACTION,
            _apply_result(decision_id=802),
            {"account_id": 12, "order_id": 91, "decision_id": 801},
        ),
        (
            APPLY_ACTION,
            _apply_result(quantity=100.0),
            {"account_id": 12, "order_id": 91, "decision_id": 801},
        ),
        (
            APPLY_ACTION,
            _apply_result(incremental_fees={"total_fee": "0.03"}),
            {"account_id": 12, "order_id": 91, "decision_id": 801},
        ),
        (CANCEL_ACTION, _cancel_result(account_id=13), {"account_id": 12, "order_id": 91}),
        (CANCEL_ACTION, _cancel_result(status="active"), {"account_id": 12, "order_id": 91}),
        (CANCEL_ACTION, _cancel_result(released_cash=0.0), {"account_id": 12, "order_id": 91}),
    ],
    ids=[
        "foreign-order-apply",
        "foreign-decision-apply",
        "numeric-not-decimal-string",
        "incomplete-fee-basis",
        "foreign-account-cancel",
        "nonterminal-cancel",
        "numeric-release",
    ],
)
def test_invalid_operation_result_clears_all_facts(
    action: str,
    payload: object,
    params: dict[str, object],
) -> None:
    view = project_tui_order_history_result(
        action, payload, http_status=200, requested_params=params
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["sections"] == []
    assert view["next_steps"] == []


def test_known_operation_rejection_hides_owner_message_and_clears_facts() -> None:
    view = project_tui_order_history_result(
        APPLY_ACTION,
        {"success": False, "code": "PRIVATE_CODE", "message": "private backend detail"},
        http_status=409,
        requested_params={"account_id": 12, "order_id": 91, "decision_id": 801},
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["sections"] == []
    assert view["next_steps"] == []
    assert "PRIVATE_CODE" not in repr(view)
    assert "private backend detail" not in repr(view)


def test_indeterminate_apply_requires_original_read_before_same_target_retry() -> None:
    view = project_tui_order_history_result(
        APPLY_ACTION,
        {"success": False, "code": "fill_outcome_unknown", "effects_indeterminate": True},
        http_status=503,
        requested_params={"account_id": 12, "order_id": 91, "decision_id": 801},
    )

    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert view["sections"] == []
    summary = str(view["business_summary"])
    assert "结果暂不能确认" in summary
    assert "原撮合决定" in summary and "成交回执" in summary
    assert "重新撮合" in summary
    assert {step["action_key"] for step in view["next_steps"]} == {
        "simulated-trading.order-decisions",
        "simulated-trading.order-fills",
    }
    assert all(
        step["params"].get("account_id") == 12 and step["params"].get("order_id") == 91
        for step in view["next_steps"]
    )


def test_order_history_actions_expose_confirmed_owner_mutations_only() -> None:
    actions = {
        action["key"]: action
        for action in RUNTIME_SIMULATED_TRADING_ACTIONS
        if action.get("key") in {APPLY_ACTION, CANCEL_ACTION}
    }
    assert set(actions) == {APPLY_ACTION, CANCEL_ACTION}
    for action in actions.values():
        assert action["method"] == "POST"
        assert action["risk"] == "write"
        assert action["audience"] == "authenticated"
        assert action["confirmation_required"] is True
        assert action["audit_required"] is True
        assert action["session_auth_required"] is True
        assert action["raw_debug"] is False
        assert action["screen_key"] == "execution.accounts"
        assert action["effect"] == "update"
        fields = {field["key"]: field for field in action["fields"]}
        assert fields["account_id"]["binding"] == "path"
        assert fields["order_id"]["binding"] == "path"
        assert fields["confirmed"]["binding"] == "body"
        assert fields["confirmed"]["input_type"] == "hidden"
        assert fields["confirmed"]["default"] is True
        assert all(field["binding"] != "query" for field in action["fields"])
    apply_fields = {field["key"]: field for field in actions[APPLY_ACTION]["fields"]}
    assert apply_fields["decision_id"]["binding"] == "path"


def test_owner_mutation_confirmation_names_exact_target_scope() -> None:
    from apps.terminal.application.tui_order_history_result import (
        order_operation_confirmation_message,
    )

    apply_message = order_operation_confirmation_message(
        APPLY_ACTION,
        {"account_id": "12", "order_id": "91", "decision_id": "801"},
    )
    cancel_message = order_operation_confirmation_message(
        CANCEL_ACTION, {"account_id": 12, "order_id": 91}
    )
    assert apply_message == "确认对账户 12 的订单 91，按原撮合决定 801 恢复入账？不会重新撮合。"
    assert cancel_message == "确认撤销账户 12 的订单 91 当前剩余未成交数量？已成交部分不会改变。"
    assert (
        order_operation_confirmation_message(
            APPLY_ACTION, {"account_id": True, "order_id": 91, "decision_id": 801}
        )
        is None
    )


@pytest.mark.parametrize(
    ("action_key", "params", "payload", "expected_endpoint"),
    [
        (
            APPLY_ACTION,
            {"account_id": 12, "order_id": 91, "decision_id": 801},
            _apply_result(),
            "/api/simulated-trading/accounts/12/orders/91/decisions/801/apply/",
        ),
        (
            CANCEL_ACTION,
            {"account_id": 12, "order_id": 91},
            _cancel_result(),
            "/api/simulated-trading/accounts/12/orders/91/cancel/",
        ),
    ],
)
def test_owner_mutation_confirmation_sends_only_confirmed_json(
    monkeypatch: pytest.MonkeyPatch,
    action_key: str,
    params: dict[str, object],
    payload: object,
    expected_endpoint: str,
) -> None:
    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    action = deepcopy(next(a for a in RUNTIME_SIMULATED_TRADING_ACTIONS if a["key"] == action_key))
    calls: list[dict[str, object]] = []
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **kwargs: calls.append(kwargs)
            or {"status_code": 200, "payload": payload}
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda user: {"write"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": action_key})
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})
    user = SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=False)

    pending = service.run_action(
        action_key=action_key,
        params=params,
        user=user,
        session=SimpleNamespace(session_key="session"),
    )
    assert pending["confirmation_required"] is True
    assert pending["confirmation"]["message"]
    assert calls == []

    result = service.run_action(
        action_key=action_key,
        params=params,
        user=user,
        session=SimpleNamespace(session_key="session"),
        confirmed=True,
    )
    assert result["outcome"] == "success"
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["endpoint"] == expected_endpoint
    assert calls[0]["params"] == {}
    assert calls[0]["body"] == {"confirmed": True}
