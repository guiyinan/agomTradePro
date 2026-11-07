"""Exercise M1 qualification through public SDK and MCP calls over live HTTP."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import requests
from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session
from rest_framework.test import APIClient

from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from tests.integration.simulated_trading import test_readonly_rebalance_plan_owner_api as owner_case
from tests.integration.simulated_trading.test_m1_published_close_browser_journey import (
    isolated_m1_revision_table as isolated_m1_revision_table,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_account_runtime

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connections[DEFAULT_DB_ALIAS].vendor != "postgresql",
        reason="public SDK/MCP M1 journey requires the isolated PostgreSQL test database",
    ),
]


@dataclass(frozen=True, slots=True)
class _HttpExchange:
    """Sanitized observation of one actual SDK HTTP request."""

    method: str
    path: str
    origin: str
    status: int
    content_type: str
    owner_token_present: bool
    request_json: dict[str, Any] | None
    response_json: dict[str, Any] | list[Any] | None


@dataclass(slots=True)
class _HttpTrace:
    """Permit HTTP only to the isolated Django live-server origin."""

    expected_origin: tuple[str, str, int]
    exchanges: list[_HttpExchange]
    blocked_origins: list[tuple[str, str, int]]


@dataclass(frozen=True, slots=True)
class _M1OwnerCase:
    """Owner accounts, strategies, published revisions, and test-only credentials."""

    owner: Any
    account: SimulatedAccountModel
    strategy: Any
    owner_revision: str
    foreign_account: SimulatedAccountModel
    foreign_revision: str
    access_token: str


@dataclass(frozen=True, slots=True)
class _PublicRuntime:
    """Checkout SDK/MCP entrypoints pointed at one isolated Django server."""

    sdk_client: Any
    mcp_server: Any
    trace: _HttpTrace
    owner_case: _M1OwnerCase


def _effective_port(parts: Any) -> int:
    """Return the explicit or protocol-default port from a parsed URL."""
    if parts.port is not None:
        return int(parts.port)
    return 443 if parts.scheme.lower() == "https" else 80


@pytest.fixture
def _m1_owner_case(
    monkeypatch: pytest.MonkeyPatch,
    isolated_m1_revision_table: None,
    preserve_account_authority_generation: None,
    record_property: Callable[[str, object], None],
) -> _M1OwnerCase:
    """Publish real owner revisions while keeping market inputs as local fixtures."""
    del isolated_m1_revision_table, preserve_account_authority_generation
    record_property("native_postgresql_database", assert_native_postgres_test_database())
    # Django caches the column's table alias; each fixture has a new disposable schema.
    for field in M1RebalanceRiskPolicyRevisionModel._meta.concrete_fields:
        field.__dict__.pop("cached_col", None)
    configure_account_runtime()
    monkeypatch.delenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", raising=False)
    real_now = timezone.now
    owner, account = owner_case._create_owner_account(
        username="ref03-publiccall-owner",
        positions=(),
        stop_loss_pct=8.0,
    )
    strategy = owner_case._create_strategy(
        user=owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    foreign_owner, foreign_account = owner_case._create_owner_account(
        username="ref03-publiccall-foreign",
        positions=(),
        stop_loss_pct=8.0,
    )
    foreign_strategy = owner_case._create_strategy(
        user=foreign_owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    for user in (owner, foreign_owner):
        AccountProfileModel.objects.update_or_create(
            user=user,
            defaults={
                "approval_status": "approved",
                "user_agreement_accepted": True,
                "risk_warning_acknowledged": True,
                "mcp_enabled": True,
                "rbac_role": "owner",
            },
        )

    # Isolated market data supports only the policy-routing assertion; this is
    # not evidence for ASH-08 same-day source or published-close qualification.
    price_reader, _, _, _ = owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=owner.pk,
        classification_asset_types={owner_case.ASSET_BUY: "equity"},
    )
    owner_revision = owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=APIClient(),
        owner=owner,
        account=account,
        strategy=strategy,
    )
    foreign_revision = owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=APIClient(),
        owner=foreign_owner,
        account=foreign_account,
        strategy=foreign_strategy,
    )

    # The policy helper freezes publication at a real current instant. Resume
    # the real clock so this call never relies on a future-dated freshness shim.
    monkeypatch.setattr(timezone, "now", real_now)
    price_reader.observed_at = real_now().astimezone(UTC)

    _, access_token = UserAccessTokenModel.create_token(
        user=owner,
        name="ref03-publiccall-owner",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )
    return _M1OwnerCase(
        owner=owner,
        account=account,
        strategy=strategy,
        owner_revision=owner_revision,
        foreign_account=foreign_account,
        foreign_revision=foreign_revision,
        access_token=access_token,
    )


@pytest.fixture
def _public_runtime(
    monkeypatch: pytest.MonkeyPatch,
    live_server: Any,
    _m1_owner_case: _M1OwnerCase,
) -> Iterator[_PublicRuntime]:
    """Load real checkout clients and guard every SDK request to live_server."""
    live_parts = urlsplit(str(live_server.url))
    host = str(live_parts.hostname or "").lower().rstrip(".")
    expected = (live_parts.scheme.lower(), host, _effective_port(live_parts))
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

    trace = _HttpTrace(expected_origin=expected, exchanges=[], blocked_origins=[])
    expected_token = f"Token {_m1_owner_case.access_token}"
    original_request = requests.Session.request

    def guarded_request(
        session: requests.Session,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Block off-origin access and retain only sanitized real responses."""
        parsed = urlsplit(str(url))
        actual = (
            parsed.scheme.lower(),
            str(parsed.hostname or "").lower().rstrip("."),
            _effective_port(parsed),
        )
        if actual != expected:
            trace.blocked_origins.append(actual)
            raise AssertionError("SDK HTTP request escaped the isolated live_server origin")

        response = original_request(session, method, url, **kwargs)
        prepared = response.request
        prepared_headers = prepared.headers if prepared is not None else {}
        body = kwargs.get("json")
        try:
            response_body = response.json()
        except ValueError:
            response_body = None
        trace.exchanges.append(
            _HttpExchange(
                method=method.upper(),
                path=parsed.path,
                origin=f"{actual[0]}://{actual[1]}:{actual[2]}",
                status=response.status_code,
                content_type=response.headers.get("Content-Type", ""),
                owner_token_present=prepared_headers.get("Authorization") == expected_token,
                request_json=dict(body) if isinstance(body, dict) else None,
                response_json=(response_body if isinstance(response_body, (dict, list)) else None),
            )
        )
        return response

    monkeypatch.setattr(requests.Session, "request", guarded_request)
    sdk_root = (Path(__file__).resolve().parents[3] / "sdk").resolve()
    monkeypatch.syspath_prepend(str(sdk_root))
    monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", str(live_server.url))
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", _m1_owner_case.access_token)
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

    prefixes = ("agomtradepro", "agomtradepro_mcp")
    previous_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)
    }
    for name in previous_modules:
        del sys.modules[name]

    try:
        sdk = importlib.import_module("agomtradepro")
        server_module = importlib.import_module("agomtradepro_mcp.server")
        rbac = importlib.import_module("agomtradepro_mcp.rbac")
        for module in (sdk, server_module):
            assert Path(str(module.__file__)).resolve().is_relative_to(sdk_root)
        rbac._BACKEND_ROLE_CACHE = None
        rbac._BACKEND_PROFILE_CACHE = None
        assert rbac.get_current_role() == "owner"
        assert any(
            exchange.method == "GET"
            and exchange.path == "/api/account/profile/"
            and exchange.status == 200
            and exchange.content_type.startswith("application/json")
            and exchange.owner_token_present
            for exchange in trace.exchanges
        )

        yield _PublicRuntime(
            sdk_client=sdk.AgomTradeProClient(),
            mcp_server=server_module.server,
            trace=trace,
            owner_case=_m1_owner_case,
        )
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
                del sys.modules[name]
        sys.modules.update(previous_modules)


def _mcp_tool_payload(result: Any) -> dict[str, Any]:
    """Decode one real MCP call_tool response without bypassing the protocol."""
    for name in ("structuredContent", "structured_content"):
        structured = getattr(result, name, None)
        if isinstance(structured, dict):
            return structured
    for item in getattr(result, "content", ()):
        text = getattr(item, "text", None)
        if isinstance(text, str):
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
    raise AssertionError("MCP call_tool returned no structured object payload")


def _inspection_path(account_id: int) -> str:
    """Return the canonical daily-inspection route observed over live HTTP."""
    return f"/api/simulated-trading/accounts/{account_id}/inspections/run/"


def _assert_owner_http_identity(trace: _HttpTrace) -> None:
    """Require every actual SDK request to use the owner's token and local origin."""
    assert trace.blocked_origins == []
    assert trace.exchanges
    expected_origin = (
        f"{trace.expected_origin[0]}://{trace.expected_origin[1]}:{trace.expected_origin[2]}"
    )
    assert all(exchange.owner_token_present for exchange in trace.exchanges)
    assert all(exchange.origin == expected_origin for exchange in trace.exchanges)


def _mcp_plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only the selected risk fields from one confirmed MCP result."""
    result = payload.get("result")
    if not isinstance(result, dict):
        return {}
    reports = result.get("reports")
    if not isinstance(reports, list) or not reports or not isinstance(reports[0], dict):
        return {}
    report = reports[0]
    plan = report.get("plan")
    if not isinstance(plan, dict):
        return {}
    context = plan.get("risk_context")
    if not isinstance(context, dict):
        return {}
    rows = plan.get("asset_items")
    buy = (
        next(
            (
                row
                for row in rows
                if isinstance(row, dict) and row.get("asset_code") == owner_case.ASSET_BUY
            ),
            None,
        )
        if isinstance(rows, list)
        else None
    )
    return {
        "account_id": report.get("account_id"),
        "plan_status": plan.get("status"),
        "read_only": plan.get("read_only"),
        "execution_submitted": plan.get("execution_submitted"),
        "risk_policy_version": context.get("risk_policy_version"),
        "risk_policy_qualification_status": context.get("risk_policy_qualification_status"),
        "risk_policy_reason_codes": context.get("risk_policy_reason_codes"),
        "buy_status": buy.get("status") if isinstance(buy, dict) else None,
        "buy_actionable_quantity": (
            buy.get("actionable_quantity") if isinstance(buy, dict) else None
        ),
    }


def _http_evidence(exchange: _HttpExchange) -> dict[str, Any]:
    """Return only approved, non-secret fields from an observed SDK exchange."""
    body = exchange.response_json if isinstance(exchange.response_json, dict) else {}
    report_list = body.get("reports")
    report = report_list[0] if isinstance(report_list, list) and report_list else {}
    plan = report.get("plan") if isinstance(report, dict) else None
    context = plan.get("risk_context") if isinstance(plan, dict) else None
    response_summary: dict[str, Any] = {
        "success": body.get("success"),
        "error": body.get("error"),
    }
    if isinstance(body.get("revocation_status"), str):
        response_summary["revocation_status"] = body["revocation_status"]
    if isinstance(context, dict):
        response_summary.update(
            {
                "risk_policy_version": context.get("risk_policy_version"),
                "risk_policy_qualification_status": context.get("risk_policy_qualification_status"),
                "risk_policy_reason_codes": context.get("risk_policy_reason_codes"),
            }
        )
    return {
        "method": exchange.method,
        "origin": exchange.origin,
        "path": exchange.path,
        "status": exchange.status,
        "content_type": exchange.content_type,
        "owner_token_present": exchange.owner_token_present,
        "response": response_summary,
    }


def _mcp_error_code(payload: dict[str, Any]) -> str | None:
    """Return a structured error code without retaining an error message."""
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def test_mcp_public_call_requires_confirmation_before_qualified_inspection(
    _public_runtime: _PublicRuntime,
    record_property: Callable[[str, object], None],
) -> None:
    """The public MCP protocol stages scope first, then sends owner-authenticated HTTP."""
    assert_native_postgres_test_database()
    owner_case_data = _public_runtime.owner_case
    run_path = _inspection_path(owner_case_data.account.pk)
    foreign_path = f"/api/simulated-trading/accounts/{owner_case_data.foreign_account.pk}/"

    financial_before = owner_case._financial_snapshot()
    report_count_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=owner_case_data.account.pk
    ).count()
    proposal_count_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=owner_case_data.account.pk
    ).count()

    async def exercise_public_mcp() -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        async with create_connected_server_and_client_session(
            _public_runtime.mcp_server
        ) as session:
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            assert {"agom_capability_call", "agom_confirmation_resume"}.issubset(tool_names)

            before_denial = len(_public_runtime.trace.exchanges)
            denied_result = await session.call_tool(
                "agom_capability_call",
                {
                    "capability_key": "trading.run.simulated_daily_inspection",
                    "arguments": {
                        "account_id": owner_case_data.foreign_account.pk,
                        "inspection_date": timezone.localdate().isoformat(),
                        "auto_create_proposal": False,
                        "idempotency_key": f"ref03-denied-{uuid4().hex}",
                    },
                },
            )
            denied = _mcp_tool_payload(denied_result)
            assert denied.get("status") == "error"
            assert "confirmation_token" not in denied
            denied_exchanges = _public_runtime.trace.exchanges[before_denial:]
            denied_http = next(item for item in denied_exchanges if item.path == foreign_path)
            assert denied_http.status == 403
            assert denied_http.content_type.startswith("application/json")
            assert denied_http.owner_token_present is True
            assert not any(item.path.endswith("/inspections/run/") for item in denied_exchanges)

            # Try the MCP public schema with a foreign published version. Strict
            # rejection must happen before an inspection can be submitted.
            before_selector = len(_public_runtime.trace.exchanges)
            selector_result = await session.call_tool(
                "agom_capability_call",
                {
                    "capability_key": "trading.run.simulated_daily_inspection",
                    "arguments": {
                        "account_id": owner_case_data.account.pk,
                        "strategy_id": owner_case_data.strategy.pk,
                        "inspection_date": timezone.localdate().isoformat(),
                        "auto_create_proposal": False,
                        "risk_policy_version": owner_case_data.foreign_revision,
                        "idempotency_key": f"ref03-preview-{uuid4().hex}",
                    },
                },
            )
            selector = _mcp_tool_payload(selector_result)
            selector_exchanges = _public_runtime.trace.exchanges[before_selector:]
            assert not any(
                item.method == "POST" and item.path == run_path for item in selector_exchanges
            )
            assert selector.get("status") == "error"
            assert "confirmation_token" not in selector
            selector_cancelled = {"status": "not_staged"}

            before_preview = len(_public_runtime.trace.exchanges)
            staged_result = await session.call_tool(
                "agom_capability_call",
                {
                    "capability_key": "trading.run.simulated_daily_inspection",
                    "arguments": {
                        "account_id": owner_case_data.account.pk,
                        "strategy_id": owner_case_data.strategy.pk,
                        "inspection_date": timezone.localdate().isoformat(),
                        "auto_create_proposal": False,
                        "idempotency_key": f"ref03-preview-{uuid4().hex}",
                    },
                },
            )
            staged = _mcp_tool_payload(staged_result)

            assert staged.get("status") == "confirmation_required"
            staged_preview = staged.get("preview_result")
            assert isinstance(staged_preview, dict)
            assert staged_preview.get("preview_only") is True
            assert staged_preview.get("account_id") == owner_case_data.account.pk
            assert staged_preview.get("account_summary", {}).get("account_type") == "simulated"
            assert "risk_policy_version" not in staged_preview
            assert not any(
                item.method == "POST" and item.path == run_path
                for item in _public_runtime.trace.exchanges[before_preview:]
            )

            token = staged.get("confirmation_token")
            assert isinstance(token, str) and token
            confirmed_result = await session.call_tool(
                "agom_confirmation_resume",
                {"confirmation_token": token, "approve": True},
            )
            confirmed = _mcp_tool_payload(confirmed_result)
            assert confirmed.get("ok") is True
            assert confirmed.get("status") == "completed"
            result = confirmed.get("result")
            assert isinstance(result, dict)
            assert result.get("success") is True
            report = result["reports"][0]
            assert report["account_id"] == owner_case_data.account.pk
            plan = report["plan"]
            assert plan["read_only"] is True
            assert plan["execution_submitted"] is False
            assert plan["risk_context"]["risk_policy_version"] == owner_case_data.owner_revision
            assert plan["risk_context"]["risk_policy_qualification_status"] == "qualified"
            buy = next(
                row for row in plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY
            )
            assert buy["action"] == "buy"
            assert buy["status"] == "ready"
            assert Decimal(str(buy["actionable_quantity"])) > 0

            # Revoke through the real SDK route between stage and confirmation;
            # the second public preview must requalify against the live revoke.

            before_revoked_preview = len(_public_runtime.trace.exchanges)
            revoked_staged_result = await session.call_tool(
                "agom_capability_call",
                {
                    "capability_key": "trading.run.simulated_daily_inspection",
                    "arguments": {
                        "account_id": owner_case_data.account.pk,
                        "strategy_id": owner_case_data.strategy.pk,
                        "inspection_date": timezone.localdate().isoformat(),
                        "auto_create_proposal": False,
                        "idempotency_key": f"ref03-revoked-{uuid4().hex}",
                    },
                },
            )
            revoked_staged = _mcp_tool_payload(revoked_staged_result)
            assert revoked_staged.get("status") == "confirmation_required"
            assert revoked_staged.get("preview_result", {}).get("preview_only") is True
            assert not any(
                item.method == "POST" and item.path == run_path
                for item in _public_runtime.trace.exchanges[before_revoked_preview:]
            )
            revoked_token = revoked_staged.get("confirmation_token")
            assert isinstance(revoked_token, str) and revoked_token

            revoke_response = _public_runtime.sdk_client.post(
                f"api/account/accounts/{owner_case_data.account.pk}/m1-risk-policy-revisions/"
                f"{owner_case_data.owner_revision}/revoke/",
                json={"reason": "Public-call REF-03 revocation fixture."},
                idempotency_key=f"ref03-revoke-{uuid4().hex}",
            )
            assert revoke_response["revocation_status"] == "revoked"

            revoked_confirmed_result = await session.call_tool(
                "agom_confirmation_resume",
                {"confirmation_token": revoked_token, "approve": True},
            )
            revoked_confirmed = _mcp_tool_payload(revoked_confirmed_result)
            assert revoked_confirmed.get("ok") is True
            assert revoked_confirmed.get("status") == "completed"
            revoked_result = revoked_confirmed.get("result")
            assert isinstance(revoked_result, dict)
            revoked_plan = revoked_result["reports"][0]["plan"]
            revoked_context = revoked_plan["risk_context"]
            assert revoked_context["risk_policy_version"] == owner_case_data.owner_revision
            assert revoked_context["risk_policy_qualification_status"] == "revoked"
            revoked_buy = next(
                row
                for row in revoked_plan["asset_items"]
                if row["asset_code"] == owner_case.ASSET_BUY
            )
            assert revoked_buy["status"] == "blocked"
            assert revoked_buy["actionable_quantity"] is None
            assert "M1_RISK_POLICY_REVOKED" in revoked_buy["reason_codes"]
            return (
                denied,
                selector,
                {**staged, "selector_cancelled_status": selector_cancelled.get("status")},
                confirmed,
                revoke_response,
                revoked_confirmed,
            )

    denied, selector, staged, confirmed, revoke_response, revoked_confirmed = asyncio.run(
        exercise_public_mcp()
    )
    owner_case._assert_no_financial_writes(
        before=financial_before,
        account=owner_case_data.account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
        report_count_delta=1,
    )
    assert denied.get("ok") is False
    assert staged.get("preview_result", {}).get("risk_policy_version") is None
    assert (
        confirmed.get("result", {}).get("reports", [{}])[0]["plan"]["risk_context"][
            "risk_policy_version"
        ]
        == owner_case_data.owner_revision
    )
    assert revoke_response["revocation_status"] == "revoked"
    assert _mcp_plan_summary(revoked_confirmed)["risk_policy_qualification_status"] == "revoked"
    requests_to_inspection = [
        item
        for item in _public_runtime.trace.exchanges
        if item.path == run_path and item.method == "POST"
    ]
    assert len(requests_to_inspection) == 2
    assert all(item.status == 200 and item.owner_token_present for item in requests_to_inspection)
    assert all(item.content_type.startswith("application/json") for item in requests_to_inspection)
    assert all(
        item.request_json is not None and "risk_policy_version" not in item.request_json
        for item in requests_to_inspection
    )
    _assert_owner_http_identity(_public_runtime.trace)
    record_property(
        "ref03_mcp_calls",
        json.dumps(
            {
                "denied": {
                    "ok": denied.get("ok"),
                    "status": denied.get("status"),
                    "error_code": _mcp_error_code(denied),
                },
                "selector_attempt": {
                    "ok": selector.get("ok"),
                    "status": selector.get("status"),
                    "error_code": _mcp_error_code(selector),
                },
                "staged": {
                    "ok": staged.get("ok"),
                    "status": staged.get("status"),
                    "preview_only": staged.get("preview_result", {}).get("preview_only"),
                },
                "confirmed": _mcp_plan_summary(confirmed),
                "revoked_confirmed": _mcp_plan_summary(revoked_confirmed),
            },
            sort_keys=True,
        ),
    )
    record_property(
        "ref03_sdk_http_exchanges",
        json.dumps(
            [_http_evidence(item) for item in _public_runtime.trace.exchanges], sort_keys=True
        ),
    )


def test_public_sdk_raw_body_cannot_select_another_owner_revision(
    _public_runtime: _PublicRuntime,
    record_property: Callable[[str, object], None],
) -> None:
    """A generic SDK POST cannot override path account identity or active revision."""
    assert_native_postgres_test_database()
    owner_case_data = _public_runtime.owner_case
    endpoint = _inspection_path(owner_case_data.account.pk)
    forged_body: dict[str, Any] = {
        "strategy_id": owner_case_data.strategy.pk,
        "inspection_date": timezone.localdate().isoformat(),
        "auto_create_proposal": False,
        "account_id": owner_case_data.foreign_account.pk,
        "risk_policy_version": owner_case_data.foreign_revision,
    }
    financial_before = owner_case._financial_snapshot()
    report_count_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=owner_case_data.account.pk
    ).count()
    proposal_count_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=owner_case_data.account.pk
    ).count()

    response = _public_runtime.sdk_client.post(endpoint.lstrip("/"), json=forged_body)

    assert response["success"] is True
    owner_case._assert_no_financial_writes(
        before=financial_before,
        account=owner_case_data.account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )
    report = response["reports"][0]
    assert report["account_id"] == owner_case_data.account.pk
    plan = report["plan"]
    assert plan["risk_context"]["risk_policy_version"] == owner_case_data.owner_revision
    assert plan["risk_context"]["risk_policy_qualification_status"] == "qualified"
    assert owner_case_data.foreign_revision not in json.dumps(response, sort_keys=True)

    matching = [
        item
        for item in _public_runtime.trace.exchanges
        if item.method == "POST" and item.path == endpoint
    ]
    assert len(matching) == 1
    assert matching[0].status == 200
    assert matching[0].content_type.startswith("application/json")
    assert matching[0].owner_token_present is True
    assert matching[0].request_json == forged_body
    assert isinstance(matching[0].response_json, dict)
    response_report = matching[0].response_json["reports"][0]
    assert response_report["account_id"] == owner_case_data.account.pk
    assert (
        response_report["plan"]["risk_context"]["risk_policy_version"]
        == owner_case_data.owner_revision
    )
    _assert_owner_http_identity(_public_runtime.trace)
    record_property(
        "ref03_sdk_bypass_http_exchange",
        json.dumps(
            {
                "request_fields": sorted(forged_body),
                "foreign_account_submitted": forged_body["account_id"],
                "foreign_revision_submitted": forged_body["risk_policy_version"],
                "http": _http_evidence(matching[0]),
                "selected_plan": {
                    "account_id": response_report["account_id"],
                    "risk_policy_version": response_report["plan"]["risk_context"][
                        "risk_policy_version"
                    ],
                    "risk_policy_qualification_status": response_report["plan"]["risk_context"][
                        "risk_policy_qualification_status"
                    ],
                },
            },
            sort_keys=True,
        ),
    )


def _publish_short_lived_revision(runtime: _PublicRuntime) -> str:
    """Replace the fixture policy through real HTTP and wait for its real expiry."""
    case = runtime.owner_case
    root = f"api/account/accounts/{case.account.pk}/m1-risk-policy-revisions/"
    revoked = runtime.sdk_client.post(
        f"{root}{case.owner_revision}/revoke/",
        json={"reason": "Replace the test policy with a short-lived decision."},
        idempotency_key=f"ref03-expiry-revoke-{uuid4().hex}",
    )
    assert revoked["revocation_status"] == "revoked"
    now = timezone.now()
    effective_from = now + timedelta(seconds=5)
    effective_until = now + timedelta(seconds=6)
    published = runtime.sdk_client.post(
        root,
        json={
            "strategy_id": case.strategy.pk,
            "effective_from": effective_from.isoformat(),
            "effective_until": effective_until.isoformat(),
            "reason": "Real-clock expiry fixture for the public SDK qualification read.",
            "max_single_position_applicability": "applicable",
            "max_single_position_limit_pct": "19",
            "max_total_position_applicability": "applicable",
            "max_total_position_limit_pct": "90",
            "max_stop_loss_applicability": "applicable",
            "max_stop_loss_limit_pct": "7",
        },
        idempotency_key=f"ref03-expiry-publish-{uuid4().hex}",
    )
    assert published["publication_status"] == "published"
    remaining = (effective_until - timezone.now()).total_seconds()
    if remaining > 0:
        time.sleep(remaining)
    assert timezone.now() >= effective_until
    return str(published["risk_policy_version"])


@pytest.mark.parametrize(
    ("state", "expected_reason"),
    [
        ("qualified", None),
        ("source_changed", "M1_RISK_POLICY_SOURCE_CHANGED"),
        ("not_effective", "M1_RISK_POLICY_OUTSIDE_EFFECTIVE_WINDOW"),
    ],
    ids=["current", "changed-source", "real-clock-expired"],
)
def test_public_sdk_ordinary_preview_preserves_policy_qualification(
    _public_runtime: _PublicRuntime,
    record_property: Callable[[str, object], None],
    state: str,
    expected_reason: str | None,
) -> None:
    """The normal SDK method exposes qualification and blocks stale policy BUYs."""
    case = _public_runtime.owner_case
    version = case.owner_revision
    if state == "source_changed":
        case.account.max_position_pct = 18.0
        case.account.save(update_fields=["max_position_pct"])
    elif state == "not_effective":
        version = _publish_short_lived_revision(_public_runtime)
    before = owner_case._financial_snapshot()
    reports_before = owner_case.DailyInspectionReportModel.objects.filter(
        account_id=case.account.pk
    ).count()
    proposals_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=case.account.pk
    ).count()

    result = _public_runtime.sdk_client.simulated_trading.run_daily_inspection(
        account_id=case.account.pk,
        strategy_id=case.strategy.pk,
        inspection_date=timezone.localdate(),
        auto_create_proposal=False,
    )

    assert result["success"] is True
    plan = result["reports"][0]["plan"]
    context = plan["risk_context"]
    assert context["risk_policy_version"] == version
    assert context["risk_policy_qualification_status"] == state
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    buy = next(row for row in plan["asset_items"] if row["asset_code"] == owner_case.ASSET_BUY)
    if expected_reason is None:
        assert buy["status"] == "ready"
        assert Decimal(str(buy["actionable_quantity"])) > 0
    else:
        assert buy["status"] == "blocked"
        assert buy["actionable_quantity"] is None
        assert buy["actionable_amount"] is None
        assert expected_reason in buy["reason_codes"]
        assert expected_reason in context["risk_policy_reason_codes"]
    owner_case._assert_no_financial_writes(
        before=before,
        account=case.account,
        report_count_before=reports_before,
        proposal_count_before=proposals_before,
    )
    inspection = next(
        item
        for item in _public_runtime.trace.exchanges
        if item.path == _inspection_path(case.account.pk)
    )
    assert inspection.status == 200
    assert inspection.content_type.startswith("application/json")
    _assert_owner_http_identity(_public_runtime.trace)
    record_property(
        "ref03_sdk_ordinary_qualification",
        json.dumps(
            {
                "http": [_http_evidence(item) for item in _public_runtime.trace.exchanges],
                "plan": _mcp_plan_summary({"result": result}),
                "reason_codes": buy["reason_codes"],
            },
            sort_keys=True,
        ),
    )
