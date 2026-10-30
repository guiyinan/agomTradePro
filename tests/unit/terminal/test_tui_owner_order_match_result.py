"""Keep a recorded matching decision distinct from posting its original fill."""

from __future__ import annotations

import pytest

from apps.terminal.application.tui_order_history_result import order_operation_confirmation_message
from apps.terminal.application.tui_order_match_result import project_tui_order_match_result

ACTION = "simulated-trading.order-match"
PARAMS = {"account_id": 7, "order_id": 41, "session_date": "2026-10-16"}


def _payload(**changes: object) -> dict[str, object]:
    return {
        "success": True,
        "outcome": "success",
        **PARAMS,
        "decision_recorded": True,
        "decision_outcome": "no_match",
        "matched_quantity": "0.000000",
        "matched_price": None,
        "reason_code": "LIMIT_NOT_REACHED",
        "replayed": False,
        **changes,
    }


@pytest.mark.parametrize("replayed", [True, False])
def test_saved_no_match_is_known_but_does_not_report_posting(replayed: bool) -> None:
    view = project_tui_order_match_result(
        _payload(replayed=replayed), http_status=200, requested_params=PARAMS
    )
    assert view["outcome"] == "success"
    assert "未撮合" in view["status"]
    assert "入账" in view["business_summary"]
    assert view["next_steps"] == [
        {
            "label": "核对该订单已保存的撮合决定",
            "action_key": "simulated-trading.order-decisions",
            "params": {"account_id": 7, "order_id": 41, "limit": 5},
        }
    ]


def test_saved_match_preserves_exact_values_and_requires_original_apply() -> None:
    view = project_tui_order_match_result(
        _payload(decision_outcome="matched", matched_quantity="10.000001", matched_price="9.9999"),
        http_status=200,
        requested_params=PARAMS,
    )
    assert view["outcome"] == "success"
    fields = {field["key"]: field["value"] for field in view["fields"]}
    assert fields["matched_quantity"] == "10.000001"
    assert fields["matched_price"] == "9.9999"
    assert "单独确认" in view["business_summary"]
    assert all(
        step["action_key"] != "simulated-trading.order-decision-apply"
        for step in view["next_steps"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": 8},
        {"order_id": 42},
        {"session_date": "2026-10-19"},
        {"decision_recorded": False},
        {"replayed": "false"},
        {"matched_quantity": "1"},
        {"decision_outcome": "matched", "matched_price": "10"},
        {"decision_outcome": "blocked"},
        {"matched_quantity": 0},
    ],
)
def test_mismatched_or_unproved_decisions_clear_displayed_facts(changes: dict[str, object]) -> None:
    view = project_tui_order_match_result(
        _payload(**changes), http_status=200, requested_params=PARAMS
    )
    assert view["outcome"] == "blocked"
    assert view["status"] == "操作结果未确认"
    assert view["fields"] == []
    assert view["sections"] == []


def test_unknown_result_links_only_to_original_order_history() -> None:
    view = project_tui_order_match_result(
        {"success": False, "effects_indeterminate": True}, http_status=503, requested_params=PARAMS
    )
    assert view["outcome"] == "blocked"
    assert view["fields"] == []
    assert "不能确认" in view["business_summary"]
    assert view["next_steps"][0]["params"] == {"account_id": 7, "order_id": 41, "limit": 5}


@pytest.mark.parametrize(
    ("http_status", "error_code", "expected_status", "expected_phrase"),
    [
        (400, "OWNER_ORDER_INPUT_INVALID", "请求校验未通过", "未通过校验"),
        (
            409,
            "OWNER_ORDER_MATCH_QMT_BINDING_UNAVAILABLE",
            "撮合条件未满足",
            "QMT 绑定",
        ),
        (
            409,
            "OWNER_ORDER_MATCH_QMT_BINDING_AMBIGUOUS",
            "撮合条件未满足",
            "QMT 绑定",
        ),
        (409, "OWNER_ORDER_MATCH_ORDER_NOT_ACTIVE", "撮合条件未满足", "订单已终结"),
        (409, "ORDER_RESERVATION_TERMINAL", "撮合条件未满足", "订单已终结"),
        (409, "LOCAL_DAILY_MATCH_PENDING_FILL", "撮合条件未满足", "待处理的撮合决定"),
    ],
)
def test_known_request_rejections_and_match_gates_are_not_reported_as_unknown(
    http_status: int, error_code: str, expected_status: str, expected_phrase: str
) -> None:
    view = project_tui_order_match_result(
        {"success": False, "code": error_code, "message": "private backend detail"},
        http_status=http_status,
        requested_params=PARAMS,
    )

    assert view["outcome"] == "blocked"
    assert view["status"] == expected_status
    assert expected_phrase in view["business_summary"]
    assert "不能确认" not in view["business_summary"]
    assert error_code not in repr(view)
    assert "private backend detail" not in repr(view)
    assert view["next_steps"][0]["params"] == {"account_id": 7, "order_id": 41, "limit": 5}


@pytest.mark.parametrize(
    ("http_status", "error_code", "effects_indeterminate"),
    [
        (503, "OWNER_ORDER_OPERATION_RESULT_UNKNOWN", True),
        (409, "OWNER_ORDER_MATCH_QMT_BINDING_UNAVAILABLE", True),
        (409, "LOCAL_DAILY_MATCH_RECORD_INVALID", False),
    ],
)
def test_unknown_or_conflicting_match_results_still_require_history_readback(
    http_status: int, error_code: str, effects_indeterminate: bool
) -> None:
    view = project_tui_order_match_result(
        {
            "success": False,
            "code": error_code,
            "effects_indeterminate": effects_indeterminate,
        },
        http_status=http_status,
        requested_params=PARAMS,
    )

    assert view["outcome"] == "blocked"
    assert view["status"] == "操作结果未确认"
    assert "不能确认" in view["business_summary"]
    assert error_code not in repr(view)
    assert view["next_steps"][0]["params"] == {"account_id": 7, "order_id": 41, "limit": 5}


def test_confirmation_identifies_the_chosen_session_and_separate_posting() -> None:
    message = order_operation_confirmation_message(ACTION, PARAMS)
    assert message is not None and "2026-10-16" in message and "订单 41" in message
    assert "单独确认" in message
    assert (
        order_operation_confirmation_message(ACTION, {**PARAMS, "session_date": "2026-02-30"})
        is None
    )


def test_match_metadata_requires_selected_day_session_and_confirmation() -> None:
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
        RUNTIME_SIMULATED_TRADING_ACTIONS,
    )

    action = next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == ACTION)
    assert action["method"] == "POST"
    assert action["risk"] == "write"
    assert action["session_auth_required"] is True
    assert action["confirmation_required"] is True
    assert action["audit_required"] is True
    fields = {field["key"]: field for field in action["fields"]}
    assert set(fields) == {"account_id", "order_id", "session_date", "confirmed"}
    day = fields["session_date"]
    assert day["binding"] == "body" and day["input_type"] == "date"
    assert day["required"] is True and "default" not in day
    assert fields["confirmed"]["default"] is True
