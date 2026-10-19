"""Loopback browser journeys for the read-only single-asset research TUI.

The real authenticated TUI action, owner HTTP view, composition factory,
application use case, and renderer remain in the path. Only the Data Center
reader port is supplied by an explicit local fixture; this is test admission,
not production source activation or external-provider evidence.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client
from playwright.sync_api import Page, Response, Route, expect, sync_playwright

from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.runtime_config import configure_critical_runtime

SCREEN = "task.asset-research"
ACTION_KEY = "equity.research-snapshot"
ACTION_PATH = f"/api/tui/actions/{ACTION_KEY}/run/"
ASSET_CODE = "600000.SH"
EXPECTED_RESEARCH_CALLS = (
    ("get_decision_readiness", None),
    ("resolve_asset", ASSET_CODE),
    ("get_latest_quotes", ASSET_CODE),
    ("get_price_history", ASSET_CODE),
    ("get_valuations", ASSET_CODE),
    ("get_financials", ASSET_CODE),
    ("get_news", ASSET_CODE),
    ("get_capital_flows", ASSET_CODE),
)


@dataclass(frozen=True)
class ResearchCase:
    """Owner-reader financial payload and expected owner outcome for one journey."""

    name: str
    expected_outcome: str
    financial_payload: dict[str, object]


@dataclass
class FixtureDataCenterResearchReader:
    """Explicit local implementation of the owner Data Center read port."""

    financial_payload: dict[str, object]
    calls: list[tuple[str, str | None]]

    def resolve_asset(self, stock_code: str) -> Mapping[str, object]:
        """Resolve the fixture request to one canonical local equity identity."""
        self.calls.append(("resolve_asset", stock_code))
        return {
            "code": ASSET_CODE,
            "name": "浦发银行",
            "asset_class": "equity",
            "currency": "CNY",
        }

    def get_decision_readiness(self) -> Mapping[str, object]:
        """Return test-only readiness without contacting providers or production."""
        self.calls.append(("get_decision_readiness", None))
        return {
            "status": "ok",
            "must_not_use_for_decision": False,
            "checks": {"fixture_read_port": {"status": "ok"}},
        }

    def get_latest_quotes(
        self,
        stock_code: str,
        *,
        strict_freshness: bool = True,
    ) -> Mapping[str, object]:
        """Return one fixture quote through the owner reader contract."""
        assert strict_freshness is True
        self.calls.append(("get_latest_quotes", stock_code))
        return {
            "rows": [
                {
                    "asset_code": ASSET_CODE,
                    "current_price": 9.42,
                    "currency": "CNY",
                    "source": "local-owner-read-port",
                    "snapshot_at": "2026-10-19T01:55:00Z",
                }
            ]
        }

    def get_price_history(self, stock_code: str, *, limit: int) -> Mapping[str, object]:
        """Return one bounded fixture price bar through the owner reader contract."""
        assert limit > 0
        self.calls.append(("get_price_history", stock_code))
        return {
            "bars": [
                {
                    "asset_code": ASSET_CODE,
                    "bar_date": "2026-10-16",
                    "freq": "daily",
                    "close": 9.31,
                    "source": "local-owner-read-port",
                }
            ]
        }

    def get_valuations(self, stock_code: str, *, limit: int) -> Mapping[str, object]:
        """Return one fixture valuation through the owner reader contract."""
        assert limit > 0
        self.calls.append(("get_valuations", stock_code))
        return {
            "valuations": [
                {
                    "asset_code": ASSET_CODE,
                    "pe_ttm": 6.8,
                    "unit": "ratio",
                    "val_date": "2026-10-16",
                    "source": "local-owner-read-port",
                }
            ]
        }

    def get_financials(self, stock_code: str, *, limit: int) -> Mapping[str, object]:
        """Return the explicit partial or blocked financial publication fixture."""
        assert limit > 0
        self.calls.append(("get_financials", stock_code))
        return self.financial_payload

    def get_news(self, stock_code: str, *, limit: int) -> Mapping[str, object]:
        """Return one fixture news row through the owner reader contract."""
        assert limit > 0
        self.calls.append(("get_news", stock_code))
        return {
            "news": [
                {
                    "asset_code": ASSET_CODE,
                    "title": "本地研究浏览器测试材料",
                    "published_at": "2026-10-19T01:40:00Z",
                    "source": "local-owner-read-port",
                }
            ]
        }

    def get_capital_flows(self, stock_code: str, *, limit: int) -> Mapping[str, object]:
        """Return one fixture capital-flow row through the owner reader contract."""
        assert limit > 0
        self.calls.append(("get_capital_flows", stock_code))
        return {
            "flows": [
                {
                    "asset_code": ASSET_CODE,
                    "flow_date": "2026-10-19",
                    "main_net": 1250000,
                    "unit": "CNY",
                    "source": "local-owner-read-port",
                }
            ]
        }


@dataclass
class ResearchBrowserRun:
    """Live browser state and evidence captured for a single local journey."""

    page: Page
    live_server: Any
    reader: FixtureDataCenterResearchReader
    requests: list[dict[str, str]]
    nonlocal_browser_attempts: list[str]
    page_errors: list[str]
    request_failures: list[str]

    def assert_local_traffic(self) -> None:
        """Require the browser to use only this live-server origin."""
        expected_netloc = urlsplit(self.live_server.url).netloc
        assert expected_netloc
        assert all(urlsplit(item["url"]).netloc == expected_netloc for item in self.requests)
        assert self.nonlocal_browser_attempts == []
        assert self.request_failures == []
        assert self.page_errors == []
        action_posts = [
            item
            for item in self.requests
            if item["method"] == "POST" and urlsplit(item["url"]).path == ACTION_PATH
        ]
        assert len(action_posts) == 1
        assert self.reader.calls == list(EXPECTED_RESEARCH_CALLS)


def _financial_payload(*, blocked: bool) -> dict[str, object]:
    """Build one explicit owner fact with nullable source clocks and real coverage counts."""
    payload: dict[str, object] = {
        "publication_outcome": "partial",
        "coverage_requested_count": 4,
        "coverage_eligible_count": 3,
        "coverage_selected_count": 2,
        "coverage_missing_count": 1,
        "rows": [
            {
                "asset_code": ASSET_CODE,
                "metric_code": "revenue",
                "value": 123.45,
                "unit": "CNY",
                "period_end": "2025-12-31",
                "report_date": "2026-03-31",
                "observed_at": None,
                "available_at": None,
                "source_observed_at": None,
                "source_available_at": None,
                "fetched_at": "2026-10-19T01:58:00Z",
                "source": "local-owner-read-port",
            }
        ],
    }
    if blocked:
        payload.update(
            {
                "must_not_use_for_decision": True,
                "block_reason_code": "publication_member_fact_changed",
                "freshness_status": "blocked",
            }
        )
    return payload


@pytest.fixture
def research_case(request: pytest.FixtureRequest) -> ResearchCase:
    """Select a named test-only owner payload without altering production activation."""
    case_name = request.param
    assert case_name in {"partial", "blocked"}
    blocked = case_name == "blocked"
    return ResearchCase(
        name=case_name,
        expected_outcome="blocked" if blocked else "partial",
        financial_payload=_financial_payload(blocked=blocked),
    )


@pytest.fixture
def reader_calls() -> list[tuple[str, str | None]]:
    """Collect owner reads so the browser journey proves the real UseCase path."""
    return []


@pytest.fixture
def research_reader(
    monkeypatch: pytest.MonkeyPatch,
    research_case: ResearchCase,
    reader_calls: list[tuple[str, str | None]],
) -> FixtureDataCenterResearchReader:
    """Inject only the composition's owner Data Center read port."""
    import apps.equity.research_snapshot_composition as composition

    reader = FixtureDataCenterResearchReader(
        financial_payload=research_case.financial_payload,
        calls=reader_calls,
    )
    monkeypatch.setattr(composition, "DataCenterEquityResearchSnapshotReader", lambda: reader)
    return reader


@pytest.fixture
def test_only_runtime_admission() -> None:
    """Seed the isolated test DB's critical values; this does not activate production."""
    assert not str(os.environ.get("DJANGO_SETTINGS_MODULE", "")).endswith(".production")
    configure_critical_runtime()


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Apply and restore the repository's Windows Chromium subprocess policy."""
    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


@pytest.fixture(autouse=True)
def loopback_only_python_network(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[str]]:
    """Reject and record Python socket attempts outside loopback before transport."""
    attempts: list[str] = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
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

    def reject(kind: str, host: object) -> None:
        attempts.append(f"{kind}:{host!r}")
        raise AssertionError(f"research browser attempted nonlocal network: {kind}:{host!r}")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        host = host_from_address(address)
        if not is_local_host(host):
            reject("connect", host)
        return original_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: object) -> int:
        host = host_from_address(address)
        if not is_local_host(host):
            reject("connect_ex", host)
        return original_connect_ex(sock, address)

    def guarded_create_connection(
        address: object, *args: object, **kwargs: object
    ) -> socket.socket:
        host = host_from_address(address)
        if not is_local_host(host):
            reject("create_connection", host)
        return original_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not is_local_host(host):
            reject("getaddrinfo", host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield attempts


@pytest.fixture
def browser_journey(
    live_server: Any,
    django_user_model: Any,
    research_reader: FixtureDataCenterResearchReader,
    test_only_runtime_admission: None,
    subprocess_policy: None,
    loopback_only_python_network: list[str],
    request: pytest.FixtureRequest,
) -> Iterator[ResearchBrowserRun]:
    """Open the real screen with a real session cookie and a loopback-only browser."""
    owner = django_user_model.objects.create_user(
        username=f"research-browser-{uuid4().hex[:12]}",
        password="local-research-browser-test-only",
        is_staff=False,
    )
    client = Client()
    client.force_login(owner)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    requests: list[dict[str, str]] = []
    nonlocal_browser_attempts: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []

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
            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", enforce_local_origin)
        page = context.new_page()
        page.on(
            "request",
            lambda browser_request: requests.append(
                {"method": browser_request.method, "url": browser_request.url}
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda browser_request: request_failures.append(
                f"{browser_request.method} {browser_request.url}: {browser_request.failure}"
            ),
        )
        run = ResearchBrowserRun(
            page=page,
            live_server=live_server,
            reader=research_reader,
            requests=requests,
            nonlocal_browser_attempts=nonlocal_browser_attempts,
            page_errors=page_errors,
            request_failures=request_failures,
        )
        try:
            page.goto(
                f"{live_server.url}/tui/?screen={SCREEN}",
                wait_until="networkidle",
            )
            expect(page.locator("[data-main-panel] .tui-action-entry-form")).to_be_visible()
            yield run
        finally:
            evidence = (
                Path(settings.BASE_DIR)
                / ".tmp/ash04-research-browser-evidence"
                / f"{request.node.name}-{uuid4().hex[:12]}"
            )
            evidence.mkdir(parents=True, exist_ok=False)
            screenshot_path = evidence / "viewport.png"
            if not page.is_closed():
                page.screenshot(path=str(screenshot_path), full_page=True)
            evidence_payload = {
                "case": request.node.name,
                "screen": SCREEN,
                "production_activation": False,
                "reader_port_calls": research_reader.calls,
                "browser_requests": requests,
                "nonlocal_browser_attempts": nonlocal_browser_attempts,
                "nonlocal_python_socket_attempts": loopback_only_python_network,
                "request_failures": request_failures,
                "page_errors": page_errors,
                "screenshot": str(screenshot_path),
            }
            (evidence / "journey.json").write_text(
                json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            context.close()
            browser.close()
            assert loopback_only_python_network == []
            run.assert_local_traffic()


def _submit_research(page: Page, live_server: Any) -> Response:
    """Submit the rendered single-asset action and wait for its real response."""
    form = page.locator("[data-main-panel] .tui-action-entry-form")
    if not form.is_visible():
        disclosure = page.locator("[data-research-again-entry] > summary")
        if disclosure.count() == 1:
            disclosure.click()
    expect(form).to_be_visible()
    expect(form).to_contain_text("股票名称或代码")
    form.locator('[name="stock_code"]').fill(ASSET_CODE)
    submit = form.locator(".tui-action-button")
    expect(submit).to_have_text("开始研究")
    with page.expect_response(
        lambda response: urlsplit(response.url).path == ACTION_PATH
    ) as response_info:
        submit.click()
    response = response_info.value
    assert urlsplit(response.url).netloc == urlsplit(live_server.url).netloc
    assert response.request.method == "POST"
    return response


def _owner_result(response: Response, expected_outcome: str) -> dict[str, Any]:
    """Check the actual TUI action transport and owner outcome envelope."""
    assert response.status == 200
    assert response.headers.get("content-type", "").split(";", 1)[0] == "application/json"
    result = response.json()
    assert isinstance(result, dict)
    assert result["outcome"] == expected_outcome
    assert result["response"]["status_code"] == 200
    assert result["view_model"]["outcome"] == expected_outcome
    assert result["debug"] == {"raw_available": False, "raw_response": None}
    return result


def _financial_section(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the actual financial section from the rendered TUI view model."""
    view_model = result["view_model"]
    assert isinstance(view_model, Mapping)
    sections = view_model["sections"]
    assert isinstance(sections, list)
    section = next(item for item in sections if item["key"] == "financials")
    assert isinstance(section, dict)
    return section


def _open_financial_section(page: Page) -> Any:
    """Expand the actual financial evidence section in the browser."""
    financial = page.locator(".tui-research-evidence-section").filter(
        has=page.locator(".tui-research-evidence-label", has_text="财务")
    )
    assert financial.count() == 1
    if financial.get_attribute("open") is None:
        financial.locator(":scope > summary").click()
    expect(financial).to_have_attribute("open", "")
    return financial


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("research_case", ["partial"], indirect=True)
def test_partial_financial_coverage_is_visible_and_keeps_this_asset_row(
    research_case: ResearchCase,
    browser_journey: ResearchBrowserRun,
) -> None:
    """The TUI shows partial scope at P0 while preserving its financial fact."""
    page = browser_journey.page
    response = _submit_research(page, browser_journey.live_server)
    result = _owner_result(response, research_case.expected_outcome)
    section = _financial_section(result)
    assert section["owner_status"] == "partial"
    assert section["must_not_use_for_decision"] is False
    assert section["item_count"] == 1
    assert section["rows"][0]["fields"]
    fields = {field["key"]: field["value"] for field in section["rows"][0]["fields"]}
    assert fields["asset_code"] == ASSET_CODE
    assert fields["metric_code"] == "revenue"
    assert fields["value"] == "123.45"
    assert fields["unit"] == "CNY"
    assert fields["fetched_at"] == "2026-10-19T01:58:00Z"
    source_times = section.get("source_times", [])
    source_fields = {item["field"] for item in source_times}
    assert source_fields.isdisjoint(
        {"observed_at", "available_at", "source_observed_at", "source_available_at"}
    )
    assert "fetched_at" in source_fields

    p0_gaps = page.locator('[data-research-fact-key="evidence_gaps"]')
    expect(p0_gaps).to_be_visible()
    for text in (
        "本次财务发布范围",
        "部分返回",
        "请求：4",
        "符合条件：3",
        "已选入：2",
        "缺失：1",
    ):
        expect(p0_gaps).to_contain_text(text)

    financial = _open_financial_section(page)
    for text in (ASSET_CODE, "revenue", "123.45", "CNY"):
        expect(financial).to_contain_text(text)
    clocks = financial.locator(".tui-research-evidence-clocks")
    expect(clocks).to_be_visible()
    if clocks.get_attribute("open") is None:
        clocks.locator(":scope > summary").click()
    expect(clocks).to_have_attribute("open", "")
    expect(clocks).to_contain_text("抓取时间")
    expect(clocks).not_to_contain_text("观测时间")
    expect(clocks).not_to_contain_text("可用时间")
    browser_journey.assert_local_traffic()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("research_case", ["blocked"], indirect=True)
def test_financial_block_keeps_original_reason_and_non_decision_warning_visible(
    research_case: ResearchCase,
    browser_journey: ResearchBrowserRun,
) -> None:
    """A blocked financial publication remains visible with its stable reason."""
    page = browser_journey.page
    response = _submit_research(page, browser_journey.live_server)
    result = _owner_result(response, research_case.expected_outcome)
    view_model = result["view_model"]
    assert view_model["must_not_use_for_decision"] is True
    section = _financial_section(result)
    assert section["owner_status"] == "blocked"
    assert section["must_not_use_for_decision"] is True
    assert section["block_reason_code"] == "publication_member_fact_changed"
    assert section["item_count"] == 1
    assert section["rows"][0]["fields"]

    p0_gaps = page.locator('[data-research-fact-key="evidence_gaps"]')
    expect(p0_gaps).to_be_visible()
    expect(p0_gaps).to_contain_text("本次财务发布范围")
    expect(p0_gaps).to_contain_text("数据与发布记录不一致")
    expect(page.locator("[data-research-compact-summary]")).to_contain_text("禁止用于决策")

    financial = _open_financial_section(page)
    reason = financial.locator(".tui-research-evidence-reason")
    expect(reason).to_have_attribute("data-reason-code", "publication_member_fact_changed")
    expect(reason).to_contain_text("数据与发布记录不一致")
    expect(financial).to_contain_text("禁止用于决策")
    for text in (ASSET_CODE, "revenue", "123.45", "CNY"):
        expect(financial).to_contain_text(text)
    browser_journey.assert_local_traffic()
