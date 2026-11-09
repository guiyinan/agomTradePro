"""HTTP contracts for the session-only simulated rebalance-plan journey."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
)
from apps.simulated_trading.application.rebalance_journey_service import (
    RebalanceJourneyApplication,
    _targets,
)
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.interface.rebalance_plan_journey_views import (
    RebalancePlanExactAPIView,
    RebalancePlanJourneyResponseSerializer,
    RebalancePlanListCreateAPIView,
    RebalancePlanOrderPreviewAPIView,
    RebalancePlanReconciliationAPIView,
    RebalancePlanReviewAPIView,
    RebalancePlanSuccessorAPIView,
)

_REVISION_HASH = "a" * 64
_PLAN = {
    "identity": {
        "plan_id": "plan-17",
        "family_id": "family-8",
        "root_plan_id": "root-4",
        "version": 1,
        "parent_plan_id": None,
        "parent_version": None,
        "parent_revision_hash": None,
        "account_id": 9,
        "owner_user_id": 37,
        "transition_plan_hash": "b" * 64,
        "revision_hash": _REVISION_HASH,
        "recorded_at": "2026-11-05T08:00:00+08:00",
        "valid_until": "2026-11-05T12:00:00+08:00",
    },
    "transition_plan": {"schema": "canonical-v1"},
    "basis": {
        "account": {"account_id": 9, "owner_user_id": 37, "requested_by_user_id": 37},
        "money_unit": "CNY",
        "portfolio_snapshot": {},
        "decision": {},
        "target": {},
        "planning_policy": {},
        "risk": {
            "report_content_hash": "c" * 64,
            "binding_hash": "d" * 64,
            "outcome": "allowed",
            "must_not_use_for_decision": False,
        },
        "fee_policy": {},
        "quantity_rule": {},
        "settlement_rule": {},
        "execution_calendar": {},
        "source_bindings": [],
        "current_positions": [],
        "target_positions": [],
        "business_date": "2026-11-05",
        "execution_session": "2026-11-06",
        "prepared_at": "2026-11-05T08:00:00+08:00",
        "valid_until": "2026-11-05T12:00:00+08:00",
    },
    "orders": [],
    "status": "pending_review",
    "automatic_submission": False,
}


def _success(
    *, action: str = "read", attempt_key: str = "plan-order-preview-1"
) -> dict[str, object]:
    if action == "list":
        return {
            "success": True,
            "account_id": 9,
            "plans": [_PLAN],
            "review": None,
            "progress": None,
            "capabilities": {},
        }
    owner_order_key = f"owner-order-{attempt_key}"
    return {
        "success": True,
        "account_id": 9,
        "plan": _PLAN,
        "review": None,
        "progress": None,
        "capabilities": {},
        **(
            {
                "preview": {
                    "binding": {"account_id": 9, "action_attempt_key": attempt_key},
                    "revision_recorded_at": "2026-11-05T08:00:00+08:00",
                    "preview": {
                        "account_id": 9,
                        "success": True,
                        "read_only": True,
                        "execution_submitted": False,
                        "order": {"idempotency_key": owner_order_key},
                    },
                },
                "continuation": {
                    "action_key": "simulated-trading.order-confirm",
                    "input": {
                        "account_id": "9",
                        "order_key": owner_order_key,
                        "preview_token": "private-preview-token",
                    },
                    "expires_at": "2026-11-05T08:30:00+08:00",
                },
            }
            if action == "preview_order"
            else {}
        ),
    }


def _principal() -> SimpleNamespace:
    return SimpleNamespace(pk=37, is_authenticated=True, is_active=True)


def _authenticate_json_post(request: HttpRequest) -> None:
    """Exercise SessionAuthentication CSRF with a masked token and matching cookie."""

    token = get_token(request)
    secret = request.META.get("CSRF_COOKIE")
    if not isinstance(secret, str):
        raise AssertionError("Django did not issue a CSRF cookie secret")
    request.COOKIES[settings.CSRF_COOKIE_NAME] = secret
    request.META["HTTP_X_CSRFTOKEN"] = token
    request.META["HTTP_ACCEPT"] = "application/json"
    request.META["HTTP_ORIGIN"] = "https://testserver"
    request.user = _principal()


def test_response_serializer_requires_one_exact_plan_shape_and_matching_account() -> None:
    assert RebalancePlanJourneyResponseSerializer(data=_success()).is_valid()
    invalid = _success()
    invalid["plan"] = {**_PLAN, "identity": {**_PLAN["identity"], "account_id": 10}}
    serializer = RebalancePlanJourneyResponseSerializer(data=invalid)
    assert not serializer.is_valid()

    with_list_and_plan = _success()
    with_list_and_plan["plans"] = [_PLAN]
    assert not RebalancePlanJourneyResponseSerializer(data=with_list_and_plan).is_valid()

    automatic = _success()
    automatic["plan"] = {**_PLAN, "automatic_submission": True}
    assert not RebalancePlanJourneyResponseSerializer(data=automatic).is_valid()

    mismatched_handoff = _success(action="preview_order")
    mismatched_handoff["continuation"] = {
        "action_key": "simulated-trading.order-confirm",
        "input": {
            "account_id": "9",
            "order_key": "another-order",
            "preview_token": "private-preview-token",
        },
    }
    assert not RebalancePlanJourneyResponseSerializer(data=mismatched_handoff).is_valid()


def test_create_maps_authenticated_actor_and_idempotency_header_without_client_facts() -> None:
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        "/api/simulated-trading/accounts/9/rebalance-plans/",
        {"target_weights": "600000.SH,50", "reference_price_basis": "published_close"},
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY="create-plan-1",
        HTTP_ACCEPT="application/json",
    )
    _authenticate_json_post(request)
    view = RebalancePlanListCreateAPIView.as_view()

    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=_success(action="read"),
    ) as run:
        response = view(request, account_id=9)

    assert response.status_code == 200
    response.render()
    assert response["Content-Type"] == "application/json"
    command = run.call_args.args[0]
    assert command.action == "create"
    assert command.user_id == 37
    assert command.account_id == 9
    assert command.request_key == "create-plan-1"
    assert command.target_weights == "600000.SH,50"
    assert command.reference_price_basis == "published_close"
    assert not hasattr(command, "cash")
    assert not hasattr(command, "positions")
    assert not hasattr(command, "price")
    assert not hasattr(command, "fees")


def test_create_rejects_client_financial_facts_and_missing_idempotency_key() -> None:
    view = RebalancePlanListCreateAPIView.as_view()
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey"
    ) as run:
        extra_request = APIRequestFactory().post(
            "/api/simulated-trading/accounts/9/rebalance-plans/",
            {
                "target_weights": "600000.SH,50",
                "reference_price_basis": "market",
                "cash": "999999.00",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="create-plan-1",
        )
        force_authenticate(extra_request, user=_principal())
        extra_response = view(extra_request, account_id=9)

        missing_key_request = APIRequestFactory().post(
            "/api/simulated-trading/accounts/9/rebalance-plans/",
            {"target_weights": "600000.SH,50", "reference_price_basis": "market"},
            format="json",
        )
        force_authenticate(missing_key_request, user=_principal())
        missing_key_response = view(missing_key_request, account_id=9)

    assert extra_response.status_code == 400
    assert missing_key_response.status_code == 400
    run.assert_not_called()


def test_list_serializes_the_application_response() -> None:
    revision = Mock()
    revision.to_payload.return_value = _PLAN
    repository = Mock()
    repository.list_for_account.return_value = (revision,)
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 16, tzinfo=UTC)
    application = RebalanceJourneyApplication(
        repository=repository,
        authorizer=Mock(),
        clock=clock,
        preparation_factory=Mock(),
        progress_reader=Mock(),
        order_previewer=Mock(),
    )
    request = APIRequestFactory().get("/api/simulated-trading/accounts/9/rebalance-plans/")
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        side_effect=application.execute,
    ):
        response = RebalancePlanListCreateAPIView.as_view()(request, account_id=9)

    assert response.status_code == 200
    response.render()
    assert response["Content-Type"] == "application/json"
    assert response.data["plans"][0]["identity"]["revision_hash"] == _REVISION_HASH
    assert response.data["review"] is None
    assert response.data["progress"] is None
    assert response.data["capabilities"] == {"read_only": True, "can_execute_plan": False}


def test_retained_successor_targets_round_trip_through_the_entry_contract() -> None:
    revision = Mock()
    revision.basis.target_positions = [
        SimpleNamespace(asset_code="600036.SH", target_weight=Decimal("0.00000000")),
        SimpleNamespace(asset_code="601398.SH", target_weight=Decimal("0.00000001")),
    ]

    targets = parse_temporary_security_targets(_targets(revision))

    assert [(item.asset_code, item.weight) for item in targets.items] == [
        ("600036.SH", Decimal("0")),
        ("601398.SH", Decimal("0.00000001")),
    ]


def test_exact_read_requires_version_and_hash_and_does_not_require_write_key() -> None:
    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/",
        {"plan_version": "1", "revision_hash": _REVISION_HASH},
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=_success(),
    ) as run:
        response = RebalancePlanExactAPIView.as_view()(request, account_id=9, plan_id="plan-17")

    assert response.status_code == 200
    command = run.call_args.args[0]
    assert command.action == "read"
    assert command.plan_id == "plan-17"
    assert command.plan_version == 1
    assert command.revision_hash == _REVISION_HASH
    assert command.request_key is None


@pytest.mark.parametrize(
    ("view_class", "body", "key", "expected_action"),
    [
        (
            RebalancePlanReviewAPIView,
            {"plan_version": 1, "revision_hash": _REVISION_HASH, "confirmed": True},
            "review-1",
            "review",
        ),
        (
            RebalancePlanSuccessorAPIView,
            {"plan_version": 1, "revision_hash": _REVISION_HASH, "confirmed": True},
            "successor-1",
            "successor",
        ),
    ],
)
def test_write_journeys_require_literal_confirmation_and_exact_revision(
    view_class: type,
    body: dict[str, object],
    key: str,
    expected_action: str,
) -> None:
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=_success(),
    ) as run:
        response = view_class.as_view()(request, account_id=9, plan_id="plan-17")

    assert response.status_code == 200
    command = run.call_args.args[0]
    assert command.action == expected_action
    assert command.request_key == key
    assert command.plan_version == 1
    assert command.revision_hash == _REVISION_HASH
    assert command.user_id == 37


def test_review_requires_explicit_confirmation_before_any_application_call() -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/review/",
        {"plan_version": 1, "revision_hash": _REVISION_HASH, "confirmed": False},
        format="json",
        HTTP_IDEMPOTENCY_KEY="review-1",
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey"
    ) as run:
        response = RebalancePlanReviewAPIView.as_view()(request, account_id=9, plan_id="plan-17")

    assert response.status_code == 400
    run.assert_not_called()


def test_order_preview_maps_only_exact_pins_and_user_numeric_intent() -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.400000",
            "reason": "按计划核对后分笔模拟",
        },
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
        HTTP_ACCEPT="application/json",
    )
    _authenticate_json_post(request)
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=_success(action="preview_order"),
    ) as run:
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )

    assert response.status_code == 200
    response.render()
    assert response["Content-Type"] == "application/json"
    command = run.call_args.args[0]
    assert command.action == "preview_order"
    assert command.user_id == 37
    assert command.account_id == 9
    assert command.plan_id == "plan-17"
    assert command.plan_version == 1
    assert command.revision_hash == _REVISION_HASH
    assert command.order_ordinal == 0
    assert command.order_content_hash == "b" * 64
    assert command.plan_order_binding_id == "c" * 64
    assert command.quantity == Decimal("100")
    assert str(command.limit_price) == "13.400000"
    assert command.reason == "按计划核对后分笔模拟"
    assert command.request_key == "plan-order-preview-1"
    assert response.data["preview"]["binding"]["action_attempt_key"] == command.request_key
    assert response.data["preview"]["preview"]["order"]["idempotency_key"] != command.request_key
    assert (
        response.data["continuation"]["input"]["order_key"]
        == response.data["preview"]["preview"]["order"]["idempotency_key"]
    )
    assert not hasattr(command, "asset_code")
    assert not hasattr(command, "security_id")
    assert not hasattr(command, "side")
    assert not hasattr(command, "fee_budget")
    assert not hasattr(command, "cash")
    assert not hasattr(command, "positions")


def test_order_preview_preserves_shared_owner_confirm_continuation() -> None:
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.400000",
        },
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
        HTTP_ACCEPT="application/json",
    )
    _authenticate_json_post(request)
    owner_result = _success(action="preview_order")
    owner_result["continuation"]["action_key"] = "simulated-trading.order-confirm"

    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=owner_result,
    ):
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )

    assert response.status_code == 200
    assert response.data["continuation"]["action_key"] == "simulated-trading.order-confirm"
    assert owner_result["continuation"]["action_key"] == "simulated-trading.order-confirm"


def test_order_preview_rejects_cross_mismatched_owner_order_key() -> None:
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.400000",
        },
        format="json",
        secure=True,
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
        HTTP_ACCEPT="application/json",
    )
    _authenticate_json_post(request)
    invalid = _success(action="preview_order")
    invalid["continuation"]["input"]["order_key"] = "unrelated-owner-key"
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=invalid,
    ):
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )

    assert response.status_code == 503
    response.render()
    assert response["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    "body",
    [
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": 100.0,
            "limit_price": "13.40",
        },
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "0",
            "limit_price": "13.40",
        },
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "0",
        },
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.40",
            "asset_code": "600000.SH",
        },
    ],
)
def test_order_preview_rejects_float_zero_or_client_security_facts(body: dict[str, object]) -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey"
    ) as run:
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )
    assert response.status_code == 400
    run.assert_not_called()


def test_order_preview_requires_idempotency_key_before_application_call() -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.40",
        },
        format="json",
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey"
    ) as run:
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )
    assert response.status_code == 400
    run.assert_not_called()


def test_order_preview_rejects_application_binding_for_another_attempt() -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.40",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        return_value=_success(action="preview_order", attempt_key="another-attempt"),
    ) as run:
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )

    assert response.status_code == 503
    run.assert_called_once()


def test_foreign_account_is_redacted_and_only_the_public_service_decides_access() -> None:
    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/10/rebalance-plans/plan-17/",
        {"plan_version": "1", "revision_hash": _REVISION_HASH},
    )
    force_authenticate(request, user=_principal())
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey",
        side_effect=RebalanceJourneyAccessDenied(),
    ):
        response = RebalancePlanExactAPIView.as_view()(request, account_id=10, plan_id="plan-17")

    assert response.status_code == 403
    assert response.data == {
        "success": False,
        "error": "该模拟账户或调仓计划不可用，或当前用户无权查看。",
        "code": "REBALANCE_JOURNEY_ACCESS_DENIED",
    }
    assert "plan-17" not in str(response.data)


def test_journey_views_accept_session_authentication_only_for_sdk_mcp_boundary() -> None:
    assert RebalancePlanListCreateAPIView.authentication_classes == (SessionAuthentication,)
    assert RebalancePlanExactAPIView.authentication_classes == (SessionAuthentication,)
    assert RebalancePlanReviewAPIView.authentication_classes == (SessionAuthentication,)
    assert RebalancePlanSuccessorAPIView.authentication_classes == (SessionAuthentication,)
    assert RebalancePlanReconciliationAPIView.authentication_classes == (SessionAuthentication,)
    assert RebalancePlanOrderPreviewAPIView.authentication_classes == (SessionAuthentication,)


def test_order_preview_does_not_accept_bearer_token_authentication() -> None:
    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/9/rebalance-plans/plan-17/orders/0/preview/",
        {
            "plan_version": 1,
            "revision_hash": _REVISION_HASH,
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.40",
        },
        format="json",
        HTTP_AUTHORIZATION="Bearer unsupported-token",
        HTTP_IDEMPOTENCY_KEY="plan-order-preview-1",
    )
    with patch(
        "apps.simulated_trading.interface.rebalance_plan_journey_views.run_rebalance_journey"
    ) as run:
        response = RebalancePlanOrderPreviewAPIView.as_view()(
            request, account_id=9, plan_id="plan-17", order_ordinal=0
        )

    assert response.status_code == 403
    run.assert_not_called()
