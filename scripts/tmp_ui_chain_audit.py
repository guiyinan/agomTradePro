import json
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8000"
USERNAME = "admin"
PASSWORD = "Aa123456"

PAGES = [
    "/dashboard/",
    "/regime/dashboard/",
    "/policy/workbench/",
    "/macro/data/",
    "/signal/manage/",
    "/backtest/",
    "/simulated-trading/my-accounts/",
    "/decision/workspace/",
    "/equity/screen/",
    "/fund/dashboard/",
    "/ops/",
]

API_ENDPOINTS = [
    "/api/dashboard/v1/summary/",
    "/api/dashboard/v1/regime-quadrant/",
    "/api/dashboard/v1/signal-status/",
    "/api/policy/status/",
    "/api/signal/health/",
    "/api/backtest/statistics/",
    "/api/simulated-trading/accounts/",
    "/api/account/profile/",
    "/api/realtime/health/",
]


def trim(text: str | None, limit: int = 600) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact[:limit]


def main() -> None:
    out_path = Path("tmp_ui_chain_audit.json")
    result: dict = {"base_url": BASE_URL, "login": {}, "pages": [], "apis": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.goto(f"{BASE_URL}/account/login/", wait_until="networkidle", timeout=30000)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle", timeout=30000)

        result["login"] = {
            "final_url": page.url,
            "title": page.title(),
            "body_text": trim(page.locator("body").inner_text()),
            "has_logout": page.locator("text=登出").count() > 0,
        }

        for path in PAGES:
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[dict] = []

            def on_console(msg):
                if msg.type == "error":
                    console_errors.append(msg.text)

            def on_page_error(exc):
                page_errors.append(str(exc))

            def on_response(resp):
                if resp.status >= 400:
                    failed_requests.append({"url": resp.url, "status": resp.status})

            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            page.on("response", on_response)

            page.goto(f"{BASE_URL}{path}", wait_until="networkidle", timeout=30000)
            body = page.locator("body").inner_text()
            headings = page.locator("h1, h2, h3").all_inner_texts()
            alerts = page.locator(".alert, .error, .warning, .empty-state").all_inner_texts()

            result["pages"].append(
                {
                    "path": path,
                    "url": page.url,
                    "title": page.title(),
                    "headings": headings[:10],
                    "alerts": alerts[:10],
                    "body_excerpt": trim(body, 1000),
                    "console_errors": console_errors[:20],
                    "page_errors": page_errors[:20],
                    "failed_requests": failed_requests[:30],
                }
            )

            page.remove_listener("console", on_console)
            page.remove_listener("pageerror", on_page_error)
            page.remove_listener("response", on_response)

        api_page = context.new_page()
        for endpoint in API_ENDPOINTS:
            status = None
            payload = None
            error = None
            try:
                response = api_page.goto(f"{BASE_URL}{endpoint}", wait_until="networkidle", timeout=30000)
                status = response.status if response else None
                text = api_page.locator("body").inner_text()
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = trim(text, 800)
            except Exception as exc:
                error = str(exc)

            result["apis"].append(
                {
                    "path": endpoint,
                    "status": status,
                    "payload": payload,
                    "error": error,
                }
            )

        browser.close()

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
