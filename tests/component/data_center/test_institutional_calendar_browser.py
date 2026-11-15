"""Real ordinary-user TUI journeys over migrated, source-bound calendar data."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client
from django.urls import get_resolver
from playwright.sync_api import Route, expect, sync_playwright
from pytest_django.plugin import DjangoDbBlocker

from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.institutional_calendar_import import import_nbs_calendar_originals
from tests.component.equity.test_research_snapshot_tui_browser import loopback_python_network_guard
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.institutional_calendar_world import retained_originals
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime

SCREEN = "research.institutional-calendar"
ACTION_PATH = "/api/tui/actions/data-center.institutional-calendar-read/run/"


@pytest.fixture(scope="module", autouse=True)
def initialize_complete_url_registry(
    django_db_setup: object, django_db_blocker: DjangoDbBlocker
) -> None:
    """Load real route definitions before the per-case restricted flush app scope."""
    with django_db_blocker.unblock():
        assert_native_postgres_test_database(expected_name="cal02_institutional_calendar_qa")
        tuple(get_resolver().url_patterns)


@pytest.fixture
def local_network_only(monkeypatch: pytest.MonkeyPatch):
    yield from loopback_python_network_guard(monkeypatch)


@pytest.mark.django_db(
    transaction=True,
    available_apps=(
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.staticfiles",
        "apps.account",
        "apps.audit",
        "apps.config_center",
        "apps.data_center",
        "apps.terminal",
    ),
)
@pytest.mark.parametrize(
    "case,width,height",
    [
        ("qualified", 1440, 1000),
        ("qualified", 390, 844),
        ("unknown", 1440, 1000),
        ("expired", 1440, 1000),
        ("empty", 1440, 1000),
        ("historical", 1440, 1000),
    ],
)
def test_ordinary_user_completes_source_bound_calendar_task(
    live_server: Any,
    django_user_model: Any,
    local_network_only: list[str],
    case: str,
    width: int,
    height: int,
) -> None:
    """Use one rendered form, the real TUI runner and the actual owner/ORM read path."""
    assert_native_postgres_test_database(expected_name="cal02_institutional_calendar_qa")
    configure_critical_runtime()
    schedule, actual = retained_originals()
    import_nbs_calendar_originals(
        schedule=schedule,
        actual=actual,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    if case == "unknown":
        ProviderConfigModel.objects.filter(name=schedule.policy.source_id).update(is_active=False)
    if case == "expired":
        provider = ProviderConfigModel.objects.get(name=schedule.policy.source_id)
        extra = dict(provider.extra_config)
        policy = dict(extra["institutional_calendar"])
        policy["valid_until"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        extra["institutional_calendar"] = policy
        ProviderConfigModel.objects.filter(pk=provider.pk).update(extra_config=extra)
    owner = django_user_model.objects.create_user(
        username="calendar-browser-" + uuid4().hex[:10],
        password="calendar-test-only",
        is_staff=False,
        is_superuser=False,
    )
    client = Client()
    client.force_login(owner)
    original_loop_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    evidence = (
        Path(
            os.environ.get(
                "CAL02_BROWSER_EVIDENCE_DIR",
                str(
                    Path(settings.BASE_DIR)
                    / "artifacts/cal02-institutional-calendar-20261115/browser"
                ),
            )
        )
        / f"{case}-{width}-{uuid4().hex[:8]}"
    )
    evidence.mkdir(parents=True, exist_ok=False)
    nonlocal_requests: list[str] = []
    errors: list[str] = []
    try:
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
                target = urlsplit(route.request.url)
                if target.netloc != urlsplit(live_server.url).netloc:
                    nonlocal_requests.append(route.request.url)
                    route.abort("blockedbyclient")
                else:
                    route.continue_()

            context.route("**/*", local_only)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(live_server.url + "/tui/?screen=" + SCREEN, wait_until="networkidle")
            page.locator(
                '[data-main-panel] [data-dashboard-action="data-center.institutional-calendar-read"][data-dashboard-open]'
            ).first.click()
            form = (
                page.locator("form.tui-action-form:visible")
                .filter(has=page.locator('[name="date_from"]'))
                .first
            )
            try:
                expect(form).to_be_visible()
            except AssertionError:
                page.screenshot(path=str(evidence / "form-failure.png"), full_page=True)
                (evidence / "form-failure.html").write_text(page.content(), encoding="utf-8")
                raise
            start, end = (
                ("2027-01-01", "2027-01-31") if case == "empty" else ("2026-11-01", "2026-12-31")
            )
            form.locator('[name="date_from"]').fill(start)
            form.locator('[name="date_to"]').fill(end)
            form.locator('[name="known_at"]').fill(
                "2026-11-09T01:29:00Z" if case == "historical" else actual.recorded_at.isoformat()
            )
            form.locator('[name="mode"]').select_option(
                "market_available" if case == "historical" else "system_known"
            )
            page.screenshot(path=str(evidence / "query-form.png"), full_page=False)
            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_PATH
            ) as response_info:
                form.locator(".tui-action-submit").click()
            response = response_info.value
            payload = response.json()
            (evidence / "response.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            assert response.status == 200
            assert payload["response"]["status_code"] == 200
            model = payload["view_model"]
            assert model["kind"] == "datagrid"
            rendered = json.dumps(model, ensure_ascii=False)
            assert "来源与研究边界" in rendered and "研究未完成" in rendered
            expect(page.locator("[data-main-panel]")).to_contain_text("研究未完成")
            if case == "qualified":
                assert "已确认" in rendered and "已实际发布" in rendered and "暂定" in rendered
                assert "六候自然日窗口" in rendered and "www.stats.gov.cn" in rendered
            elif case in {"unknown", "expired"}:
                assert "已确认" not in rendered
                assert "来源待核验" in rendered
                assert ("已过期" if case == "expired" else "缺失或不唯一") in rendered
            elif case == "empty":
                assert "官方发布" not in rendered
                assert "自然日窗口" in rendered
            else:
                assert "已确认" not in rendered and "暂定" in rendered
                assert "市场可得重建" in rendered
            page.screenshot(path=str(evidence / "result-viewport.png"), full_page=False)
            page.screenshot(path=str(evidence / "result-full.png"), full_page=True)
            if case == "qualified" and width >= 1000:
                page.get_by_role("row").filter(has_text="2026-11-09").first.click()
                link = page.get_by_text(actual.url, exact=True).filter(visible=True).first
                link.scroll_into_view_if_needed()
                expect(link).to_be_in_viewport()
                source_clock = (
                    page.get_by_text(actual.first_seen_at.isoformat(), exact=True)
                    .filter(visible=True)
                    .first
                )
                source_clock.scroll_into_view_if_needed()
                expect(source_clock).to_be_in_viewport()
                page.screenshot(path=str(evidence / "confirmed-source-detail.png"), full_page=False)
            (evidence / "sources.json").write_text(
                json.dumps(
                    {
                        "schedule_sha256": schedule.sha256,
                        "actual_sha256": actual.sha256,
                        "first_seen_schedule": schedule.first_seen_at.isoformat(),
                        "first_seen_actual": actual.first_seen_at.isoformat(),
                        "recorded_at": actual.recorded_at.isoformat(),
                        "ordinary_user": not owner.is_staff and not owner.is_superuser,
                        "case": case,
                        "viewport": [width, height],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            context.close()
            browser.close()
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_loop_policy)
    assert nonlocal_requests == [] and errors == [] and local_network_only == []
