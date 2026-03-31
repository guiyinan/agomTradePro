"""
Comprehensive system test from user perspective.
Tests: page accessibility, navigation, login, API endpoints, data chains, user workflows.
"""

import sys
import json
import time
import traceback
from datetime import datetime

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
RESULTS = []


def log(category, url_or_action, status, detail="", severity="info"):
    RESULTS.append(
        {
            "time": datetime.now().isoformat(),
            "category": category,
            "target": url_or_action,
            "status": status,
            "detail": detail,
            "severity": severity,
        }
    )
    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️"}.get(status, "❓")
    print(f"  {icon} [{category}] {url_or_action} - {detail}")


def test_page(page, url, name, expect_login_redirect=False, expect_status=200):
    """Test a single page URL, return True if OK."""
    try:
        resp = page.goto(f"{BASE}{url}", wait_until="networkidle", timeout=15000)
        status = resp.status if resp else 0
        current_url = page.url

        if expect_login_redirect:
            if (
                "/account/login" in current_url
                or "/login" in current_url
                or "/admin/login" in current_url
            ):
                log("Page", url, "pass", f"{name} - redirects to login (expected)", "info")
                return True
            else:
                log(
                    "Page",
                    url,
                    "warn",
                    f"{name} - expected login redirect but got {current_url}",
                    "warn",
                )
                return True

        if status == 200:
            log("Page", url, "pass", f"{name} - HTTP {status}", "info")
            return True
        elif status == 301 or status == 302:
            log("Page", url, "pass", f"{name} - Redirect {status}", "info")
            return True
        elif status == 404:
            log("Page", url, "fail", f"{name} - 404 NOT FOUND", "error")
            return False
        elif status == 500:
            log("Page", url, "fail", f"{name} - 500 SERVER ERROR", "error")
            return False
        elif status == 403:
            log("Page", url, "warn", f"{name} - 403 FORBIDDEN", "warn")
            return False
        else:
            log("Page", url, "warn", f"{name} - HTTP {status}", "warn")
            return False
    except Exception as e:
        log("Page", url, "fail", f"{name} - Exception: {str(e)[:100]}", "error")
        return False


def test_api(session, url, name, method="GET", data=None, expect_status=200):
    """Test an API endpoint."""
    try:
        full_url = f"{BASE}{url}"
        if method == "GET":
            resp = session.get(full_url, timeout=15000, allow_redirects=True)
        else:
            resp = session.post(full_url, json=data, timeout=15000, allow_redirects=True)

        if resp.status_code == expect_status:
            try:
                body = resp.json()
                log("API", url, "pass", f"{name} - HTTP {resp.status_code}", "info")
                return True, body
            except:
                log("API", url, "pass", f"{name} - HTTP {resp.status_code} (non-JSON)", "info")
                return True, resp.text
        elif resp.status_code == 401:
            log("API", url, "warn", f"{name} - 401 Unauthorized (needs auth)", "warn")
            return False, None
        elif resp.status_code == 404:
            log("API", url, "fail", f"{name} - 404 NOT FOUND", "error")
            return False, None
        elif resp.status_code == 500:
            log("API", url, "fail", f"{name} - 500 SERVER ERROR", "error")
            try:
                err = resp.text[:200]
            except:
                err = ""
            log("API", url, "fail", f"  Error body: {err}", "error")
            return False, None
        else:
            log(
                "API",
                url,
                "warn",
                f"{name} - HTTP {resp.status_code} (expected {expect_status})",
                "warn",
            )
            return False, None
    except Exception as e:
        log("API", url, "fail", f"{name} - Exception: {str(e)[:100]}", "error")
        return False, None


def find_all_links(page):
    """Extract all internal links from the current page."""
    links = page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('a[href]'));
        return links.map(a => ({
            href: a.href,
            text: a.textContent.trim().substring(0, 60)
        })).filter(l => l.href.startsWith(window.location.origin));
    }""")
    return links


def main():
    import requests

    print("=" * 80)
    print("AgomTradePro Comprehensive System Test")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)

    # ========================
    # Phase 1: API Endpoints (no auth needed for many)
    # ========================
    print("\n--- Phase 1: API Endpoints ---")

    api_tests = [
        ("/api/", "API Root"),
        ("/api/health/", "Health Check"),
        ("/api/ready/", "Readiness Check"),
        ("/api/regime/current/", "Current Regime"),
        ("/api/regime/history/", "Regime History"),
        ("/api/policy/status/", "Policy Status"),
        ("/api/policy/events/", "Policy Events"),
        ("/api/signals/", "Signals List"),
        ("/api/signal/", "Signal (singular)"),
        ("/api/macro/supported-indicators/", "Macro Indicators"),
        ("/api/macro/data/", "Macro Data (no params)"),
        ("/api/backtest/", "Backtest List"),
        ("/api/audit/", "Audit List"),
        ("/api/dashboard/", "Dashboard API"),
        ("/api/pulse/", "Pulse API"),
        ("/api/account/profile/", "Account Profile"),
        ("/api/account/portfolios/", "Account Portfolios"),
        ("/api/equity/", "Equity API"),
        ("/api/fund/", "Fund API"),
        ("/api/sector/", "Sector API"),
        ("/api/asset-analysis/", "Asset Analysis API"),
        ("/api/filter/", "Filter API"),
        ("/api/factor/", "Factor API"),
        ("/api/rotation/", "Rotation API"),
        ("/api/hedge/", "Hedge API"),
        ("/api/events/", "Events API"),
        ("/api/sentiment/", "Sentiment API"),
        ("/api/strategy/", "Strategy API"),
        ("/api/simulated-trading/", "Simulated Trading API"),
        ("/api/simulated-trading/accounts/", "Simulated Trading Accounts"),
        ("/api/market-data/", "Market Data API"),
        ("/api/realtime/", "Realtime API"),
        ("/api/ai/", "AI Provider API"),
        ("/api/prompt/", "Prompt API"),
        ("/api/terminal/", "Terminal API"),
        ("/api/beta-gate/", "Beta Gate API"),
        ("/api/alpha/", "Alpha API"),
        ("/api/system/", "System API"),
        ("/api/system/config-center/", "Config Center API"),
        ("/api/system/config-capabilities/", "Config Capabilities API"),
        ("/api/share/", "Share API"),
        ("/api/agent-runtime/", "Agent Runtime API"),
        ("/api/ai-capability/", "AI Capability API"),
        ("/api/schema/", "API Schema"),
        ("/api/docs/", "Swagger UI"),
        ("/api/redoc/", "ReDoc"),
        ("/metrics/", "Prometheus Metrics"),
        ("/api/decision/funnel/context/", "Decision Funnel Context"),
        ("/api/decision/audit/", "Decision Audit"),
    ]

    session = requests.Session()
    api_ok = 0
    api_fail = 0
    for url, name in api_tests:
        ok, _ = test_api(session, url, name)
        if ok:
            api_ok += 1
        else:
            api_fail += 1

    print(f"\n  API Summary: {api_ok} passed, {api_fail} failed out of {len(api_tests)}")

    # ========================
    # Phase 2: Browser-based page tests
    # ========================
    print("\n--- Phase 2: Browser Page Tests ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Capture console errors
        console_errors = []
        page.on(
            "console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None
        )

        # 2a: Landing page
        print("\n  [Landing Page]")
        test_page(page, "/", "Home / Landing")
        page.screenshot(path="test_screenshots/01_home.png", full_page=True)

        # Check landing page content
        page.goto(f"{BASE}/", wait_until="networkidle", timeout=15000)
        links = find_all_links(page)
        log("Nav", "/", "info", f"Found {len(links)} links on home page", "info")

        # 2b: Login as admin
        print("\n  [Login]")
        page.goto(f"{BASE}/admin/login/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/02_login_page.png", full_page=True)

        try:
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "Aa123456")
            page.click('input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)
            if "/admin/" in page.url and "login" not in page.url:
                log("Auth", "/admin/login/", "pass", "Admin login successful", "info")
                page.screenshot(path="test_screenshots/03_admin_logged_in.png", full_page=True)
            else:
                log(
                    "Auth",
                    "/admin/login/",
                    "fail",
                    f"Login may have failed, URL: {page.url}",
                    "error",
                )
                page.screenshot(path="test_screenshots/03_admin_login_fail.png", full_page=True)
        except Exception as e:
            log("Auth", "/admin/login/", "fail", f"Login error: {str(e)[:100]}", "error")

        # 2c: Test all major page routes
        print("\n  [Page Routes - Authenticated]")
        page_routes = [
            ("/", "Home"),
            ("/admin/", "Admin Index"),
            ("/dashboard/", "Dashboard"),
            ("/regime/", "Regime Page"),
            ("/macro/", "Macro Data Page"),
            ("/signal/", "Signal Page"),
            ("/policy/", "Policy Page"),
            ("/policy/workbench/", "Policy Workbench"),
            ("/backtest/", "Backtest Page"),
            ("/audit/", "Audit Page"),
            ("/sector/", "Sector Page"),
            ("/equity/", "Equity Page"),
            ("/fund/", "Fund Page"),
            ("/asset-analysis/", "Asset Analysis Page"),
            ("/filter/", "Filter Page"),
            ("/factor/", "Factor Page"),
            ("/rotation/", "Rotation Page"),
            ("/hedge/", "Hedge Page"),
            ("/strategy/", "Strategy Page"),
            ("/realtime/", "Realtime Page"),
            ("/simulated-trading/", "Simulated Trading"),
            ("/simulated-trading/my-accounts/", "My Accounts"),
            ("/account/", "Account Page"),
            ("/ai/", "AI Provider Page"),
            ("/prompt/", "Prompt Page"),
            ("/terminal/", "Terminal Page"),
            ("/terminal/config/", "Terminal Config"),
            ("/docs/", "Docs Page"),
            ("/ops/", "Ops Center"),
            ("/ops/mcp-tools/", "MCP Tools Page"),
            ("/ops/agent-runtime/", "Agent Runtime Ops"),
            ("/chat-example/", "Chat Example"),
            ("/asset-analysis/screen/", "Asset Screen"),
            ("/decision/workspace/", "Decision Workspace"),
            ("/events/", "Events Page"),
            ("/sentiment/", "Sentiment Page"),
            ("/market-data/", "Market Data Page"),
            ("/metrics/", "Prometheus Metrics"),
        ]

        page_ok = 0
        page_fail = 0
        for url, name in page_routes:
            if test_page(page, url, name):
                page_ok += 1
            else:
                page_fail += 1

        print(f"\n  Page Summary: {page_ok} passed, {page_fail} failed out of {len(page_routes)}")

        # 2d: Collect all links from home page and test them
        print("\n  [Link Crawl from Home Page]")
        page.goto(f"{BASE}/", wait_until="networkidle", timeout=15000)
        home_links = find_all_links(page)
        unique_hrefs = set()
        for link in home_links:
            href = link["href"].replace(BASE, "")
            if href and not href.startswith("#") and href not in unique_hrefs:
                unique_hrefs.add(href)
                test_page(page, href, f"Home link: {link['text'][:30]}")

        # 2e: Test navigation from dashboard
        print("\n  [Dashboard Navigation]")
        page.goto(f"{BASE}/dashboard/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/04_dashboard.png", full_page=True)
        dash_links = find_all_links(page)
        log("Nav", "/dashboard/", "info", f"Found {len(dash_links)} links on dashboard", "info")

        # 2f: Test regime page workflow
        print("\n  [Regime Page Workflow]")
        page.goto(f"{BASE}/regime/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/05_regime.png", full_page=True)
        regime_links = find_all_links(page)
        log("Nav", "/regime/", "info", f"Found {len(regime_links)} links on regime page", "info")

        # 2g: Test signal page workflow
        print("\n  [Signal Page Workflow]")
        page.goto(f"{BASE}/signal/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/06_signal.png", full_page=True)

        # 2h: Test policy page workflow
        print("\n  [Policy Page Workflow]")
        page.goto(f"{BASE}/policy/workbench/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/07_policy.png", full_page=True)

        # 2i: Test backtest page workflow
        print("\n  [Backtest Page Workflow]")
        page.goto(f"{BASE}/backtest/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/08_backtest.png", full_page=True)

        # 2j: Test terminal
        print("\n  [Terminal Page]")
        page.goto(f"{BASE}/terminal/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/09_terminal.png", full_page=True)

        # 2k: Test AI provider page
        print("\n  [AI Provider Page]")
        page.goto(f"{BASE}/ai/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/10_ai_provider.png", full_page=True)

        # 2l: Test account page
        print("\n  [Account Page]")
        page.goto(f"{BASE}/account/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/11_account.png", full_page=True)

        # 2m: Test simulated trading page
        print("\n  [Simulated Trading Page]")
        page.goto(f"{BASE}/simulated-trading/my-accounts/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/12_simulated_trading.png", full_page=True)

        # 2n: Collect ALL links from major pages and test them
        print("\n  [Deep Link Crawl from All Major Pages]")
        all_tested = set()
        for start_url in ["/", "/dashboard/", "/regime/", "/signal/", "/policy/", "/backtest/"]:
            try:
                page.goto(f"{BASE}{start_url}", wait_until="networkidle", timeout=15000)
                page_links = find_all_links(page)
                for link in page_links:
                    href = link["href"].replace(BASE, "").split("?")[0]
                    if href and not href.startswith("#") and href not in all_tested:
                        all_tested.add(href)
                        test_page(page, href, f"[from {start_url}] {link['text'][:30]}")
            except:
                pass

        # 2o: Report console errors
        print("\n  [Console Errors Summary]")
        if console_errors:
            for err in console_errors[:20]:
                log("Console", "JS Error", "warn", err[:120], "warn")
        else:
            log("Console", "JS Errors", "pass", "No console errors captured", "info")

        browser.close()

    # ========================
    # Phase 3: API Data Chain Tests
    # ========================
    print("\n--- Phase 3: API Data Chain Tests ---")

    # Login to get session
    login_resp = session.post(
        f"{BASE}/admin/login/",
        data={
            "username": "admin",
            "password": "Aa123456",
        },
        allow_redirects=True,
    )
    log(
        "Auth",
        "Session login",
        "pass" if login_resp.status_code == 200 else "fail",
        f"HTTP {login_resp.status_code}",
        "info",
    )

    # Test data chain: Macro -> Regime -> Signals
    print("\n  [Data Chain: Macro Indicators]")
    ok, indicators = test_api(session, "/api/macro/supported-indicators/", "Macro Indicators")
    if ok and indicators:
        if isinstance(indicators, dict) and "data" in indicators:
            ind_count = len(indicators["data"]) if isinstance(indicators["data"], list) else "N/A"
            log("Data", "macro indicators", "info", f"Count: {ind_count}", "info")
        elif isinstance(indicators, list):
            log("Data", "macro indicators", "info", f"Count: {len(indicators)}", "info")

    print("\n  [Data Chain: Regime -> Current]")
    ok, regime = test_api(session, "/api/regime/current/", "Current Regime")
    if ok and regime:
        if isinstance(regime, dict):
            if "data" in regime:
                r = regime["data"]
                log(
                    "Data",
                    "regime",
                    "info",
                    f"Regime: {r.get('dominant_regime', 'N/A')}, Confidence: {r.get('confidence', 'N/A')}",
                    "info",
                )
            elif "dominant_regime" in regime:
                log(
                    "Data",
                    "regime",
                    "info",
                    f"Regime: {regime.get('dominant_regime', 'N/A')}, Confidence: {regime.get('confidence', 'N/A')}",
                    "info",
                )

    print("\n  [Data Chain: Policy Status]")
    ok, policy = test_api(session, "/api/policy/status/", "Policy Status")
    if ok and policy:
        if isinstance(policy, dict):
            if "data" in policy:
                log(
                    "Data",
                    "policy",
                    "info",
                    f"Level: {policy['data'].get('current_level', 'N/A')}, Name: {policy['data'].get('level_name', 'N/A')}",
                    "info",
                )
            else:
                log(
                    "Data",
                    "policy",
                    "info",
                    f"Level: {policy.get('current_level', 'N/A')}, Name: {policy.get('level_name', 'N/A')}",
                    "info",
                )

    print("\n  [Data Chain: Signals]")
    ok, signals = test_api(session, "/api/signals/", "Signals")
    if ok and signals:
        if isinstance(signals, dict) and "data" in signals:
            sig_count = len(signals["data"]) if isinstance(signals["data"], list) else "N/A"
            log("Data", "signals", "info", f"Signal count: {sig_count}", "info")
        elif isinstance(signals, list):
            log("Data", "signals", "info", f"Signal count: {len(signals)}", "info")

    print("\n  [Data Chain: Pulse]")
    ok, pulse = test_api(session, "/api/pulse/", "Pulse API")
    if ok and pulse:
        log("Data", "pulse", "info", f"Pulse data: {str(pulse)[:200]}", "info")

    print("\n  [Data Chain: Backtest]")
    ok, backtest = test_api(session, "/api/backtest/", "Backtest List")
    if ok and backtest:
        if isinstance(backtest, dict) and "results" in backtest:
            log("Data", "backtest", "info", f"Backtest count: {len(backtest['results'])}", "info")
        elif isinstance(backtest, list):
            log("Data", "backtest", "info", f"Backtest count: {len(backtest)}", "info")

    print("\n  [Data Chain: Audit]")
    ok, audit = test_api(session, "/api/audit/", "Audit List")

    print("\n  [Data Chain: Simulated Trading Accounts]")
    ok, accounts = test_api(session, "/api/simulated-trading/accounts/", "Sim Trading Accounts")

    print("\n  [Data Chain: Dashboard]")
    ok, dashboard = test_api(session, "/api/dashboard/", "Dashboard Data")

    # ========================
    # Phase 4: Redirect Tests
    # ========================
    print("\n--- Phase 4: Redirect Tests ---")
    redirects_to_test = [
        ("/policy/dashboard/", "/policy/workbench/", "Policy Dashboard -> Workbench"),
        ("/sentiment/dashboard/", "/policy/workbench/", "Sentiment Dashboard -> Workbench"),
        ("/sentiment/analyze/", "/policy/workbench/", "Sentiment Analyze -> Workbench"),
        ("/api/portfolio/", "/api/simulated-trading/accounts/", "Portfolio -> Sim Trading"),
        ("/api/macro/indicators/", "/api/macro/supported-indicators/", "Macro Indicators alias"),
    ]
    for src, expected_dst, name in redirects_to_test:
        try:
            resp = session.get(f"{BASE}{src}", allow_redirects=True, timeout=10)
            final_url = resp.url.replace(BASE, "")
            if expected_dst in final_url:
                log("Redirect", src, "pass", f"{name} -> {final_url}", "info")
            else:
                log(
                    "Redirect",
                    src,
                    "warn",
                    f"{name}: expected {expected_dst}, got {final_url}",
                    "warn",
                )
        except Exception as e:
            log("Redirect", src, "fail", f"{name} - {str(e)[:80]}", "error")

    # ========================
    # Phase 5: Form & Interactive Workflow Tests
    # ========================
    print("\n--- Phase 5: Interactive Workflow Tests (Playwright) ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Login first
        page.goto(f"{BASE}/admin/login/", wait_until="networkidle", timeout=15000)
        try:
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "Aa123456")
            page.click('input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)
        except:
            pass

        # 5a: Test admin site navigation
        print("\n  [Admin Site]")
        page.goto(f"{BASE}/admin/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/13_admin_index.png", full_page=True)

        # Check admin sidebar links
        admin_links = page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('#content-main a, .app-module a, .model a'));
            return links.map(a => ({href: a.href, text: a.textContent.trim().substring(0, 50)}));
        }""")
        log("Admin", "admin links", "info", f"Found {len(admin_links)} admin section links", "info")

        # Click through a few admin sections
        for link in admin_links[:5]:
            href = link["href"].replace(BASE, "")
            test_page(page, href, f"Admin: {link['text'][:30]}")

        # 5b: Test Setup Wizard
        print("\n  [Setup Wizard]")
        test_page(page, "/setup/", "Setup Wizard")

        # 5c: Test docs page
        print("\n  [Docs Page]")
        test_page(page, "/docs/", "Docs Page")

        # 5d: Test Ops Center
        print("\n  [Ops Center]")
        page.goto(f"{BASE}/ops/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/14_ops.png", full_page=True)
        ops_links = find_all_links(page)
        log("Nav", "/ops/", "info", f"Found {len(ops_links)} links on ops center", "info")

        # 5e: Test MCP Tools page
        print("\n  [MCP Tools]")
        page.goto(f"{BASE}/ops/mcp-tools/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/15_mcp_tools.png", full_page=True)

        # 5f: Test chat-example
        print("\n  [Chat Example]")
        page.goto(f"{BASE}/chat-example/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/16_chat_example.png", full_page=True)

        # 5g: Test API schema/docs pages
        print("\n  [API Docs]")
        page.goto(f"{BASE}/api/docs/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/17_swagger.png", full_page=True)

        # 5h: Test decision workspace
        print("\n  [Decision Workspace]")
        page.goto(f"{BASE}/decision/workspace/", wait_until="networkidle", timeout=15000)
        page.screenshot(path="test_screenshots/18_decision_workspace.png", full_page=True)

        # 5i: Test audit pages
        print("\n  [Audit Pages]")
        audit_pages = [
            "/audit/",
            "/audit/review/",
            "/audit/attribution/",
            "/audit/operation-logs/",
            "/audit/decision-traces/",
            "/audit/threshold-validation/",
            "/audit/indicator-performance/",
        ]
        for url in audit_pages:
            test_page(page, url, f"Audit: {url}")

        # 5j: Test rotation pages
        print("\n  [Rotation Pages]")
        rotation_pages = [
            "/rotation/",
            "/rotation/configs/",
            "/rotation/assets/",
            "/rotation/signals/",
            "/rotation/account-config/",
        ]
        for url in rotation_pages:
            test_page(page, url, f"Rotation: {url}")

        # 5k: Test alpha trigger pages
        print("\n  [Alpha Trigger Pages]")
        alpha_pages = [
            "/alpha-trigger/",
            "/alpha-trigger/create/",
            "/alpha-trigger/performance/",
        ]
        for url in alpha_pages:
            test_page(page, url, f"Alpha Trigger: {url}")

        # 5l: Test beta gate pages
        print("\n  [Beta Gate Pages]")
        beta_pages = [
            "/beta-gate/",
            "/beta-gate/config/",
            "/beta-gate/test-asset/",
        ]
        for url in beta_pages:
            test_page(page, url, f"Beta Gate: {url}")

        # 5m: Test decision rhythm pages
        print("\n  [Decision Rhythm Pages]")
        rhythm_pages = [
            "/decision-rhythm/quota/",
            "/decision-rhythm/quota/config/",
        ]
        for url in rhythm_pages:
            test_page(page, url, f"Decision Rhythm: {url}")

        # 5n: Test fund pages
        print("\n  [Fund Pages]")
        fund_pages = ["/fund/", "/fund/analysis/", "/fund/compare/"]
        for url in fund_pages:
            test_page(page, url, f"Fund: {url}")

        # 5o: Test equity pages
        print("\n  [Equity Pages]")
        equity_pages = ["/equity/", "/equity/analysis/", "/equity/screener/"]
        for url in equity_pages:
            test_page(page, url, f"Equity: {url}")

        # 5p: Test sector pages
        print("\n  [Sector Pages]")
        sector_pages = ["/sector/", "/sector/heatmap/", "/sector/rotation/"]
        for url in sector_pages:
            test_page(page, url, f"Sector: {url}")

        browser.close()

    # ========================
    # Final Report
    # ========================
    print("\n" + "=" * 80)
    print("FINAL TEST REPORT")
    print("=" * 80)

    passed = sum(1 for r in RESULTS if r["status"] == "pass")
    failed = sum(1 for r in RESULTS if r["status"] == "fail")
    warned = sum(1 for r in RESULTS if r["status"] == "warn")
    info = sum(1 for r in RESULTS if r["status"] == "info")

    print(f"\nTotal Results: {len(RESULTS)}")
    print(f"  ✅ Passed: {passed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  ⚠️  Warnings: {warned}")
    print(f"  ℹ️  Info: {info}")

    if failed > 0:
        print(f"\n{'=' * 60}")
        print("FAILED ITEMS (need fixing):")
        print(f"{'=' * 60}")
        for r in RESULTS:
            if r["status"] == "fail":
                print(f"  ❌ [{r['category']}] {r['target']} - {r['detail']}")

    if warned > 0:
        print(f"\n{'=' * 60}")
        print("WARNINGS (may need attention):")
        print(f"{'=' * 60}")
        for r in RESULTS:
            if r["status"] == "warn":
                print(f"  ⚠️  [{r['category']}] {r['target']} - {r['detail']}")

    # Save detailed report
    report_path = "test_comprehensive_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed report saved to: {report_path}")

    return failed


if __name__ == "__main__":
    import os

    os.makedirs("test_screenshots", exist_ok=True)
    exit_code = main()
    sys.exit(1 if exit_code > 0 else 0)
