"""Real HTTP checks for C3c account-import outcomes and confirmation replay."""

from __future__ import annotations

import copy
import importlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import override
from rest_framework.exceptions import NotFound

from apps.account.infrastructure.portfolio_models import (
    CapitalFlowModel,
    PortfolioModel,
    TransactionModel,
)
from tests.component.account.test_c3b_capital_flow_import_http import (
    _dispatcher_for_mode as _dispatcher_for_mode,
)
from tests.component.account.test_transaction_fee_mcp_http_journey import _Exchange as _Exchange
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

Ledger = Literal["transactions", "capital_flows"]
Fault = Literal["post_commit_503", "empty_201", "malformed_201", "timeout_after_commit"]

TRANSACTION_PATH = "/api/account/transactions/"
CAPITAL_FLOW_PATH = "/api/account/capital-flows/"
FLOW_DATE = "2026-09-19"


def _create_path(ledger: Ledger) -> str:
    """Return the real create endpoint selected by the import capability."""
    return TRANSACTION_PATH if ledger == "transactions" else CAPITAL_FLOW_PATH


def _import_arguments(
    ledger: Ledger,
    portfolio_id: int,
    rows: list[dict[str, Any]],
    idempotency_key: str,
) -> dict[str, Any]:
    """Build one explicit append request without relying on date defaults."""
    row_argument = "transactions" if ledger == "transactions" else "capital_flows"
    return {
        "portfolio_id": portfolio_id,
        row_argument: rows,
        "mode": "append",
        "idempotency_key": idempotency_key,
    }


def _transaction_row(
    asset_code: str,
    notes: str,
    *,
    commission: str | None = None,
) -> dict[str, Any]:
    """Return a valid transaction row with a fixed explicit timestamp."""
    row: dict[str, Any] = {
        "action": "buy",
        "asset_code": asset_code,
        "shares": "10",
        "price": "9.50",
        "traded_at": (datetime.now(UTC) - timedelta(minutes=2)).replace(microsecond=0).isoformat(),
        "notes": notes,
    }
    if commission is not None:
        row["commission"] = commission
    return row


def _capital_flow_row(notes: str, amount: str = "123.45") -> dict[str, Any]:
    """Return a valid capital-flow row with an explicit calendar date."""
    return {
        "flow_type": "deposit",
        "amount": amount,
        "flow_date": FLOW_DATE,
        "notes": notes,
    }


def _row_identifiers(ledger: Ledger, rows: list[dict[str, Any]]) -> list[str]:
    """Extract the stable unique row keys used only for test-side DB queries."""
    key = "asset_code" if ledger == "transactions" else "notes"
    return [str(row[key]) for row in rows]


def _stored_rows(
    ledger: Ledger,
    portfolio: PortfolioModel,
    identifiers: list[str],
) -> list[tuple[Any, ...]]:
    """Read persisted rows by stable request identity and include their primary keys."""
    if ledger == "transactions":
        return list(
            TransactionModel.objects.filter(
                portfolio=portfolio,
                asset_code__in=identifiers,
            )
            .order_by("pk")
            .values_list(
                "pk",
                "asset_code",
                "action",
                "shares",
                "price",
                "traded_at",
                "notes",
            )
        )
    return list(
        CapitalFlowModel.objects.filter(
            portfolio=portfolio,
            notes__in=identifiers,
        )
        .order_by("pk")
        .values_list(
            "pk",
            "portfolio_id",
            "user_id",
            "flow_type",
            "amount",
            "flow_date",
            "notes",
        )
    )


def _stored_ids(
    ledger: Ledger,
    portfolio: PortfolioModel,
    identifiers: list[str],
) -> list[int]:
    """Return only persisted IDs for the post-commit fault observation."""
    return [int(row[0]) for row in _stored_rows(ledger, portfolio, identifiers)]


def _create_posts(
    log: _HttpLog,
    start: int,
    ledger: Ledger,
) -> list[_Exchange]:
    """Return logged real HTTP create calls for one endpoint."""
    path = _create_path(ledger)
    return [
        exchange
        for exchange in log.exchanges[start:]
        if exchange["method"] == "POST" and exchange["path"] == path
    ]


def _assert_summary(
    summary: dict[str, Any],
    *,
    requested: int,
    validated: int,
    attempted: int,
    succeeded: int,
    failed: int,
    unknown: int,
    unattempted: int,
    stored: int | None,
    creates: int,
    planned: int | None = None,
) -> None:
    """Check C3c counts without conflating preview candidates and confirmed writes."""
    expected: dict[str, int | None] = {
        "requested_count": requested,
        "validated_count": validated,
        "attempted_count": attempted,
        "succeeded_count": succeeded,
        "failed_count": failed,
        "unknown_count": unknown,
        "unattempted_count": unattempted,
        "stored_count": stored,
        "create_count": creates,
        "delete_count": 0,
    }
    if planned is not None:
        expected["planned_create_count"] = planned
    for field, value in expected.items():
        assert summary[field] == value, (field, summary)


def _assert_valid_preview(preview: dict[str, Any], row_count: int) -> None:
    """Require a no-write preview whose candidate count is explicitly planned."""
    assert preview["outcome"] == "noop"
    assert preview["success"] is True
    _assert_summary(
        preview["summary"],
        requested=row_count,
        validated=row_count,
        attempted=0,
        succeeded=0,
        failed=0,
        unknown=0,
        unattempted=0,
        stored=0,
        creates=0,
        planned=row_count,
    )


def _attach_safe_junit_observation(
    request: pytest.FixtureRequest,
    *,
    endpoint: str,
    log: _HttpLog,
    start: int,
    persisted_rows: list[tuple[Any, ...]],
    response: Any,
    injected: list[dict[str, Any]] | None = None,
) -> None:
    """Attach allowlisted HTTP/DB evidence without credentials or request bodies."""
    exchanges = [
        exchange
        for exchange in log.exchanges[start:]
        if exchange["path"] == endpoint or exchange["path"].startswith(endpoint)
    ]
    outer = response if isinstance(response, dict) else {}
    nested = outer.get("result")
    if not isinstance(nested, dict):
        nested = outer.get("preview_result")
    if not isinstance(nested, dict):
        nested = outer
    raw_outcome = nested.get("outcome")
    if not isinstance(raw_outcome, str):
        raw_outcome = outer.get("status")
    raw_summary = nested.get("summary")
    if not isinstance(raw_summary, dict):
        raw_summary = outer.get("summary")
    summary_fields = (
        "requested_count",
        "validated_count",
        "attempted_count",
        "succeeded_count",
        "failed_count",
        "unknown_count",
        "unattempted_count",
        "stored_count",
        "create_count",
        "planned_create_count",
        "delete_count",
        "error_count",
    )
    safe_summary = {
        field: raw_summary[field]
        for field in summary_fields
        if isinstance(raw_summary, dict)
        and field in raw_summary
        and (raw_summary[field] is None or type(raw_summary[field]) is int)
    }
    fault_evidence: list[dict[str, Any]] = []
    for item in injected or []:
        if not isinstance(item, dict):
            continue
        committed = item.get("persisted_ids_after_server_response")
        safe_ids = (
            [value for value in committed if type(value) is int]
            if isinstance(committed, list)
            else []
        )
        record: dict[str, Any] = {"committed_row_ids": safe_ids}
        fault = item.get("fault")
        if isinstance(fault, str):
            record["fault"] = fault
        server_status = item.get("server_status")
        if type(server_status) is int:
            record["server_status"] = server_status
        fault_evidence.append(record)
    persisted_ids = [int(row[0]) for row in persisted_rows if row and type(row[0]) is int]
    observation = {
        "endpoint": endpoint,
        "requests": [
            {"method": exchange["method"], "status": exchange["status"]} for exchange in exchanges
        ],
        "post_count": sum(exchange["method"] == "POST" for exchange in exchanges),
        "persisted_row_count": len(persisted_rows),
        "persisted_row_ids": persisted_ids,
        "returned_outcome": raw_outcome if isinstance(raw_outcome, str) else None,
        "returned_summary": safe_summary,
        "post_commit_faults": fault_evidence,
    }
    request.node.user_properties.append(
        (
            "c3c_safe_http_observation",
            json.dumps(observation, sort_keys=True, separators=(",", ":")),
        )
    )


def _install_post_commit_fault(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ledger: Ledger,
    fault: Fault,
    persisted_ids: Callable[[], list[int]],
) -> list[dict[str, Any]]:
    """Alter the client response only after the real server returns and persists 201."""
    original_request = requests.Session.request
    evidence: list[dict[str, Any]] = []
    target_path = _create_path(ledger)

    def faulting_request(
        session: requests.Session,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Observe a real local response, then inject one client-side post-commit fault."""
        response = original_request(session, method, url, **kwargs)
        parsed = urlsplit(str(url))
        if method.upper() != "POST" or parsed.path != target_path or evidence:
            return response

        evidence.append(
            {
                "fault": fault,
                "server_status": response.status_code,
                "server_content_type": response.headers.get("Content-Type", ""),
                "persisted_ids_after_server_response": persisted_ids(),
            }
        )
        if fault == "post_commit_503":
            response.status_code = 503
            response.reason = "Service Unavailable"
            response._content = b'{"code":"INJECTED_POST_COMMIT_503"}'
            response._content_consumed = True
        elif fault == "empty_201":
            response._content = b""
            response._content_consumed = True
        elif fault == "malformed_201":
            response._content = b'{"unexpected":"receipt"}'
            response._content_consumed = True
        else:
            raise requests.Timeout("Injected response loss after the real local 201.")
        return response

    monkeypatch.setattr(requests.Session, "request", faulting_request)
    return evidence


def _assert_create_receipt(ledger: Ledger, event: dict[str, Any], portfolio_id: int) -> None:
    """Assert the actual endpoint receipt fields, without assuming a returned row ID."""
    assert event["status"] == 201
    assert event["content_type"].startswith("application/json")
    receipt = event["response_json"]
    assert isinstance(receipt, dict)
    assert "id" not in receipt
    if ledger == "transactions":
        assert {
            "portfolio",
            "action",
            "asset_code",
            "shares",
            "price",
            "traded_at",
        } <= receipt.keys()
        assert receipt["portfolio"] == portfolio_id
    else:
        assert {"flow_type", "amount", "flow_date", "notes"} <= receipt.keys()
        assert "portfolio" not in receipt


@pytest.mark.parametrize("ledger", ["transactions", "capital_flows"], ids=["trades", "flows"])
@pytest.mark.parametrize("legacy_tools", [False, True], ids=["owner-fallback", "registered"])
def test_confirmed_success_counts_only_validated_server_receipts(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    ledger: Ledger,
    legacy_tools: bool,
) -> None:
    """Both dispatch routes count one confirmed real 201 and never require a response ID."""
    portfolio, _raw_token = live_owner_account
    identifier = "C3COK01.SZ" if ledger == "transactions" else "C3c success receipt"
    rows = (
        [_transaction_row(identifier, "C3c transaction success")]
        if ledger == "transactions"
        else [_capital_flow_row(identifier)]
    )
    identifiers = _row_identifiers(ledger, rows)
    dispatcher, _server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=legacy_tools,
    )
    arguments = _import_arguments(
        ledger,
        int(portfolio.pk),
        rows,
        f"c3c-success-{ledger}-{legacy_tools}",
    )
    start = len(exact_origin_http_log.exchanges)
    before_rows = _stored_rows(ledger, portfolio, identifiers)

    staged = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=arguments,
    )
    preview = staged["preview_result"]
    preview_posts = _create_posts(exact_origin_http_log, start, ledger)
    before_confirmation_rows = _stored_rows(ledger, portfolio, identifiers)

    completed = dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    posts = _create_posts(exact_origin_http_log, start, ledger)
    persisted_rows = _stored_rows(ledger, portfolio, identifiers)
    _attach_safe_junit_observation(
        request,
        endpoint=_create_path(ledger),
        log=exact_origin_http_log,
        start=start,
        persisted_rows=persisted_rows,
        response=completed,
    )

    assert before_rows == []
    assert staged["status"] == "confirmation_required"
    assert staged["idempotency_key"] == arguments["idempotency_key"]
    _assert_valid_preview(preview, 1)
    assert preview_posts == []
    assert before_confirmation_rows == []
    assert completed["status"] == "completed"
    assert completed["ok"] is True
    result = completed["result"]
    assert result["outcome"] == "success"
    assert result["success"] is True
    _assert_summary(
        result["summary"],
        requested=1,
        validated=1,
        attempted=1,
        succeeded=1,
        failed=0,
        unknown=0,
        unattempted=0,
        stored=1,
        creates=1,
    )
    assert len(posts) == 1
    _assert_create_receipt(ledger, posts[0], int(portfolio.pk))
    assert len(persisted_rows) == 1
    assert persisted_rows[0][0] > 0

    request_json = posts[0]["request_json"]
    assert isinstance(request_json, dict)
    assert request_json["portfolio"] == int(portfolio.pk)
    if ledger == "transactions":
        row = rows[0]
        assert request_json["asset_code"] == row["asset_code"]
        assert request_json["action"] == "buy"
        assert Decimal(str(request_json["price"])) == Decimal("9.50")
        assert request_json["notes"] == row["notes"]
        receipt = posts[0]["response_json"]
        assert isinstance(receipt, dict)
        assert receipt["asset_code"] == row["asset_code"]
        assert Decimal(str(receipt["price"])) == Decimal("9.50")
        assert float(receipt["shares"]) == 10.0
        receipt_time = datetime.fromisoformat(str(receipt["traded_at"]).replace("Z", "+00:00"))
        assert receipt_time == datetime.fromisoformat(str(row["traded_at"]))
        assert receipt["notes"] == row["notes"]
        assert persisted_rows[0][1] == row["asset_code"]
        assert persisted_rows[0][2] == "buy"
        assert Decimal(str(persisted_rows[0][4])) == Decimal("9.50")
    else:
        row = rows[0]
        assert request_json["flow_type"] == row["flow_type"]
        assert Decimal(str(request_json["amount"])) == Decimal("123.45")
        assert request_json["flow_date"] == FLOW_DATE
        assert request_json["notes"] == row["notes"]
        receipt = posts[0]["response_json"]
        assert isinstance(receipt, dict)
        assert receipt["flow_type"] == "deposit"
        assert Decimal(str(receipt["amount"])) == Decimal("123.45")
        assert receipt["flow_date"] == FLOW_DATE
        assert receipt["notes"] == row["notes"]
        assert persisted_rows[0][1] == int(portfolio.pk)
        assert persisted_rows[0][2] == portfolio.user_id
        assert Decimal(str(persisted_rows[0][4])) == Decimal("123.45")
        assert persisted_rows[0][5].isoformat() == FLOW_DATE

    replay = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=copy.deepcopy(arguments),
    )
    posts_after_replay = _create_posts(exact_origin_http_log, start, ledger)
    persisted_after_replay = _stored_rows(ledger, portfolio, identifiers)
    changed_arguments = copy.deepcopy(arguments)
    row_argument = "transactions" if ledger == "transactions" else "capital_flows"
    changed_arguments[row_argument][0]["notes"] += " changed"
    conflict = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=changed_arguments,
    )
    posts_after_conflict = _create_posts(exact_origin_http_log, start, ledger)
    persisted_after_conflict = _stored_rows(ledger, portfolio, identifiers)

    assert replay["status"] == "idempotent_replay"
    assert replay["idempotency_reused"] is True
    assert replay["result"] == result
    assert conflict["status"] == "error"
    assert conflict["error"]["code"] == "idempotency_key_conflict"
    assert posts_after_replay == posts
    assert len(posts_after_replay) == len(posts) == 1
    assert persisted_after_replay == persisted_rows
    assert len(persisted_after_replay) == len(persisted_rows) == 1
    assert posts_after_conflict == posts
    assert len(posts_after_conflict) == len(posts) == 1
    assert persisted_after_conflict == persisted_rows
    assert len(persisted_after_conflict) == len(persisted_rows) == 1


_UNKNOWN_CASES: tuple[tuple[Ledger, Fault, bool], ...] = (
    ("transactions", "post_commit_503", False),
    ("transactions", "empty_201", True),
    ("transactions", "malformed_201", False),
    ("transactions", "timeout_after_commit", True),
    ("capital_flows", "post_commit_503", True),
    ("capital_flows", "empty_201", False),
    ("capital_flows", "malformed_201", True),
    ("capital_flows", "timeout_after_commit", False),
)


@pytest.mark.parametrize(
    ("ledger", "fault", "legacy_tools"),
    _UNKNOWN_CASES,
    ids=[
        "trades-503-fallback",
        "trades-empty201-registered",
        "trades-malformed201-fallback",
        "trades-timeout-registered",
        "flows-503-registered",
        "flows-empty201-fallback",
        "flows-malformed201-registered",
        "flows-timeout-fallback",
    ],
)
def test_ambiguous_post_commit_result_stops_and_replays_same_key(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    ledger: Ledger,
    fault: Fault,
    legacy_tools: bool,
) -> None:
    """A committed row with an altered client response remains unknown and is not replayed."""
    portfolio, _raw_token = live_owner_account
    if ledger == "transactions":
        rows = [
            _transaction_row("C3CUN1.SZ", "C3c unknown first"),
            _transaction_row("C3CUN2.SZ", "C3c unknown unattempted"),
        ]
    else:
        rows = [
            _capital_flow_row("C3c unknown first"),
            _capital_flow_row("C3c unknown unattempted", "234.56"),
        ]
    identifiers = _row_identifiers(ledger, rows)
    dispatcher, _server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=legacy_tools,
    )
    arguments = _import_arguments(
        ledger,
        int(portfolio.pk),
        rows,
        f"c3c-unknown-{ledger}-{fault}-{legacy_tools}",
    )
    start = len(exact_origin_http_log.exchanges)
    before_rows = _stored_rows(ledger, portfolio, identifiers)
    injected = _install_post_commit_fault(
        monkeypatch,
        ledger=ledger,
        fault=fault,
        persisted_ids=lambda: _stored_ids(ledger, portfolio, identifiers),
    )

    staged = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=arguments,
    )
    preview = staged["preview_result"]
    preview_posts = _create_posts(exact_origin_http_log, start, ledger)
    completed = dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    posts = _create_posts(exact_origin_http_log, start, ledger)
    persisted_rows = _stored_rows(ledger, portfolio, identifiers)
    replay = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=copy.deepcopy(arguments),
    )
    changed_arguments = copy.deepcopy(arguments)
    row_argument = "transactions" if ledger == "transactions" else "capital_flows"
    changed_arguments[row_argument][0]["notes"] += " changed"
    conflict = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=changed_arguments,
    )
    posts_after_replay = _create_posts(exact_origin_http_log, start, ledger)
    persisted_after_replay = _stored_rows(ledger, portfolio, identifiers)
    _attach_safe_junit_observation(
        request,
        endpoint=_create_path(ledger),
        log=exact_origin_http_log,
        start=start,
        persisted_rows=persisted_rows,
        response=completed,
        injected=injected,
    )

    assert before_rows == []
    assert staged["status"] == "confirmation_required"
    _assert_valid_preview(preview, 2)
    assert preview_posts == []
    assert completed["status"] == "completed"
    assert completed["ok"] is True
    result = completed["result"]
    assert result["outcome"] == "unknown"
    assert result["success"] is False
    _assert_summary(
        result["summary"],
        requested=2,
        validated=2,
        attempted=1,
        succeeded=0,
        failed=0,
        unknown=1,
        unattempted=1,
        stored=None,
        creates=0,
    )
    assert result["summary"]["error_count"] == 1
    assert len(injected) == 1
    assert injected[0]["fault"] == fault
    assert injected[0]["server_status"] == 201
    assert injected[0]["server_content_type"].startswith("application/json")
    assert len(injected[0]["persisted_ids_after_server_response"]) == 1
    assert len(posts) == 1
    _assert_create_receipt(ledger, posts[0], int(portfolio.pk))
    assert len(persisted_rows) == 1
    assert persisted_rows[0][0] == injected[0]["persisted_ids_after_server_response"][0]
    assert persisted_rows == persisted_after_replay
    assert posts_after_replay == posts
    assert replay["status"] == "idempotent_replay"
    assert replay["idempotency_reused"] is True
    assert replay["result"] == result
    assert conflict["status"] == "error"
    assert conflict["error"]["code"] == "idempotency_key_conflict"
    assert _stored_rows(ledger, portfolio, [identifiers[1]]) == []
    first_row = rows[0]
    first_request = posts[0]["request_json"]
    assert isinstance(first_request, dict)
    if ledger == "transactions":
        assert first_request["asset_code"] == first_row["asset_code"]
        assert persisted_rows[0][1] == first_row["asset_code"]
        assert persisted_rows[0][6] == first_row["notes"]
    else:
        assert first_request["notes"] == first_row["notes"]
        assert persisted_rows[0][6] == first_row["notes"]


@pytest.mark.parametrize(
    ("ledger", "legacy_tools"),
    [("transactions", False), ("capital_flows", True)],
    ids=["transaction-validation-fallback", "capital-flow-validation-registered"],
)
def test_known_real_validation_400_is_failed_and_later_valid_row_is_stored(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    ledger: Ledger,
    legacy_tools: bool,
) -> None:
    """Only the actual recognized pre-save validation envelope is a known rejection."""
    portfolio, _raw_token = live_owner_account
    if ledger == "transactions":
        rows = [
            _transaction_row("C3CBAD1.SZ", "C3c invalid precision", commission="0.001"),
            _transaction_row("C3COK02.SZ", "C3c valid after validation"),
        ]
    else:
        rows = [
            _capital_flow_row("C3c invalid amount", "1000000000000000000000.00"),
            _capital_flow_row("C3c valid after amount rejection", "234.56"),
        ]
    identifiers = _row_identifiers(ledger, rows)
    dispatcher, _server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=legacy_tools,
    )
    arguments = _import_arguments(
        ledger,
        int(portfolio.pk),
        rows,
        f"c3c-known-400-{ledger}",
    )
    start = len(exact_origin_http_log.exchanges)
    staged = dispatcher.call(
        capability_key=f"account.import.{ledger}",
        arguments=arguments,
    )
    preview = staged["preview_result"]
    preview_posts = _create_posts(exact_origin_http_log, start, ledger)
    completed = dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    posts = _create_posts(exact_origin_http_log, start, ledger)
    persisted_rows = _stored_rows(ledger, portfolio, identifiers)
    _attach_safe_junit_observation(
        request,
        endpoint=_create_path(ledger),
        log=exact_origin_http_log,
        start=start,
        persisted_rows=persisted_rows,
        response=completed,
    )

    assert staged["status"] == "confirmation_required"
    _assert_valid_preview(preview, 2)
    assert preview_posts == []
    assert completed["status"] == "completed"
    result = completed["result"]
    assert result["outcome"] == "partial"
    assert result["success"] is False
    _assert_summary(
        result["summary"],
        requested=2,
        validated=2,
        attempted=2,
        succeeded=1,
        failed=1,
        unknown=0,
        unattempted=0,
        stored=1,
        creates=1,
    )
    assert result["summary"]["error_count"] == 1
    assert [(row["method"], row["status"]) for row in posts] == [("POST", 400), ("POST", 201)]
    rejected_request = posts[0]["request_json"]
    successful_request = posts[1]["request_json"]
    assert isinstance(rejected_request, dict)
    assert isinstance(successful_request, dict)
    rejected_body = posts[0]["response_json"]
    assert isinstance(rejected_body, dict)
    assert set(rejected_body) == {"error", "code", "details"}
    assert rejected_body["code"] == "VALIDATION_ERROR"
    assert isinstance(rejected_body["details"], dict)
    if ledger == "transactions":
        assert "commission" in rejected_body["details"]
        assert rejected_request["commission"] == "0.001"
        assert len(persisted_rows) == 1
        assert persisted_rows[0][1] == "C3COK02.SZ"
        assert successful_request["asset_code"] == "C3COK02.SZ"
    else:
        assert "amount" in rejected_body["details"]
        assert float(rejected_request["amount"]) > 10**20
        assert len(persisted_rows) == 1
        assert persisted_rows[0][6] == "C3c valid after amount rejection"
        assert successful_request["notes"] == "C3c valid after amount rejection"


def test_foreign_capital_flow_portfolio_404_is_known_pre_save_failure(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
) -> None:
    """The real create view's owner-scoped 404 is counted failed with no stored row."""
    portfolio, _raw_token = live_owner_account
    foreign_user = get_user_model().objects.create_user(
        username="c3c_foreign_flow_owner",
        password="testpass123",
        email="c3c-foreign-flow-owner@example.com",
    )
    foreign_portfolio = PortfolioModel.objects.create(
        user=foreign_user,
        name="C3c foreign portfolio",
    )
    rows = [_capital_flow_row("C3c foreign owner rejection")]
    dispatcher, _server_module = _dispatcher_for_mode(
        mcp_runtime,
        monkeypatch,
        request,
        legacy_tools=False,
    )
    arguments = _import_arguments(
        "capital_flows",
        int(foreign_portfolio.pk),
        rows,
        "c3c-capital-flow-owner-404",
    )
    start = len(exact_origin_http_log.exchanges)
    staged = dispatcher.call(
        capability_key="account.import.capital_flows",
        arguments=arguments,
    )
    preview = staged["preview_result"]
    preview_posts = _create_posts(exact_origin_http_log, start, "capital_flows")
    completed = dispatcher.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )
    posts = _create_posts(exact_origin_http_log, start, "capital_flows")
    foreign_rows = list(
        CapitalFlowModel.objects.filter(portfolio=foreign_portfolio).values_list("pk", "notes")
    )
    owner_rows = list(
        CapitalFlowModel.objects.filter(
            portfolio=portfolio, notes="C3c foreign owner rejection"
        ).values_list("pk", "notes")
    )
    _attach_safe_junit_observation(
        request,
        endpoint=CAPITAL_FLOW_PATH,
        log=exact_origin_http_log,
        start=start,
        persisted_rows=foreign_rows + owner_rows,
        response=completed,
    )

    assert staged["status"] == "confirmation_required"
    _assert_valid_preview(preview, 1)
    assert preview_posts == []
    assert completed["status"] == "completed"
    result = completed["result"]
    assert result["outcome"] == "failed"
    assert result["success"] is False
    _assert_summary(
        result["summary"],
        requested=1,
        validated=1,
        attempted=1,
        succeeded=0,
        failed=1,
        unknown=0,
        unattempted=0,
        stored=0,
        creates=0,
    )
    assert result["summary"]["error_count"] == 1
    assert len(posts) == 1
    assert posts[0]["method"] == "POST"
    assert posts[0]["status"] == 404
    assert posts[0]["content_type"].startswith("application/json")
    request_json = posts[0]["request_json"]
    assert isinstance(request_json, dict)
    assert request_json["portfolio"] == int(foreign_portfolio.pk)
    with override(settings.LANGUAGE_CODE):
        expected_not_found_message = str(NotFound.default_detail)
    assert posts[0]["response_json"] == {
        "error": expected_not_found_message,
        "code": "API_ERROR",
    }
    assert foreign_rows == []
    assert owner_rows == []


@pytest.mark.parametrize("legacy_tools", [False, True], ids=["owner-fallback", "registered"])
def test_unsupported_capital_flow_mode_is_rejected_before_client_confirmation_or_http(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    live_owner_account: tuple[PortfolioModel, str],
    mcp_runtime: _McpRuntime,
    exact_origin_http_log: _HttpLog,
    legacy_tools: bool,
) -> None:
    """Both real dispatch routes reject unsupported modes before staging or ledger I/O."""
    portfolio, _raw_token = live_owner_account
    rows = [_capital_flow_row(f"C3c unsupported mode {legacy_tools}")]
    arguments = _import_arguments(
        "capital_flows",
        int(portfolio.pk),
        rows,
        f"c3c-unsupported-mode-{legacy_tools}",
    )
    arguments["mode"] = "unsupported"
    before_rows = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list("pk", "portfolio_id", "user_id", "flow_type", "amount", "flow_date", "notes")
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
        arguments=arguments,
    )
    after_rows = list(
        CapitalFlowModel.objects.filter(portfolio=portfolio)
        .order_by("pk")
        .values_list("pk", "portfolio_id", "user_id", "flow_type", "amount", "flow_date", "notes")
    )
    _attach_safe_junit_observation(
        request,
        endpoint=CAPITAL_FLOW_PATH,
        log=exact_origin_http_log,
        start=start,
        persisted_rows=after_rows,
        response=result,
    )

    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["capability_key"] == "account.import.capital_flows"
    assert "confirmation_token" not in result
    assert "preview_result" not in result
    error = result["error"]
    assert isinstance(error, dict)
    assert error["code"] == "capital_flow_import_append_only"
    assert error["upstream_status_code"] is None

    api_error = importlib.import_module("agomtradepro.exceptions").AgomTradeProAPIError
    if legacy_tools:
        assert server_module is not None
        direct_importer = server_module.server._tool_manager._tools["import_capital_flows_json"].fn
        with pytest.raises(api_error) as caught:
            direct_importer(
                int(portfolio.pk),
                rows,
                mode="unsupported",
                dry_run=True,
                idempotency_key=arguments["idempotency_key"],
            )
    else:
        owner_module = importlib.import_module(
            "agomtradepro_mcp.registry.runtime_handlers.owners.account"
        )
        with pytest.raises(api_error) as caught:
            owner_module._fallback_import_capital_flows_json(
                int(portfolio.pk),
                rows,
                mode="unsupported",
                dry_run=True,
                idempotency_key=arguments["idempotency_key"],
            )

    assert caught.value.status_code is None
    assert caught.value.response is not None
    assert caught.value.response["code"] == "capital_flow_import_append_only"
    assert caught.value.response["origin"] == "client_validation"
    assert error["code"] == caught.value.response["code"]
    factory.assert_not_called()
    ledger_requests = [
        exchange
        for exchange in exact_origin_http_log.exchanges[start:]
        if exchange["path"] == CAPITAL_FLOW_PATH or exchange["path"].startswith(CAPITAL_FLOW_PATH)
    ]
    assert ledger_requests == []
    assert after_rows == before_rows
