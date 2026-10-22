"""Exercise the TUX-10 candidate shell against real local Django auth and metadata.

No owner responses are intercepted. This checks navigation and diagnostics scope;
it does not establish research, financial-data, human or production acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import expect, sync_playwright

from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

TASK_ENTRY_SCREEN_EXPECTATIONS = {
    "today": "task.today-focus",
    "research": "task.asset-research",
    "portfolio": "task.portfolio-check",
    "account-inspection": "task.account-inspection",
}
TASK_ENTRY_P0_PANEL_EXPECTATIONS = {
    "today": "today-focus-market-context",
    "portfolio": "portfolio-check-selector",
    "account-inspection": "account-inspection-run",
}


def _artifact_directory(suite: str) -> Path:
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
    directory = root / f"{safe_label or 'candidate'}-{uuid4().hex}-{suite}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture
def _playwright_subprocess_policy() -> Iterator[None]:
    """Restore the prior policy after this subprocess-based Windows browser test."""
    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_policy)


@pytest.mark.django_db(transaction=True)
def test_task_shell_on_real_local_django(live_server, _playwright_subprocess_policy):
    output = _artifact_directory("shell")
    cases = []
    sessions = []
    for administrator in (False, True):
        user = get_user_model().objects.create_user(
            username=f"tux07-browser-{administrator}",
            password="local-browser-test-only",
            is_staff=administrator,
        )
        role_client = Client()
        role_client.force_login(user)
        sessions.append((administrator, role_client.cookies[settings.SESSION_COOKIE_NAME].value))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for administrator, session_cookie in sessions:
                for width, height in ((1440, 1000), (390, 844)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    context.add_cookies(
                        [
                            {
                                "name": settings.SESSION_COOKIE_NAME,
                                "value": session_cookie,
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
                    role = "admin" if administrator else "user"
                    try:
                        expect(page.locator("[data-task-home]")).to_be_visible()
                    except AssertionError:
                        diagnostic = output / f"shell-failure-{role}-{width}"
                        page.screenshot(path=str(diagnostic.with_suffix(".png")), full_page=True)
                        diagnostic.with_suffix(".json").write_text(
                            json.dumps(
                                {
                                    "url": page.url,
                                    "body": page.locator("body").inner_text(),
                                    "requests": requests,
                                    "page_errors": failures,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        raise
                    entry_nodes = page.locator(
                        "[data-task-home] [data-experience-entry]"
                    ).evaluate_all(
                        "nodes => nodes.map(node => ({"
                        "key: node.dataset.experienceEntry, "
                        "screenKey: node.dataset.experienceScreenKey"
                        "}))"
                    )
                    assert len(entry_nodes) == len(TASK_ENTRY_SCREEN_EXPECTATIONS)
                    entry_screens = {
                        str(node["key"]): str(node["screenKey"]) for node in entry_nodes
                    }
                    assert entry_screens == TASK_ENTRY_SCREEN_EXPECTATIONS
                    for entry_key, screen_key in TASK_ENTRY_SCREEN_EXPECTATIONS.items():
                        response = page.request.get(
                            f"{live_server.url}/api/tui/screens/{screen_key}/"
                        )
                        assert response.status == 200, f"{entry_key}: {response.status}"
                        payload = response.json()
                        screen = payload.get("screen")
                        assert isinstance(screen, dict), f"{entry_key}: missing screen contract"
                        assert screen.get("key") == screen_key
                        if entry_key == "research":
                            entry_state = screen.get("entry_state")
                            assert isinstance(entry_state, dict)
                            assert entry_state.get("mode") == "parameter_gate"
                            assert screen.get("default_action_key") == "equity.research-snapshot"
                            continue
                        panels = screen.get("dashboard_panels")
                        assert isinstance(panels, list), f"{entry_key}: missing dashboard panels"
                        p0_keys = {
                            str(panel.get("key") or "")
                            for panel in panels
                            if isinstance(panel, dict)
                            and str(panel.get("user_priority") or "").lower() == "p0"
                        }
                        assert TASK_ENTRY_P0_PANEL_EXPECTATIONS[entry_key] in p0_keys

                    assert any(
                        urlsplit(url).path == "/static/css/tui-workbench.css"
                        and urlsplit(url).query == "v=tui-task-first-20261018"
                        for _, url in requests
                    )
                    assert any(
                        urlsplit(url).path == "/static/js/tui-workbench.js"
                        and urlsplit(url).query == "v=tui-task-first-20261018"
                        for _, url in requests
                    )
                    catalog = page.request.get(f"{live_server.url}/api/tui/catalog/").json()
                    assert catalog["diagnostics"]["raw_response_allowed"] is administrator
                    before = list(requests)
                    route = page.url
                    history_length = page.evaluate("history.length")
                    page.keyboard.press("F6")
                    page.keyboard.press("Control+Enter")
                    assert requests == before
                    assert page.url == route
                    assert page.evaluate("history.length") == history_length
                    page.keyboard.press("F9")
                    assert page.evaluate(
                        "Boolean(document.activeElement && document.activeElement.closest('[data-task-home] [data-experience-entry]'))"
                    )
                    assert not page.evaluate(
                        "Boolean(document.activeElement && document.activeElement.closest('[hidden]'))"
                    )
                    assert requests == before
                    task_mode = page.locator('[data-experience-mode="task"]')
                    professional_mode = page.locator('[data-experience-mode="professional"]')
                    assert page.locator('[data-experience-mode][tabindex="0"]').count() == 1
                    expect(task_mode).to_have_attribute("aria-selected", "true")
                    task_mode.focus()
                    page.keyboard.press("End")
                    expect(professional_mode).to_have_attribute("aria-selected", "true")
                    expect(professional_mode).to_have_attribute("tabindex", "0")
                    expect(task_mode).to_have_attribute("tabindex", "-1")
                    assert page.evaluate(
                        "document.activeElement === document.querySelector('[data-experience-mode=professional]')"
                    )
                    page.keyboard.press("Home")
                    expect(task_mode).to_have_attribute("aria-selected", "true")
                    expect(task_mode).to_have_attribute("tabindex", "0")
                    expect(professional_mode).to_have_attribute("tabindex", "-1")
                    page.keyboard.press("ArrowRight")
                    expect(professional_mode).to_have_attribute("aria-selected", "true")
                    page.keyboard.press("Shift+Tab")
                    assert not page.evaluate(
                        "Boolean(document.activeElement && document.activeElement.closest('[hidden]'))"
                    )
                    assert page.locator('[data-experience-mode][tabindex="0"]').count() == 1
                    task_mode.focus()
                    page.keyboard.press("Home")
                    expect(task_mode).to_have_attribute("aria-selected", "true")
                    expect(task_mode).to_have_attribute("tabindex", "0")
                    expect(professional_mode).to_have_attribute("tabindex", "-1")
                    assert requests == before
                    assert page.url == route
                    assert page.evaluate("history.length") == history_length
                    assert not failures
                    assert all(
                        urlsplit(url).netloc == urlsplit(live_server.url).netloc
                        for _, url in requests
                    )
                    assert all(method == "GET" for method, _ in requests)
                    api_paths = [
                        urlsplit(url).path
                        for _, url in requests
                        if urlsplit(url).path.startswith("/api/")
                    ]
                    assert all(
                        path.startswith(
                            ("/api/tui/bootstrap/", "/api/tui/catalog/", "/api/tui/screens/")
                        )
                        for path in api_paths
                    ), api_paths
                    expect(page.locator("[data-raw-toggle]")).to_be_hidden()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(output / f"shell-{role}-{width}.png"), full_page=True)
                    page.locator(
                        '[data-task-home] [data-experience-entry="account-inspection"]'
                    ).click()
                    expect(
                        page.locator(
                            '.tui-experience-rail-entry.is-active[data-screen-key="task.account-inspection"]'
                        )
                    ).to_have_count(1)
                    expect(
                        page.locator(
                            '[data-dashboard-panel="account-inspection-run"]'
                            '[data-panel-priority="p0"]'
                        )
                    ).to_be_visible()
                    assert all(method == "GET" for method, _ in requests)
                    assert all(
                        urlsplit(url).netloc == urlsplit(live_server.url).netloc
                        for _, url in requests
                    )
                    api_paths = [
                        urlsplit(url).path
                        for _, url in requests
                        if urlsplit(url).path.startswith("/api/")
                    ]
                    assert all(
                        path.startswith(
                            ("/api/tui/bootstrap/", "/api/tui/catalog/", "/api/tui/screens/")
                        )
                        or path == "/api/tui/operator/governance-queue/"
                        for path in api_paths
                    ), api_paths
                    forbidden = ["broker-execution.qmt-setup"] if not administrator else []
                    for target in ["unknown.workspace", *forbidden]:
                        page.goto(
                            f"{live_server.url}/tui/?screen={target}", wait_until="networkidle"
                        )
                        expect(page.locator(".tui-application-error")).to_be_visible()
                        assert urlsplit(page.url).query == f"screen={target}"
                        assert page.locator("[data-task-home]").count() == 0
                        page.locator("[data-panel-recovery-screen]").first.click()
                        expect(page.locator("[data-task-home]")).to_be_visible()
                        assert page.locator("[data-dashboard-panel]").count() == 0
                        assert "screen=" not in urlsplit(page.url).query
                    cases.append(
                        {
                            "role": role,
                            "viewport": [width, height],
                            "requests": requests,
                            "page_errors": failures,
                        }
                    )
                    context.close()
            (output / "shell-real-server-review.json").write_text(
                json.dumps(
                    {
                        "scope": "Real isolated local Django shell, auth and metadata; no owner-result or production acceptance",
                        "cases": cases,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            browser.close()
