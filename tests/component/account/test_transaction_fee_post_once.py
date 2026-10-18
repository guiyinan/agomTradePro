"""Exercise transaction import retry behavior against the real local API."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection

from apps.account.infrastructure.portfolio_models import PortfolioModel, TransactionModel
from tests.component.account.test_transaction_fee_mcp_http_journey import (
    _assert_external_requests_are_blocked,
    _HttpLog,
    _McpRuntime,
    _transaction_posts,
    _transaction_row,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import (
    exact_origin_http_log as exact_origin_http_log,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import (
    live_owner_account as live_owner_account,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import mcp_runtime as mcp_runtime

pytestmark = pytest.mark.django_db(transaction=True)


def test_real_transaction_create_then_lost_503_is_not_replayed(
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    live_owner_account: tuple[PortfolioModel, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed create whose response is lost must not be sent a second time."""
    monkeypatch.setenv("AGOMTRADEPRO_MAX_RETRIES", "2")
    from apps.account.interface.transaction_api_views import TransactionViewSet

    successful_view_statuses: list[int] = []
    returned_view_statuses: list[int] = []
    original_create = TransactionViewSet.create

    def persist_then_lose_first_response(
        view: TransactionViewSet,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        response = original_create(view, request, *args, **kwargs)
        successful_view_statuses.append(response.status_code)
        if len(successful_view_statuses) == 1 and response.status_code == 201:
            assert (
                not connection.in_atomic_block
            ), "the create must leave its atomic block before its response is changed to 503"
            response.status_code = 503
        returned_view_statuses.append(response.status_code)
        return response

    monkeypatch.setattr(TransactionViewSet, "create", persist_then_lose_first_response)
    row = _transaction_row("RETRYONCE.SZ", commission="0.25", slippage="0")

    staged = mcp_runtime.dispatcher.call(
        capability_key="account.import.transactions",
        arguments={
            "portfolio_id": mcp_runtime.portfolio.pk,
            "transactions": [row],
            "mode": "append",
            "idempotency_key": "post-once-lost-response",
        },
    )
    assert staged["status"] == "confirmation_required"
    assert _transaction_posts(exact_origin_http_log) == []
    assert (
        TransactionModel.objects.filter(
            portfolio=mcp_runtime.portfolio,
            asset_code="RETRYONCE.SZ",
        ).count()
        == 0
    )

    committed = mcp_runtime.dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )

    # Capture actual server executions and persisted rows before the early
    # status assertion, so a legacy retry failure exposes its full evidence.
    posts = [
        exchange
        for exchange in _transaction_posts(exact_origin_http_log)
        if exchange["request_json"] is not None
        and exchange["request_json"].get("asset_code") == "RETRYONCE.SZ"
    ]
    persisted_ids: list[int] = list(
        TransactionModel.objects.filter(
            portfolio=mcp_runtime.portfolio,
            asset_code="RETRYONCE.SZ",
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    assert successful_view_statuses == [201], (
        "unexpected server create executions: "
        f"view_statuses={successful_view_statuses}, "
        f"returned_statuses={returned_view_statuses}, "
        f"http_posts={len(posts)}, persisted_ids={persisted_ids}"
    )
    assert returned_view_statuses == [503]
    assert len(posts) == 1
    assert posts[0]["status"] == 503
    assert posts[0]["content_type"].startswith("application/json")
    assert committed["status"] == "completed"
    assert committed["result"]["success"] is False
    assert committed["result"]["summary"]["error_count"] == 1
    assert "503" in committed["result"]["errors"][0]["error"]
    assert len(persisted_ids) == 1
    _assert_external_requests_are_blocked(exact_origin_http_log)
