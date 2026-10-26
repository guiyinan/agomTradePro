"""Browser journeys for the Fee A correction screen in Django Admin."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from functools import wraps
from typing import Any, Literal, ParamSpec, TypeVar
from urllib.parse import urlsplit

import pytest
from django.apps import apps
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission, User
from django.db import connections
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Response,
    Route,
    WebSocketRoute,
    expect,
    sync_playwright,
)

from apps.account.infrastructure.models import PortfolioModel, TransactionModel
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

TEST_PASSWORD = "local-only-fee-admin-browser-pass"
FEE_FIELDS = ("commission", "slippage", "stamp_duty", "transfer_fee")
FeeAmounts = tuple[Decimal, Decimal, Decimal, Decimal]
KnownFlags = tuple[bool | None, bool | None, bool | None, bool | None]
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _run_database_call(
    function: Callable[_P, _R],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    """Run one synchronous ORM helper on a dedicated worker thread."""

    def invoke() -> _R:
        try:
            return function(*args, **kwargs)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="fee-admin-browser-db",
    ) as executor:
        return executor.submit(invoke).result()


def _database_thread(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Keep synchronous Django ORM helpers off Playwright's event-loop thread."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        return _run_database_call(function, *args, **kwargs)

    return wrapped


@pytest.fixture
def _playwright_subprocess_policy() -> Iterator[None]:
    """Apply the existing Windows subprocess policy for headless Chromium."""

    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_policy)


@pytest.fixture
def chromium_browser(_playwright_subprocess_policy: None) -> Iterator[Browser]:
    """Launch one headless Chromium instance for this isolated component test."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@_database_thread
def _new_admin_user(
    username: str,
    *,
    actor_type: Literal["superuser", "foreign_owner", "delegated_staff"] = "superuser",
) -> User:
    """Create a synthetic actor and any explicit Admin permission.

    Actors and permissions are persisted in the disposable test database.
    """

    if actor_type == "superuser":
        return User.objects.create_superuser(
            username=username,
            email=f"{username}@example.invalid",
            password=TEST_PASSWORD,
        )

    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.invalid",
        password=TEST_PASSWORD,
        is_staff=actor_type == "delegated_staff",
    )
    if actor_type == "delegated_staff":
        account_app = apps.get_app_config(TransactionModel._meta.app_label)
        create_permissions(
            account_app,
            verbosity=0,
            interactive=False,
            using="default",
        )
        permission = Permission.objects.get(
            codename="change_transactionmodel",
            content_type__app_label="account",
        )
        user.user_permissions.add(permission)
    return user


@pytest.mark.django_db(transaction=True)
def test_delegated_actor_bootstraps_real_change_permission() -> None:
    """Restore standard app permissions missing after a restricted-app flush."""

    Permission.objects.filter(
        codename="change_transactionmodel",
        content_type__app_label=TransactionModel._meta.app_label,
        content_type__model=TransactionModel._meta.model_name,
    ).delete()
    assert not Permission.objects.filter(
        codename="change_transactionmodel",
        content_type__app_label=TransactionModel._meta.app_label,
        content_type__model=TransactionModel._meta.model_name,
    ).exists()

    actor = _new_admin_user(
        "fee_browser_permission_bootstrap",
        actor_type="delegated_staff",
    )

    assert actor.is_staff is True
    assert actor.is_superuser is False
    assert list(
        actor.user_permissions.values_list(
            "codename",
            "content_type__app_label",
            "content_type__model",
        )
    ) == [
        (
            "change_transactionmodel",
            TransactionModel._meta.app_label,
            TransactionModel._meta.model_name,
        )
    ]


@_database_thread
def _seed_portfolio(user: User, name: str) -> PortfolioModel:
    """Create one synthetic owner portfolio for the browser journey."""

    return PortfolioModel.objects.create(user=user, name=name)


@_database_thread
def _seed_transaction(
    portfolio: PortfolioModel,
    *,
    fees: FeeAmounts,
    known: KnownFlags,
    estimated_cost: Decimal | None = None,
    cost_variance: Decimal | None = None,
    cost_variance_pct: float | None = None,
    asset_code: str = "600000.SH",
) -> TransactionModel:
    """Persist a synthetic ledger row with explicit availability state."""

    return TransactionModel.objects.create(
        portfolio=portfolio,
        action="buy",
        asset_code=asset_code,
        shares=5.0,
        price=Decimal("10.2500"),
        notional=Decimal("51.25"),
        commission=fees[0],
        commission_known=known[0],
        slippage=fees[1],
        slippage_known=known[1],
        stamp_duty=fees[2],
        stamp_duty_known=known[2],
        transfer_fee=fees[3],
        transfer_fee_known=known[3],
        estimated_cost=estimated_cost,
        cost_variance=cost_variance,
        cost_variance_pct=cost_variance_pct,
        traded_at=timezone.now(),
        notes="Synthetic isolated Fee A browser fixture",
    )


def _login_admin(page: Page, base_url: str, username: str) -> None:
    """Authenticate through Django Admin's real login form and CSRF token."""

    login_url = f"{base_url}{reverse('admin:login')}"
    response = page.goto(login_url, wait_until="networkidle")
    _assert_html(response, expected_status=200)
    expect(page.locator("#login-form")).to_be_visible()
    page.locator("#id_username").fill(username)
    page.locator("#id_password").fill(TEST_PASSWORD)
    with page.expect_response(
        lambda item: item.request.method == "POST"
        and urlsplit(item.url).path == reverse("admin:login")
    ) as login_post:
        page.locator('#login-form input[type="submit"]').click()
    _assert_html(login_post.value, expected_status=302)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#user-tools")).to_contain_text(username)


def _assert_html(response: Response | None, *, expected_status: int) -> None:
    """Require the expected HTTP status and rendered Django Admin HTML."""

    assert response is not None
    assert response.status == expected_status
    assert response.headers.get("content-type", "").startswith("text/html")


def _post_to_path(page: Page, path: str) -> Response:
    """Submit the visible form once and return its real local POST response."""

    with page.expect_response(
        lambda item: item.request.method == "POST" and urlsplit(item.url).path == path
    ) as submitted:
        page.locator('.submit-row input[type="submit"]').click()
    return submitted.value


@_database_thread
def _snapshot(transaction: TransactionModel) -> tuple[object, ...]:
    """Capture persisted fee state and derived values for no-write assertions."""

    transaction.refresh_from_db()
    return (
        transaction.commission,
        transaction.commission_known,
        transaction.slippage,
        transaction.slippage_known,
        transaction.stamp_duty,
        transaction.stamp_duty_known,
        transaction.transfer_fee,
        transaction.transfer_fee_known,
        transaction.cost_variance,
        transaction.cost_variance_pct,
    )


@_database_thread
def _change_log_count(user: User, transaction: TransactionModel) -> int:
    """Count real Django Admin change receipts for exactly this ledger row."""

    return LogEntry.objects.filter(
        user=user,
        content_type__app_label="account",
        content_type__model="transactionmodel",
        object_id=str(transaction.pk),
        action_flag=CHANGE,
    ).count()


@_database_thread
def _transaction_counts(
    transaction: TransactionModel,
    *,
    portfolio: PortfolioModel | None = None,
) -> tuple[int, int | None]:
    """Read persisted ledger counts for one row and optionally its portfolio."""

    transaction_count = TransactionModel.objects.filter(pk=transaction.pk).count()
    portfolio_count = (
        TransactionModel.objects.filter(portfolio=portfolio).count()
        if portfolio is not None
        else None
    )
    return transaction_count, portfolio_count


def _assert_local_requests(request_urls: list[str], base_url: str) -> None:
    """Verify observed requests use only the exact isolated live-server origin."""

    expected_origin = _network_origin(base_url)
    assert expected_origin is not None
    assert request_urls
    assert all(_network_origin(url) == expected_origin for url in request_urls)


def _network_origin(url: str) -> tuple[str, str] | None:
    """Normalize network origins while preserving exact host and port."""

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme == "ws":
        scheme = "http"
    elif scheme == "wss":
        scheme = "https"
    if not scheme or not parsed.netloc:
        return None
    return scheme, parsed.netloc.lower()


def _guarded_context(
    browser: Browser,
    base_url: str,
) -> tuple[BrowserContext, list[str]]:
    """Create a context that routes only to the exact live-server origin."""

    expected_origin = _network_origin(base_url)
    assert expected_origin is not None
    blocked_urls: list[str] = []
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        service_workers="block",
    )

    def route_http_request(route: Route) -> None:
        """Continue real local requests and abort every other network request."""

        request_url = route.request.url
        if _network_origin(request_url) == expected_origin:
            route.continue_()
            return
        blocked_urls.append(request_url)
        route.abort("blockedbyclient")

    def route_websocket(websocket: WebSocketRoute) -> None:
        """Connect only same-origin WebSockets and close external attempts."""

        if _network_origin(websocket.url) == expected_origin:
            websocket.connect_to_server()
            return
        blocked_urls.append(websocket.url)
        websocket.close(code=1008, reason="external network is disabled in this test")

    context.route("**/*", route_http_request)
    context.route_web_socket("**/*", route_websocket)
    return context, blocked_urls


def _assert_no_external_requests(blocked_urls: list[str]) -> None:
    """Fail with the attempted URLs after the browser has blocked them."""

    assert not blocked_urls, f"browser attempted external requests: {blocked_urls}"


@pytest.mark.django_db(transaction=True)
def test_owner_sees_known_zero_and_unknown_fees_then_records_one_audited_correction(
    chromium_browser: Browser,
    live_server: Any,
) -> None:
    """The real Admin UI preserves blanks, records explicit zero, and logs once."""

    owner = _new_admin_user("fee_browser_owner")
    portfolio = _seed_portfolio(owner, "fee-browser-owner-portfolio")
    transaction = _seed_transaction(
        portfolio,
        fees=(Decimal("0.00"), Decimal("7.25"), Decimal("0.00"), Decimal("1.50")),
        known=(True, None, False, None),
        estimated_cost=Decimal("10.00"),
        cost_variance=Decimal("88.00"),
        cost_variance_pct=8.8,
    )
    base_url = str(live_server.url)
    request_urls: list[str] = []
    context, blocked_urls = _guarded_context(chromium_browser, base_url)
    page = context.new_page()
    page.on("request", lambda request: request_urls.append(request.url))
    try:
        _login_admin(page, base_url, owner.username)

        list_url = f"{base_url}{reverse('admin:account_transactionmodel_changelist')}"
        list_response = page.goto(list_url, wait_until="networkidle")
        _assert_html(list_response, expected_status=200)
        row = page.locator("#result_list tbody tr").filter(has_text=portfolio.name)
        expect(row).to_be_visible()
        fees_cell = row.locator(".field-actual_fee_display")
        expect(fees_cell).to_contain_text("手续费 0.00")
        expect(fees_cell).to_contain_text("滑点 未知/未采集")
        expect(fees_cell).to_contain_text("印花税 未知/未采集")
        expect(fees_cell).to_contain_text("过户费 未知/未采集")
        assert "滑点 7.25" not in fees_cell.inner_text()
        row.locator("a").first.click()
        page.wait_for_load_state("networkidle")

        page.get_by_role("link", name="修正已采集费用").click()
        page.wait_for_load_state("networkidle")
        content_heading = page.locator("#content h1")
        expect(content_heading).to_have_count(1)
        expect(content_heading).to_contain_text(f"修正交易 {transaction.pk} 的实际费用")
        current_fees = page.locator("#content p").filter(has_text="当前实际费用")
        expect(current_fees).to_contain_text("手续费 0.00")
        expect(current_fees).to_contain_text("滑点 未知/未采集")
        expect(current_fees).to_contain_text("印花税 未知/未采集")
        expect(current_fees).to_contain_text("过户费 未知/未采集")
        for field in FEE_FIELDS:
            expect(page.locator(f"#id_{field}")).to_be_visible()
            assert page.locator(f"#id_{field}").input_value() == ""
        assert page.locator('input[name$="_known"]').count() == 0

        submit_button = page.locator('.submit-row input[type="submit"]')
        expect(submit_button).to_be_visible()
        expect(submit_button).to_be_enabled()
        style = submit_button.evaluate("""element => {
                const rect = element.getBoundingClientRect();
                const css = getComputedStyle(element);
                const color = css.backgroundColor;
                const alpha = color.startsWith('rgba(')
                    ? Number(color.slice(color.lastIndexOf(',') + 1).replace(')', '').trim())
                    : 1;
                return {
                    width: rect.width,
                    height: rect.height,
                    backgroundAlpha: alpha,
                    backgroundImage: css.backgroundImage,
                    opacity: Number(css.opacity),
                    radius: Number.parseFloat(css.borderTopLeftRadius),
                };
            }""")
        assert style["width"] > 0 and style["height"] > 0
        assert style["opacity"] > 0
        assert style["backgroundAlpha"] > 0 or style["backgroundImage"] != "none"
        assert style["radius"] > 0

        correction_path = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[transaction.pk],
        )
        correction_posts: list[str] = []
        page.on(
            "request",
            lambda request: (
                correction_posts.append(request.url)
                if request.method == "POST" and urlsplit(request.url).path == correction_path
                else None
            ),
        )
        page.locator("#id_slippage").fill("0")
        submitted = _post_to_path(page, correction_path)
        _assert_html(submitted, expected_status=302)
        page.wait_for_load_state("networkidle")
        assert len(correction_posts) == 1
        expect(page.locator(".messagelist")).to_contain_text("实际费用已修正")

        assert _transaction_counts(transaction)[0] == 1
        assert _change_log_count(owner, transaction) == 1
        assert _snapshot(transaction) == (
            Decimal("0.00"),
            True,
            Decimal("0.00"),
            True,
            Decimal("0.00"),
            False,
            Decimal("1.50"),
            None,
            None,
            None,
        )
        _assert_local_requests(request_urls, base_url)
    finally:
        context.close()
        _assert_no_external_requests(blocked_urls)


@pytest.mark.django_db(transaction=True)
def test_browser_rejects_negative_and_out_of_range_corrections_without_writes(
    chromium_browser: Browser,
    live_server: Any,
) -> None:
    """Field-level negative/decimal overflow and aggregate overflow never persist."""

    owner = _new_admin_user("fee_browser_invalid_owner")
    portfolio = _seed_portfolio(owner, "fee-browser-invalid-portfolio")
    transaction = _seed_transaction(
        portfolio,
        fees=(Decimal("1.00"), Decimal("2.00"), Decimal("3.00"), Decimal("4.00")),
        known=(True, True, True, True),
        estimated_cost=Decimal("10.00"),
        cost_variance=Decimal("90.00"),
        cost_variance_pct=9.0,
    )
    original = _snapshot(transaction)
    base_url = str(live_server.url)
    request_urls: list[str] = []
    context, blocked_urls = _guarded_context(chromium_browser, base_url)
    page = context.new_page()
    page.on("request", lambda request: request_urls.append(request.url))
    try:
        _login_admin(page, base_url, owner.username)
        correction_path = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[transaction.pk],
        )
        correction_url = f"{base_url}{correction_path}"
        for value in ("-0.01", "100000000.00"):
            response = page.goto(correction_url, wait_until="networkidle")
            _assert_html(response, expected_status=200)
            page.locator("#id_commission").fill(value)
            submitted = _post_to_path(page, correction_path)
            _assert_html(submitted, expected_status=200)
            expect(page.locator(".errorlist").first).to_be_visible()
            assert _snapshot(transaction) == original
            assert _change_log_count(owner, transaction) == 0
            assert _transaction_counts(transaction)[0] == 1

        boundary = _seed_transaction(
            portfolio,
            fees=(
                Decimal("99999999.99"),
                Decimal("0.00"),
                Decimal("0.00"),
                Decimal("0.00"),
            ),
            known=(True, True, True, True),
            estimated_cost=Decimal("0.00"),
            cost_variance=Decimal("99999999.99"),
            asset_code="600001.SH",
        )
        boundary_original = _snapshot(boundary)
        boundary_path = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[boundary.pk],
        )
        response = page.goto(f"{base_url}{boundary_path}", wait_until="networkidle")
        _assert_html(response, expected_status=200)
        page.locator("#id_slippage").fill("0.01")
        submitted = _post_to_path(page, boundary_path)
        _assert_html(submitted, expected_status=200)
        expect(
            page.locator(".errorlist").filter(has_text="实际费用修正导致成本差异超出可存储范围")
        ).to_be_visible()
        assert _snapshot(boundary) == boundary_original
        assert _change_log_count(owner, boundary) == 0
        assert _transaction_counts(transaction, portfolio=portfolio) == (1, 2)
        _assert_local_requests(request_urls, base_url)
    finally:
        context.close()
        _assert_no_external_requests(blocked_urls)


@pytest.mark.django_db(transaction=True)
def test_browser_csrf_and_foreign_owner_denials_leave_the_ledger_unchanged(
    chromium_browser: Browser,
    live_server: Any,
) -> None:
    """A missing CSRF token and a non-owner staff actor cannot change fees."""

    owner = _new_admin_user("fee_browser_csrf_owner")
    portfolio = _seed_portfolio(owner, "fee-browser-csrf-portfolio")
    transaction = _seed_transaction(
        portfolio,
        fees=(Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
        known=(False, False, False, False),
    )
    original = _snapshot(transaction)
    foreign_owner = _new_admin_user(
        "fee_browser_foreign_owner",
        actor_type="foreign_owner",
    )
    foreign_portfolio = _seed_portfolio(
        foreign_owner,
        "fee-browser-foreign-portfolio",
    )
    foreign_transaction = _seed_transaction(
        foreign_portfolio,
        fees=(Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
        known=(False, False, False, False),
        asset_code="600002.SH",
    )
    foreign_original = _snapshot(foreign_transaction)
    delegated_staff = _new_admin_user(
        "fee_browser_nonowner_staff",
        actor_type="delegated_staff",
    )
    base_url = str(live_server.url)
    request_urls: list[str] = []

    owner_context, owner_blocked_urls = _guarded_context(chromium_browser, base_url)
    owner_page = owner_context.new_page()
    owner_page.on("request", lambda request: request_urls.append(request.url))
    try:
        _login_admin(owner_page, base_url, owner.username)
        correction_path = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[transaction.pk],
        )
        response = owner_page.goto(
            f"{base_url}{correction_path}",
            wait_until="networkidle",
        )
        _assert_html(response, expected_status=200)
        owner_page.locator(
            '#content form[method="post"] input[name="csrfmiddlewaretoken"]'
        ).evaluate("element => element.remove()")
        owner_page.locator("#id_commission").fill("3.00")
        denied = _post_to_path(owner_page, correction_path)
        _assert_html(denied, expected_status=403)
        assert _snapshot(transaction) == original
        assert _change_log_count(owner, transaction) == 0
        assert _transaction_counts(transaction)[0] == 1
    finally:
        owner_context.close()
        _assert_no_external_requests(owner_blocked_urls)

    staff_context, staff_blocked_urls = _guarded_context(chromium_browser, base_url)
    staff_page = staff_context.new_page()
    staff_page.on("request", lambda request: request_urls.append(request.url))
    try:
        _login_admin(staff_page, base_url, delegated_staff.username)
        foreign_path = reverse(
            "admin:account_transactionmodel_correct_costs",
            args=[foreign_transaction.pk],
        )
        form_response = staff_page.goto(
            f"{base_url}{foreign_path}",
            wait_until="networkidle",
        )
        _assert_html(form_response, expected_status=200)
        staff_page.locator("#id_commission").fill("9.00")
        denied = _post_to_path(staff_page, foreign_path)
        _assert_html(denied, expected_status=403)
        assert _snapshot(foreign_transaction) == foreign_original
        assert _change_log_count(delegated_staff, foreign_transaction) == 0
        assert _transaction_counts(foreign_transaction)[0] == 1
        _assert_local_requests(request_urls, base_url)
    finally:
        staff_context.close()
        _assert_no_external_requests(staff_blocked_urls)
