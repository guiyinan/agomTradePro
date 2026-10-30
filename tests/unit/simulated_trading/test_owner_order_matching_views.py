"""Contract tests for the ordinary owner's explicit daily-order match endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
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
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    local_daily_match_request_hash,
)
from apps.simulated_trading.application.owner_order_matching import OwnerOrderMatchRecorded
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchOutcome,
    LocalOrderMatchResult,
)
from apps.simulated_trading.interface import owner_order_matching_views
from apps.simulated_trading.interface.owner_order_matching_views import OwnerOrderMatchAPIView

_MATCH_PATH = "/api/simulated-trading/accounts/7/orders/41/match/"
_ACTOR_ID = 11
_SESSION_DATE = date(2026, 10, 28)
_BINDING_ID = str(UUID("10000000-0000-4000-8000-000000000041"))


@dataclass
class _MatchUseCase:
    """Capture the exact public identities and return or raise one typed result."""

    outcome: OwnerOrderMatchRecorded | Exception
    calls: list[tuple[int, int, int, date, bool]]

    def execute(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        session_date: date,
        confirmed: bool,
    ) -> OwnerOrderMatchRecorded:
        """Retain the resolved numeric scope without accepting source values."""

        self.calls.append((account_id, user_id, order_id, session_date, confirmed))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _recorded(*, replayed: bool = False) -> OwnerOrderMatchRecorded:
    """Build one complete valid persisted NO_MATCH outcome for the response edge."""

    command = LocalDailyMatchCommand(
        account_id=7,
        user_id=_ACTOR_ID,
        order_idempotency_key="retained-order-key-41",
        operation_key=f"owner-order-match.v1:41:{_SESSION_DATE.isoformat()}",
        session_date=_SESSION_DATE,
        qmt_binding_id=_BINDING_ID,
    )
    decision = LocalDailyMatchDecision(
        command=command,
        request_hash=local_daily_match_request_hash(command),
        result=LocalOrderMatchResult(
            outcome=LocalMatchOutcome.NO_MATCH,
            reason_code="DAILY_CLOSE_NOT_CROSSED",
            matched_quantity=Decimal("0.000000"),
            matched_price=None,
        ),
        event=None,
        replayed=replayed,
    )
    return OwnerOrderMatchRecorded(account_id=7, order_id=41, decision=decision)


def _post(
    *,
    body: str,
    content_type: str = "application/json",
    query: str = "",
    authenticated: bool = True,
) -> Response:
    """Dispatch one raw HTTP body without database access or caller source claims."""

    request = APIRequestFactory().post(
        f"{_MATCH_PATH}{query}",
        data=body,
        content_type=content_type,
    )
    if authenticated:
        force_authenticate(
            request,
            user=SimpleNamespace(
                id=_ACTOR_ID,
                pk=_ACTOR_ID,
                is_authenticated=True,
                is_active=True,
            ),
        )
    return OwnerOrderMatchAPIView.as_view()(request, account_id=7, order_id=41)


def test_owner_order_match_route_and_session_contract_resolve() -> None:
    """Pin the route to the session-authenticated JSON owner matching view."""

    from django.urls import resolve

    route = resolve(_MATCH_PATH)

    assert route.url_name == "order-match"
    assert route.func.view_class is OwnerOrderMatchAPIView
    assert OwnerOrderMatchAPIView.authentication_classes == [SessionAuthentication]
    assert OwnerOrderMatchAPIView.permission_classes == [IsAuthenticated]
    assert OwnerOrderMatchAPIView.parser_classes == [JSONParser]


def test_match_requires_a_session_principal_before_constructing_the_use_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject anonymous calls before any owner or market dependency is constructed."""

    called = False

    def unexpected_builder() -> _MatchUseCase:
        """Detect accidental use-case construction for an unauthenticated request."""

        nonlocal called
        called = True
        return _MatchUseCase(outcome=_recorded(), calls=[])

    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        unexpected_builder,
    )

    response = _post(
        body='{"session_date":"2026-10-28","confirmed":true}',
        authenticated=False,
    )

    assert response.status_code == 403
    assert called is False


@pytest.mark.parametrize("replayed", [False, True])
def test_match_response_projects_exact_durable_no_match_without_internal_keys(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    """Report a durable NO_MATCH distinctly and keep its exact zero quantity."""

    use_case = _MatchUseCase(outcome=_recorded(replayed=replayed), calls=[])
    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        lambda: use_case,
    )

    response = _post(
        body='{"session_date":"2026-10-28","confirmed":true}',
    )

    assert response.status_code == 200
    assert response.accepted_media_type == "application/json"
    assert response.data == {
        "success": True,
        "outcome": "success",
        "account_id": 7,
        "order_id": 41,
        "session_date": "2026-10-28",
        "decision_recorded": True,
        "decision_outcome": "no_match",
        "matched_quantity": "0.000000",
        "matched_price": None,
        "reason_code": "DAILY_CLOSE_NOT_CROSSED",
        "replayed": replayed,
    }
    assert use_case.calls == [(7, _ACTOR_ID, 41, _SESSION_DATE, True)]
    assert not {
        "order_idempotency_key",
        "operation_key",
        "qmt_binding_id",
        "source_namespace",
        "event_payload_hash",
    }.intersection(response.data)


@pytest.mark.parametrize(
    ("body", "content_type", "query"),
    [
        ("{not-json", "application/json", ""),
        ('{"session_date":"2026-10-28","confirmed":false}', "application/json", ""),
        ('{"session_date":"2026-10-28","confirmed":1}', "application/json", ""),
        ('{"session_date":"2026-10-28","confirmed":"true"}', "application/json", ""),
        ('{"session_date":"2026-10-28"}', "application/json", ""),
        (
            '{"session_date":"2026-10-28","confirmed":true,"qmt_binding_id":"10000000-0000-4000-8000-000000000041"}',
            "application/json",
            "",
        ),
        (
            '{"session_date":"2026-10-28","confirmed":true,"user_id":999}',
            "application/json",
            "",
        ),
        ('{"session_date":"20261028","confirmed":true}', "application/json", ""),
        ("[]", "application/json", ""),
        ("confirmed=true", "application/x-www-form-urlencoded", ""),
        ('{"session_date":"2026-10-28","confirmed":true}', "application/json", "?user_id=999"),
    ],
)
def test_match_rejects_malformed_or_caller_controlled_input_before_building_use_case(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    content_type: str,
    query: str,
) -> None:
    """Reject malformed, extra, coercible and source-claiming request fields."""

    called = False

    def unexpected_builder() -> _MatchUseCase:
        """Detect any use-case construction before the request is accepted."""

        nonlocal called
        called = True
        return _MatchUseCase(outcome=_recorded(), calls=[])

    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        unexpected_builder,
    )

    response = _post(body=body, content_type=content_type, query=query)

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
            SimulatedTradeAccountScopeUnavailable("private-order-key"),
            404,
            "OWNER_ORDER_NOT_FOUND",
            False,
        ),
        (
            SimulatedTradeExecutionInputError("private-order-key"),
            400,
            "SIMULATED_TRADE_INPUT_INVALID",
            False,
        ),
        (
            SimulatedTradeExecutionBlocked("private-order-key"),
            409,
            "SIMULATED_TRADE_EXECUTION_BLOCKED",
            False,
        ),
        (
            SimulatedTradeExecutionResultUnknown("private-order-key"),
            503,
            "SIMULATED_TRADE_EXECUTION_RESULT_UNKNOWN",
            True,
        ),
    ],
)
def test_match_errors_have_stable_status_without_internal_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_code: str,
    indeterminate: bool,
) -> None:
    """Map scope, validation, blocked and uncertain outcomes without echoing internals."""

    use_case = _MatchUseCase(outcome=error, calls=[])
    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        lambda: use_case,
    )

    response = _post(body='{"session_date":"2026-10-28","confirmed":true}')

    assert response.status_code == expected_status
    assert response.data["success"] is False
    assert response.data["code"] == expected_code
    assert "private-order-key" not in str(response.data)
    assert response.data.get("effects_indeterminate", False) is indeterminate
    assert use_case.calls == [(7, _ACTOR_ID, 41, _SESSION_DATE, True)]
