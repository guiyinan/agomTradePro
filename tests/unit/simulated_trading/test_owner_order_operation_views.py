"""Contract tests for the owner order Apply and Cancel JSON boundary."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from django.db import DatabaseError
from django.urls import resolve
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelled,
    OwnerOrderFillApplied,
)
from apps.simulated_trading.domain.order_reservation import OrderReservation
from apps.simulated_trading.interface import owner_order_operation_views
from apps.simulated_trading.interface.owner_order_operation_views import (
    OwnerOrderCancelAPIView,
    OwnerOrderDecisionApplyAPIView,
)
from tests.unit.simulated_trading.test_order_reservation_fill_application import _scenario

_APPLY_PATH = "/api/simulated-trading/accounts/7/orders/41/decisions/701/apply/"
_CANCEL_PATH = "/api/simulated-trading/accounts/7/orders/41/cancel/"


@dataclass
class _Operations:
    """Record public operation arguments and return or raise one typed outcome."""

    fill_outcome: OwnerOrderFillApplied | Exception
    cancel_outcome: OwnerOrderCancelled | Exception
    fill_calls: list[tuple[int, int, int, int, bool]]
    cancel_calls: list[tuple[int, int, int, bool]]

    def apply_retained_fill(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        decision_id: int,
        confirmed: bool,
    ) -> OwnerOrderFillApplied:
        """Record only numeric target identities and the literal confirmation."""

        self.fill_calls.append((account_id, user_id, order_id, decision_id, confirmed))
        if isinstance(self.fill_outcome, Exception):
            raise self.fill_outcome
        return self.fill_outcome

    def cancel_remaining(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        confirmed: bool,
    ) -> OwnerOrderCancelled:
        """Record the owner order and literal confirmation before returning."""

        self.cancel_calls.append((account_id, user_id, order_id, confirmed))
        if isinstance(self.cancel_outcome, Exception):
            raise self.cancel_outcome
        return self.cancel_outcome


def _operations(
    *,
    fill: OwnerOrderFillApplied | Exception | None = None,
    cancel: OwnerOrderCancelled | Exception | None = None,
) -> _Operations:
    """Create complete typed outcomes from the existing pure Domain scenario."""

    scenario = _scenario()
    return _Operations(
        fill_outcome=(
            OwnerOrderFillApplied(
                account_id=scenario.intent.account_id,
                order_id=scenario.context.reservation_id,
                decision_id=701,
                result=scenario.result,
            )
            if fill is None
            else fill
        ),
        cancel_outcome=(
            OwnerOrderCancelled(
                account_id=scenario.intent.account_id,
                order_id=scenario.context.reservation_id,
                reservation=scenario.result.reservation.release_remaining(),
            )
            if cancel is None
            else cancel
        ),
        fill_calls=[],
        cancel_calls=[],
    )


def _post(
    *,
    view: type[OwnerOrderDecisionApplyAPIView] | type[OwnerOrderCancelAPIView],
    path: str,
    user: object | None = None,
    data: object = None,
    content_type: str = "application/json",
) -> Response:
    """Dispatch one authenticated JSON request directly without database access."""

    factory = APIRequestFactory()
    if content_type == "application/json":
        request = factory.post(path, data=data, format="json")
    else:
        request = factory.post(path, data=data, content_type=content_type)
    actor = (
        SimpleNamespace(id=11, pk=11, is_authenticated=True, is_active=True)
        if user is None
        else user
    )
    force_authenticate(request, user=actor)
    if view is OwnerOrderDecisionApplyAPIView:
        return view.as_view()(request, account_id=7, order_id=41, decision_id=701)
    return view.as_view()(request, account_id=7, order_id=41)


def test_apply_response_projects_only_proven_fill_economics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the immutable fill result without leaking source locators or guessed receipt data."""

    operations = _operations()
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: operations,
    )

    response = _post(
        view=OwnerOrderDecisionApplyAPIView, path=_APPLY_PATH, data={"confirmed": True}
    )

    scenario = _scenario()
    economics = scenario.result.economics
    assert response.status_code == 200
    assert response.accepted_media_type == "application/json"
    assert response.data == {
        "success": True,
        "account_id": scenario.intent.account_id,
        "order_id": scenario.context.reservation_id,
        "decision_id": 701,
        "trade_id": scenario.result.trade_id,
        "fill_sequence": economics.cumulative_state.fill_count,
        "asset_code": economics.asset_code,
        "side": economics.side.value,
        "quantity": str(economics.quantity),
        "price": str(economics.price),
        "gross_amount": str(economics.gross_amount),
        "incremental_fees": {
            "commission": str(economics.incremental_fees.commission),
            "transfer_fee": str(economics.incremental_fees.transfer_fee),
            "stamp_duty": str(economics.incremental_fees.stamp_duty),
            "slippage": str(economics.incremental_fees.slippage),
            "total_fee": str(economics.incremental_fees.total_fee),
        },
        "occurred_at": economics.fill_occurred_at.isoformat(),
        "status": "applied",
        "replayed": False,
    }
    assert not {
        "receipt_id",
        "recorded_at",
        "observation_basis",
        "source_namespace",
        "source_version",
        "event_payload_hash",
        "idempotency_key",
    }.intersection(response.data)
    assert operations.fill_calls == [(7, 11, 41, 701, True)]


def test_cancel_response_uses_current_terminal_status_and_cumulative_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose cumulative release values and never invent a cancellation replay flag."""

    operations = _operations()
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: operations,
    )
    response = _post(view=OwnerOrderCancelAPIView, path=_CANCEL_PATH, data={"confirmed": True})
    scenario = _scenario()
    reservation = scenario.result.reservation.release_remaining()

    assert response.status_code == 200
    assert response.data == {
        "success": True,
        "account_id": scenario.intent.account_id,
        "order_id": scenario.context.reservation_id,
        "status": reservation.status.value,
        "released_cash": str(reservation.cash_released),
        "released_shares": str(reservation.shares_released),
        "remaining_cash": str(reservation.remaining_cash),
        "remaining_shares": str(reservation.remaining_shares),
    }
    assert "replayed" not in response.data
    assert operations.cancel_calls == [(7, 11, 41, True)]


@pytest.mark.parametrize(
    ("path", "view", "data", "content_type"),
    [
        (_APPLY_PATH, OwnerOrderDecisionApplyAPIView, {"confirmed": False}, "application/json"),
        (_APPLY_PATH, OwnerOrderDecisionApplyAPIView, {"confirmed": 1}, "application/json"),
        (
            _APPLY_PATH,
            OwnerOrderDecisionApplyAPIView,
            {"confirmed": True, "price": "10.00"},
            "application/json",
        ),
        (_CANCEL_PATH, OwnerOrderCancelAPIView, {}, "application/json"),
        (
            _APPLY_PATH + "?unexpected=1",
            OwnerOrderDecisionApplyAPIView,
            {"confirmed": True},
            "application/json",
        ),
        (
            _CANCEL_PATH,
            OwnerOrderCancelAPIView,
            "confirmed=true",
            "application/x-www-form-urlencoded",
        ),
    ],
)
def test_request_rejects_nonliteral_confirmation_extra_fields_and_non_json(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    view: type[OwnerOrderDecisionApplyAPIView] | type[OwnerOrderCancelAPIView],
    data: object,
    content_type: str,
) -> None:
    """Reject malformed bodies and query values before constructing the use case."""

    called = False

    def unexpected_builder() -> _Operations:
        nonlocal called
        called = True
        return _operations()

    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        unexpected_builder,
    )
    response = _post(view=view, path=path, data=data, content_type=content_type)

    assert response.status_code == 400
    assert response.data == {
        "success": False,
        "code": "OWNER_ORDER_INPUT_INVALID",
        "message": "订单操作请求无效",
    }
    assert called is False


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "indeterminate"),
    [
        (
            SimulatedTradeAccountScopeUnavailable("private order key"),
            404,
            "OWNER_ORDER_NOT_FOUND",
            False,
        ),
        (
            SimulatedTradeExecutionInputError("private order key"),
            400,
            "SIMULATED_TRADE_INPUT_INVALID",
            False,
        ),
        (
            SimulatedTradeExecutionBlocked("private order key"),
            409,
            "SIMULATED_TRADE_EXECUTION_BLOCKED",
            False,
        ),
        (
            SimulatedTradeExecutionResultUnknown("private order key"),
            503,
            "SIMULATED_TRADE_EXECUTION_RESULT_UNKNOWN",
            True,
        ),
        (DatabaseError("private order key"), 503, "OWNER_ORDER_OPERATION_UNAVAILABLE", True),
    ],
)
def test_application_errors_have_stable_status_and_never_echo_internal_text(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_code: str,
    indeterminate: bool,
) -> None:
    """Map scope, input, blocked, unknown and database outcomes without details."""

    operations = _operations(fill=error)
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: operations,
    )
    response = _post(
        view=OwnerOrderDecisionApplyAPIView,
        path=_APPLY_PATH,
        data={"confirmed": True},
    )

    assert response.status_code == expected_status
    assert response.data["success"] is False
    assert response.data["code"] == expected_code
    assert "private order key" not in str(response.data)
    assert response.data.get("effects_indeterminate", False) is indeterminate


@pytest.mark.parametrize(
    ("operation", "view", "payload_builder"),
    [
        ("apply", OwnerOrderDecisionApplyAPIView, "fill_applied_payload"),
        ("cancel", OwnerOrderCancelAPIView, "order_cancelled_payload"),
    ],
)
def test_response_projection_failure_is_reported_as_indeterminate_after_writer_return(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    view: type[OwnerOrderDecisionApplyAPIView] | type[OwnerOrderCancelAPIView],
    payload_builder: str,
) -> None:
    """Do not imply a write failed when public response projection fails afterward."""

    operations = _operations()
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: operations,
    )

    def fail_after_write(_outcome: object) -> object:
        """Simulate a projection bug after the fake writer recorded its call."""

        raise ValueError("private post-write projection detail")

    monkeypatch.setattr(owner_order_operation_views, payload_builder, fail_after_write)
    path = _APPLY_PATH if operation == "apply" else _CANCEL_PATH

    response = _post(view=view, path=path, data={"confirmed": True})

    assert response.status_code == 503
    assert response.data == {
        "success": False,
        "code": "OWNER_ORDER_OPERATION_RESULT_UNKNOWN",
        "message": "操作结果暂无法确认，请先核对订单历史后使用相同目标重试",
        "effects_indeterminate": True,
    }
    assert "private post-write projection detail" not in str(response.data)
    if operation == "apply":
        assert operations.fill_calls == [(7, 11, 41, 701, True)]
        assert operations.cancel_calls == []
    else:
        assert operations.cancel_calls == [(7, 11, 41, True)]
        assert operations.fill_calls == []


def test_explicit_session_authentication_json_parser_and_confirmation_contract() -> None:
    """Pin the write endpoints to session auth and JSON rather than token/form fallbacks."""

    assert OwnerOrderDecisionApplyAPIView.authentication_classes == [SessionAuthentication]
    assert OwnerOrderCancelAPIView.authentication_classes == [SessionAuthentication]
    assert OwnerOrderDecisionApplyAPIView.permission_classes == [IsAuthenticated]
    assert OwnerOrderCancelAPIView.permission_classes == [IsAuthenticated]
    assert OwnerOrderDecisionApplyAPIView.parser_classes == [JSONParser]
    assert OwnerOrderCancelAPIView.parser_classes == [JSONParser]


def test_public_route_names_resolve_to_the_two_owner_write_views() -> None:
    """Keep the documented API paths wired to their explicit Interface views."""

    apply_route = resolve("/api/simulated-trading/accounts/7/orders/41/decisions/701/apply/")
    cancel_route = resolve("/api/simulated-trading/accounts/7/orders/41/cancel/")

    assert apply_route.url_name == "order-decision-apply"
    assert apply_route.func.view_class is OwnerOrderDecisionApplyAPIView
    assert cancel_route.url_name == "order-cancel"
    assert cancel_route.func.view_class is OwnerOrderCancelAPIView


def test_domain_cancel_result_is_terminal_and_typed() -> None:
    """Keep response construction grounded in the real reservation value object."""

    scenario = _scenario()
    reservation = scenario.result.reservation.release_remaining()
    assert isinstance(reservation, OrderReservation)
    operation = OwnerOrderCancelled(
        account_id=scenario.intent.account_id,
        order_id=scenario.context.reservation_id,
        reservation=reservation,
    )
    assert operation.reservation is reservation
