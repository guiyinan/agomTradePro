"""Actual local research task journeys using synthetic source-bearing facts.

Owner responses are not replaced. One marked transport-abort case tests retry;
all subsequent successful responses still come from the actual local owner.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from playwright.sync_api import expect, sync_playwright

from apps.data_center.infrastructure.models import FinancialFactModel, MarketThermometerConfigModel
from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.exceptions import DataFetchError
from tests.component.equity.test_research_snapshot_tui_browser import (
    loopback_only_python_network as loopback_only_python_network,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.tui_research.scenario import research_scenario

TASK = "task.asset-research"
ACTION_PATH = "/api/tui/actions/equity.research-snapshot/run/"


def _artifact_directory() -> Path:
    """Return a run-unique private evidence directory for this candidate."""

    root = Path(
        getattr(
            settings,
            "TUX10_ARTIFACT_ROOT",
            Path(settings.BASE_DIR) / ".tmp/tux10-browser-next-candidate-bbc7d69ff/artifacts",
        )
    )
    raw_label = os.environ.get("TUX10_RUN_LABEL", "candidate")
    safe_label = "".join(char for char in raw_label if char.isalnum() or char in "-_.")
    output = root / f"{safe_label or 'candidate'}-{uuid4().hex}-research"
    output.mkdir(parents=True, exist_ok=True)
    return output


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


def _submit(page, value: str, *, keyboard: bool = False):
    form = _open_entry(page)
    stock_code = form.locator('[name="stock_code"]')
    if keyboard:
        page.keyboard.press("F9")
        assert form.evaluate("form => form.contains(document.activeElement)")
    stock_code.fill(value)
    with page.expect_response(
        lambda response: urlsplit(response.url).path == ACTION_PATH
    ) as response:
        if keyboard:
            page.keyboard.press("F6")
        else:
            form.locator(".tui-action-button").click()
    return response.value


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_workspace_candidate_opens_owned_research_without_creating_config(
    live_server, django_user_model, subprocess_policy, monkeypatch, loopback_only_python_network
) -> None:
    """An ordinary investor can read the selected account's candidate and follow its detail."""
    source_health = DataFetchError("private provider detail", code="MARKET_CALENDAR_UNAVAILABLE")

    def read_health(self, *, asset_codes):
        if isinstance(source_health, Exception):
            raise source_health
        return source_health

    monkeypatch.setattr(
        "apps.decision_rhythm.application.advisor_providers.DecisionDataHealthProvider.get_health",
        read_health,
    )
    # The destination page starts a quote refresh after navigation.
    monkeypatch.setattr(
        "apps.realtime.infrastructure.repositories.AKSharePriceDataProvider.get_realtime_price",
        lambda self, asset_code: None,
    )
    monkeypatch.setattr(
        "apps.realtime.infrastructure.repositories.AKSharePriceDataProvider.get_realtime_prices_batch",
        lambda self, asset_codes: [],
    )
    owner = django_user_model.objects.create_user(username="workspace-research-owner")
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="研究账户",
        account_type="simulated",
        initial_capital="10000",
        current_cash="10000",
        total_value="10000",
    )
    recommendation = UnifiedRecommendationModel.objects.create(
        recommendation_id="workspace-research-only",
        account_id=str(account.pk),
        security_code="600547.SH",
        side="BUY",
        human_rationale="山东黄金研究样本",
    )
    second_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="第二个研究账户",
        account_type="simulated",
        initial_capital="10000",
        current_cash="10000",
        total_value="10000",
    )
    second = UnifiedRecommendationModel.objects.create(
        recommendation_id="workspace-second-owned",
        account_id=str(second_account.pk),
        security_code="600547.SH",
        side="BUY",
        human_rationale="第二账户独立依据",
    )
    empty_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="新账户",
        account_type="simulated",
        initial_capital="10000",
        current_cash="10000",
        total_value="10000",
    )
    MarketThermometerConfigModel.objects.filter(pk=1).delete()
    client = Client()
    client.force_login(owner)
    methods: list[str] = []
    url = f"{live_server.url}/decision/workspace/?source=dashboard-alpha&security_code=600547.sh&account_id=00{account.pk}&step=4"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": live_server.url,
                    }
                ]
            )
            page.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlsplit(route.request.url).netloc == urlsplit(live_server.url).netloc
                    else route.abort("blockedbyclient")
                ),
            )
            page.on("request", lambda request: methods.append(request.method))
            with page.expect_response(
                lambda response: urlsplit(response.url).path == "/api/decision/advisor/sheet/"
            ) as advisor_response:
                page.goto(url)
            assert advisor_response.value.status == 200
            sheet = advisor_response.value.json()["data"]
            order = sheet["order_intents"][0]
            assert sheet["data_health"]["blocked_reasons"] == [
                "decision_data_health_unavailable:MARKET_CALENDAR_UNAVAILABLE"
            ]
            assert "private provider detail" not in advisor_response.value.text()
            health = page.locator("#advisor-data-health")
            expect(health).to_contain_text("交易日历不可用")
            expect(health).to_contain_text("联系数据管理员")
            assert order["blocking_status"] == "BLOCKED_PRICE_MISSING"
            advisor_orders = page.locator("#advisor-order-list")
            expect(advisor_orders).to_contain_text("状态：缺少有效现价，已阻断")
            expect(advisor_orders).not_to_contain_text("BLOCKED_PRICE_MISSING")
            assert order["price_band"]["low"] is None and order["price_band"]["high"] is None
            assert order["estimated_amount"] == 0 and order["estimated_price"] is None
            expected_prices = "预计金额：¥0 · 价格区间：暂无"
            expect(advisor_orders).to_contain_text(expected_prices)
            # Capture the button's clipboard write without replacing the host's clipboard.
            page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
                configurable: true, value: {writeText: async value => {window.copiedAdvisorList = value;}}
            })""")
            page.get_by_role("button", name="复制手工执行清单").click()
            copied = page.evaluate("window.copiedAdvisorList")
            assert " | amount=0 | price=暂无 | status=缺少有效现价，已阻断 | " in copied
            assert "BLOCKED_PRICE_MISSING" not in copied
            samples = page.evaluate("""() => [
                {estimated_amount:123.45,price_band:{low:9.9,high:10.1}},
                {estimated_amount:null,price_band:{low:null,high:8}},
                {estimated_amount:0,price_band:{label:'10.5 - 11'}},
                {estimated_amount:0,estimated_price:7.5},
                {estimated_amount:0,price_band:{price_low:3,price_high:4}},
                {estimated_amount:0,price_band:{label:'价格缺失'}},
                {estimated_amount:0,estimated_price:8.75,price_band:{low:null,high:null,label:'价格缺失'}}
            ].map(getAdvisorOrderPrices)""")
            assert samples == [
                {"amount": 123.45, "price": "9.90 - 10.10"},
                {"amount": None, "price": "8.00"},
                {"amount": 0, "price": "10.5 - 11"},
                {"amount": 0, "price": "7.50"},
                {"amount": 0, "price": "3.00 - 4.00"},
                {"amount": 0, "price": "暂无"},
                {"amount": 0, "price": "8.75"},
            ]
            # A future provider code must also stay out of the order's visible status line.
            status_text = page.evaluate("""() => {
                    const sheet = currentAdvisorSheet;
                    const order = {...sheet.order_intents[0], blocking_status: 'FUTURE_ORDER',
                        risk_gate_status: 'FUTURE_RISK', data_asof: {quote_freshness_status: 'FUTURE_QUOTE'}};
                    renderAdvisorSheet({...sheet, order_intents: [order]});
                    const text = document.querySelector('#advisor-order-list').innerText;
                    renderAdvisorSheet(sheet);
                    return text;
                }""")
            assert "状态：待核实 · 风控：待核实 · 数据：待核实" in status_text
            expect(page.locator("#workspace-account-selector")).to_have_value(str(account.pk))
            card = page.locator(
                f'[data-recommendation-id="{recommendation.recommendation_id}"].recommendation-card'
            )
            expect(card).to_contain_text("山东黄金研究样本")
            selector = page.locator("#workspace-account-selector")
            expect(selector.locator(f'option[value="{second_account.pk}"]')).to_be_attached()
            selector.select_option(str(empty_account.pk))
            expect(page.locator("#advisor-order-list")).to_contain_text("暂无建议订单")
            expect(page.locator("#advisor-verdict")).to_have_text("今日建议：复核")
            expect(page.locator("#advisor-blocked-orders")).to_have_text("0")
            expect(health).to_contain_text("决策数据：受限")
            stale_quote = {
                "status": "blocked",
                "must_not_use_for_decision": True,
                "freshness_status": "stale",
            }
            for next_health, message in [
                (RuntimeError("private provider detail"), "尚未取得可用于决策的核验结果"),
                ({"status": "ok", "must_not_use_for_decision": False}, "决策数据：可用"),
                ({"status": "blocked", "quotes": {"600547.SH": stale_quote}}, "行情数据已过期"),
            ]:
                source_health = next_health
                selector.select_option("default")
                expect(health).to_be_empty()
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == "/api/decision/advisor/sheet/"
                ) as updated:
                    selector.select_option(str(account.pk))
                assert updated.value.status == 200
                assert "private provider detail" not in updated.value.text()
                expect(health).to_contain_text(message)
            expect(card).to_contain_text("山东黄金研究样本")
            held = []

            def is_first_list(request):
                query = parse_qs(urlsplit(request.url).query)
                return (
                    urlsplit(request.url).path == "/api/decision/workspace/recommendations/"
                    and query.get("account_id") == [str(account.pk)]
                    and "include_ignored" not in query
                )

            def delay_first_list(route):
                if is_first_list(route.request):
                    held.append(route)
                else:
                    route.continue_()

            page.route("**/api/decision/workspace/recommendations/**", delay_first_list)
            with page.expect_request(is_first_list):
                page.locator('button[onclick="window.loadRecommendations()"]').click()
            expect(page.locator("#recommendations-list .app-loading-text")).to_be_visible()
            selector.select_option(str(second_account.pk))
            second_card = page.locator(
                f'.recommendation-card[data-recommendation-id="{second.recommendation_id}"]'
            )
            expect(second_card).to_contain_text("第二账户独立依据")
            assert held
            with page.expect_response(lambda response: is_first_list(response.request)) as resumed:
                held[0].continue_()
            assert resumed.value.status == 200
            resumed.value.finished()
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            expect(second_card).to_contain_text("第二账户独立依据")
            expect(card).to_have_count(0)
            page.unroute("**/api/decision/workspace/recommendations/**", delay_first_list)
            selector.select_option(str(account.pk))
            expect(card).to_contain_text("山东黄金研究样本")
            link = page.locator("#workspace-bridge-research-entry").get_by_role("link")
            target = f"/equity/detail/600547.SH/?account_id={account.pk}"
            expect(link).to_have_attribute("href", target)
            # The detail header renders before its quote request completes.
            # Keep the browser and its isolated providers alive for that response.
            with page.expect_response(
                lambda response: urlsplit(response.url).path == "/api/data-center/prices/quotes/"
                and parse_qs(urlsplit(response.url).query).get("asset_code") == ["600547.SH"]
            ) as quote:
                link.click()
            expect(page).to_have_url(live_server.url + target)
            expect(page.locator("#stockCode")).to_have_text("600547.SH")
            assert quote.value.status == 404
            assert quote.value.json() == {"detail": "No quote found."}
        finally:
            browser.close()
    assert not MarketThermometerConfigModel.objects.exists()
    assert set(methods) == {"GET"}
    assert loopback_only_python_network == []


@pytest.mark.django_db(transaction=True)
def test_real_research_and_authorized_professional_return(
    live_server, django_user_model, subprocess_policy
) -> None:
    """Ordinary/admin desktop/mobile users complete a real read and return."""

    sessions = _sessions(django_user_model)
    output = _artifact_directory()
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
                    shell_ready_marks = page.evaluate(
                        "performance.getEntriesByName('agomtui:shell-ready').map(item => item.startTime)"
                    )
                    task_entry_started_ms = page.evaluate("performance.now()")
                    page.locator(f'[data-task-home] [data-experience-screen-key="{TASK}"]').click()
                    expect(page.locator("[data-main-panel] .tui-action-entry-form")).to_be_visible()
                    assert not any(urlsplit(url).path == ACTION_PATH for _, url in requests)
                    requested = "研究夹具" if role == "user" and width == 1440 else "600000.SH"
                    response = _submit(page, requested, keyboard=True)
                    action_posts = [
                        (method, url)
                        for method, url in requests
                        if urlsplit(url).path == ACTION_PATH
                    ]
                    assert len(action_posts) == 1
                    assert action_posts[0][0] == "POST"
                    assert urlsplit(action_posts[0][1]).netloc == urlsplit(live_server.url).netloc
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
                    first_summary_visible_ms = (
                        page.evaluate("performance.now()") - task_entry_started_ms
                    )
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
                    return_read_started_ms = page.evaluate("performance.now()")
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path == ACTION_PATH
                    ) as returned:
                        page.locator("[data-next-step-return]").click()
                    assert returned.value.json()["outcome"] == "success"
                    expect(page.locator(".tui-research-evidence-section")).to_have_count(6)
                    return_result_visible_ms = (
                        page.evaluate("performance.now()") - return_read_started_ms
                    )
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
                            "local_automation_observations": {
                                "scope": "Actual local fixture UI assertions; server cache not forced cold; no production speed or P95 claim",
                                "browser_context": "fresh for this role/viewport",
                                "shell_ready_mark_ms": (
                                    shell_ready_marks[-1] if shell_ready_marks else None
                                ),
                                "task_entry_to_visible_summary_ms": first_summary_visible_ms,
                                "same_context_professional_return_to_visible_result_ms": return_result_visible_ms,
                                "request_count": len(requests),
                                "business_action_request_count": sum(
                                    urlsplit(url).path.startswith("/api/tui/actions/")
                                    for _, url in requests
                                ),
                            },
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
