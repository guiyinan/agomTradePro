"""Real local Chromium journey for the read-only two-portfolio comparison task."""

import asyncio
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import Page, expect, sync_playwright

from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    PositionModel,
    SimulatedAccountModel,
    UnifiedAccountCashFlowModel,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy


@pytest.fixture
def playwright_policy() -> Iterator[None]:
    """Apply and restore the repository's Windows subprocess policy."""

    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


def _account(user, name: str) -> SimulatedAccountModel:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("50000"),
        current_market_value=Decimal("50000"),
        total_value=Decimal("100000"),
    )


def _history(account: SimulatedAccountModel, gain: Decimal) -> None:
    UnifiedAccountCashFlowModel.objects.create(
        account=account,
        flow_type="initial_capital",
        amount=Decimal("100000"),
        flow_date=date(2024, 1, 1),
        source_app="simulated_trading",
    )
    for index in range(3):
        value = Decimal("100000") + gain * index
        DailyNetValueModel.objects.create(
            account=account,
            record_date=date(2024, 1, 1) + timedelta(days=index),
            correction_event_watermark=0,
            correction_event_watermark_sha256=fee_correction_account_genesis_sha256(account.pk),
            net_value=value,
            cash=Decimal("50000"),
            market_value=value - Decimal("50000"),
        )


def _position(account: SimulatedAccountModel, code: str, value: str) -> None:
    PositionModel.objects.create(
        account=account,
        asset_code=code,
        asset_name=code,
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("10"),
        market_value=Decimal(value),
        first_buy_date=date(2024, 1, 1),
    )


def _run_action(page: Page, action_key: str, left: int, right: int) -> None:
    form = page.locator(f'[data-action-ui-key="{action_key}"]')
    expect(form).to_be_visible()
    form.locator('[name="left_account_id"]').fill(str(left))
    form.locator('[name="right_account_id"]').fill(str(right))
    form.locator('[name="start_date"]').fill("2024-01-01")
    form.locator('[name="end_date"]').fill("2024-01-03")
    with page.expect_response(
        lambda response: f"/api/tui/actions/{action_key}/run/" in response.url
    ) as pending:
        form.locator(".tui-action-button").click()
    assert pending.value.status == 200


@pytest.mark.django_db(transaction=True)
def test_two_portfolio_comparison_browser_journey(live_server, playwright_policy) -> None:
    """Complete metrics, curves, overlap and industry comparison through the real TUI."""

    user = get_user_model().objects.create_user(
        username="portfolio-comparison-browser",
        password="local-test-only",
    )
    left = _account(user, "稳健组合")
    right = _account(user, "进取组合")
    _history(left, Decimal("1000"))
    _history(right, Decimal("500"))
    _position(left, "000001.SZ", "60000")
    _position(left, "000002.SZ", "40000")
    _position(right, "000001.SZ", "50000")
    _position(right, "600000.SH", "50000")
    client = Client()
    client.force_login(user)
    history_count = DailyNetValueModel.objects.count()
    artifact = Path(settings.BASE_DIR) / ".tmp/tux11-browser/portfolio-comparison.png"
    artifact.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": live_server.url,
                    }
                ]
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(
                f"{live_server.url}/tui/?screen=task.portfolio-comparison",
                wait_until="networkidle",
            )
            expect(page.get_by_text("双组合对比", exact=True).first).to_be_visible()
            expect(page.get_by_text("稳健组合", exact=True).first).to_be_visible()
            expect(page.get_by_text("进取组合", exact=True).first).to_be_visible()

            _run_action(page, "portfolio-comparison.metrics", left.pk, right.pk)
            expect(page.get_by_text("时间加权收益率", exact=True).first).to_be_visible()
            expect(
                page.get_by_text("组合 A 归一化净值（期初=100）", exact=True).first
            ).to_be_visible()
            expect(page.locator(".tui-chart-svg").first).to_be_visible()

            _run_action(page, "portfolio-comparison.holdings", left.pk, right.pk)
            expect(page.get_by_text("当前持仓重合度（%）", exact=True).first).to_be_visible()
            expect(page.get_by_text("000002.SZ", exact=True).first).to_be_visible()
            expect(page.get_by_text("600000.SH", exact=True).first).to_be_visible()

            _run_action(page, "portfolio-comparison.industries", left.pk, right.pk)
            expect(page.get_by_text("行业未知", exact=True).first).to_be_visible()
            assert errors == []
            assert DailyNetValueModel.objects.count() == history_count
            page.screenshot(path=str(artifact), full_page=True)
        finally:
            browser.close()
