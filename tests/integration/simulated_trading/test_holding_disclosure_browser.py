"""Loopback holding-disclosure journey with explicitly synthetic source evidence.

Real session, account/position ORM, HTTP, Application and TUI stay in the path.
Only the Data Center public financial read is supplied by a local fixture; this
does not establish real-provider coverage or production source qualification.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import Page, Route, expect, sync_playwright

from apps.data_center.application import public as data_center_public
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.task_monitor.infrastructure.models import TaskExecutionModel
from tests.component.account.test_authentication import _create_profile
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
    _form,
    _response,
    _set_control_value,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.runtime_config import configure_critical_runtime

pytestmark = pytest.mark.django_db(transaction=True)
_ACTION = "simulated-trading.holding-disclosures"
_ASSET = "600000.SH"
_SOURCE_ANNOUNCED = "2026-10-31T05:20:00+00:00"


@dataclass
class DisclosureBook:
    """One actual local account and a controllable public-source read fixture."""

    owner: Any
    account: SimulatedAccountModel
    foreign_account_id: int
    source: dict[str, object]
    calls: list[str]


@pytest.fixture
def disclosure_book(monkeypatch: pytest.MonkeyPatch) -> DisclosureBook:
    """Create only explicit local holdings and patch one source-owned read port."""

    configure_critical_runtime()
    owner = get_user_model().objects.create_user(username=f"disclosure-{uuid4().hex}")
    _create_profile(owner)
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="披露资料核对测试账户",
        account_type="simulated",
        initial_capital=Decimal("10000"),
        current_cash=Decimal("9000"),
        current_market_value=Decimal("1000"),
        total_value=Decimal("10000"),
        auto_trading_enabled=False,
    )
    foreign = get_user_model().objects.create_user(username=f"foreign-{uuid4().hex}")
    _create_profile(foreign)
    foreign_account = SimulatedAccountModel.objects.create(
        user=foreign,
        account_name="Other owner",
        account_type="simulated",
        initial_capital=Decimal("10000"),
        current_cash=Decimal("9000"),
        current_market_value=Decimal("1000"),
        total_value=Decimal("10000"),
        auto_trading_enabled=False,
    )
    for held_account in (account, foreign_account):
        PositionModel.objects.create(
            account=held_account,
            asset_code=_ASSET,
            asset_name="本地持仓样本",
            asset_type="equity",
            quantity=Decimal("100"),
            available_quantity=Decimal("100"),
            avg_cost=Decimal("10"),
            total_cost=Decimal("1000"),
            current_price=Decimal("10"),
            market_value=Decimal("1000"),
            first_buy_date=date(2026, 10, 1),
        )
    source: dict[str, object] = {
        "publication_id": "7fcaf2f4-0b5b-477d-8d88-e9d46a774955",
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
        "reliability": "source_bound",
        "rows": [
            {
                "asset_code": _ASSET,
                "period_end": "2026-09-30",
                "period_type": "quarterly",
                "metric_code": "roe",
                "value": 12.5,
                "unit": "%",
                "source": "本地披露原件样本",
                "report_date": "2026-10-31",
                "available_at": "2026-10-31T05:25:00+00:00",
                "fetched_at": "2026-10-31T05:30:00+00:00",
                "source_evidence": {
                    "announced_at": _SOURCE_ANNOUNCED,
                    "source_record_id": "synthetic-disclosure-row-1",
                    "raw_payload_hash": "a" * 64,
                },
            }
        ],
    }
    book = DisclosureBook(
        owner=owner,
        account=account,
        foreign_account_id=foreign_account.pk,
        source=source,
        calls=[],
    )

    def read_financials(asset_code: str, **kwargs: object) -> dict[str, object]:
        """Return retained test data without bypassing account or holding authority."""

        assert asset_code == _ASSET
        assert kwargs.get("limit") == 20
        book.calls.append(asset_code)
        return copy.deepcopy(book.source)

    monkeypatch.setattr(data_center_public, "get_published_financial_facts", read_financials)
    return book


@pytest.fixture(params=[(1440, 1000), (390, 844)], ids=["desktop", "narrow"])
def disclosure_page(
    live_server: Any,
    disclosure_book: DisclosureBook,
    request: pytest.FixtureRequest,
) -> Iterator[Page]:
    """Open the actual account workspace with a real session and loopback-only traffic."""

    client = Client(enforce_csrf_checks=True)
    client.force_login(disclosure_book.owner)
    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    errors: list[str] = []
    traffic: list[dict[str, str]] = []
    width, height = request.param
    evidence = (
        Path(settings.BASE_DIR)
        / "artifacts/ash05-event-review-20261110"
        / (f"browser-{width}-{uuid4().hex[:8]}")
    )
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                    "url": live_server.url,
                }
            ]
        )

        def local_only(route: Route) -> None:
            """Prevent a browser fixture from contacting an external source."""

            if urlsplit(route.request.url).netloc != urlsplit(live_server.url).netloc:
                errors.append(f"Nonlocal request: {route.request.url}")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: traffic.append({"method": req.method, "url": req.url}))
        try:
            navigation = page.goto(
                f"{live_server.url}/tui/?screen=execution.accounts", wait_until="networkidle"
            )
            assert navigation is not None and navigation.status == 200
            assert navigation.headers["content-type"].startswith("text/html")
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()
            yield page
            assert errors == []
        finally:
            page.screenshot(path=str(evidence / "final-viewport.png"))
            (evidence / "traffic.json").write_text(
                json.dumps({"requests": traffic, "page_errors": errors}, indent=2),
                encoding="utf-8",
            )
            context.close()
            browser.close()
            if changed:
                asyncio.set_event_loop_policy(original_policy)


def _business_state() -> object:
    """Snapshot financial, publication and task rows, excluding transport audit logs."""

    return _db_call(
        lambda: (
            list(SimulatedAccountModel.objects.order_by("pk").values()),
            list(PositionModel.objects.order_by("pk").values()),
            list(SimulatedTradeModel.objects.order_by("pk").values()),
            list(CanonicalPublicationModel.objects.order_by("pk").values()),
            list(CanonicalPublicationPointerModel.objects.order_by("pk").values()),
            list(TaskExecutionModel.objects.order_by("pk").values()),
        )
    )


def test_owner_reads_holding_disclosure_and_failed_scope_clears_previous_facts(
    disclosure_page: Page,
    disclosure_book: DisclosureBook,
) -> None:
    """Complete the real holdings-to-disclosure read without posting or stale facts."""

    page = disclosure_page
    book = disclosure_book
    before = _business_state()
    positions = _form(page, "simulated-trading.positions")
    _set_control_value(positions.locator('[name="account_id"]'), str(book.account.pk))
    position_result = _response(
        page,
        "simulated-trading.positions",
        positions.locator(".tui-action-submit").click,
    )
    assert position_result["response"]["status_code"] == 200
    expect(page.locator("[data-main-panel]")).to_contain_text(_ASSET)

    form = _form(page, _ACTION)
    _set_control_value(form.locator('[name="account_id"]'), str(book.account.pk))
    form.locator('[name="asset_code"]').fill(_ASSET)
    result = _response(page, _ACTION, form.locator(".tui-action-submit").click)
    assert result["response"]["status_code"] == 200
    panel = page.locator("[data-main-panel]")
    expect(panel).to_contain_text("资料范围不完整")
    expect(panel).to_contain_text("不用于投资决策")
    notice = panel.get_by_text("资料范围不完整", exact=False).first
    expect(notice).to_be_visible()
    notice_bounds = notice.bounding_box()
    assert notice_bounds is not None and page.viewport_size is not None
    assert 0 <= notice_bounds["y"] < page.viewport_size["height"]
    assert notice_bounds["width"] > 100 and notice_bounds["height"] > 0
    page.screenshot(
        path=str(
            Path(settings.BASE_DIR)
            / "artifacts/ash05-event-review-20261110"
            / f"disclosure-summary-{page.viewport_size['width']}-{uuid4().hex[:8]}.png"
        )
    )
    for section in panel.locator("details").all():
        if section.get_attribute("open") is None:
            section.locator(":scope > summary").click()
    expect(panel).to_contain_text("2026-10-31")
    expect(panel).to_contain_text("本地披露原件样本")
    expect(panel).not_to_contain_text("a" * 64)
    source_cell = panel.get_by_role("cell", name="本地披露原件样本", exact=True)
    source_cell.scroll_into_view_if_needed()
    expect(source_cell).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(
        path=str(
            Path(settings.BASE_DIR)
            / "artifacts/ash05-event-review-20261110"
            / f"disclosure-visible-{page.viewport_size['width']}-{uuid4().hex[:8]}.png"
        )
    )
    assert book.calls == [_ASSET]

    origin = urlsplit(page.url)
    base = f"{origin.scheme}://{origin.netloc}/api/simulated-trading/accounts"
    repeated = page.request.get(
        f"{base}/{book.account.pk}/holding-disclosures/",
        params={"asset_code": _ASSET},
    )
    assert repeated.status == 200
    assert repeated.headers["content-type"].startswith("application/json")
    payload = repeated.json()
    assert payload["account_id"] == book.account.pk
    assert payload["asset_code"] == _ASSET
    assert payload["scope"] == "simulation_only"
    assert payload["outcome"] == "partial"
    assert payload["read_only"] is True
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True
    assert payload["freshness"] == "fresh"
    assert payload["reliability"] == "source_bound"
    assert payload["coverage_note"]
    row = payload["rows"][0]
    assert row["asset_code"] == _ASSET
    assert row["report_date"] == "2026-10-31"
    assert row["announced_at"] == _SOURCE_ANNOUNCED
    assert row["available_at"] == "2026-10-31T05:25:00+00:00"
    assert row["fetched_at"] == "2026-10-31T05:30:00+00:00"
    assert row["source_record_id"] == "synthetic-disclosure-row-1"
    assert row["raw_payload_hash"] == "a" * 64
    assert book.calls == [_ASSET, _ASSET]
    assert _business_state() == before

    denied = page.request.get(
        f"{base}/{book.foreign_account_id}/holding-disclosures/",
        params={"asset_code": _ASSET},
    )
    assert denied.status == 404
    assert denied.headers["content-type"].startswith("application/json")
    assert denied.json().get("rows", []) == []
    assert "本地披露原件样本" not in denied.text()

    form = _form(page, _ACTION)
    form.locator('[name="asset_code"]').fill("000001.SZ")
    failed = _response(page, _ACTION, form.locator(".tui-action-submit").click)
    assert failed["response"]["status_code"] == 404
    expect(panel).not_to_contain_text("本地披露原件样本")
    assert book.calls == [_ASSET, _ASSET]
    assert _business_state() == before
