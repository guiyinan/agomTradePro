from __future__ import annotations

import re
from itertools import combinations
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

VIEWPORTS = (
    pytest.param(1280, 720, id="desktop-1280x720"),
    pytest.param(1440, 900, id="desktop-1440x900"),
    pytest.param(2048, 1080, id="desktop-2048x1080"),
)
ADAPTIVE_HOME_VIEWPORTS = (
    pytest.param(981, 720, id="tablet-981x720"),
    pytest.param(1024, 768, id="tablet-1024x768"),
    pytest.param(1180, 820, id="compact-desktop-1180x820"),
    pytest.param(1280, 720, id="desktop-1280x720"),
    pytest.param(1440, 900, id="desktop-1440x900"),
)


def _detail_view_model(
    *, title: str = "状态", fields: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "view_model": {
            "kind": "detail",
            "title": title,
            "status": "正常",
            "fields": fields
            or [
                {"label": "状态", "value": "可用", "presentation": "metadata"},
            ],
        }
    }


def _mock_dashboard_action(route: Route) -> None:
    match = re.search(r"/actions/([^/]+)/run/", route.request.url)
    action_key = match.group(1) if match else ""
    if action_key == "capability-router.mcp-self-status":
        payload = _detail_view_model(
            title="当前凭证",
            fields=[
                {
                    "label": "接入令牌",
                    "value": "agtp_" + "7f3c9d43" * 8,
                    "presentation": "secret",
                },
                {
                    "label": "智能路由地址",
                    "value": "https://example.test/api/ai-capability/route/",
                    "presentation": "copyable",
                },
                {
                    "label": "能力目录地址",
                    "value": "https://example.test/api/ai-capability/capabilities/",
                    "presentation": "copyable",
                },
                {
                    "label": "环境说明",
                    "value": "当前地址可用于此环境；实际可达范围取决于网络和部署配置。",
                    "presentation": "metadata",
                },
                {
                    "label": "完整接入包",
                    "value": "\n".join(
                        [
                            "AgomTradePro MCP 接入包",
                            "Token: agtp_" + "7f3c9d43" * 8,
                            "Route Endpoint: https://example.test/api/ai-capability/route/",
                            "Capability Catalog: https://example.test/api/ai-capability/capabilities/",
                            "请按以上信息连接，并先读取能力目录再选择工具。",
                        ]
                    ),
                    "presentation": "multiline",
                },
            ],
        )
    elif action_key == "capability-router.list-my-mcp-tokens":
        payload = {
            "view_model": {
                "kind": "datagrid",
                "columns": [
                    {"key": "name", "label": "名称"},
                    {"key": "preview", "label": "预览"},
                    {"key": "access_level_label", "label": "级别"},
                    {"key": "last_used_at", "label": "最后使用"},
                ],
                "rows": [
                    {
                        "name": "默认代理",
                        "preview": "agtp_7f3c...",
                        "access_level_label": "只读",
                        "last_used_at": "2026-07-17 09:00",
                    }
                ],
                "total": 1,
            }
        }
    else:
        payload = _detail_view_model(
            title="接入验证",
            fields=[
                {"label": "当前凭证", "value": "可用", "presentation": "metadata"},
                {"label": "智能路由", "value": "已就绪", "presentation": "metadata"},
                {"label": "能力目录", "value": "可读取", "presentation": "metadata"},
            ],
        )
    route.fulfill(status=200, content_type="application/json", json=payload)


def _rectangles_overlap(left: dict[str, float], right: dict[str, float]) -> bool:
    tolerance = 1.0
    return not (
        left["right"] <= right["left"] + tolerance
        or right["right"] <= left["left"] + tolerance
        or left["bottom"] <= right["top"] + tolerance
        or right["bottom"] <= left["top"] + tolerance
    )


@pytest.mark.smoke
@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_mcp_self_service_task_flow_has_no_panel_overlap(
    authenticated_page: Page,
    base_url: str,
    width: int,
    height: int,
) -> None:
    authenticated_page.set_viewport_size({"width": width, "height": height})
    authenticated_page.route("**/api/tui/actions/*/run/", _mock_dashboard_action)
    authenticated_page.goto(f"{base_url}/tui/")
    authenticated_page.wait_for_load_state("networkidle")

    location = authenticated_page.locator("[data-current-location]")
    expect(location).to_be_visible()
    location.fill("screen:capability-router.self-service")
    location.press("Enter")

    grid = authenticated_page.locator(".tui-dashboard-grid.is-content-flow")
    expect(grid).to_be_visible()
    panels = grid.locator(".tui-dash-panel")
    expect(panels).to_have_count(4)
    expect(grid.locator(".tui-loading")).to_have_count(0, timeout=10_000)

    rectangles = panels.evaluate_all("""elements => elements.map((element) => {
            const rect = element.getBoundingClientRect();
            return {
                left: rect.left,
                right: rect.right,
                top: rect.top,
                bottom: rect.bottom,
                width: rect.width,
                height: rect.height,
            };
        })""")

    assert all(rectangle["width"] > 0 and rectangle["height"] > 0 for rectangle in rectangles)
    assert (
        max(rectangle["left"] for rectangle in rectangles)
        - min(rectangle["left"] for rectangle in rectangles)
        <= 1
    )
    assert (
        max(rectangle["width"] for rectangle in rectangles)
        - min(rectangle["width"] for rectangle in rectangles)
        <= 2
    )
    for left, right in combinations(rectangles, 2):
        assert not _rectangles_overlap(left, right), (left, right)

    overflow = authenticated_page.evaluate("""() => ({
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
            panelOverflow: Array.from(document.querySelectorAll('.tui-dashboard-grid.is-content-flow .tui-dash-panel'))
                .map((panel) => getComputedStyle(panel).overflowY),
        })""")
    assert overflow["documentWidth"] <= overflow["viewportWidth"] + 1
    assert set(overflow["panelOverflow"]) == {"visible"}


@pytest.mark.smoke
@pytest.mark.parametrize(("width", "height"), ADAPTIVE_HOME_VIEWPORTS)
def test_operator_home_adaptive_grid_has_no_panel_overlap(
    authenticated_page: Page,
    base_url: str,
    width: int,
    height: int,
) -> None:
    authenticated_page.set_viewport_size({"width": width, "height": height})
    authenticated_page.goto(
        f"{base_url}/tui/?screen=command-center.overview",
        wait_until="domcontentloaded",
    )

    grid = authenticated_page.locator(".tui-dashboard-grid")
    expect(grid).to_be_visible()
    panels = grid.locator(".tui-dash-panel")
    expect(panels).to_have_count(5)

    rectangles = panels.evaluate_all("""elements => elements.map((element) => {
            const rect = element.getBoundingClientRect();
            return {
                left: rect.left,
                right: rect.right,
                top: rect.top,
                bottom: rect.bottom,
                width: rect.width,
                height: rect.height,
            };
        })""")

    assert all(rectangle["width"] > 0 and rectangle["height"] > 0 for rectangle in rectangles)
    for left, right in combinations(rectangles, 2):
        assert not _rectangles_overlap(left, right), (left, right)

    overflow = authenticated_page.evaluate("""() => ({
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
        })""")
    assert overflow["documentWidth"] <= overflow["viewportWidth"] + 1
