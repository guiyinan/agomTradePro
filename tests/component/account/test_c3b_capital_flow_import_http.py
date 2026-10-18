"""Real HTTP checks for append-only capital-flow imports."""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model

from apps.account.infrastructure.portfolio_models import CapitalFlowModel, PortfolioModel
from tests.component.account.test_transaction_fee_mcp_http_journey import _HttpLog as _HttpLog
from tests.component.account.test_transaction_fee_mcp_http_journey import _McpRuntime as _McpRuntime
from tests.component.account.test_transaction_fee_mcp_http_journey import (
    exact_origin_http_log as exact_origin_http_log,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import (
    live_owner_account as live_owner_account,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import mcp_runtime as mcp_runtime

pytestmark = pytest.mark.django_db(transaction=True)
CAPITAL_FLOW_PATH = "/api/account/capital-flows/"


def _make_capital_flow(
    portfolio: PortfolioModel,
    *,
    flow_type: str = "deposit",
    amount: Decimal = Decimal("10.00"),
) -> CapitalFlowModel:
    """Create one fully specified flow row for real API ownership checks."""
    return CapitalFlowModel.objects.create(
        user=portfolio.user,
        portfolio=portfolio,
        flow_type=flow_type,
        amount=amount,
        flow_date=date(2026, 7, 25),
        notes="C3b append-only fixture",
    )


def _dispatcher_for_mode(
    runtime: _McpRuntime,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    *,
    legacy_tools: bool,
) -> tuple[Any, Any | None]:
    """Return the existing dispatcher in fallback or registered-tool mode."""
    if not legacy_tools:
        return runtime.dispatcher, None

    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", "true")
    server_module = importlib.reload(importlib.import_module("agomtradepro_mcp.server"))

    def restore_fallback_registration() -> None:
        """Restore module registration after this test so later tests stay isolated."""
        monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", "false")
        importlib.reload(server_module)

    request.addfinalizer(restore_fallback_registration)
    return server_module.CORE_DISPATCHER, server_module


def _assert_no_capital_flow_io(log: _HttpLog, start: int) -> None:
    """No importer read or write request may occur after the recorded baseline."""
    new_requests = log.exchanges[start:]
    assert not [
        row
        for row in new_requests
        if row["path"] == CAPITAL_FLOW_PATH or row["path"].startswith(CAPITAL_FLOW_PATH)
    ]


@pytest.mark.parametrize("legacy_tools", [False, True], ids=["owner-fallback", "registered"])
def test_replace_is_rejected_before_client_or_capital_flow_http(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    request: pytest.FixtureRequest,
    legacy_tools: bool,
) -> None:
    """Neither importer mode may issue a read/delete/create for replacement."""
    portfolio, _ = live_owner_account
    first = _make_capital_flow(portfolio)
    second = _make_capital_flow(portfolio, flow_type="dividend", amount=Decimal("2.00"))
    before = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list("pk", "flow_type", "amount", "flow_date", "notes")
    )
    dispatcher, server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=legacy_tools,
    )
    sdk = importlib.import_module("agomtradepro")
    factory = Mock(side_effect=AssertionError("client factory must not be called"))
    monkeypatch.setattr(sdk, "AgomTradeProClient", factory)
    monkeypatch.setattr(mcp_runtime.account_tools, "AgomTradeProClient", factory)
    start = len(exact_origin_http_log.exchanges)

    result = dispatcher.call(
        capability_key="account.import.capital_flows",
        arguments={
            "portfolio_id": int(portfolio.pk),
            "capital_flows": [
                {
                    "flow_type": "deposit",
                    "amount": "99.00",
                    "flow_date": "2026-07-25",
                }
            ],
            "mode": "replace",
            "idempotency_key": f"c3b-replace-{legacy_tools}",
        },
    )

    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["capability_key"] == "account.import.capital_flows"
    error = result["error"]
    assert isinstance(error, dict)
    assert error["code"] == "capital_flow_import_append_only"
    assert error["upstream_status_code"] is None
    assert "confirmation_token" not in result
    factory.assert_not_called()
    _assert_no_capital_flow_io(exact_origin_http_log, start)
    after = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list("pk", "flow_type", "amount", "flow_date", "notes")
    )
    assert after == before
    assert first.pk in {row[0] for row in after}
    assert second.pk in {row[0] for row in after}

    if legacy_tools:
        assert server_module is not None
        registered = server_module.server._tool_manager._tools["import_capital_flows_csv"].fn
        api_error = importlib.import_module("agomtradepro.exceptions").AgomTradeProAPIError
        with pytest.raises(api_error):
            registered(
                int(portfolio.pk),
                "flow_type,amount,flow_date\ndeposit,99.00,2026-07-25\n",
                mode="replace",
            )
        factory.assert_not_called()
        _assert_no_capital_flow_io(exact_origin_http_log, start)


def test_append_preview_and_all_invalid_fallback_do_not_create_sdk_client(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Preview and a locally rejected batch require neither a client nor a GET."""
    portfolio, _ = live_owner_account
    sdk = importlib.import_module("agomtradepro")
    factory = Mock(side_effect=AssertionError("client factory must not be called"))
    monkeypatch.setattr(sdk, "AgomTradeProClient", factory)
    monkeypatch.setattr(mcp_runtime.account_tools, "AgomTradeProClient", factory)
    start = len(exact_origin_http_log.exchanges)

    preview = mcp_runtime.dispatcher.call(
        capability_key="account.import.capital_flows",
        arguments={
            "portfolio_id": int(portfolio.pk),
            "capital_flows": [
                {
                    "flow_type": "deposit",
                    "amount": "10.00",
                    "flow_date": "2026-07-25",
                }
            ],
            "mode": "append",
            "idempotency_key": "c3b-append-preview",
        },
    )
    assert preview["status"] == "confirmation_required"
    _assert_no_capital_flow_io(exact_origin_http_log, start)

    owner_module = importlib.import_module(
        "agomtradepro_mcp.registry.runtime_handlers.owners.account"
    )
    rejected = owner_module._fallback_import_capital_flows_json(
        int(portfolio.pk),
        [{"flow_type": "", "amount": "10.00", "flow_date": "2026-07-25"}],
        mode="append",
        dry_run=False,
    )
    assert rejected["success"] is False
    assert rejected["summary"]["valid_rows"] == 0
    factory.assert_not_called()
    _assert_no_capital_flow_io(exact_origin_http_log, start)


@pytest.mark.parametrize(
    "legacy_tools",
    [False, True],
    ids=["owner-fallback", "registered"],
)
def test_append_preview_then_confirm_creates_one_exact_owned_flow(
    monkeypatch: pytest.MonkeyPatch,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    request: pytest.FixtureRequest,
    legacy_tools: bool,
) -> None:
    """Confirmation creates one exact flow while preserving all prior rows."""
    portfolio, _ = live_owner_account
    _make_capital_flow(portfolio, flow_type="deposit", amount=Decimal("1.25"))
    _make_capital_flow(portfolio, flow_type="dividend", amount=Decimal("7.50"))
    historical_rows = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list(
            "pk",
            "user_id",
            "portfolio_id",
            "flow_type",
            "amount",
            "flow_date",
            "notes",
        )
    )
    dispatcher, _server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=legacy_tools,
    )
    request_start = len(exact_origin_http_log.exchanges)
    flow_date = "2026-09-19"
    amount = Decimal("1234.56")
    notes = f"C3b append confirmation {legacy_tools}"

    staged = dispatcher.call(
        capability_key="account.import.capital_flows",
        arguments={
            "portfolio_id": int(portfolio.pk),
            "capital_flows": [
                {
                    "flow_type": "deposit",
                    "amount": str(amount),
                    "flow_date": flow_date,
                    "notes": notes,
                }
            ],
            "mode": "append",
            "idempotency_key": f"c3b-capital-flow-success-{legacy_tools}",
        },
    )

    assert staged["status"] == "confirmation_required"
    assert staged["idempotency_key"] == f"c3b-capital-flow-success-{legacy_tools}"
    assert staged["preview_result"]["success"] is True
    assert staged["preview_result"]["dry_run"] is True
    assert staged["preview_result"]["summary"]["valid_rows"] == 1
    assert not CapitalFlowModel.objects.filter(portfolio=portfolio, notes=notes).exists()
    assert (
        list(
            CapitalFlowModel.objects.filter(portfolio=portfolio)
            .order_by("pk")
            .values_list(
                "pk", "user_id", "portfolio_id", "flow_type", "amount", "flow_date", "notes"
            )
        )
        == historical_rows
    )
    staged_flows = [
        row
        for row in exact_origin_http_log.exchanges[request_start:]
        if row["path"] == CAPITAL_FLOW_PATH or row["path"].startswith(CAPITAL_FLOW_PATH)
    ]
    assert staged_flows == []

    committed = dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )

    assert committed["status"] == "completed"
    assert committed["result"]["success"] is True
    assert committed["result"]["summary"]["valid_rows"] == 1
    assert committed["result"]["summary"]["delete_count"] == 0
    flow_requests = [
        row
        for row in exact_origin_http_log.exchanges[request_start:]
        if row["path"] == CAPITAL_FLOW_PATH or row["path"].startswith(CAPITAL_FLOW_PATH)
    ]
    assert [(row["method"], row["path"], row["status"]) for row in flow_requests] == [
        ("POST", CAPITAL_FLOW_PATH, 201)
    ]
    post = flow_requests[0]
    assert post["content_type"].startswith("application/json")
    request_json = post["request_json"]
    assert isinstance(request_json, dict)
    assert request_json["portfolio"] == int(portfolio.pk)
    assert request_json["flow_type"] == "deposit"
    assert Decimal(str(request_json["amount"])) == amount
    assert request_json["flow_date"] == flow_date
    assert request_json["notes"] == notes

    created = CapitalFlowModel.objects.get(portfolio=portfolio, notes=notes)
    assert created.user_id == portfolio.user_id
    assert created.portfolio_id == portfolio.pk
    assert created.flow_type == "deposit"
    assert created.amount == amount
    assert created.flow_date == date.fromisoformat(flow_date)
    assert created.pk not in {row[0] for row in historical_rows}
    after_rows = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list("pk", "user_id", "portfolio_id", "flow_type", "amount", "flow_date", "notes")
    )
    assert [row for row in after_rows if row[0] != created.pk] == historical_rows
    assert len(after_rows) == len(historical_rows) + 1


def test_owned_single_flow_delete_remains_supported_and_foreign_flow_is_hidden(
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Importer replacement is blocked without removing the owned-row API delete."""
    portfolio, _ = live_owner_account
    assert mcp_runtime.portfolio.pk == portfolio.pk
    owned = _make_capital_flow(portfolio)
    foreign_user = get_user_model().objects.create_user(
        username="c3b_foreign_capital_flow_owner",
        password="testpass123",
        email="c3b-foreign-capital-flow@example.com",
    )
    foreign_portfolio = PortfolioModel.objects.create(
        user=foreign_user,
        name="C3b foreign portfolio",
    )
    foreign = _make_capital_flow(foreign_portfolio, amount=Decimal("3.00"))
    sdk = importlib.import_module("agomtradepro")
    client = sdk.AgomTradeProClient()
    start = len(exact_origin_http_log.exchanges)

    client.delete(f"api/account/capital-flows/{owned.pk}/")
    api_error = importlib.import_module("agomtradepro.exceptions").AgomTradeProAPIError
    with pytest.raises(api_error) as caught:
        client.delete(f"api/account/capital-flows/{foreign.pk}/")

    assert caught.value.status_code == 404
    assert not CapitalFlowModel.objects.filter(pk=owned.pk).exists()
    assert CapitalFlowModel.objects.filter(pk=foreign.pk).exists()
    deletes = [
        row
        for row in exact_origin_http_log.exchanges[start:]
        if row["method"] == "DELETE" and row["path"].startswith(CAPITAL_FLOW_PATH)
    ]
    assert [(row["path"], row["status"]) for row in deletes] == [
        (f"{CAPITAL_FLOW_PATH}{owned.pk}/", 204),
        (f"{CAPITAL_FLOW_PATH}{foreign.pk}/", 404),
    ]
