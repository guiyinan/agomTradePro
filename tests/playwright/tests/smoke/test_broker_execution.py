"""Browser acceptance coverage for the governed QMT Classic Web surfaces."""

from __future__ import annotations

import pytest
from playwright.sync_api import ConsoleMessage, Page, expect

_SURFACES = (
    ("/broker-execution/", "overview", "实盘执行中心"),
    ("/broker-execution/orders/", "orders", "实盘订单"),
    (
        "/broker-execution/orders/00000000-0000-0000-0000-000000000000/",
        "order_detail",
        "订单详情",
    ),
    ("/broker-execution/reconciliation/", "reconciliation", "实盘对账"),
    ("/broker-execution/connection/", "connection", "本地连接"),
    ("/broker-execution/settings/", "settings", "执行设置"),
    ("/broker-execution/audit/", "audit", "实盘审计"),
)


@pytest.mark.smoke
def test_broker_execution_surfaces_render_without_browser_errors(
    authenticated_page: Page,
    base_url: str,
) -> None:
    """Render all seven user tasks and verify their critical UI controls."""

    console_errors: list[str] = []
    page_errors: list[str] = []

    def capture_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            console_errors.append(message.text)

    authenticated_page.on("console", capture_console)
    authenticated_page.on("pageerror", lambda error: page_errors.append(str(error)))

    for path, page_key, heading in _SURFACES:
        response = authenticated_page.goto(f"{base_url.rstrip('/')}{path}")
        assert response is not None
        assert response.status == 200
        authenticated_page.wait_for_load_state("networkidle")
        expect(authenticated_page.locator(".be-shell")).to_have_attribute(
            "data-page", page_key
        )
        expect(authenticated_page.locator(".be-head h1")).to_have_text(heading)
        expect(authenticated_page.locator(".be-nav a")).to_have_count(6)

    authenticated_page.goto(f"{base_url.rstrip('/')}/broker-execution/connection/")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page.locator("#binding-form")).to_be_visible()
    expect(authenticated_page.locator("#credential-form")).to_be_visible()

    authenticated_page.goto(f"{base_url.rstrip('/')}/broker-execution/settings/")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page.locator("#settings-form")).to_be_visible()
    expect(authenticated_page.locator("#access-grant-form")).to_be_visible()

    authenticated_page.goto(f"{base_url.rstrip('/')}/broker-execution/audit/")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page.locator("#audit-filter")).to_be_visible()
    with authenticated_page.expect_download() as download_info:
        authenticated_page.locator("#audit-export").click()
    assert download_info.value.suggested_filename.startswith("broker-execution-audit-")
    assert download_info.value.suggested_filename.endswith(".csv")

    assert page_errors == []
    assert console_errors == []
