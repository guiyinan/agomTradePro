"""
AgomTradePro Full Test Suite - Localhost:8000
Comprehensive test covering: API smoke, core business, UAT (Playwright), MCP, SDK
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import requests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

BASE_URL = os.environ.get("AGOMTRADEPRO_BASE_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN") or os.environ.get("AGOMTRADEPRO_API_TOKEN")
USERNAME = os.environ.get("API_USERNAME") or os.environ.get("AGOMTRADEPRO_USERNAME")
PASSWORD = os.environ.get("API_PASSWORD") or os.environ.get("AGOMTRADEPRO_PASSWORD")
AUTH_HEADERS = {"Authorization": f"Token {API_TOKEN}"} if API_TOKEN else {}
SESSION = requests.Session()
SESSION.trust_env = False
AUTH_BOOTSTRAPPED = False
AUTH_MODE = "none"

PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0
RESULTS: list[dict] = []


def _bootstrap_auth() -> None:
    global AUTH_BOOTSTRAPPED, AUTH_MODE
    if AUTH_BOOTSTRAPPED:
        return

    if API_TOKEN:
        try:
            response = SESSION.get(
                f"{BASE_URL}/api/account/profile/",
                headers=AUTH_HEADERS,
                timeout=15,
            )
            if response.status_code == 200:
                AUTH_MODE = "token"
                AUTH_BOOTSTRAPPED = True
                return
        except Exception:
            pass

    if USERNAME and PASSWORD:
        login_url = f"{BASE_URL}/account/login/"
        response = SESSION.get(login_url, timeout=15)
        csrf_token = SESSION.cookies.get("csrftoken", "")
        login_response = SESSION.post(
            f"{login_url}?next=/dashboard/",
            data={
                "username": USERNAME,
                "password": PASSWORD,
                "csrfmiddlewaretoken": csrf_token,
            },
            headers={"Referer": login_url},
            timeout=15,
            allow_redirects=False,
        )
        if login_response.status_code in (302, 303):
            AUTH_MODE = "session"
            AUTH_BOOTSTRAPPED = True
            return

    AUTH_BOOTSTRAPPED = True


def _auth_headers(method: str = "GET") -> dict[str, str]:
    if AUTH_MODE == "token":
        return dict(AUTH_HEADERS)

    headers: dict[str, str] = {}
    if AUTH_MODE == "session" and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        csrf_token = SESSION.cookies.get("csrftoken")
        if csrf_token:
            headers["X-CSRFToken"] = csrf_token
        headers["Referer"] = f"{BASE_URL}/account/login/"
    return headers


def record(name: str, status: str, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT, SKIP_COUNT
    if status == "PASS":
        PASS_COUNT += 1
        icon = "OK"
    elif status == "FAIL":
        FAIL_COUNT += 1
        icon = " X"
    else:
        SKIP_COUNT += 1
        icon = "~~"
    RESULTS.append({"name": name, "status": status, "detail": detail})
    print(f"  [{icon}] {name}: {status}" + (f" - {detail}" if detail else ""))


def api_get(path: str, expect_status: int = 200, use_auth: bool = True) -> tuple[bool, Any]:
    try:
        if use_auth:
            _bootstrap_auth()
        h = _auth_headers("GET") if use_auth else {}
        r = SESSION.get(f"{BASE_URL}{path}", headers=h, timeout=15)
        if r.status_code != expect_status:
            return False, f"status={r.status_code}, body={r.text[:200]}"
        try:
            return True, r.json()
        except Exception:
            return True, r.text[:200]
    except Exception as e:
        return False, str(e)


def api_post(path: str, data: dict = None, expect_status: int = 200) -> tuple[bool, Any]:
    try:
        _bootstrap_auth()
        r = SESSION.post(
            f"{BASE_URL}{path}",
            json=data or {},
            headers=_auth_headers("POST"),
            timeout=15,
        )
        if r.status_code != expect_status:
            return False, f"status={r.status_code}, body={r.text[:200]}"
        try:
            return True, r.json()
        except Exception:
            return True, r.text[:200]
    except Exception as e:
        return False, str(e)


# ============================================================
# Section 1: Health & Infrastructure
# ============================================================
def test_health_infra():
    print("\n" + "=" * 60)
    print("  Section 1: Health & Infrastructure")
    print("=" * 60)

    ok, data = api_get("/api/health/", use_auth=False)
    record(
        "Health check",
        "PASS" if ok and data.get("status") == "ok" else "FAIL",
        str(data)[:100] if ok else data,
    )

    ok, data = api_get("/api/ready/", use_auth=False)
    checks = data.get("checks", {}) if ok else {}
    db_ok = checks.get("database", {}).get("status") == "ok" if checks else False
    record(
        "Readiness - DB",
        "PASS" if db_ok else "FAIL",
        f"database={checks.get('database', {})}" if checks else str(data)[:100],
    )

    redis_ok = checks.get("redis", {}).get("status") == "ok" if checks else False
    record(
        "Readiness - Redis",
        "PASS" if redis_ok else "FAIL",
        f"redis={checks.get('redis', {})}" if checks else str(data)[:100],
    )

    celery_ok = checks.get("celery", {}).get("status") == "ok" if checks else False
    record(
        "Readiness - Celery",
        "PASS" if celery_ok else "FAIL",
        f"celery={checks.get('celery', {})}" if checks else str(data)[:100],
    )

    ok, data = api_get("/api/", use_auth=False)
    endpoints = data.get("endpoints", {}) if ok else {}
    record(
        "API Root (endpoints count)",
        "PASS" if ok and len(endpoints) > 20 else "FAIL",
        f"{len(endpoints)} endpoints" if ok else str(data)[:100],
    )

    ok, _ = api_get("/metrics/", use_auth=False)
    record("Prometheus metrics", "PASS" if ok else "FAIL")

    ok, _ = api_get("/api/schema/", use_auth=False)
    record("OpenAPI schema", "PASS" if ok else "FAIL")


# ============================================================
# Section 2: Core Business APIs
# ============================================================
def test_core_business():
    print("\n" + "=" * 60)
    print("  Section 2: Core Business APIs")
    print("=" * 60)

    ok, data = api_get("/api/regime/current/")
    if ok and isinstance(data, dict) and data.get("success"):
        d = data.get("data", {})
        record(
            "Regime current",
            "PASS",
            f"regime={d.get('dominant_regime')}, confidence={d.get('confidence', 0):.2f}",
        )
    else:
        record("Regime current", "FAIL", str(data)[:200])

    ok, data = api_get("/api/regime/history/")
    record(
        "Regime history",
        "PASS" if ok else "FAIL",
        f"count={data.get('count', len(data.get('data', [])))}" if ok else str(data)[:100],
    )

    ok, data = api_get("/api/policy/status/")
    if ok and isinstance(data, dict) and "current_level" in data:
        record(
            "Policy status",
            "PASS",
            f"level={data.get('current_level')}, name={data.get('level_name')}",
        )
    else:
        record("Policy status", "FAIL", str(data)[:200])

    ok, data = api_get("/api/signal/")
    record(
        "Signals list",
        "PASS" if ok else "FAIL",
        f"count={data.get('count', 'N/A')}" if ok else str(data)[:100],
    )

    ok, data = api_get("/api/pulse/current/")
    record("Pulse current", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/pulse/history/")
    record("Pulse history", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/data-center/")
    record(
        "Data center API root",
        "PASS" if ok and "macro_series" in data.get("endpoints", {}) else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/data-center/macro/series/?indicator_code=CN_PMI")
    record(
        "Data center macro series (PMI)",
        "PASS" if ok and "data" in data else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )


# ============================================================
# Section 3: Business Module APIs
# ============================================================
def test_business_modules():
    print("\n" + "=" * 60)
    print("  Section 3: Business Module APIs")
    print("=" * 60)

    ok, data = api_get("/api/account/profile/")
    record(
        "Account profile",
        "PASS" if ok and "display_name" in (data if isinstance(data, dict) else {}) else "FAIL",
        f"display_name={data.get('display_name')}"
        if ok and isinstance(data, dict)
        else str(data)[:100],
    )

    ok, data = api_get("/api/account/")
    record("Account API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/backtest/")
    record(
        "Backtest API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/backtest/backtests/")
    record("Backtest list", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/strategy/")
    record(
        "Strategy API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/strategy/strategies/")
    record("Strategy list", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/alpha/")
    record("Alpha API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/alpha/health/")
    record("Alpha health", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/factor/")
    record("Factor API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/rotation/")
    record(
        "Rotation API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/hedge/")
    record("Hedge API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/equity/")
    record("Equity API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/fund/")
    record("Fund API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/sector/")
    record("Sector API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/audit/")
    record("Audit API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/filter/")
    record("Filter API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/sentiment/")
    record(
        "Sentiment API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/realtime/")
    record(
        "Realtime API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/data-center/")
    record(
        "Data Center API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/events/")
    record("Events API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/simulated-trading/")
    record(
        "Simulated Trading API root",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/dashboard/")
    record(
        "Dashboard API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/share/")
    record("Share API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/ai/")
    record(
        "AI Provider API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/prompt/")
    record("Prompt API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/terminal/")
    record(
        "Terminal API root", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/system/")
    record(
        "System/Task Monitor API root",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/agent-runtime/")
    record(
        "Agent Runtime API root",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/ai-capability/")
    record(
        "AI Capability API root",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )


# ============================================================
# Section 4: Decision Workflow APIs
# ============================================================
def test_decision_workflow():
    print("\n" + "=" * 60)
    print("  Section 4: Decision Workflow APIs")
    print("=" * 60)

    ok, data = api_get("/api/decision/funnel/context/")
    record(
        "Decision funnel context",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/decision/audit/")
    record("Decision audit", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/decision/workspace/aggregated/")
    record(
        "Decision workspace aggregated",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/decision/workspace/params/")
    record(
        "Decision workspace params",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok_accounts, accounts_data = api_get("/api/simulated-trading/accounts/")
    account_id = None
    if ok_accounts and isinstance(accounts_data, dict):
        accounts = accounts_data.get("accounts", [])
        if accounts:
            account_id = accounts[0].get("account_id")

    recommendations_path = "/api/decision/workspace/recommendations/"
    if account_id is not None:
        recommendations_path = f"{recommendations_path}?account_id={account_id}"

    ok, data = api_get(recommendations_path)
    record(
        "Decision workspace recommendations",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/decision-rhythm/summary/")
    record(
        "Decision rhythm summary",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/decision-rhythm/")
    record(
        "Decision rhythm list", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )

    ok, data = api_get("/api/beta-gate/")
    record("Beta Gate API", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100])

    ok, data = api_get("/api/alpha-triggers/")
    record(
        "Alpha Triggers list", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )


# ============================================================
# Section 5: System Config & Capabilities
# ============================================================
def test_system_config():
    print("\n" + "=" * 60)
    print("  Section 5: System Config & Capabilities")
    print("=" * 60)

    ok, data = api_get("/api/system/config-center/")
    record(
        "Config center snapshot",
        "PASS" if ok else "FAIL",
        str(data)[:150] if ok else str(data)[:100],
    )

    ok, data = api_get("/api/system/config-capabilities/")
    record(
        "Config capabilities", "PASS" if ok else "FAIL", str(data)[:150] if ok else str(data)[:100]
    )


# ============================================================
# Section 6: Page Routes (HTML responses)
# ============================================================
def test_page_routes():
    print("\n" + "=" * 60)
    print("  Section 6: Page Routes (HTML)")
    print("=" * 60)

    page_routes = [
        ("/", "Home page"),
        ("/dashboard/", "Dashboard"),
        ("/regime/", "Regime page"),
        ("/macro/", "Macro page"),
        ("/policy/", "Policy page"),
        ("/signal/", "Signal page"),
        ("/backtest/", "Backtest page"),
        ("/strategy/", "Strategy page"),
        ("/sector/", "Sector page"),
        ("/equity/", "Equity page"),
        ("/fund/", "Fund page"),
        ("/factor/", "Factor page"),
        ("/rotation/", "Rotation page"),
        ("/hedge/", "Hedge page"),
        ("/audit/", "Audit page"),
        ("/ai/", "AI Provider page"),
        ("/prompt/", "Prompt page"),
        ("/terminal/", "Terminal page"),
        ("/settings/", "Settings center"),
        ("/settings/mcp-tools/", "MCP tools page"),
        ("/docs/", "Docs page"),
        ("/simulated-trading/", "Simulated trading page"),
        ("/realtime/", "Realtime page"),
        ("/decision/workspace/", "Decision workspace"),
        ("/api/docs/", "Swagger UI"),
        ("/api/redoc/", "ReDoc"),
    ]
    for path, name in page_routes:
        try:
            _bootstrap_auth()
            r = SESSION.get(
                f"{BASE_URL}{path}",
                headers=_auth_headers("GET"),
                timeout=15,
                allow_redirects=True,
            )
            if r.status_code == 200:
                is_html = "text/html" in r.headers.get("Content-Type", "")
                record(name, "PASS", f"HTML={is_html}, {len(r.content)} bytes")
            elif r.status_code in (301, 302):
                record(name, "PASS", f"redirect -> {r.headers.get('Location', '?')}")
            else:
                record(name, "FAIL", f"status={r.status_code}")
        except Exception as e:
            record(name, "FAIL", str(e)[:100])


# ============================================================
# Section 7: MCP Server Test
# ============================================================
def test_mcp_server():
    print("\n" + "=" * 60)
    print("  Section 7: MCP Server")
    print("=" * 60)

    try:
        from agomtradepro_mcp import server

        record("MCP Server import", "PASS")
    except ImportError as e:
        record("MCP Server import", "SKIP", str(e))
        return

    try:
        from agomtradepro_mcp.server import server as srv

        record("MCP Server instance", "PASS", f"name={srv.name}")
    except Exception as e:
        record("MCP Server instance", "FAIL", str(e))

    try:
        import asyncio
        from agomtradepro_mcp.server import server as srv

        tools = asyncio.run(srv.list_tools())
        record(
            "MCP Tools count",
            "PASS" if len(tools) > 0 else "FAIL",
            f"{len(tools)} tools registered",
        )
    except Exception as e:
        record("MCP Tools listing", "FAIL", str(e)[:150])

    try:
        import asyncio
        from agomtradepro_mcp.server import list_resources

        resources = asyncio.run(list_resources())
        record("MCP Resources", "PASS", f"{len(resources)} resources")
    except Exception as e:
        record("MCP Resources", "FAIL", str(e)[:150])

    try:
        import asyncio
        from agomtradepro_mcp.server import list_prompts

        prompts = asyncio.run(list_prompts())
        record("MCP Prompts", "PASS", f"{len(prompts)} prompts")
    except Exception as e:
        record("MCP Prompts", "FAIL", str(e)[:150])

    try:
        from agomtradepro_mcp.tools import (
            regime_tools,
            signal_tools,
            macro_tools,
            policy_tools,
            backtest_tools,
            account_tools,
            strategy_tools,
        )

        record("MCP Tool modules import", "PASS", "7 core tool modules")
    except ImportError as e:
        record("MCP Tool modules import", "FAIL", str(e))


# ============================================================
# Section 8: SDK Client Test
# ============================================================
def test_sdk_client():
    print("\n" + "=" * 60)
    print("  Section 8: SDK Client")
    print("=" * 60)

    try:
        sdk_path = str(project_root / "sdk")
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        from agomtradepro import AgomTradeProClient

        record("SDK import", "PASS")
    except ImportError as e:
        record("SDK import", "SKIP", str(e))
        return

    try:
        kwargs = {"base_url": BASE_URL}
        if API_TOKEN:
            kwargs["api_token"] = API_TOKEN
        elif USERNAME and PASSWORD:
            kwargs["username"] = USERNAME
            kwargs["password"] = PASSWORD
        client = AgomTradeProClient(**kwargs)
        record("SDK client creation", "PASS")
    except Exception as e:
        record("SDK client creation", "FAIL", str(e))
        return

    try:
        indicators = client.macro.list_indicators()
        record(
            "SDK macro indicators",
            "PASS" if indicators else "FAIL",
            f"{len(indicators)} indicators",
        )
    except Exception as e:
        record("SDK macro indicators", "FAIL", str(e)[:100])

    try:
        regime = client.regime.get_current()
        record("SDK regime current", "PASS", f"regime={regime.dominant_regime}")
    except Exception as e:
        record("SDK regime current", "FAIL", str(e)[:100])

    try:
        status = client.policy.get_status()
        record("SDK policy status", "PASS", f"gear={status.current_gear}")
    except Exception as e:
        record("SDK policy status", "FAIL", str(e)[:100])

    try:
        signals = client.signal.list()
        record("SDK signals list", "PASS", f"{len(signals)} signals")
    except Exception as e:
        record("SDK signals list", "FAIL", str(e)[:100])


# ============================================================
# Summary
# ============================================================
def print_summary():
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    total = PASS_COUNT + FAIL_COUNT + SKIP_COUNT
    for r in RESULTS:
        icon = {"PASS": "OK", "FAIL": " X", "SKIP": "~~"}[r["status"]]
        detail = f" - {r['detail']}" if r["detail"] else ""
        print(f"  [{icon}] {r['name']}: {r['status']}{detail}")

    print()
    print(f"  Total: {total} tests")
    print(f"  PASS:  {PASS_COUNT}")
    print(f"  FAIL:  {FAIL_COUNT}")
    print(f"  SKIP:  {SKIP_COUNT}")
    print(f"  Pass Rate: {PASS_COUNT / total * 100:.1f}%" if total > 0 else "  N/A")
    print()

    if FAIL_COUNT == 0:
        print("  ALL TESTS PASSED!")
    else:
        print(f"  {FAIL_COUNT} TEST(S) FAILED - see details above")
    print("=" * 60)

    return 0 if FAIL_COUNT == 0 else 1


def main():
    print("=" * 60)
    print("  AgomTradePro Full Test Suite")
    print(f"  Target: {BASE_URL}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    ok, _ = api_get("/api/health/", use_auth=False)
    if not ok:
        print("  ERROR: Server is not running!")
        return 1

    test_health_infra()
    test_core_business()
    test_business_modules()
    test_decision_workflow()
    test_system_config()
    test_page_routes()
    test_mcp_server()
    test_sdk_client()

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
