"""Actual local research task journeys using synthetic source-bearing facts.

Owner responses are not replaced. One marked transport-abort case tests retry;
all subsequent successful responses still come from the actual local owner.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from playwright.sync_api import expect, sync_playwright

from apps.data_center.infrastructure.models import FinancialFactModel
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.tui_research.scenario import research_scenario

TASK = "task.asset-research"
ACTION_PATH = "/api/tui/actions/equity.research-snapshot/run/"


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Use and restore the Windows subprocess policy without async DB bypasses."""

    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


def _sessions(django_user_model) -> list[tuple[str, str]]:
    sessions = []
    for staff in (False, True):
        user = django_user_model.objects.create_user(
            username=f"tux08-browser-{staff}", is_staff=staff
        )
        client = Client()
        client.force_login(user)
        sessions.append(
            ("admin" if staff else "user", client.cookies[settings.SESSION_COOKIE_NAME].value)
        )
    return sessions


def _open_entry(page):
    form = page.locator("[data-main-panel] .tui-action-entry-form")
    form.wait_for(state="attached")
    if not form.is_visible():
        page.locator("[data-research-again-entry] > summary").click()
    expect(form).to_be_visible()
    return form


def _submit(page, value: str):
    form = _open_entry(page)
    form.locator('[name="stock_code"]').fill(value)
    with page.expect_response(
        lambda response: urlsplit(response.url).path == ACTION_PATH
    ) as response:
        form.locator(".tui-action-button").click()
    return response.value


@pytest.mark.django_db(transaction=True)
def test_real_research_and_authorized_professional_return(
    live_server, django_user_model, subprocess_policy
) -> None:
    """Ordinary/admin desktop/mobile users complete a real read and return."""

    sessions = _sessions(django_user_model)
    output = Path(
        getattr(settings, "TUX08_ARTIFACT_ROOT", Path(settings.BASE_DIR) / ".tmp/tux08-browser")
    )
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    with research_scenario() as scenario, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for role, cookie in sessions:
                for width, height in ((1440, 1000), (390, 844)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    context.add_cookies(
                        [
                            {
                                "name": settings.SESSION_COOKIE_NAME,
                                "value": cookie,
                                "url": live_server.url,
                            }
                        ]
                    )
                    page = context.new_page()
                    requests = []
                    failures = []
                    page.on(
                        "request",
                        lambda request, recorded=requests: recorded.append(
                            (request.method, request.url)
                        ),
                    )
                    page.on(
                        "pageerror", lambda error, recorded=failures: recorded.append(str(error))
                    )
                    page.goto(f"{live_server.url}/tui/", wait_until="networkidle")
                    expect(page.locator("[data-task-home]")).to_be_visible()
                    page.locator(f'[data-task-home] [data-experience-screen-key="{TASK}"]').click()
                    expect(page.locator("[data-main-panel] .tui-action-entry-form")).to_be_visible()
                    assert not any(urlsplit(url).path == ACTION_PATH for _, url in requests)
                    requested = "研究夹具" if role == "user" and width == 1440 else "600000.SH"
                    response = _submit(page, requested)
                    assert response.status == 200
                    result = response.json()
                    assert result["outcome"] == "success"
                    assert result["response"]["status_code"] == 200
                    expect(page.locator(".tui-research-evidence-section")).to_have_count(6)
                    main = page.locator("[data-main-panel]")
                    expect(main).to_contain_text("12.34")
                    expect(main).to_contain_text("证伪条件")
                    summary = page.locator("[data-research-compact-summary]")
                    expect(summary).to_be_visible()
                    expect(page.locator(".tui-rail")).to_be_hidden()
                    expect(page.locator(".tui-actions-panel")).to_be_hidden()
                    main_box = main.bounding_box()
                    assert main_box is not None and main_box["width"] >= width * 0.9
                    identity = page.locator("[data-research-identity]")
                    assert identity.evaluate(
                        "el => { const r=el.getBoundingClientRect(); const m=el.closest('[data-main-panel]').getBoundingClientRect(); return r.top >= m.top && r.bottom <= Math.min(innerHeight,m.bottom); }"
                    )
                    expect(page.locator("[data-research-again-entry]")).not_to_have_attribute(
                        "open", ""
                    )
                    expect(
                        page.locator("[data-main-panel] .tui-action-entry-form [name=stock_code]")
                    ).to_have_value(requested)
                    page.screenshot(
                        path=str(output / f"research-summary-{role}-{width}.png"), full_page=False
                    )
                    financial = page.locator(".tui-research-evidence-section").filter(
                        has=page.locator(".tui-research-evidence-label", has_text="财务")
                    )
                    financial.locator(":scope > summary").focus()
                    page.keyboard.press("Enter")
                    expect(financial).to_have_attribute("open", "")
                    expect(financial).to_contain_text("123.45")
                    expect(financial).to_contain_text("CNY")
                    financial.locator(".tui-research-evidence-clocks > summary").click()
                    expect(financial).to_contain_text("财务公告时间")
                    expect(financial).to_contain_text(
                        scenario.financial.refreshed_fact.announced_at.isoformat()
                    )
                    assert "record.source_evidence" not in financial.inner_text()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    style = financial.evaluate(
                        "el => ({radius: getComputedStyle(el).borderRadius, background: getComputedStyle(el).backgroundColor})"
                    )
                    assert style["radius"] != "0px"
                    assert style["background"] not in ("transparent", "rgba(0, 0, 0, 0)")
                    page.screenshot(
                        path=str(output / f"research-{role}-{width}.png"), full_page=True
                    )
                    before = sum(urlsplit(url).path == ACTION_PATH for _, url in requests)
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == "/api/tui/screens/research.asset-lab/"
                    ) as target_metadata:
                        page.locator("[data-main-panel] [data-next-step-index]").first.click()
                    expect(page.locator("[data-next-step-return]")).to_be_visible()
                    assert parse_qs(urlsplit(page.url).query) == {
                        "screen": ["research.asset-lab"],
                        "action": ["equity.valuation-overview"],
                    }
                    assert sum(urlsplit(url).path == ACTION_PATH for _, url in requests) == before
                    target = next(
                        action
                        for action in target_metadata.value.json()["actions"]
                        if action["key"] == "equity.valuation-overview"
                    )
                    expect(
                        page.locator(
                            f'[data-action-ui-key="{target["ui_key"]}"] [name="stock_code"]'
                        )
                    ).to_have_value("600000.SH")
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path == ACTION_PATH
                    ) as returned:
                        page.locator("[data-next-step-return]").click()
                    assert returned.value.json()["outcome"] == "success"
                    expect(page.locator(".tui-research-evidence-section")).to_have_count(6)
                    assert parse_qs(urlsplit(page.url).query) == {
                        "screen": [TASK],
                        "action": ["equity.research-snapshot"],
                    }
                    before_toggle = list(requests)
                    main_content = main.inner_html()
                    page.locator('[data-experience-mode="professional"]').click()
                    expect(page.locator(".tui-actions-panel")).to_be_visible()
                    page.locator('[data-experience-mode="task"]').click()
                    expect(page.locator(".tui-actions-panel")).to_be_hidden()
                    assert requests == before_toggle
                    assert main.inner_html() == main_content
                    assert not failures
                    assert all(
                        urlsplit(url).netloc == urlsplit(live_server.url).netloc
                        for _, url in requests
                    )
                    cases.append(
                        {
                            "role": role,
                            "viewport": [width, height],
                            "outcome": result["outcome"],
                            "requests": requests,
                            "page_errors": failures,
                        }
                    )
                    context.close()
        finally:
            browser.close()
    (output / "research-real-browser.json").write_text(
        json.dumps({"scope": __doc__, "cases": cases}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.django_db(transaction=True)
def test_real_partial_missing_forbidden_and_explicit_network_retry(
    live_server, django_user_model, subprocess_policy
) -> None:
    """Missing materials, unknown identity and expired login remain actionable."""

    _, cookie = _sessions(django_user_model)[0]
    with research_scenario(with_optionals=False), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 390, "height": 844})
            context.add_cookies(
                [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
            )
            page = context.new_page()
            failures = []
            page.on("pageerror", lambda error, recorded=failures: recorded.append(str(error)))
            page.goto(f"{live_server.url}/tui/?screen={TASK}", wait_until="networkidle")
            partial = _submit(page, "600000.SH").json()
            assert partial["outcome"] == "partial"
            expect(page.locator("[data-main-panel]")).to_contain_text("部分返回")
            missing = _submit(page, "NO_MATCH_TUX08").json()
            assert missing["outcome"] == "blocked"
            assert missing["view_model"]["owner_status"] == "missing"
            expect(page.locator("[data-research-again-entry] > summary")).to_be_visible()
            # Abort exactly one outbound browser request; do not fake a successful owner response.
            page.route(f"**{ACTION_PATH}", lambda route: route.abort("connectionfailed"), times=1)
            form = _open_entry(page)
            form.locator('[name="stock_code"]').fill("600000.SH")
            form.locator(".tui-action-button").click()
            expect(page.locator("[data-action-read-retry]")).to_be_visible()
            expect(
                page.locator("[data-main-panel] .tui-action-entry-form [name=stock_code]")
            ).to_have_value("600000.SH")
            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_PATH
            ) as retry:
                page.locator("[data-action-read-retry]").click()
            assert retry.value.json()["outcome"] == "partial"
            context.clear_cookies()
            forbidden = _submit(page, "600000.SH")
            assert forbidden.status == 403
            expect(page.locator(".tui-application-error")).to_be_visible()
            assert "/api/" not in page.locator("[data-main-panel]").inner_text()
            assert not failures
            context.close()
        finally:
            browser.close()


@pytest.mark.django_db(transaction=True)
def test_real_restricted_evidence_and_explicit_recovery(
    live_server, django_user_model, subprocess_policy
) -> None:
    """An actual fact/member mismatch blocks the page until the fact is restored."""

    _, cookie = _sessions(django_user_model)[0]
    with research_scenario() as scenario:
        fact = scenario.financial.fact
        original = fact.value
        FinancialFactModel.objects.filter(pk=fact.pk).update(value=original + Decimal("1"))

        def restore() -> None:
            # Browser sync APIs run an event loop: use a separate DB thread,
            # never DJANGO_ALLOW_ASYNC_UNSAFE or a mocked owner response.
            try:
                FinancialFactModel.objects.filter(pk=fact.pk).update(value=original)
            finally:
                connections.close_all()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.add_cookies(
                    [
                        {
                            "name": settings.SESSION_COOKIE_NAME,
                            "value": cookie,
                            "url": live_server.url,
                        }
                    ]
                )
                page = context.new_page()
                page.goto(f"{live_server.url}/tui/?screen={TASK}", wait_until="networkidle")
                response = _submit(page, "600000.SH")
                assert response.status == 200
                result = response.json()
                assert result["outcome"] == "blocked"
                assert result["response"]["status_code"] == 200
                assert result["view_model"]["must_not_use_for_decision"] is True
                expect(
                    page.locator("[data-main-panel] .tui-action-entry-form [name=stock_code]")
                ).to_have_value("600000.SH")
                expect(page.locator(".tui-research-evidence-section")).to_have_count(6)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(restore).result()
                recovered = _submit(page, "600000.SH")
                assert recovered.json()["outcome"] == "success"
                expect(page.locator(".tui-research-evidence-section")).to_have_count(6)
                context.close()
            finally:
                browser.close()


@pytest.mark.django_db(transaction=True)
def test_real_stale_source_is_visible_as_restricted(
    live_server, django_user_model, subprocess_policy
) -> None:
    """The browser displays actual stale source evidence without a TTL override."""

    _, cookie = _sessions(django_user_model)[0]
    with (
        research_scenario(financial_age_days=91, require_ready=False),
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 390, "height": 844})
            context.add_cookies(
                [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
            )
            page = context.new_page()
            page.goto(f"{live_server.url}/tui/?screen={TASK}", wait_until="networkidle")
            response = _submit(page, "600000.SH")
            result = response.json()
            assert response.status == 200
            assert result["outcome"] == "blocked"
            assert result["view_model"]["must_not_use_for_decision"] is True
            financial = page.locator(".tui-research-evidence-section").filter(
                has=page.locator(".tui-research-evidence-label", has_text="财务")
            )
            expect(financial).to_contain_text("数据过期")
            expect(financial).to_contain_text("禁止用于决策")
            expect(page.locator("[data-research-again-entry] > summary")).to_be_visible()
            context.close()
        finally:
            browser.close()
