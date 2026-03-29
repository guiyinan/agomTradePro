"""AgomTradePro UAT + E2E Browser Tests via Playwright"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
TOKEN = "56d30eb16b230581312397997d27b3b613941811"
SCREENSHOT_DIR = Path("tests/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PASS = 0
FAIL = 0
RESULTS = []


def record(name, status, detail=""):
    global PASS, FAIL
    if status == "PASS":
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append((name, status, detail))
    icon = "OK" if status == "PASS" else " X"
    print(f"  [{icon}] {name}: {status}" + (f" - {detail}" if detail else ""))


def login_via_session(page, browser_context):
    page.goto(f"{BASE}/account/login/")
    page.wait_for_load_state("networkidle", timeout=10000)
    username_input = page.locator('input[name="username"]')
    password_input = page.locator('input[name="password"]')
    if username_input.count() > 0 and password_input.count() > 0:
        username_input.fill("admin")
        password_input.fill("admin")
        submit = page.locator('button[type="submit"], input[type="submit"]')
        if submit.count() > 0:
            submit.first.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            record(
                "Login",
                "PASS" if page.url != f"{BASE}/account/login/" else "FAIL",
                f"redirected to {page.url}",
            )
        else:
            record("Login", "FAIL", "no submit button")
    else:
        record("Login", "FAIL", "no login form found")


def test_pages(page):
    print("\n  --- Page Rendering Tests ---")

    test_routes = [
        ("/", "Home/Index"),
        ("/dashboard/", "Dashboard"),
        ("/regime/", "Regime"),
        ("/macro/", "Macro"),
        ("/policy/workbench/", "Policy Workbench"),
        ("/signal/", "Signal"),
        ("/backtest/", "Backtest"),
        ("/strategy/", "Strategy"),
        ("/sector/", "Sector"),
        ("/equity/", "Equity"),
        ("/fund/", "Fund"),
        ("/factor/", "Factor"),
        ("/rotation/", "Rotation"),
        ("/hedge/", "Hedge"),
        ("/audit/", "Audit"),
        ("/ai/", "AI Provider"),
        ("/prompt/", "Prompt"),
        ("/terminal/", "Terminal"),
        ("/ops/", "Ops Center"),
        ("/ops/mcp-tools/", "MCP Tools"),
        ("/docs/", "Docs"),
        ("/simulated-trading/", "Simulated Trading"),
        ("/realtime/", "Realtime"),
        ("/decision/workspace/", "Decision Workspace"),
        ("/api/docs/", "Swagger UI"),
        ("/account/", "Account"),
    ]

    for path, name in test_routes:
        try:
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=15000)
            title = page.title()
            status_code = page.evaluate("() => window.__pageError ? 'error' : 'ok'")
            has_error = page.locator("text=Server Error").count() > 0
            has_404 = (
                "not found" in title.lower() or page.locator("text=Page not found").count() > 0
            )
            if has_error or has_404:
                record(name, "FAIL", f"title={title}, has_error={has_error}, has_404={has_404}")
            else:
                record(name, "PASS", f"title={title[:50]}")
                page.screenshot(
                    path=str(SCREENSHOT_DIR / f"{name.replace(' ', '_').replace('/', '_')}.png")
                )
        except Exception as e:
            record(name, "FAIL", str(e)[:100])


def test_regime_page_interactions(page):
    print("\n  --- Regime Page Interactions ---")
    try:
        page.goto(f"{BASE}/regime/", wait_until="networkidle", timeout=15000)
        page.screenshot(path=str(SCREENSHOT_DIR / "regime_initial.png"))

        tabs = page.locator("[data-bs-toggle='tab'], .nav-link, .tab-btn")
        if tabs.count() > 0:
            tabs.first.click()
            page.wait_for_timeout(500)
            record("Regime tab interaction", "PASS", f"clicked tab, {tabs.count()} tabs available")
        else:
            record("Regime tab interaction", "SKIP", "no tabs found")
    except Exception as e:
        record("Regime page interactions", "FAIL", str(e)[:100])


def test_terminal_page(page):
    print("\n  --- Terminal Page Tests ---")
    try:
        page.goto(f"{BASE}/terminal/", wait_until="networkidle", timeout=15000)
        page.screenshot(path=str(SCREENSHOT_DIR / "terminal_initial.png"))

        terminal_input = page.locator(
            "input[type='text'], textarea, .terminal-input, [contenteditable='true']"
        )
        if terminal_input.count() > 0:
            record("Terminal input field", "PASS", f"found {terminal_input.count()} input(s)")
        else:
            record("Terminal input field", "SKIP", "no input found")
    except Exception as e:
        record("Terminal page", "FAIL", str(e)[:100])


def test_decision_workspace(page):
    print("\n  --- Decision Workspace Tests ---")
    try:
        page.goto(f"{BASE}/decision/workspace/", wait_until="networkidle", timeout=15000)
        page.screenshot(path=str(SCREENSHOT_DIR / "decision_workspace.png"))
        title = page.title()
        record("Decision workspace loads", "PASS", f"title={title[:50]}")

        funnel_steps = page.locator("[data-step], .step-indicator, .funnel-step")
        if funnel_steps.count() > 0:
            record("Funnel steps visible", "PASS", f"{funnel_steps.count()} steps")
        else:
            record("Funnel steps visible", "SKIP", "no step indicators found")
    except Exception as e:
        record("Decision workspace", "FAIL", str(e)[:100])


def test_dashboard_page(page):
    print("\n  --- Dashboard Page Tests ---")
    try:
        page.goto(f"{BASE}/dashboard/", wait_until="networkidle", timeout=15000)
        page.screenshot(path=str(SCREENSHOT_DIR / "dashboard.png"))
        title = page.title()
        record("Dashboard loads", "PASS", f"title={title[:50]}")

        cards = page.locator(".card, .dashboard-card, [class*='card']")
        record(
            "Dashboard cards", "PASS" if cards.count() > 0 else "SKIP", f"{cards.count()} card(s)"
        )
    except Exception as e:
        record("Dashboard", "FAIL", str(e)[:100])


def test_navigation(page):
    print("\n  --- Navigation Tests ---")
    try:
        page.goto(f"{BASE}/", wait_until="networkidle", timeout=15000)

        nav_links = page.locator("nav a, .navbar a, .sidebar a, .nav-link")
        link_count = nav_links.count()
        record("Navigation links", "PASS" if link_count > 0 else "FAIL", f"{link_count} links")

        broken = []
        for i in range(min(link_count, 10)):
            href = nav_links.nth(i).get_attribute("href")
            if href and href.startswith("/"):
                try:
                    resp = page.request.get(f"{BASE}{href}", timeout=8000)
                    if resp.status >= 400:
                        broken.append(f"{href}={resp.status}")
                except Exception:
                    broken.append(f"{href}=timeout")

        if broken:
            record("Navigation link targets", "FAIL", f"broken: {', '.join(broken[:5])}")
        else:
            record("Navigation link targets", "PASS", f"checked {min(link_count, 10)} links")
    except Exception as e:
        record("Navigation", "FAIL", str(e)[:100])


def test_swagger_ui(page):
    print("\n  --- Swagger UI Tests ---")
    try:
        page.goto(f"{BASE}/api/docs/", wait_until="networkidle", timeout=15000)
        page.screenshot(path=str(SCREENSHOT_DIR / "swagger_ui.png"))

        swagger_content = page.locator(".swagger-ui, #swagger-ui, .scheme-container")
        if swagger_content.count() > 0:
            record("Swagger UI renders", "PASS")
        else:
            body_text = page.inner_text("body")
            record(
                "Swagger UI renders",
                "PASS" if "swagger" in body_text.lower() or "api" in body_text.lower() else "FAIL",
                body_text[:80],
            )
    except Exception as e:
        record("Swagger UI", "FAIL", str(e)[:100])


def main():
    print("=" * 60)
    print("  AgomTradePro UAT + E2E Browser Tests (Playwright)")
    print(f"  Target: {BASE}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        login_via_session(page, context)
        test_pages(page)
        test_regime_page_interactions(page)
        test_terminal_page(page)
        test_decision_workspace(page)
        test_dashboard_page(page)
        test_navigation(page)
        test_swagger_ui(page)

        browser.close()

    print("\n" + "=" * 60)
    print("  UAT/E2E SUMMARY")
    print("=" * 60)
    total = PASS + FAIL
    for name, status, detail in RESULTS:
        icon = "OK" if status == "PASS" else " X"
        print(f"  [{icon}] {name}: {status}" + (f" - {detail}" if detail else ""))
    print()
    print(f"  Total: {total}, PASS: {PASS}, FAIL: {FAIL}")
    print(f"  Pass Rate: {PASS / total * 100:.1f}%" if total > 0 else "  N/A")
    print(f"  Screenshots: {SCREENSHOT_DIR.resolve()}")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
