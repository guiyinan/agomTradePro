"""M5 live-server UAT for the Web-to-TUI migration exit criteria."""

from __future__ import annotations

import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page, expect

VIEWPORTS = (
    pytest.param(1440, 900, id="desktop-1440x900"),
    pytest.param(1024, 768, id="tablet-1024x768"),
    pytest.param(390, 844, id="mobile-390x844"),
)
PASSWORD = "CodexM5Uat!2026"
EXTERNAL_AI_UAT_ENABLED = os.environ.get("AGOM_M5_EXTERNAL_AI_UAT", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EXTERNAL_AI_UAT_SKIP_REASON = (
    "requires AGOM_M5_EXTERNAL_AI_UAT=1 and a controlled live AI provider "
    "configured in the disposable Playwright database"
)
ROOT = Path(__file__).resolve().parents[4]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"


def _matrix_deep_links() -> tuple[tuple[str, str, str, str], ...]:
    """Return one reviewed primary TUI deep link per migrated route page."""

    links: list[tuple[str, str, str, str]] = []
    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not (
                row.get("status") == "migrated"
                and row.get("template_role") == "route_page"
                and row.get("destination_class") in {"A", "B"}
            ):
                continue
            template_path = str(row.get("template_path") or "").strip()
            screen_key = next(
                (
                    value.strip()
                    for value in str(row.get("target_screen_key") or "").split(";")
                    if value.strip()
                ),
                "",
            )
            redirect_target = str(row.get("redirect_target") or "").strip()
            redirect_actions = parse_qs(urlparse(redirect_target).query).get("action") or []
            action_key = next(
                (
                    value.strip()
                    for value in redirect_actions
                    if value.strip() and "{" not in value and "}" not in value
                ),
                "",
            )
            if not action_key:
                action_key = next(
                    (
                        value.strip()
                        for value in str(row.get("target_action_keys") or "").split(";")
                        if value.strip() and "{" not in value and "}" not in value
                    ),
                    "",
                )
            if not template_path or not screen_key or not action_key:
                raise AssertionError(f"Incomplete migrated deep link: {template_path}")
            links.append(
                (
                    template_path,
                    screen_key,
                    action_key,
                    str(row.get("audience") or "authenticated").strip(),
                )
            )
    return tuple(sorted(links))


MATRIX_DEEP_LINKS = _matrix_deep_links()

PARAMETERIZED_READ_CASES: tuple[tuple[str, str, str, str, dict[str, str | int]], ...] = (
    (
        "core/templates/asset_analysis/screen.html",
        "research.asset-lab",
        "asset-analysis.pool-screen",
        "regular",
        {"asset_type": "equity", "regime": "Recovery"},
    ),
    (
        "core/templates/dashboard/alpha_ranking.html",
        "research.signals",
        "dashboard.alpha-ranking",
        "regular",
        {"format": "json"},
    ),
    (
        "apps/risk_center/templates/risk_center/console.html",
        "macro-regime.strategy",
        "risk-center.effective-policy",
        "admin",
        {"account_id": 2},
    ),
    (
        "core/templates/equity/detail.html",
        "research.asset-lab",
        "equity.valuation-overview",
        "regular",
        {"stock_code": "000001.SZ"},
    ),
    (
        "core/templates/filter/dashboard.html",
        "research.asset-lab",
        "macro.trend-filter-summary",
        "regular",
        {"indicator_code": "PMI"},
    ),
    (
        "core/templates/policy/policy_events.html",
        "policy.workbench",
        "policy.event-list",
        "regular",
        {"start_date": "2026-06-27", "end_date": "2026-07-27"},
    ),
    (
        "core/templates/simulated_trading/inspection_notify.html",
        "execution.accounts",
        "simulated-trading.inspection-notification",
        "regular",
        {"account_id": 6},
    ),
    (
        "core/templates/simulated_trading/my_positions.html",
        "execution.accounts",
        "simulated-trading.positions",
        "regular",
        {"account_id": 6},
    ),
    (
        "core/templates/simulated_trading/my_trades.html",
        "execution.accounts",
        "simulated-trading.trades",
        "regular",
        {"account_id": 6},
    ),
)


def _login(page: Page, base_url: str, *, username: str, target: str) -> None:
    """Log one isolated UAT user into an explicit TUI deep link."""

    page.goto(
        f"{base_url}/account/login/?next={target}",
        wait_until="domcontentloaded",
    )
    page.get_by_role("textbox", name="用户名", exact=True).fill(username)
    page.get_by_role("textbox", name="密码", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(re.compile(r".*/tui/\?.*"))


@pytest.mark.uat
def test_account_read_missing_fields_and_confirmation_cancel(
    authenticated_page: Page,
    base_url: str,
) -> None:
    """Read/detail flows work and a write cannot bypass input or confirmation."""

    page = authenticated_page
    account_name = "M5 浏览器演练账户"
    page.goto(
        f"{base_url}/tui/?screen=execution.accounts" "&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )

    expect(page.locator("[data-workbench-status]")).to_have_text("读取完成", timeout=60_000)
    expect(page.get_by_role("grid", name="查看我的投资账户")).to_be_visible()
    result_summary = page.get_by_text(
        re.compile(r"^查看我的投资账户：\d+ 行。$"),
        exact=True,
    )
    expect(result_summary).to_be_visible()
    summary_text = result_summary.text_content()
    summary_match = re.fullmatch(r"查看我的投资账户：(\d+) 行。", summary_text or "")
    assert summary_match is not None
    assert int(summary_match.group(1)) >= 2
    assert page.locator("html").evaluate(
        "(element) => element.scrollWidth <= element.clientWidth + 1"
    )

    page.keyboard.press("F9")
    expect(page.get_by_role("searchbox", name="任务", exact=True)).to_be_visible()
    create_form = page.locator("form:has(#tui-simulated-trading\\.account-create-account_name)")
    expect(create_form).to_have_count(1)
    create_form.get_by_role("button", name="创建", exact=True).click()

    missing_dialog = page.get_by_role("dialog", name="补填参数", exact=True)
    expect(missing_dialog).to_be_visible()
    missing_dialog.get_by_placeholder("请输入账户名称", exact=True).fill(account_name)
    missing_dialog.get_by_role("spinbutton").fill("500000")
    missing_dialog.get_by_role("button", name="继续", exact=True).click()

    confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
    expect(confirmation).to_be_visible()
    expect(
        confirmation.get_by_text(
            "此操作会修改系统状态：创建投资账户。确认后才会执行。",
            exact=True,
        )
    ).to_be_visible()
    confirmation.get_by_role("button", name="取消", exact=True).click()
    expect(confirmation).to_be_hidden()
    expect(page.get_by_text("已取消", exact=True)).to_be_visible()

    page.goto(
        f"{base_url}/tui/?screen=execution.accounts" "&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )
    expect(page.get_by_text(summary_text or "", exact=True)).to_be_visible()
    expect(page.get_by_text(account_name, exact=True)).to_have_count(0)

    page.keyboard.press("F9")
    detail_form = page.locator("form:has(#tui-simulated-trading\\.account-detail-account_id)")
    detail_form.locator("select").select_option("2")
    detail_form.get_by_role("button", name="查看", exact=True).click()
    expect(page.get_by_text("账户 / 账户名称", exact=True)).to_be_visible()
    expect(page.get_by_text("admin_模拟仓", exact=True)).to_be_visible()


@pytest.mark.uat
def test_operator_group_can_open_queue_but_regular_user_cannot(
    page: Page,
    base_url: str,
) -> None:
    """TUI visibility and the owner API preserve the operator role boundary."""

    target = "/tui/%3Fscreen%3Dai-ops.terminal" "%26action%3Dagent-runtime.operator-task-list"

    _login(page, base_url, username="m5_uat_operator", target=target)
    expect(page.get_by_role("grid", name="智能任务队列")).to_be_visible()
    expect(page.get_by_text("读取完成", exact=True)).to_be_visible()

    page.goto(f"{base_url}/account/logout/", wait_until="domcontentloaded")
    _login(page, base_url, username="m5_uat_regular", target=target)
    expect(page.get_by_text("链接中的任务在当前账号下不可用", exact=True)).to_be_visible()
    expect(page.get_by_role("grid", name="智能任务队列")).to_have_count(0)


@pytest.mark.uat
@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
def test_tui_core_layout_has_no_horizontal_overflow(
    authenticated_page: Page,
    base_url: str,
    width: int,
    height: int,
) -> None:
    """The migrated core workspace remains usable at the reviewed breakpoints."""

    page = authenticated_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(
        f"{base_url}/tui/?screen=execution.accounts" "&action=simulated-trading.accounts",
        wait_until="domcontentloaded",
    )
    expect(page.get_by_role("grid", name="查看我的投资账户")).to_be_visible()
    page.keyboard.press("F9")
    expect(page.get_by_role("searchbox", name="任务", exact=True)).to_be_visible()

    layout = page.evaluate("""() => ({
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
            workspaceVisible: getComputedStyle(
                document.querySelector('[aria-label="TUI workspace"]')
            ).display !== 'none',
            unnamedButtons: Array.from(document.querySelectorAll('button')).filter(
                (element) => !(
                    element.getAttribute('aria-label')
                    || (element.textContent || '').trim()
                    || element.getAttribute('title')
                )
            ).length,
        })""")
    assert layout["documentWidth"] <= layout["viewportWidth"] + 1
    assert layout["workspaceVisible"] is True
    assert layout["unnamedButtons"] == 0


@pytest.mark.uat
def test_every_migrated_route_resolves_its_reviewed_tui_deep_link(
    authenticated_page: Page,
    base_url: str,
) -> None:
    """All migrated route pages resolve an admin-visible screen/action pair."""

    page = authenticated_page
    failures: list[str] = []
    assert len(MATRIX_DEEP_LINKS) == 108
    page.route(
        re.compile(r".*/api/tui/actions/.*/run/$"),
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"response":{"status_code":200,"body":{}}}',
        ),
    )

    for template_path, screen_key, action_key, _audience in MATRIX_DEEP_LINKS:
        query = urlencode({"screen": screen_key, "action": action_key})
        try:
            page.goto(
                f"{base_url}/tui/?{query}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.locator(
                "[data-actions-panel] [data-action-ui-key], [data-dashboard-panel]"
            ).first.wait_for(state="attached", timeout=30_000)
            page.wait_for_timeout(100)
            status = page.locator("[data-workbench-status]").inner_text()
            if "链接中的任务在当前账号下不可用" in status:
                failures.append(f"{template_path}: action unavailable: {screen_key} / {action_key}")
            elif "链接中的任务暂时无法定位" in status:
                failures.append(
                    f"{template_path}: action not locatable: {screen_key} / {action_key}"
                )
        except Exception as exc:
            failures.append(
                f"{template_path}: {screen_key} / {action_key}: {type(exc).__name__}: {exc}"
            )

    assert failures == [], "\n".join(failures)


def _uat_role(audience: str) -> str:
    """Choose the least-privileged planned role for one route page."""

    normalized = audience.lower()
    if "operator" in normalized:
        return "operator"
    if "admin" in normalized and "authenticated" not in normalized:
        return "admin"
    return "regular"


def _login_context(
    context: BrowserContext,
    base_url: str,
    *,
    username: str,
    password: str,
) -> Page:
    """Authenticate one reusable browser context for matrix UAT."""

    page = context.new_page()
    page.goto(f"{base_url}/account/login/?next=/tui/", wait_until="domcontentloaded")
    page.get_by_role("textbox", name="用户名", exact=True).fill(username)
    page.get_by_role("textbox", name="密码", exact=True).fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(re.compile(r".*/tui/.*"))
    return page


@pytest.fixture(scope="session")
def local_route_uat_fixture_ids(
    django_db_setup: object,
    django_db_blocker: object,
) -> dict[str, int | str]:
    """Seed deterministic local-only records consumed through the live TUI server."""

    def seed() -> dict[str, int | str]:
        from django.contrib.auth import get_user_model

        from apps.agent_runtime.infrastructure.models import AgentProposalModel, AgentTaskModel
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
        from apps.audit.infrastructure.models import AttributionReport
        from apps.backtest.infrastructure.models import BacktestResultModel
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

        with django_db_blocker.unblock():
            user_model = get_user_model()
            operator = user_model.objects.get(username="m5_uat_operator")
            regular = user_model.objects.get(username="m5_uat_regular")
            task, _ = AgentTaskModel.objects.update_or_create(
                request_id="m5-uat-agent-task-detail",
                defaults={
                    "task_domain": "research",
                    "task_type": "m5_route_uat",
                    "status": "awaiting_approval",
                    "input_payload": {"asset_code": "000001.SZ"},
                    "requires_human": True,
                    "created_by": operator,
                },
            )
            proposal, _ = AgentProposalModel.objects.update_or_create(
                request_id="m5-uat-agent-proposal-detail",
                defaults={
                    "task": task,
                    "proposal_type": "signal_write",
                    "status": "submitted",
                    "risk_level": "medium",
                    "approval_required": True,
                    "approval_status": "pending",
                    "proposal_payload": {"asset_code": "000001.SZ", "side": "hold"},
                    "created_by": operator,
                },
            )
            candidate, _ = AlphaCandidateModel.objects.update_or_create(
                candidate_id="m5-uat-alpha-candidate-detail",
                defaults={
                    "trigger_id": "m5-uat-alpha-candidate-trigger",
                    "asset_code": "000001.SZ",
                    "asset_class": "a_share",
                    "direction": "LONG",
                    "strength": "STRONG",
                    "confidence": 0.82,
                    "status": "ACTIONABLE",
                    "thesis": "M5 candidate route evidence",
                    "entry_zone": {"low": 10.0, "high": 11.0},
                    "exit_zone": {"target": 13.0},
                    "time_horizon": 30,
                    "expected_return": 0.12,
                    "risk_level": "MEDIUM",
                },
            )
            attribution_backtest, _ = BacktestResultModel.objects.update_or_create(
                user=regular,
                name="M5 attribution route fixture",
                defaults={
                    "status": "completed",
                    "start_date": "2026-01-01",
                    "end_date": "2026-03-31",
                    "initial_capital": "1000000.00",
                    "rebalance_frequency": "monthly",
                    "final_capital": "1060000.00",
                    "total_return": 0.06,
                },
            )
            report, _ = AttributionReport.objects.update_or_create(
                backtest=attribution_backtest,
                period_start="2026-01-01",
                period_end="2026-03-31",
                defaults={
                    "attribution_method": "heuristic",
                    "regime_timing_pnl": 0.02,
                    "asset_selection_pnl": 0.03,
                    "interaction_pnl": 0.01,
                    "total_pnl": 0.06,
                    "regime_accuracy": 0.75,
                    "regime_predicted": "recovery",
                    "regime_actual": "recovery",
                },
            )
            factor_config, _ = FactorPortfolioConfigModel.objects.update_or_create(
                name="M5 factor calculation fixture",
                defaults={
                    "description": "Local route-task UAT fixture",
                    "factor_weights": {"quality": 1.0},
                    "universe": "all_a",
                    "top_n": 5,
                    "is_active": True,
                },
            )

        return {
            "agent_task_id": task.id,
            "agent_proposal_id": proposal.id,
            "candidate_id": candidate.candidate_id,
            "attribution_report_id": report.id,
            "factor_config_id": factor_config.id,
        }

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(seed).result()


def _visible_action_form(page: Page, selector: str) -> Locator:
    """Return one attached form after opening the task panel when required."""

    form = page.locator(selector)
    form.wait_for(state="attached")
    if not form.is_visible():
        page.keyboard.press("F9")
    expect(form).to_be_visible()
    return form


def _run_confirmed_action(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
    params: dict[str, str | int | bool],
    form_selector: str,
    result_timeout_ms: int = 5_000,
) -> Locator:
    """Submit one visible TUI action and require its confirmed success receipt."""

    query = urlencode({"screen": screen_key, "action": action_key, **params})
    page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
    form = _visible_action_form(page, form_selector)
    form.locator("button[type='submit']").click()
    confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name="确认执行", exact=True).click()
    expect(page.locator("[data-workbench-status]")).to_have_text(
        "读取完成", timeout=result_timeout_ms
    )
    expect(page.locator(".tui-error")).to_have_count(0)
    main = page.locator("[data-main-panel]")
    expect(main.locator(".tui-view-status")).to_contain_text("正常 / ")
    return main


def _run_read_deep_link(
    page: Page,
    base_url: str,
    *,
    screen_key: str,
    action_key: str,
    params: dict[str, str | int | bool] | None = None,
) -> Locator:
    """Execute one parameter-complete read deep link and return its rendered result."""

    query = urlencode({"screen": screen_key, "action": action_key, **(params or {})})
    page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
    expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
    expect(page.locator(".tui-error")).to_have_count(0)
    return page.locator("[data-main-panel]")


@pytest.mark.uat
def test_role_appropriate_direct_read_primary_tasks_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Execute every fixture-free primary read through its least-privileged role."""

    contexts = {
        role: browser.new_context(base_url=base_url) for role in ("regular", "operator", "admin")
    }
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "operator": _login_context(
                contexts["operator"],
                base_url,
                username="m5_uat_operator",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        screen_cache: dict[tuple[str, str], dict[str, object]] = {}
        direct_routes: list[tuple[str, str, str, str]] = []
        metadata_failures: list[str] = []

        for template_path, screen_key, action_key, audience in MATRIX_DEEP_LINKS:
            role = _uat_role(audience)
            cache_key = (role, screen_key)
            if cache_key not in screen_cache:
                response = contexts[role].request.get(f"{base_url}/api/tui/screens/{screen_key}/")
                if not response.ok:
                    metadata_failures.append(
                        f"{template_path}: {role} cannot load {screen_key}: {response.status}"
                    )
                    continue
                screen_cache[cache_key] = response.json()
            payload = screen_cache[cache_key]
            actions = payload.get("actions")
            action_values = actions if isinstance(actions, list) else []
            action = next(
                (
                    item
                    for item in action_values
                    if isinstance(item, dict) and item.get("key") == action_key
                ),
                None,
            )
            if action is None:
                metadata_failures.append(
                    f"{template_path}: {role} cannot see {screen_key} / {action_key}"
                )
                continue
            fields = action.get("fields")
            has_required_fields = bool(
                isinstance(fields, list)
                and any(isinstance(field, dict) and field.get("required") for field in fields)
            )
            is_direct_read = (
                str(action.get("risk") or "read") in {"read", "admin"}
                and str(action.get("method") or "GET").upper() == "GET"
                and not has_required_fields
                and action.get("confirmation_required") is not True
            )
            if is_direct_read:
                direct_routes.append((template_path, screen_key, action_key, role))

        assert metadata_failures == [], "\n".join(metadata_failures)
        unique_tasks = {
            (screen_key, action_key, role) for _, screen_key, action_key, role in direct_routes
        }
        assert len(direct_routes) >= 65
        assert len(unique_tasks) >= 60

        execution_failures: list[str] = []
        for screen_key, action_key, role in sorted(unique_tasks):
            page = pages[role]
            query = urlencode({"screen": screen_key, "action": action_key})
            try:
                page.goto(
                    f"{base_url}/tui/?{query}",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_function(
                    """() => {
                        const status = document.querySelector('[data-workbench-status]')
                            ?.textContent?.trim() || '';
                        return status === '读取完成'
                            || status.startsWith('已定位到 ')
                            || Boolean(document.querySelector('.tui-error'));
                    }""",
                    timeout=60_000,
                )
                status = page.locator("[data-workbench-status]").inner_text()
                error_count = page.locator(".tui-error").count()
                if error_count or not (status == "读取完成" or status.startswith("已定位到 ")):
                    execution_failures.append(
                        f"{role}: {screen_key} / {action_key}: status={status}; errors={error_count}"
                    )
            except Exception as exc:
                execution_failures.append(
                    f"{role}: {screen_key} / {action_key}: {type(exc).__name__}: {exc}"
                )

        assert execution_failures == [], "\n".join(execution_failures)
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
def test_parameterized_read_primary_tasks_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Execute reviewed parameterized reads through their least-privileged role."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "admin")}
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        failures: list[str] = []
        for template_path, screen_key, action_key, role, params in PARAMETERIZED_READ_CASES:
            page = pages[role]
            query = urlencode({"screen": screen_key, "action": action_key, **params})
            try:
                page.goto(
                    f"{base_url}/tui/?{query}",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_function(
                    """() => {
                        const status = document.querySelector('[data-workbench-status]')
                            ?.textContent?.trim() || '';
                        return status === '读取完成'
                            || Boolean(document.querySelector('.tui-error'));
                    }""",
                    timeout=90_000,
                )
                status = page.locator("[data-workbench-status]").inner_text()
                error_count = page.locator(".tui-error").count()
                if error_count or status != "读取完成":
                    failures.append(
                        f"{template_path}: {role}: {screen_key} / {action_key}: "
                        f"status={status}; errors={error_count}"
                    )
            except Exception as exc:
                failures.append(
                    f"{template_path}: {role}: {screen_key} / {action_key}: "
                    f"{type(exc).__name__}: {exc}"
                )

        assert failures == [], "\n".join(failures)
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
def test_strategy_create_detail_update_lifecycle_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Create, read, and update one user-owned strategy through confirmed TUI writes."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        strategy_name = f"M5 UAT 策略 {uuid4().hex[:8]}"
        create_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-create",
                "name": strategy_name,
                "strategy_type": "rule_based",
            }
        )
        page.goto(f"{base_url}/tui/?{create_query}", wait_until="domcontentloaded")
        create_form = _visible_action_form(page, "form:has(#tui-strategy\\.workbench-create-name)")
        expect(create_form.locator("#tui-strategy\\.workbench-create-name")).to_have_value(
            strategy_name
        )
        create_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        main = page.locator("[data-main-panel]")
        expect(main.get_by_text(strategy_name, exact=True)).to_be_visible()
        strategy_id = int(
            main.get_by_text("ID", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
        )
        assert strategy_id > 0

        detail_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-detail",
                "strategy_id": strategy_id,
            }
        )
        page.goto(f"{base_url}/tui/?{detail_query}", wait_until="domcontentloaded")
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(strategy_name, exact=True)
        ).to_be_visible()

        updated_description = "M5 UAT 已验证详情与确认式更新"
        update_query = urlencode(
            {
                "screen": "macro-regime.strategy",
                "action": "strategy.workbench-update",
                "strategy_id": strategy_id,
                "description": updated_description,
            }
        )
        page.goto(f"{base_url}/tui/?{update_query}", wait_until="domcontentloaded")
        update_form = _visible_action_form(
            page, "form:has(#tui-strategy\\.workbench-update-strategy_id)"
        )
        update_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(updated_description, exact=True)
        ).to_be_visible()
        expect(page.locator(".tui-error")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.uat
def test_personal_ai_provider_detail_update_lifecycle_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Create, read, and update one user-owned AI provider through the TUI."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        provider_name = f"M5 UAT 服务商 {uuid4().hex[:8]}"
        create_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.create-my-provider",
                "name": provider_name,
                "provider_type": "custom",
                "base_url": "https://example.invalid/v1",
                "is_active": "false",
            }
        )
        page.goto(f"{base_url}/tui/?{create_query}", wait_until="domcontentloaded")
        create_form = _visible_action_form(
            page,
            "form:has(#tui-ai-ops\\.create-my-provider-name)",
        )
        create_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        main = page.locator("[data-main-panel]")
        expect(main.get_by_text(provider_name, exact=True)).to_be_visible()
        provider_id = int(
            main.get_by_text("ID", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
        )
        assert provider_id > 0

        detail_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.my-provider-detail",
                "provider_id": provider_id,
            }
        )
        page.goto(f"{base_url}/tui/?{detail_query}", wait_until="domcontentloaded")
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(provider_name, exact=True)
        ).to_be_visible()

        updated_description = "M5 UAT 已验证用户归属和确认式更新"
        update_query = urlencode(
            {
                "screen": "ai-ops.providers",
                "action": "ai-ops.update-my-provider",
                "provider_id": provider_id,
                "description": updated_description,
            }
        )
        page.goto(f"{base_url}/tui/?{update_query}", wait_until="domcontentloaded")
        update_form = _visible_action_form(
            page,
            "form:has(#tui-ai-ops\\.update-my-provider-provider_id)",
        )
        update_form.locator("button[type='submit']").click()
        confirmation = page.get_by_role("dialog", name="确认操作", exact=True)
        expect(confirmation).to_be_visible()
        confirmation.get_by_role("button", name="确认执行", exact=True).click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成")
        expect(
            page.locator("[data-main-panel]").get_by_text(updated_description, exact=True)
        ).to_be_visible()
        expect(page.locator(".tui-error")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.uat
def test_policy_admin_create_flows_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Create a policy event, keyword rule, and RSS source through confirmed writes."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="admin",
            password="Aa123456",
        )
        suffix = uuid4().hex[:8]

        event_title = f"M5 UAT 政策事件 {suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.event-create",
            params={
                "event_date": "2026-07-27",
                "level": "P3",
                "title": event_title,
                "description": "M5 UAT 已完成管理员确认式政策事件创建和持久化验证",
                "evidence_url": f"https://example.invalid/evidence/{suffix}",
            },
            form_selector="form:has(#tui-policy\\.event-create-event_date)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.event-list",
            params={"start_date": "2026-07-27", "end_date": "2026-07-27"},
        )
        expect(main.get_by_text(event_title, exact=True)).to_be_visible()

        keyword = f"m5-uat-{suffix}"
        keyword_category = f"uat-{suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-keyword-create",
            params={
                "level": "P3",
                "keywords": f'["{keyword}"]',
                "weight": 1,
                "category": keyword_category,
                "is_active": True,
            },
            form_selector="form:has(#tui-policy\\.rss-keyword-create-level)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-keyword-list",
        )
        expect(main.get_by_text(keyword_category, exact=True)).to_be_visible()

        source_name = f"M5 UAT RSS {suffix}"
        _run_confirmed_action(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-source-create",
            params={
                "name": source_name,
                "url": f"https://example.invalid/feed/{suffix}.xml",
                "category": "other",
                "is_active": True,
                "fetch_interval_hours": 24,
            },
            form_selector="form:has(#tui-policy\\.rss-source-create-name)",
        )
        main = _run_read_deep_link(
            page,
            base_url,
            screen_key="policy.workbench",
            action_key="policy.rss-source-list",
        )
        expect(main.get_by_text(source_name, exact=True)).to_be_visible()
    finally:
        context.close()


@pytest.mark.uat
def test_governance_and_screening_confirmed_flows_complete(
    browser: Browser,
    base_url: str,
) -> None:
    """Complete quota, Beta Gate, equity, and fund confirmed workflows."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "admin")}
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "admin": _login_context(
                contexts["admin"],
                base_url,
                username="admin",
                password="Aa123456",
            ),
        }
        suffix = uuid4().hex[:8]

        main = _run_confirmed_action(
            pages["admin"],
            base_url,
            screen_key="command-center.decision-flow",
            action_key="decision-rhythm.quota-update",
            params={
                "account_id": 2,
                "period": "daily",
                "max_decisions": 12,
                "max_executions": 6,
            },
            form_selector="form:has(#tui-decision-rhythm\\.quota-update-period)",
        )
        expect(main.get_by_text("daily", exact=True)).to_be_visible()

        config_id = f"m5-{suffix}"
        main = _run_confirmed_action(
            pages["admin"],
            base_url,
            screen_key="macro-regime.strategy",
            action_key="beta-gate.config-create",
            params={"config_id": config_id, "risk_profile": "balanced"},
            form_selector="form:has(#tui-beta-gate\\.config-create-risk_profile)",
        )
        expect(main.get_by_text(config_id, exact=True)).to_be_visible()

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="macro-regime.strategy",
            action_key="beta-gate.test-assets",
            params={
                "asset_codes": '["000001.SZ"]',
                "asset_class": "equity",
                "current_regime": "Recovery",
                "regime_confidence": 0.8,
                "policy_level": 1,
            },
            form_selector="form:has(#tui-beta-gate\\.test-assets-asset_codes)",
        )

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="equity.screen-stocks",
            params={"regime": "Recovery"},
            form_selector="form:has(#tui-equity\\.screen-stocks-regime)",
        )

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="fund.multidim-screen",
            params={"regime": "Recovery"},
            form_selector="form:has(#tui-fund\\.multidim-screen-fund_type)",
        )
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
def test_local_fixture_detail_and_lifecycle_routes_complete(
    browser: Browser,
    base_url: str,
    local_route_uat_fixture_ids: dict[str, int | str],
) -> None:
    """Complete the remaining detail and lifecycle routes without external AI calls."""

    contexts = {role: browser.new_context(base_url=base_url) for role in ("regular", "operator")}
    try:
        pages = {
            "regular": _login_context(
                contexts["regular"],
                base_url,
                username="m5_uat_regular",
                password=PASSWORD,
            ),
            "operator": _login_context(
                contexts["operator"],
                base_url,
                username="m5_uat_operator",
                password=PASSWORD,
            ),
        }

        main = _run_read_deep_link(
            pages["operator"],
            base_url,
            screen_key="ai-ops.terminal",
            action_key="agent-runtime.operator-task-detail",
            params={"task_id": int(local_route_uat_fixture_ids["agent_task_id"])},
        )
        expect(main.get_by_text("m5-uat-agent-task-detail", exact=True)).to_be_visible()
        main = _run_read_deep_link(
            pages["operator"],
            base_url,
            screen_key="ai-ops.terminal",
            action_key="agent-runtime.operator-proposal-detail",
            params={"proposal_id": int(local_route_uat_fixture_ids["agent_proposal_id"])},
        )
        expect(main.get_by_text("m5-uat-agent-proposal-detail", exact=True)).to_be_visible()

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.candidate-detail",
            params={"candidate_id": str(local_route_uat_fixture_ids["candidate_id"])},
        )
        expect(main.get_by_text("m5-uat-alpha-candidate-detail", exact=True)).to_be_visible()

        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.create",
            params={
                "trigger_type": "momentum_signal",
                "asset_code": "000001.SZ",
                "asset_class": "a_share",
                "direction": "LONG",
                "trigger_condition": '{"signal":"cross_up"}',
                "invalidation_conditions": (
                    '[{"condition_type":"threshold_cross",'
                    '"indicator_code":"CN_PMI_MANUFACTURING",'
                    '"threshold":50.0,"direction":"below"}]'
                ),
                "confidence": 0.82,
                "thesis": "M5 alpha lifecycle evidence",
                "expires_in_days": 30,
            },
            form_selector="form:has(#tui-alpha-trigger\\.create-asset_code)",
        )
        trigger_match = re.search(r"trigger_[0-9a-f]{12}", main.inner_text())
        assert trigger_match is not None
        trigger_id = trigger_match.group(0)

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.trigger-detail",
            params={"trigger_id": trigger_id},
        )
        expect(main.get_by_text(trigger_id, exact=True)).to_be_visible()

        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.update",
            params={
                "trigger_id": trigger_id,
                "confidence": 0.86,
                "thesis": "M5 alpha lifecycle updated",
            },
            form_selector="form:has(#tui-alpha-trigger\\.update-trigger_id)",
        )
        expect(main.get_by_text("M5 alpha lifecycle updated", exact=True)).to_be_visible()

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.signals",
            action_key="alpha-trigger.check-invalidation",
            params={
                "trigger_id": trigger_id,
                "current_indicator_values": '{"CN_PMI_MANUFACTURING":55.0}',
                "current_regime": "Recovery",
            },
            form_selector=("form:has(#tui-alpha-trigger\\.check-invalidation-trigger_id)"),
        )

        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="execution.audit",
            action_key="audit.attribution-detail",
            params={"report_id": int(local_route_uat_fixture_ids["attribution_report_id"])},
        )
        expect(main.get_by_text("0.06", exact=True)).to_be_visible()

        backtest_name = f"M5 UAT 回测 {uuid4().hex[:8]}"
        main = _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="backtest.run",
            params={
                "name": backtest_name,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "initial_capital": 100000,
                "rebalance_frequency": "monthly",
                "transaction_cost_bps": 10,
                "trust_status": "exploratory",
            },
            form_selector="form:has(#tui-backtest\\.run-name)",
        )
        backtest_receipt = main.inner_text()
        backtest_match = re.search(r"回测ID\s+(\d+)", backtest_receipt)
        assert backtest_match is not None, backtest_receipt
        backtest_id = int(backtest_match.group(1))
        main = _run_read_deep_link(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="backtest.detail",
            params={"pk": backtest_id},
        )
        expect(main.get_by_text(backtest_name, exact=True)).to_be_visible()

        _run_confirmed_action(
            pages["regular"],
            base_url,
            screen_key="research.asset-lab",
            action_key="factor.calculate-config",
            params={
                "config_id": int(local_route_uat_fixture_ids["factor_config_id"]),
                "trade_date": "2026-07-27",
                "top_n": 5,
            },
            form_selector="form:has(#tui-factor\\.calculate-config-config_id)",
        )
    finally:
        for context in contexts.values():
            context.close()


@pytest.mark.uat
@pytest.mark.skipif(
    not EXTERNAL_AI_UAT_ENABLED,
    reason=EXTERNAL_AI_UAT_SKIP_REASON,
)
def test_sentiment_external_ai_primary_task_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Analyze uncached text through a controlled real AI provider and the TUI."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="m5_uat_regular",
            password=PASSWORD,
        )
        main = _run_confirmed_action(
            page,
            base_url,
            screen_key="research.signals",
            action_key="sentiment.analyze-text",
            params={
                "text": (
                    "M5 受控外部 AI 验收：盈利改善、现金流增强且风险保持可控。"
                    f" 唯一批次 {uuid4().hex}."
                ),
                "use_cache": False,
            },
            form_selector="form:has(#tui-sentiment\\.analyze-text-text)",
            result_timeout_ms=120_000,
        )
        receipt = main.inner_text()
        assert "情绪评分" in receipt, receipt
        assert "置信度" in receipt, receipt
        assert "分类" in receipt, receipt
        assert "AI 调用失败" not in receipt, receipt
    finally:
        context.close()


@pytest.mark.uat
@pytest.mark.skipif(
    not EXTERNAL_AI_UAT_ENABLED,
    reason=EXTERNAL_AI_UAT_SKIP_REASON,
)
def test_terminal_external_ai_primary_task_completes(
    browser: Browser,
    base_url: str,
) -> None:
    """Receive a non-empty Terminal Agent reply through a controlled real provider."""

    context = browser.new_context(base_url=base_url)
    try:
        page = _login_context(
            context,
            base_url,
            username="admin",
            password="Aa123456",
        )
        query = urlencode(
            {
                "screen": "ai-ops.terminal",
                "action": "terminal.agent_chat",
                "message": "请用一句中文说明风险预算的作用，不要调用工具。",
            }
        )
        page.goto(f"{base_url}/tui/?{query}", wait_until="domcontentloaded")
        form = _visible_action_form(
            page,
            "form:has(#tui-terminal\\.agent_chat-message)",
        )
        form.locator("button[type='submit']").click()
        expect(page.locator("[data-workbench-status]")).to_have_text("读取完成", timeout=120_000)
        expect(page.locator(".tui-error")).to_have_count(0)
        main = page.locator("[data-main-panel]")
        expect(main.locator(".tui-view-status")).to_contain_text("正常 / ")
        reply = (
            main.get_by_text("回复", exact=True)
            .locator("xpath=following-sibling::dd[1]")
            .inner_text()
            .strip()
        )
        assert reply not in {"", "-"}
    finally:
        context.close()
