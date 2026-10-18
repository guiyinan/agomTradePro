"""Exercise MCP transaction-fee transport against a real local account API."""

from __future__ import annotations

import csv
import importlib
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit

import pytest
import requests
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from apps.account.infrastructure.portfolio_models import (
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from tests.support.runtime_config import configure_account_runtime

pytestmark = pytest.mark.django_db(transaction=True)
FEE_FIELDS = ("commission", "slippage", "stamp_duty", "transfer_fee")


class _Exchange(TypedDict):
    """Sanitized observation of one real API request and response."""

    method: str
    path: str
    origin: str
    status: int
    content_type: str
    request_json: dict[str, Any] | None
    response_json: dict[str, Any] | list[Any] | None


@dataclass
class _HttpLog:
    """Capture real SDK requests and block off-origin requests before transport."""

    expected_origin: tuple[str, str, int]
    exchanges: list[_Exchange]
    blocked: list[tuple[str, str, int]]


@dataclass
class _McpRuntime:
    """Checkout SDK/MCP runtime bound to a real owner token and portfolio."""

    dispatcher: Any
    account_tools: Any
    rbac: Any
    portfolio: PortfolioModel


def _effective_port(parts: Any) -> int:
    if parts.port is not None:
        return int(parts.port)
    return 443 if parts.scheme.lower() == "https" else 80


@pytest.fixture
def exact_origin_http_log(monkeypatch: pytest.MonkeyPatch, live_server: Any) -> _HttpLog:
    """Permit real requests only to this live_server origin; retain real responses."""
    parts = urlsplit(str(live_server.url))
    host = str(parts.hostname or "").lower().rstrip(".")
    expected = (parts.scheme.lower(), host, _effective_port(parts))
    assert host and expected[0] == "http"
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", host)
    monkeypatch.setenv("no_proxy", host)

    log = _HttpLog(expected_origin=expected, exchanges=[], blocked=[])
    original_request = requests.Session.request

    def guarded_request(
        session: requests.Session,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Block non-local origins, otherwise send the actual HTTP request."""
        parsed = urlsplit(str(url))
        actual = (
            parsed.scheme.lower(),
            str(parsed.hostname or "").lower().rstrip("."),
            _effective_port(parsed),
        )
        if actual != expected:
            log.blocked.append((actual[0], actual[1], actual[2]))
            raise AssertionError("HTTP request escaped the exact live_server origin")

        response = original_request(session, method, url, **kwargs)
        body = kwargs.get("json")
        try:
            response_body = response.json()
        except ValueError:
            response_body = None
        log.exchanges.append(
            {
                "method": method.upper(),
                "path": parsed.path,
                "origin": f"{actual[0]}://{actual[1]}:{actual[2]}",
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "request_json": dict(body) if isinstance(body, dict) else None,
                "response_json": response_body if isinstance(response_body, (dict, list)) else None,
            }
        )
        return response

    monkeypatch.setattr(requests.Session, "request", guarded_request)
    return log


@pytest.fixture
def live_owner_account(db: object) -> tuple[PortfolioModel, str]:
    """Create an approved owner, real read-write token and owned portfolio."""
    configure_account_runtime()
    user = get_user_model().objects.create_user(
        username="fee_b_http_owner",
        password="testpass123",
        email="fee-b-http-owner@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Fee B HTTP Owner",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
            "rbac_role": "owner",
        },
    )
    _, raw_token = UserAccessTokenModel.create_token(
        user=user,
        name="fee-b-http-owner",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    return PortfolioModel.objects.create(user=user, name="Fee B HTTP portfolio"), raw_token


@pytest.fixture
def mcp_runtime(
    monkeypatch: pytest.MonkeyPatch,
    live_server: Any,
    live_owner_account: tuple[PortfolioModel, str],
    exact_origin_http_log: _HttpLog,
) -> _McpRuntime:
    """Load checkout SDK/MCP modules and require the role from the real API profile."""
    portfolio, raw_token = live_owner_account
    sdk_root = (Path(__file__).resolve().parents[3] / "sdk").resolve()
    monkeypatch.syspath_prepend(str(sdk_root))
    monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", str(live_server.url))
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", raw_token)
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", "false")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENFORCE_RBAC", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE_SOURCE", "backend")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ALLOWED_TOOLS", "")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_DENIED_TOOLS", "")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_ENABLED", "false")
    monkeypatch.delenv("AGOMTRADEPRO_MCP_ROLE", raising=False)
    monkeypatch.delenv("AGOMTRADEPRO_MCP_DEFAULT_ROLE", raising=False)
    importlib.invalidate_caches()

    sdk = importlib.import_module("agomtradepro")
    server = importlib.reload(importlib.import_module("agomtradepro_mcp.server"))
    rbac = importlib.import_module("agomtradepro_mcp.rbac")
    audit = importlib.import_module("agomtradepro_mcp.audit")
    account_tools = importlib.import_module("agomtradepro_mcp.tools.account_tools")
    for module in (sdk, server, account_tools):
        module_path = Path(str(module.__file__)).resolve()
        assert module_path.is_relative_to(sdk_root), module_path
    monkeypatch.setattr(rbac, "_BACKEND_ROLE_CACHE", None)
    monkeypatch.setattr(rbac, "_BACKEND_PROFILE_CACHE", None)
    monkeypatch.setattr(audit, "_audit_logger", None)
    assert rbac.get_current_role() == "owner"
    assert exact_origin_http_log.exchanges
    return _McpRuntime(server.CORE_DISPATCHER, account_tools, rbac, portfolio)


def _transaction_row(asset_code: str, **overrides: object) -> dict[str, object]:
    """Build one valid transaction import row with caller-owned fee inputs."""
    return {
        "action": "buy",
        "asset_code": asset_code,
        "shares": "10",
        "price": "9.50",
        "traded_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
        "notes": "Fee B HTTP contract",
        **overrides,
    }


def _transaction_posts(log: _HttpLog) -> list[_Exchange]:
    """Return actual create requests and their live API responses."""
    return [
        exchange
        for exchange in log.exchanges
        if exchange["method"] == "POST" and exchange["path"] == "/api/account/transactions/"
    ]


def _assert_external_requests_are_blocked(log: _HttpLog) -> None:
    """Prove the test's request fence rejects a different origin before network I/O."""
    with pytest.raises(AssertionError, match="escaped the exact live_server origin"):
        requests.get("https://outside.invalid/blocked", timeout=0.1)
    assert log.blocked == [("https", "outside.invalid", 443)]
    assert all(
        exchange["origin"]
        == f"{log.expected_origin[0]}://{log.expected_origin[1]}:{log.expected_origin[2]}"
        for exchange in log.exchanges
    )


def test_confirmed_import_preserves_unknown_zero_and_csv_fee_states(
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Real MCP confirmation writes only explicit amounts; CSV reflects server flags."""
    rows = [
        _transaction_row(
            "FEEUNKNOWN.SZ",
            slippage=None,
            stamp_duty="",
            transfer_fee="   ",
            commission_known=True,
            slippage_known=True,
            stamp_duty_known=True,
            transfer_fee_known=True,
            estimated_cost="9999.00",
        ),
        _transaction_row(
            "FEEKnown.SH",
            commission="1.25",
            slippage="0",
            stamp_duty="0.00",
            transfer_fee="0",
            commission_known=False,
            slippage_known=False,
            stamp_duty_known=False,
            transfer_fee_known=False,
            estimated_cost="9999.00",
        ),
    ]
    assert TransactionModel.objects.filter(portfolio=mcp_runtime.portfolio).count() == 0
    staged = mcp_runtime.dispatcher.call(
        capability_key="account.import.transactions",
        arguments={
            "portfolio_id": mcp_runtime.portfolio.pk,
            "transactions": rows,
            "mode": "append",
            "idempotency_key": "fee-b-http-append-positive",
        },
    )
    assert staged["status"] == "confirmation_required"
    assert staged["preview_result"]["dry_run"] is True
    assert staged["preview_result"]["summary"]["valid_rows"] == 2
    assert _transaction_posts(exact_origin_http_log) == []
    assert TransactionModel.objects.filter(portfolio=mcp_runtime.portfolio).count() == 0

    committed = mcp_runtime.dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    assert committed["status"] == "completed"
    assert committed["result"]["success"] is True
    posts = _transaction_posts(exact_origin_http_log)
    assert len(posts) == 2
    assert all(post["status"] == 201 for post in posts)
    assert all(post["content_type"].startswith("application/json") for post in posts)
    by_asset = {
        str(post["request_json"]["asset_code"]): post
        for post in posts
        if post["request_json"] is not None
    }

    unknown = by_asset["FEEUNKNOWN.SZ"]
    unknown_body = unknown["request_json"]
    assert unknown_body is not None
    assert not set(FEE_FIELDS).intersection(unknown_body)
    assert not {f"{field}_known" for field in FEE_FIELDS}.intersection(unknown_body)
    assert "estimated_cost" not in unknown_body
    unknown_response = unknown["response_json"]
    assert isinstance(unknown_response, dict)
    assert {
        field: (unknown_response[field], unknown_response[f"{field}_known"]) for field in FEE_FIELDS
    } == dict.fromkeys(FEE_FIELDS, (None, False))

    known = by_asset["FEEKnown.SH"]
    known_body = known["request_json"]
    assert known_body is not None
    assert {field: known_body[field] for field in FEE_FIELDS} == {
        "commission": "1.25",
        "slippage": "0",
        "stamp_duty": "0.00",
        "transfer_fee": "0",
    }
    assert not {f"{field}_known" for field in FEE_FIELDS}.intersection(known_body)
    assert "estimated_cost" not in known_body
    known_response = known["response_json"]
    assert isinstance(known_response, dict)
    assert {
        field: (known_response[field], known_response[f"{field}_known"]) for field in FEE_FIELDS
    } == {
        "commission": ("1.25", True),
        "slippage": ("0.00", True),
        "stamp_duty": ("0.00", True),
        "transfer_fee": ("0.00", True),
    }

    unknown_record = TransactionModel.objects.get(
        portfolio=mcp_runtime.portfolio,
        asset_code="FEEUNKNOWN.SZ",
    )
    known_record = TransactionModel.objects.get(
        portfolio=mcp_runtime.portfolio,
        asset_code="FEEKnown.SH",
    )
    for field in FEE_FIELDS:
        assert getattr(unknown_record, field) == Decimal("0.00")
        assert getattr(unknown_record, f"{field}_known") is False
    assert [getattr(known_record, field) for field in FEE_FIELDS] == [
        Decimal("1.25"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    ]
    assert all(getattr(known_record, f"{field}_known") is True for field in FEE_FIELDS)

    from mcp.server.fastmcp import FastMCP

    exporter = FastMCP("fee-b-http-export")
    mcp_runtime.account_tools.register_account_tools(exporter)
    tool = exporter._tool_manager._tools["export_transactions_csv"]
    export_fn = mcp_runtime.rbac.wrap_tool_with_rbac_and_audit(
        "export_transactions_csv",
        tool.fn,
    )
    exported = export_fn(portfolio_id=mcp_runtime.portfolio.pk, limit=20)
    records = list(csv.DictReader(io.StringIO(exported["csv"])))
    assert exported["count"] == 2
    assert list(records[0]) == [
        "id",
        "portfolio",
        "position",
        "action",
        "asset_code",
        "shares",
        "price",
        "notional",
        "commission",
        "traded_at",
        "notes",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
    ]
    by_asset_csv = {record["asset_code"]: record for record in records}
    assert {field: by_asset_csv["FEEUNKNOWN.SZ"][field] for field in FEE_FIELDS} == dict.fromkeys(
        FEE_FIELDS, ""
    )
    assert {
        field: by_asset_csv["FEEUNKNOWN.SZ"][f"{field}_known"] for field in FEE_FIELDS
    } == dict.fromkeys(FEE_FIELDS, "False")
    assert {field: by_asset_csv["FEEKnown.SH"][field] for field in FEE_FIELDS} == {
        "commission": "1.25",
        "slippage": "0.00",
        "stamp_duty": "0.00",
        "transfer_fee": "0.00",
    }
    assert all(by_asset_csv["FEEKnown.SH"][f"{field}_known"] == "True" for field in FEE_FIELDS)
    assert any(
        item["method"] == "GET"
        and item["path"] == "/api/account/profile/"
        and item["status"] == 200
        and item["content_type"].startswith("application/json")
        for item in exact_origin_http_log.exchanges
    )
    assert any(
        item["method"] == "GET"
        and item["path"] == "/api/account/transactions/"
        and item["status"] == 200
        and item["content_type"].startswith("application/json")
        for item in exact_origin_http_log.exchanges
    )
    _assert_external_requests_are_blocked(exact_origin_http_log)


def test_overprecision_string_is_rejected_by_real_api_without_writing(
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """The client preview is not server precision validation; the confirmed POST must retain text."""
    overprecision = "0.100000000000000001"
    row = _transaction_row("FEEPRECISION.SZ", commission=overprecision)
    before_count = TransactionModel.objects.filter(portfolio=mcp_runtime.portfolio).count()
    staged = mcp_runtime.dispatcher.call(
        capability_key="account.import.transactions",
        arguments={
            "portfolio_id": mcp_runtime.portfolio.pk,
            "transactions": [row],
            "mode": "append",
            "idempotency_key": "fee-b-http-overprecision",
        },
    )
    assert staged["status"] == "confirmation_required"
    assert staged["preview_result"]["summary"]["valid_rows"] == 1
    assert _transaction_posts(exact_origin_http_log) == []
    assert TransactionModel.objects.filter(portfolio=mcp_runtime.portfolio).count() == before_count

    committed = mcp_runtime.dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    assert committed["status"] == "completed"
    assert committed["result"]["success"] is False
    posts = [
        item
        for item in _transaction_posts(exact_origin_http_log)
        if item["request_json"] is not None
        and item["request_json"].get("asset_code") == "FEEPRECISION.SZ"
    ]
    assert len(posts) == 1
    rejected = posts[0]
    assert rejected["status"] == 400
    assert rejected["content_type"].startswith("application/json")
    assert rejected["request_json"] is not None
    assert rejected["request_json"]["commission"] == overprecision
    error_response = rejected["response_json"]
    assert isinstance(error_response, dict)
    assert error_response["code"] == "VALIDATION_ERROR"
    assert isinstance(error_response["details"], dict)
    assert "commission" in error_response["details"]
    assert (
        TransactionModel.objects.filter(
            portfolio=mcp_runtime.portfolio,
            asset_code="FEEPRECISION.SZ",
        ).count()
        == 0
    )
    assert TransactionModel.objects.filter(portfolio=mcp_runtime.portfolio).count() == before_count
    _assert_external_requests_are_blocked(exact_origin_http_log)


def test_replace_import_is_rejected_locally_before_transaction_api(
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Replace must fail locally without confirmation, HTTP transaction calls, or writes."""
    portfolio = mcp_runtime.portfolio
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="C1KEEP.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=10.0,
        avg_cost=Decimal("9.5000"),
        current_price=Decimal("9.50"),
    )
    trade = TransactionModel.objects.create(
        portfolio=portfolio,
        position=position,
        action="buy",
        asset_code="C1KEEP.SZ",
        shares=10.0,
        price=Decimal("9.5000"),
        notional=Decimal("95.00"),
        commission=Decimal("1.25"),
        slippage=Decimal("0.40"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("0.25"),
        commission_known=True,
        slippage_known=False,
        stamp_duty_known=None,
        transfer_fee_known=True,
        traded_at=timezone.now() - timedelta(minutes=2),
        notes="Preserve this existing transaction.",
    )
    position_fields = ("pk", "asset_code", "shares", "avg_cost", "current_price", "is_closed")
    trade_fields = (
        "pk",
        "position_id",
        "asset_code",
        "shares",
        "price",
        "notional",
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "traded_at",
        "notes",
    )
    position_before = tuple(getattr(position, field) for field in position_fields)
    trade_before = tuple(getattr(trade, field) for field in trade_fields)
    counts_before = (
        PositionModel.objects.filter(portfolio=portfolio).count(),
        TransactionModel.objects.filter(portfolio=portfolio).count(),
    )
    assert counts_before == (1, 1)
    request_start = len(exact_origin_http_log.exchanges)

    response = mcp_runtime.dispatcher.call(
        capability_key="account.import.transactions",
        arguments={
            "portfolio_id": portfolio.pk,
            "transactions": [
                _transaction_row(
                    "C1REPLACEATTEMPT.SZ",
                    commission="2.50",
                    slippage="0",
                    stamp_duty="0",
                    transfer_fee="0",
                )
            ],
            "mode": "replace",
            "idempotency_key": "fee-c1-replace-local-block",
        },
    )

    assert response["status"] == "error"
    assert response["capability_key"] == "account.import.transactions"
    error = response["error"]
    assert isinstance(error, dict)
    assert error["code"] == "transaction_import_append_only"
    assert error["upstream_status_code"] is None
    assert "confirmation_token" not in response

    new_exchanges = exact_origin_http_log.exchanges[request_start:]
    assert not any(
        exchange["path"].startswith("/api/account/transactions/") for exchange in new_exchanges
    )
    assert exact_origin_http_log.blocked == []
    assert all(
        exchange["origin"] == f"{exact_origin_http_log.expected_origin[0]}://"
        f"{exact_origin_http_log.expected_origin[1]}:{exact_origin_http_log.expected_origin[2]}"
        for exchange in new_exchanges
    )
    assert (
        PositionModel.objects.filter(portfolio=portfolio).count(),
        TransactionModel.objects.filter(portfolio=portfolio).count(),
    ) == counts_before
    position_after = PositionModel.objects.get(pk=position.pk)
    trade_after = TransactionModel.objects.get(pk=trade.pk)
    assert tuple(getattr(position_after, field) for field in position_fields) == position_before
    assert tuple(getattr(trade_after, field) for field in trade_fields) == trade_before


def test_owner_replace_fallback_is_rejected_before_http_and_preserves_rows(
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Direct legacy calls must reject replace before any live transaction request."""
    portfolio = mcp_runtime.portfolio
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="C1FALLBACKKEEP.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=10.0,
        avg_cost=Decimal("9.5000"),
        current_price=Decimal("9.50"),
    )
    trade = TransactionModel.objects.create(
        portfolio=portfolio,
        position=position,
        action="buy",
        asset_code="C1FALLBACKKEEP.SZ",
        shares=10.0,
        price=Decimal("9.5000"),
        notional=Decimal("95.00"),
        commission=Decimal("1.25"),
        slippage=Decimal("0.40"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("0.25"),
        commission_known=True,
        slippage_known=False,
        stamp_duty_known=None,
        transfer_fee_known=True,
        traded_at=timezone.now() - timedelta(minutes=2),
        notes="Preserve this existing transaction.",
    )
    position_fields = ("pk", "asset_code", "shares", "avg_cost", "current_price", "is_closed")
    trade_fields = (
        "pk",
        "position_id",
        "asset_code",
        "shares",
        "price",
        "notional",
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "traded_at",
        "notes",
    )
    position_before = tuple(getattr(position, field) for field in position_fields)
    trade_before = tuple(getattr(trade, field) for field in trade_fields)
    counts_before = (
        PositionModel.objects.filter(portfolio=portfolio).count(),
        TransactionModel.objects.filter(portfolio=portfolio).count(),
    )
    request_start = len(exact_origin_http_log.exchanges)

    owner_account = importlib.import_module(
        "agomtradepro_mcp.registry.runtime_handlers.owners.account"
    )
    api_error_type = importlib.import_module("agomtradepro.exceptions").AgomTradeProAPIError
    try:
        owner_account._fallback_import_transactions_json(
            portfolio_id=portfolio.pk,
            transactions=[
                _transaction_row(
                    "C1FALLBACKREPLACE.SZ",
                    commission="2.50",
                    slippage="0",
                    stamp_duty="0",
                    transfer_fee="0",
                )
            ],
            mode="replace",
            dry_run=False,
        )
    except api_error_type as exc:
        assert exc.status_code is None
        assert isinstance(exc.response, dict)
        assert exc.response["code"] == "transaction_import_append_only"
        assert exc.response["origin"] == "client_validation"
    else:
        observed = [
            (exchange["method"], exchange["path"], exchange["status"])
            for exchange in exact_origin_http_log.exchanges[request_start:]
            if exchange["path"].startswith("/api/account/transactions/")
        ]
        counts_after = (
            PositionModel.objects.filter(portfolio=portfolio).count(),
            TransactionModel.objects.filter(portfolio=portfolio).count(),
        )
        replacement_rows = TransactionModel.objects.filter(
            portfolio=portfolio,
            asset_code="C1FALLBACKREPLACE.SZ",
        ).count()
        pytest.fail(
            "expected local append-only rejection; the legacy call returned after "
            f"transaction HTTP exchanges (method/path/status): {observed!r}; "
            f"row counts before={counts_before!r}, after={counts_after!r}; "
            f"replacement rows stored={replacement_rows}"
        )

    transaction_exchanges = [
        exchange
        for exchange in exact_origin_http_log.exchanges[request_start:]
        if exchange["path"].startswith("/api/account/transactions/")
    ]
    observed = [
        (exchange["method"], exchange["path"], exchange["status"])
        for exchange in transaction_exchanges
    ]
    assert transaction_exchanges == [], (
        "append-only rejection must happen before transaction HTTP requests; "
        f"observed method/path/status: {observed!r}"
    )
    assert exact_origin_http_log.blocked == []
    assert (
        PositionModel.objects.filter(portfolio=portfolio).count(),
        TransactionModel.objects.filter(portfolio=portfolio).count(),
    ) == counts_before
    position_after = PositionModel.objects.get(pk=position.pk)
    trade_after = TransactionModel.objects.get(pk=trade.pk)
    assert tuple(getattr(position_after, field) for field in position_fields) == position_before
    assert tuple(getattr(trade_after, field) for field in trade_fields) == trade_before
