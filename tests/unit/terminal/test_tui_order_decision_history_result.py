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
