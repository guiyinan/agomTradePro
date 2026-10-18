"""Real MCP dispatcher-to-HTTP tests for simulated auto-trading scope."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import SplitResult, urlsplit
from uuid import uuid4

import pytest
import requests
from django.contrib.auth import get_user_model

from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from apps.simulated_trading.application import interface_services
from apps.simulated_trading.domain.auto_trading_outcomes import AccountAutoTradingOutcome
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel, SimulatedTradeModel
from tests.support.runtime_config import configure_account_runtime

pytestmark = pytest.mark.django_db(transaction=True)
TRADE_DATE = date(2026, 10, 18)
AUTO_RUN_PATH = "/api/simulated-trading/auto-trading/run/"
ACCOUNT_LIST_PATH = "/api/simulated-trading/accounts/"


class _Exchange(TypedDict):
    """Sanitized record of one actual local HTTP request and response."""

    method: str
    path: str
    origin: str
    status: int
    content_type: str
    request_json: dict[str, Any] | None
    response_json: dict[str, Any] | list[Any] | None


@dataclass
class _HttpLog:
    """Capture SDK HTTP while rejecting every origin except live_server."""

    expected_origin: tuple[str, str, int]
    exchanges: list[_Exchange]
    blocked: list[tuple[str, str, int]]


@dataclass(frozen=True)
class _Principal:
    """Persisted users, owner profile and the raw token used by the SDK."""

    owner: Any
    other: Any
    profile: AccountProfileModel
    raw_token: str


@dataclass(frozen=True)
class _Accounts:
    """Accounts that distinguish default eligibility from explicit scope."""

    eligible: SimulatedAccountModel
    auto_off: SimulatedAccountModel
    real: SimulatedAccountModel
    inactive: SimulatedAccountModel
    foreign: SimulatedAccountModel


@dataclass
class _EngineSpy:
    """Typed no-trade engine result at the execution boundary only."""

    builds: int
    calls: list[tuple[date, tuple[int, ...]]]

    def build(self) -> _EngineSpy:
        """Count construction and return this deterministic engine double."""

        self.builds += 1
        return self

    def run_daily_trading(
        self,
        trade_date: date,
        account_ids: list[int] | None = None,
    ) -> dict[int, AccountAutoTradingOutcome]:
        """Record the exact authorized IDs and return valid no-trade outcomes."""

        if account_ids is None:
            raise AssertionError("the HTTP execution boundary must pass a resolved scope")
        ordered_ids = tuple(account_ids)
        self.calls.append((trade_date, ordered_ids))
        return {
            account_id: AccountAutoTradingOutcome(account_id, 0, 0) for account_id in ordered_ids
        }


@dataclass(frozen=True)
class _McpRuntime:
    """Checkout MCP dispatcher and a real token-authenticated owner."""

    dispatcher: Any
    principal: _Principal


def _effective_port(parts: SplitResult) -> int:
    if parts.port is not None:
        return int(parts.port)
    return 443 if parts.scheme.lower() == "https" else 80


def _create_account(
    user: Any,
    account_name: str,
    *,
    account_type: str = "simulated",
    is_active: bool = True,
    auto_trading_enabled: bool = True,
) -> SimulatedAccountModel:
    """Persist one real account row with the chosen authorization state."""

    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=account_name,
        account_type=account_type,
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        total_value=Decimal("10000.00"),
        is_active=is_active,
        auto_trading_enabled=auto_trading_enabled,
    )


@pytest.fixture(autouse=True)
def _disable_user_provisioning_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep onboarding side effects outside these API scope assertions."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")


@pytest.fixture
def principal() -> _Principal:
    """Create actual users, an approved MCP owner profile and a write token."""

    configure_account_runtime()
    users = get_user_model()
    suffix = uuid4().hex[:12]
    owner = users.objects.create_user(username=f"scope-owner-{suffix}", password="testpass123")
    other = users.objects.create_user(username=f"scope-other-{suffix}", password="testpass123")
    profile, _ = AccountProfileModel.objects.update_or_create(
        user=owner,
        defaults={
            "display_name": "MCP scope owner",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
            "rbac_role": "owner",
        },
    )
    _, raw_token = UserAccessTokenModel.create_token(
        user=owner,
        name=f"scope-http-{suffix}",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    return _Principal(owner=owner, other=other, profile=profile, raw_token=raw_token)


@pytest.fixture
def accounts(principal: _Principal) -> _Accounts:
    """Persist owned eligibility distractors and a foreign eligible account."""

    suffix = uuid4().hex[:10]
    return _Accounts(
        eligible=_create_account(principal.owner, f"eligible-{suffix}"),
        auto_off=_create_account(
            principal.owner,
            f"auto-off-{suffix}",
            auto_trading_enabled=False,
        ),
        real=_create_account(principal.owner, f"real-{suffix}", account_type="real"),
        inactive=_create_account(principal.owner, f"inactive-{suffix}", is_active=False),
        foreign=_create_account(principal.other, f"foreign-{suffix}"),
    )


@pytest.fixture
def exact_origin_http_log(monkeypatch: pytest.MonkeyPatch, live_server: Any) -> _HttpLog:
    """Allow real requests to only the exact local live_server origin."""

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
        """Reject a non-local origin before I/O and preserve actual local responses."""

        parsed = urlsplit(str(url))
        actual = (
            parsed.scheme.lower(),
            str(parsed.hostname or "").lower().rstrip("."),
            _effective_port(parsed),
        )
        if actual != expected:
            log.blocked.append(actual)
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
                "response_json": (
                    response_body if isinstance(response_body, (dict, list)) else None
                ),
            }
        )
        return response

    monkeypatch.setattr(requests.Session, "request", guarded_request)
    return log


@pytest.fixture
def engine_spy(monkeypatch: pytest.MonkeyPatch) -> _EngineSpy:
    """Replace only engine construction; all account and HTTP paths stay real."""

    spy = _EngineSpy(builds=0, calls=[])
    monkeypatch.setattr(interface_services, "build_auto_trading_engine", spy.build)
    return spy


@pytest.fixture
def mcp_runtime(
    monkeypatch: pytest.MonkeyPatch,
    live_server: Any,
    principal: _Principal,
    exact_origin_http_log: _HttpLog,
) -> Iterator[_McpRuntime]:
    """Load the checkout SDK/MCP and bind its real HTTP client to owner auth."""

    prefixes = ("agomtradepro", "agomtradepro_mcp")
    previous_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)
    }
    for name in previous_modules:
        del sys.modules[name]

    sdk_root = (Path(__file__).resolve().parents[3] / "sdk").resolve()
    monkeypatch.syspath_prepend(str(sdk_root))
    monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", str(live_server.url))
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", principal.raw_token)
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

    try:
        sdk = importlib.import_module("agomtradepro")
        server = importlib.import_module("agomtradepro_mcp.server")
        rbac = importlib.import_module("agomtradepro_mcp.rbac")
        dispatcher_module = importlib.import_module("agomtradepro_mcp.registry.dispatcher")
        runtime_handler = importlib.import_module(
            "agomtradepro_mcp.registry.runtime_handlers.owners.simulated_trading"
        )
        for module in (sdk, server, dispatcher_module, runtime_handler):
            module_path = Path(str(module.__file__)).resolve()
            assert module_path.is_relative_to(sdk_root), module_path
        rbac._BACKEND_ROLE_CACHE = None
        rbac._BACKEND_PROFILE_CACHE = None
        assert rbac.get_current_role() == "owner"
        assert any(
            exchange["method"] == "GET"
            and exchange["path"] == "/api/account/profile/"
            and exchange["status"] == 200
            and exchange["content_type"].startswith("application/json")
            for exchange in exact_origin_http_log.exchanges
        )
        with pytest.raises(AssertionError, match="escaped the exact live_server origin"):
            requests.get("https://outside.invalid/blocked", timeout=0.1)
        assert exact_origin_http_log.blocked == [("https", "outside.invalid", 443)]
        yield _McpRuntime(server.CORE_DISPATCHER, principal)
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
                del sys.modules[name]
        sys.modules.update(previous_modules)


def _stage_default_scope(mcp_runtime: _McpRuntime) -> dict[str, Any]:
    """Preview using an omitted account_ids property, the public default scope."""

    return mcp_runtime.dispatcher.call(
        capability_key="trading.start.simulated_auto_trading",
        arguments={"trade_date": TRADE_DATE.isoformat(), "idempotency_key": uuid4().hex},
    )


def _stage_explicit_scope(
    mcp_runtime: _McpRuntime,
    account_ids: list[int],
) -> dict[str, Any]:
    """Preview a caller-supplied ordered account ID list."""

    return mcp_runtime.dispatcher.call(
        capability_key="trading.start.simulated_auto_trading",
        arguments={
            "trade_date": TRADE_DATE.isoformat(),
            "account_ids": account_ids,
            "idempotency_key": uuid4().hex,
        },
    )


def _resume(mcp_runtime: _McpRuntime, staged: dict[str, Any]) -> dict[str, Any]:
    """Approve one actual dispatcher confirmation token."""

    assert staged["status"] == "confirmation_required"
    token = staged.get("confirmation_token")
    assert isinstance(token, str) and token
    return mcp_runtime.dispatcher.resume_confirmation(confirmation_token=token, approve=True)


def _exchanges(log: _HttpLog, *, method: str, path: str) -> list[_Exchange]:
    """Select observed requests without substituting any response."""

    return [
        exchange
        for exchange in log.exchanges
        if exchange["method"] == method and exchange["path"] == path
    ]


def _account_reads(log: _HttpLog) -> list[_Exchange]:
    """Return real account-list and account-detail GETs from the API log."""

    return [
        exchange
        for exchange in log.exchanges
        if exchange["method"] == "GET" and exchange["path"].startswith(ACCOUNT_LIST_PATH)
    ]


def _assert_json_response(exchange: _Exchange, status: int) -> None:
    assert exchange["status"] == status
    assert exchange["content_type"].startswith("application/json")


def _assert_http_guard(log: _HttpLog) -> None:
    assert log.blocked == [("https", "outside.invalid", 443)]
    assert all(
        exchange["origin"]
        == f"{log.expected_origin[0]}://{log.expected_origin[1]}:{log.expected_origin[2]}"
        for exchange in log.exchanges
    )


def test_default_scope_freezes_only_accounts_resolved_before_confirmation(
    mcp_runtime: _McpRuntime,
    accounts: _Accounts,
    engine_spy: _EngineSpy,
    exact_origin_http_log: _HttpLog,
) -> None:
    """A newly eligible account after preview is not added to the confirmed run."""

    before_trades = SimulatedTradeModel.objects.count()
    staged = _stage_default_scope(mcp_runtime)
    assert staged["status"] == "confirmation_required"
    assert staged["preview_result"]["account_ids"] is None
    lists = _exchanges(exact_origin_http_log, method="GET", path=ACCOUNT_LIST_PATH)
    assert len(lists) == 1
    _assert_json_response(lists[0], 200)

    added = _create_account(
        mcp_runtime.principal.owner,
        f"added-after-preview-{uuid4().hex[:10]}",
    )
    assert added.pk != accounts.eligible.pk

    result = _resume(mcp_runtime, staged)
    assert result["status"] == "completed"
    posts = _exchanges(exact_origin_http_log, method="POST", path=AUTO_RUN_PATH)
    assert len(posts) == 1
    _assert_json_response(posts[0], 200)
    assert engine_spy.calls == [(TRADE_DATE, (accounts.eligible.pk,))], (
        "confirmation included an account added after preview: "
        f"observed execution IDs {engine_spy.calls!r}"
    )
    resolved_ids = [accounts.eligible.pk]
    assert staged["preview_result"]["resolved_account_ids"] == resolved_ids
    scope_summary = staged["preview_result"]["account_scope_summary"]
    assert scope_summary["scope_mode"] == "default"
    assert scope_summary["requested_account_count"] is None
    assert scope_summary["source_account_count"] == 2
    assert scope_summary["resolved_account_count"] == len(resolved_ids)
    expected_digest = hashlib.sha256(
        json.dumps(resolved_ids, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    assert scope_summary["resolved_account_ids_sha256"] == expected_digest
    assert posts[0]["request_json"] == {
        "trade_date": TRADE_DATE.isoformat(),
        "account_ids": [accounts.eligible.pk],
    }
    assert result["result"]["outcome"] == "noop"
    assert SimulatedTradeModel.objects.count() == before_trades
    added_detail_path = f"{ACCOUNT_LIST_PATH}{added.pk}/"
    assert not _exchanges(exact_origin_http_log, method="GET", path=added_detail_path)
    _assert_http_guard(exact_origin_http_log)


def test_explicit_empty_scope_posts_noop_without_account_reads_or_engine(
    mcp_runtime: _McpRuntime,
    engine_spy: _EngineSpy,
    exact_origin_http_log: _HttpLog,
) -> None:
    """An explicit empty scope confirms as a no-op and performs no account lookup."""

    before_trades = SimulatedTradeModel.objects.count()
    before_accounts = SimulatedAccountModel.objects.count()
    staged = _stage_explicit_scope(mcp_runtime, [])
    assert staged["status"] == "confirmation_required"
    assert staged["preview_result"]["account_ids"] == []
    assert _account_reads(exact_origin_http_log) == []
    result = _resume(mcp_runtime, staged)
    assert result["status"] == "completed"
    posts = _exchanges(exact_origin_http_log, method="POST", path=AUTO_RUN_PATH)
    assert len(posts) == 1
    _assert_json_response(posts[0], 200)
    assert posts[0]["request_json"] == {
        "trade_date": TRADE_DATE.isoformat(),
        "account_ids": [],
    }
    assert result["result"]["outcome"] == "noop"
    assert result["result"]["requested"] == 0
    assert result["result"]["stored"] == 0
    assert engine_spy.builds == 0 and engine_spy.calls == []
    assert SimulatedTradeModel.objects.count() == before_trades
    assert SimulatedAccountModel.objects.count() == before_accounts
    _assert_http_guard(exact_origin_http_log)


def test_explicit_account_order_survives_real_preview_and_confirmation(
    mcp_runtime: _McpRuntime,
    accounts: _Accounts,
    engine_spy: _EngineSpy,
    exact_origin_http_log: _HttpLog,
) -> None:
    """Both preview detail reads and confirmed execution retain caller order."""

    second = _create_account(
        mcp_runtime.principal.owner,
        f"ordered-second-{uuid4().hex[:10]}",
    )
    requested = [second.pk, accounts.eligible.pk]
    before_trades = SimulatedTradeModel.objects.count()
    staged = _stage_explicit_scope(mcp_runtime, requested)
    assert staged["status"] == "confirmation_required"
    assert staged["preview_result"]["account_ids"] == requested
    detail_reads = [
        exchange
        for exchange in exact_origin_http_log.exchanges
        if exchange["method"] == "GET"
        and exchange["path"].startswith(ACCOUNT_LIST_PATH)
        and exchange["path"] != ACCOUNT_LIST_PATH
    ]
    assert [exchange["path"] for exchange in detail_reads] == [
        f"{ACCOUNT_LIST_PATH}{account_id}/" for account_id in requested
    ]
    for exchange in detail_reads:
        _assert_json_response(exchange, 200)

    result = _resume(mcp_runtime, staged)
    assert result["status"] == "completed"
    posts = _exchanges(exact_origin_http_log, method="POST", path=AUTO_RUN_PATH)
    assert len(posts) == 1
    _assert_json_response(posts[0], 200)
    assert posts[0]["request_json"] == {
        "trade_date": TRADE_DATE.isoformat(),
        "account_ids": requested,
    }
    assert engine_spy.calls == [(TRADE_DATE, tuple(requested))]
    assert SimulatedTradeModel.objects.count() == before_trades
    _assert_http_guard(exact_origin_http_log)


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        pytest.param("owner_transfer", 403, id="owner-transferred"),
        pytest.param("inactive", 400, id="account-inactive"),
        pytest.param("real", 400, id="account-became-real"),
        pytest.param("auto_off", 400, id="auto-trading-disabled"),
    ],
)
def test_account_eligibility_is_rechecked_at_confirmation(
    mcp_runtime: _McpRuntime,
    accounts: _Accounts,
    engine_spy: _EngineSpy,
    exact_origin_http_log: _HttpLog,
    change: str,
    expected_status: int,
) -> None:
    """A preview does not authorize an account after its persisted eligibility changes."""

    account = accounts.eligible
    staged = _stage_explicit_scope(mcp_runtime, [account.pk])
    assert staged["status"] == "confirmation_required"
    if change == "owner_transfer":
        account.user = mcp_runtime.principal.other
        account.save(update_fields=["user"])
    elif change == "inactive":
        account.is_active = False
        account.save(update_fields=["is_active"])
    elif change == "real":
        account.account_type = "real"
        account.save(update_fields=["account_type"])
    else:
        account.auto_trading_enabled = False
        account.save(update_fields=["auto_trading_enabled"])

    before_trades = SimulatedTradeModel.objects.count()
    result = _resume(mcp_runtime, staged)
    assert result["status"] == "error"
    assert result["ok"] is False
    posts = _exchanges(exact_origin_http_log, method="POST", path=AUTO_RUN_PATH)
    assert len(posts) == 1
    _assert_json_response(posts[0], expected_status)
    assert engine_spy.builds == 0 and engine_spy.calls == []
    assert SimulatedTradeModel.objects.count() == before_trades
    _assert_http_guard(exact_origin_http_log)


def test_disabled_mcp_profile_rejects_confirmation_with_fresh_api_authentication(
    mcp_runtime: _McpRuntime,
    accounts: _Accounts,
    engine_spy: _EngineSpy,
    exact_origin_http_log: _HttpLog,
) -> None:
    """The backend rechecks the owner's MCP-enabled flag on the real write request."""

    staged = _stage_explicit_scope(mcp_runtime, [accounts.eligible.pk])
    assert staged["status"] == "confirmation_required"
    profile = mcp_runtime.principal.profile
    profile.mcp_enabled = False
    profile.save(update_fields=["mcp_enabled"])

    before_trades = SimulatedTradeModel.objects.count()
    result = _resume(mcp_runtime, staged)
    assert result["status"] == "error"
    assert result["ok"] is False
    posts = _exchanges(exact_origin_http_log, method="POST", path=AUTO_RUN_PATH)
    assert len(posts) == 1
    _assert_json_response(posts[0], 403)
    response_body = posts[0]["response_json"]
    assert isinstance(response_body, dict)
    assert "MCP access disabled" in str(response_body.get("error", ""))
    assert result["error"]["upstream_status_code"] == posts[0]["status"] == 403
    assert result["error"]["message"] == response_body["error"]
    assert engine_spy.builds == 0 and engine_spy.calls == []
    assert SimulatedTradeModel.objects.count() == before_trades
    _assert_http_guard(exact_origin_http_log)
