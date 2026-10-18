"""Real local-browser journeys for facts-first broker trade import.

These candidates use the actual TUI screen, action endpoints and local database.
They do not call market-data providers or any broker/order execution endpoint.
They are not production or human-acceptance evidence until run in the approved
loopback-only browser environment.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import traceback
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from playwright.sync_api import Page, Response, Route, expect, sync_playwright

from apps.account.infrastructure import models as account_models
from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CurrencyModel,
    PortfolioModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.simulated_trading.infrastructure import models as ledger_models
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedTradeModel,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)

SCREEN = "execution.audit"
PREVIEW_ACTION = "audit.manual-trade-import-preview"
IMPORT_ACTION = "audit.manual-trade-import"
ACTION_PATH_PREFIX = "/api/tui/actions/"


@dataclass(frozen=True)
class BrokerImportBook:
    """Explicit owner, asset, account and source-to-target map for the journey."""

    owner: Any
    portfolio: PortfolioModel
    legacy_position: account_models.PositionModel
    unified_position: ledger_models.PositionModel
    asset_code: str


@dataclass(frozen=True)
class BrokerImportState:
    """Committed database observations returned outside Playwright's event loop."""

    quantity: Decimal
    fact_states: tuple[str, ...]
    mirror_count: int
    cash: Decimal
    auto_trading_enabled: bool


def _read_book_state(book: BrokerImportBook) -> BrokerImportState:
    """Read genuine committed rows in a synchronous thread with its own connection."""

    def read() -> BrokerImportState:
        """Observe current facts and ledger state without an async safety bypass."""
        connections.close_all()
        try:
            position = ledger_models.PositionModel._default_manager.select_related("account").get(
                pk=book.unified_position.pk
            )
            return BrokerImportState(
                quantity=position.quantity,
                fact_states=tuple(
                    TransactionModel._default_manager.filter(portfolio_id=book.portfolio.pk)
                    .order_by("pk")
                    .values_list("broker_reconciliation_state", flat=True)
                ),
                mirror_count=SimulatedTradeModel._default_manager.filter(
                    account_id=position.account_id
                ).count(),
                cash=position.account.current_cash,
                auto_trading_enabled=position.account.auto_trading_enabled,
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(read).result()


def _action_path(action_key: str) -> str:
    """Return one TUI action route path."""

    return f"{ACTION_PATH_PREFIX}{action_key}/run/"


def _session_cookie(user: Any) -> str:
    """Create a real Django session cookie for the headless browser."""

    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _action_result(response: Response) -> dict[str, Any]:
    """Decode a real TUI action envelope and check its transport contract."""

    assert response.headers.get("content-type", "").split(";", 1)[0] == "application/json"
    result = response.json()
    assert isinstance(result, dict)
    return result


def _owner_status(result: dict[str, Any]) -> int:
    """Read the owner endpoint status retained inside the TUI response."""

    owner_response = result.get("response")
    assert isinstance(owner_response, dict)
    status_code = owner_response.get("status_code")
    assert isinstance(status_code, int)
    return status_code


def _view_model(result: dict[str, Any]) -> dict[str, Any]:
    """Return the actual rendered view-model payload."""

    value = result.get("view_model")
    assert isinstance(value, dict)
    return value


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Apply the repository's subprocess event-loop policy for Windows Chromium."""

    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fence Python sockets to loopback so this browser journey cannot reach providers."""

    attempts: list[dict[str, object]] = []
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def is_local_host(host: object) -> bool:
        if host is None:
            return True
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="ignore")
        if not isinstance(host, str):
            return False
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def host_from_address(address: object) -> object | None:
        return address[0] if isinstance(address, tuple) and address else None

    def blocked(kind: str, host: object) -> None:
        project_root = Path(settings.BASE_DIR).resolve()
        frames = []
        for frame in traceback.extract_stack():
            filename = Path(frame.filename).resolve()
            if filename.is_relative_to(project_root):
                relative = filename.relative_to(project_root).as_posix()
                if not relative.startswith("agomtradepro/"):
                    frames.append({"path": relative, "line": frame.lineno, "function": frame.name})
        attempts.append({"kind": kind, "host": str(host), "project_stack": frames})
        raise AssertionError(f"browser journey attempted external network: {kind}:{host!r}")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        host = host_from_address(address)
        if not is_local_host(host):
            blocked("connect", host)
        return original_connect(sock, address)

    def guarded_create_connection(
        address: object, *args: object, **kwargs: object
    ) -> socket.socket:
        host = host_from_address(address)
        if not is_local_host(host):
            blocked("create_connection", host)
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not is_local_host(host):
            blocked("getaddrinfo", host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield
    if attempts:
        evidence = Path(settings.BASE_DIR) / ".tmp/ash03-broker-browser-network"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f"{uuid4().hex}.json").write_text(
            json.dumps(attempts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    assert attempts == []


@pytest.fixture
def broker_import_book(django_user_model: Any) -> BrokerImportBook:
    """Create real local metadata plus strict portfolio and position mappings."""

    suffix = uuid4().hex[:10]
    owner = django_user_model.objects.create_user(
        username=f"broker-import-browser-{suffix}",
        password="local-browser-test-only",
        is_staff=False,
    )
    profile, _created = AccountProfileModel._default_manager.get_or_create(
        user=owner,
        defaults={"display_name": "本地成交导入浏览器测试", "rbac_role": "owner"},
    )
    if profile.rbac_role != "owner":
        profile.rbac_role = "owner"
        profile.save(update_fields=["rbac_role"])

    currency, _created = CurrencyModel._default_manager.get_or_create(
        code="CNY",
        defaults={"name": "人民币", "symbol": "¥", "is_base": True},
    )
    category, _created = AssetCategoryModel._default_manager.get_or_create(
        code="equity",
        defaults={"name": "股票", "level": 1, "path": "股票"},
    )
    asset_number = 1 + (uuid4().int % 999_999)
    asset_code = f"{asset_number:06d}.SZ"
    asset = AssetMetadataModel._default_manager.create(
        asset_code=asset_code,
        name="本地浏览器测试证券",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
    )
    portfolio = PortfolioModel._default_manager.create(
        user=owner,
        name=f"本地成交导入组合-{suffix}",
        base_currency=currency,
        is_active=True,
    )

    bridge = PortfolioApiRepository()
    account_id = bridge.ensure_real_account(portfolio)
    unified_position = ledger_models.PositionModel._default_manager.create(
        account_id=account_id,
        asset_code=asset.asset_code,
        asset_name=asset.name,
        asset_type="equity",
        quantity=Decimal("25"),
        available_quantity=Decimal("0"),
        available_quantity_known=False,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("250.00"),
        current_price=Decimal("12.0000"),
        market_value=Decimal("0.00"),
        valuation_known=False,
        first_buy_date=date(2020, 1, 2),
        first_buy_date_known=False,
        entry_reason="本地测试余额，不代表券商可卖数量",
    )
    legacy_position = bridge.upsert_legacy_projection_from_unified(
        unified_position=unified_position,
        portfolio=portfolio,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        category=category,
        currency=currency,
    )
    assert legacy_position is not None
    assert LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account_id,
    ).exists()
    assert LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="position",
        source_id=legacy_position.pk,
        target_table="simulated_position",
        target_id=unified_position.pk,
    ).exists()
    account = unified_position.account
    assert account.account_type == "real"
    assert account.auto_trading_enabled is False
    return BrokerImportBook(
        owner=owner,
        portfolio=portfolio,
        legacy_position=legacy_position,
        unified_position=unified_position,
        asset_code=asset_code,
    )


@pytest.fixture
def local_browser(
    live_server: Any,
    broker_import_book: BrokerImportBook,
    subprocess_policy: None,
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Page, list[tuple[str, str]], list[str]]]:
    """Open the actual TUI in a session-authenticated local headless browser."""

    requests: list[tuple[str, str]] = []
    page_errors: list[str] = []
    session_cookie = _session_cookie(broker_import_book.owner)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie,
                    "url": live_server.url,
                }
            ]
        )

        def enforce_local_origin(route: Route) -> None:
            """Abort nonlocal Chromium requests before any external transport."""
            if urlsplit(route.request.url).netloc != urlsplit(live_server.url).netloc:
                page_errors.append(f"Blocked nonlocal request: {route.request.url}")
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", enforce_local_origin)
        page = context.new_page()
        page.on(
            "request",
            lambda request: requests.append((request.method, request.url)),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.goto(f"{live_server.url}/tui/?screen={SCREEN}", wait_until="networkidle")
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            expect(page.locator('[data-experience-mode="professional"]')).to_have_attribute(
                "aria-selected", "true"
            )
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()
            yield page, requests, page_errors
        finally:
            evidence = Path(settings.BASE_DIR) / ".tmp/ash03-broker-browser-ui" / uuid4().hex[:12]
            evidence.mkdir(parents=True, exist_ok=False)
            if not page.is_closed():
                page.screenshot(path=str(evidence / "viewport.png"), full_page=False)
            (evidence / "requests.json").write_text(
                json.dumps(
                    {
                        "case": request.node.name,
                        "requests": requests,
                        "page_errors": page_errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            context.close()
            browser.close()


def _action_form(page: Page, action_key: str) -> Any:
    """Find a real rendered action form and expand its existing overflow group."""

    digest = sha1(action_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    form = page.locator(f'[data-actions-panel] form[data-action-ui-key="task-{digest}"]')
    assert form.count() == 1
    if not form.is_visible():
        details = form.locator("xpath=ancestor::details[1]")
        if details.count() == 1 and details.get_attribute("open") is None:
            details.locator(":scope > summary").click()
    expect(form).to_be_visible()
    return form


def _write_csv(tmp_path: Path, asset_code: str) -> Path:
    """Write one valid local A-share CSV; callers reselect this same file."""

    path = tmp_path / "manual-broker-trades.csv"
    external_id = f"browser-{uuid4().hex}"
    path.write_text(
        "traded_at,action,asset_code,shares,price,commission,stamp_duty,transfer_fee,external_trade_id\n"
        f"2024-05-20T10:11:12+08:00,buy,{asset_code},10,11.2500,1.23,,0.07,{external_id}\n",
        encoding="utf-8",
    )
    return path


def _assert_local_action_traffic(requests: list[tuple[str, str]], live_server: Any) -> None:
    """Require same-origin browser traffic and only the two import POST actions."""

    expected_netloc = urlsplit(live_server.url).netloc
    allowed_posts = {
        _action_path(PREVIEW_ACTION),
        _action_path(IMPORT_ACTION),
        _action_path("audit.health-summary"),
        _action_path("events.metric-summary"),
        _action_path("broker-execution.reconciliation-list"),
        _action_path("broker-execution.audit-list"),
    }
    for method, url in requests:
        parsed = urlsplit(url)
        assert parsed.netloc == expected_netloc
        if method == "POST":
            assert parsed.path in allowed_posts
    forbidden_path_tokens = ("market", "quote", "order")
    assert not any(
        any(token in urlsplit(url).path.lower() for token in forbidden_path_tokens)
        for _method, url in requests
    )


def _submit_preview(
    page: Page,
    live_server: Any,
    portfolio: PortfolioModel,
    csv_path: Path,
) -> tuple[Response, dict[str, Any]]:
    """Submit the visible preview action and return its real result envelope."""

    form = _action_form(page, PREVIEW_ACTION)
    form.locator('[name="portfolio_id"]').fill(str(portfolio.pk))
    form.locator('[name="file"]').set_input_files(str(csv_path))
    with page.expect_response(
        lambda response: urlsplit(response.url).path == _action_path(PREVIEW_ACTION)
    ) as response_info:
        form.locator(".tui-action-submit").click()
    response = response_info.value
    assert response.status == 200
    result = _action_result(response)
    assert _owner_status(result) == 200
    preview_rows = _view_model(result).get("rows")
    assert isinstance(preview_rows, list) and preview_rows
    assert any(isinstance(row, dict) and row.get("asset_code") for row in preview_rows)
    expect(page.locator("[data-result-continuation] button")).to_be_visible()
    return response, result


def _begin_import_confirmation(
    page: Page,
    portfolio: PortfolioModel,
    csv_path: Path,
    decision: str,
) -> Response:
    """Reselect the same CSV, choose its balance decision and open confirmation."""

    form = _action_form(page, IMPORT_ACTION)
    form.locator('[name="portfolio_id"]').fill(str(portfolio.pk))
    form.locator('[name="file"]').set_input_files(str(csv_path))
    form.locator('[name="baseline_decision"]').select_option(decision)
    with page.expect_response(
        lambda response: urlsplit(response.url).path == _action_path(IMPORT_ACTION)
    ) as response_info:
        page.locator("[data-result-continuation] button").click()
    preflight = response_info.value
    assert preflight.status == 200
    preflight_result = _action_result(preflight)
    assert preflight_result.get("confirmation_required") is True
    expect(page.locator("[data-confirm-action]")).to_be_visible()
    return preflight


def _confirm_import(page: Page) -> tuple[Response, dict[str, Any]]:
    """Click the real confirmation modal and return the actual import result."""

    with page.expect_response(
        lambda response: urlsplit(response.url).path == _action_path(IMPORT_ACTION)
    ) as response_info:
        page.locator("[data-confirm-action]").click()
    response = response_info.value
    assert response.status == 200
    return response, _action_result(response)


@pytest.mark.django_db(transaction=True)
def test_pending_browser_import_saves_fact_without_changing_balance(
    live_server: Any,
    broker_import_book: BrokerImportBook,
    local_browser: tuple[Page, list[tuple[str, str]], list[str]],
    tmp_path: Path,
) -> None:
    """Preview and pending-confirm the same CSV while leaving quantity unchanged."""

    page, requests, page_errors = local_browser
    book = broker_import_book
    csv_path = _write_csv(tmp_path, book.asset_code)
    assert _read_book_state(book).fact_states == ()

    _submit_preview(page, live_server, book.portfolio, csv_path)
    state = _read_book_state(book)
    assert state.quantity == Decimal("25")
    assert state.fact_states == ()

    _begin_import_confirmation(page, book.portfolio, csv_path, "pending")
    _response, result = _confirm_import(page)
    assert _owner_status(result) == 201
    state = _read_book_state(book)
    assert state.fact_states == ("awaiting_baseline",)
    assert state.quantity == Decimal("25")
    assert state.mirror_count == 0

    rows = _view_model(result).get("rows")
    assert isinstance(rows, list) and rows
    assert rows[0].get("row_number") == "汇总"
    assert "保存成交事实 1" in str(rows[0].get("summary", ""))
    assert "待核对 1" in str(rows[0].get("summary", ""))
    expect(page.locator("[data-main-panel]")).to_contain_text("保存成交事实 1")
    visible_text = page.locator("[data-main-panel]").inner_text()
    assert "导入汇总" in visible_text
    assert "保存成交事实 1" in visible_text
    _assert_local_action_traffic(requests, live_server)
    assert page_errors == []


@pytest.mark.django_db(transaction=True)
def test_excluded_browser_import_projects_only_after_explicit_confirmation(
    live_server: Any,
    broker_import_book: BrokerImportBook,
    local_browser: tuple[Page, list[tuple[str, str]], list[str]],
    tmp_path: Path,
) -> None:
    """An explicitly excluded fill changes the local economic quantity by its shares."""

    page, requests, page_errors = local_browser
    book = broker_import_book
    csv_path = _write_csv(tmp_path, book.asset_code)
    _submit_preview(page, live_server, book.portfolio, csv_path)
    assert _read_book_state(book).quantity == Decimal("25")

    _begin_import_confirmation(page, book.portfolio, csv_path, "excluded")
    _response, result = _confirm_import(page)
    assert _owner_status(result) == 201
    state = _read_book_state(book)
    assert state.fact_states == ("projected",)
    assert state.quantity == Decimal("35")
    assert state.mirror_count == 1
    assert state.cash == Decimal("0")
    assert state.auto_trading_enabled is False
    rows = _view_model(result).get("rows")
    assert isinstance(rows, list) and rows
    assert rows[0].get("row_number") == "汇总"
    assert "数量投影 1" in str(rows[0].get("summary", ""))
    _assert_local_action_traffic(requests, live_server)
    assert page_errors == []


@pytest.mark.django_db(transaction=True)
def test_included_browser_import_keeps_quantity_and_creates_no_mirror(
    live_server: Any,
    broker_import_book: BrokerImportBook,
    local_browser: tuple[Page, list[tuple[str, str]], list[str]],
    tmp_path: Path,
) -> None:
    """The real included-selection journey records a receipt without a second position."""

    page, requests, page_errors = local_browser
    book = broker_import_book
    csv_path = _write_csv(tmp_path, book.asset_code)
    _submit_preview(page, live_server, book.portfolio, csv_path)
    before = _read_book_state(book)
    assert before.quantity == Decimal("25")
    assert before.fact_states == ()
    assert before.mirror_count == 0

    _begin_import_confirmation(page, book.portfolio, csv_path, "included")
    _response, result = _confirm_import(page)
    assert _owner_status(result) == 201

    state = _read_book_state(book)
    assert state.fact_states == ("already_in_baseline",)
    assert state.quantity == Decimal("25")
    assert state.mirror_count == 0
    assert state.cash == Decimal("0")
    assert state.auto_trading_enabled is False

    rows = _view_model(result).get("rows")
    assert isinstance(rows, list) and rows
    assert rows[0].get("row_number") == "汇总"
    summary = str(rows[0].get("summary", ""))
    assert "本次选择：已包含" in summary
    assert "保存成交事实 1" in summary
    assert "数量投影 0" in summary
    assert "已包含 1" in summary
    expect(page.locator("[data-main-panel]")).to_contain_text("本次选择：已包含")
    expect(page.locator("[data-main-panel]")).to_contain_text("数量投影 0")
    expect(page.locator("[data-main-panel]")).to_contain_text("已包含 1")
    _assert_local_action_traffic(requests, live_server)
    assert page_errors == []


@pytest.mark.django_db(transaction=True)
def test_balance_change_after_preview_keeps_saved_fact_and_requires_repreview(
    live_server: Any,
    broker_import_book: BrokerImportBook,
    local_browser: tuple[Page, list[tuple[str, str]], list[str]],
    tmp_path: Path,
) -> None:
    """A second committed balance change blocks stale projection but keeps its receipt."""

    page, requests, page_errors = local_browser
    book = broker_import_book
    csv_path = _write_csv(tmp_path, book.asset_code)
    _submit_preview(page, live_server, book.portfolio, csv_path)
    _begin_import_confirmation(page, book.portfolio, csv_path, "excluded")

    def mutate_balance_on_separate_connection() -> None:
        """Commit a real local balance change after preflight and before confirmation."""

        connections.close_all()
        try:
            unified_changed = ledger_models.PositionModel._default_manager.filter(
                pk=book.unified_position.pk
            ).update(
                quantity=Decimal("26"),
                total_cost=Decimal("260.00"),
                market_value=Decimal("0.00"),
            )
            legacy_changed = account_models.PositionModel._default_manager.filter(
                pk=book.legacy_position.pk
            ).update(shares=26.0)
            assert unified_changed == 1
            assert legacy_changed == 1
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(mutate_balance_on_separate_connection).result()

    _response, result = _confirm_import(page)
    assert _owner_status(result) == 409
    state = _read_book_state(book)
    assert state.fact_states == ("projection_blocked",)
    assert state.quantity == Decimal("26")
    assert state.mirror_count == 0

    rows = _view_model(result).get("rows")
    assert isinstance(rows, list) and rows
    assert rows[0].get("row_number") == "汇总"
    assert "保存成交事实 1" in str(rows[0].get("summary", ""))
    expect(page.locator("[data-main-panel]")).to_contain_text("请重新预览并重新确认")
    visible_text = page.locator("[data-main-panel]").inner_text()
    assert "成交事实已保存" in visible_text
    assert "本地余额已变化" in visible_text
    assert "请重新预览并重新确认" in visible_text
    assert page.locator("[data-action-submission-retry]").count() == 0
    import_posts = [
        urlsplit(url).path
        for method, url in requests
        if method == "POST" and urlsplit(url).path == _action_path(IMPORT_ACTION)
    ]
    assert len(import_posts) == 2  # unconfirmed preflight and one confirmed submission
    _assert_local_action_traffic(requests, live_server)
    assert page_errors == []
