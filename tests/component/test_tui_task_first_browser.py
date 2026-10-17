"""Exercise the delivered shell against real local Django auth and metadata.

No owner responses are intercepted. This checks navigation and diagnostics scope;
it does not establish research, financial-data, human or production acceptance.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from playwright.sync_api import expect, sync_playwright

from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy


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
    output = Path(settings.BASE_DIR) / "docs/testing/tui-task-first-2026-10-17"
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
                        "request", lambda request: requests.append((request.method, request.url))
                    )
                    page.on("pageerror", lambda error: failures.append(str(error)))
                    page.goto(f"{live_server.url}/tui/", wait_until="networkidle")
                    try:
                        expect(page.locator("[data-task-home]")).to_be_visible()
                    except AssertionError:
                        diagnostic = Path(settings.BASE_DIR) / ".tmp/tux07-browser-failure"
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
                    assert page.locator("[data-task-home] [data-experience-entry]").count() == 3
                    catalog = page.request.get(f"{live_server.url}/api/tui/catalog/").json()
                    assert catalog["diagnostics"]["raw_response_allowed"] is administrator
                    before = list(requests)
                    route = page.url
                    history_length = page.evaluate("history.length")
                    page.locator('[data-experience-mode="professional"]').click()
                    page.locator('[data-experience-mode="task"]').click()
                    page.wait_for_timeout(250)
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
                    role = "admin" if administrator else "user"
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / f"shell-{role}-{width}.png"), full_page=True)
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
