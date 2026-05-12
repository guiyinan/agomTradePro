"""Admin panel headless browser test script."""
import io
import sys

from playwright.sync_api import sync_playwright

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def test_admin():
    """Test the Django admin panel."""
    base_url = "http://127.0.0.1:8000"
    username = "admin"
    password = "Aa123456"

    with sync_playwright() as p:
        print("=" * 60)
        print("AgomTradePro Admin Panel Test")
        print("=" * 60)

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to admin login page
        admin_url = f"{base_url}/admin/"
        print(f"\n[1] Navigating to: {admin_url}")
        response = page.goto(admin_url, wait_until="networkidle", timeout=10000)
        print(f"    Status: {response.status}")
        print(f"    Title: {page.title}")

        # Screenshot of login page
        page.screenshot(path="admin_01_login.png")
        print("    Screenshot: admin_01_login.png")

        # Fill login form
        print(f"\n[2] Logging in as '{username}'...")
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)

        # Submit form
        page.click("input[type='submit']")
        page.wait_for_load_state("networkidle")

        print(f"    Current URL: {page.url}")
        print(f"    Title: {page.title}")

        # Check if login successful
        if "/admin/login/" in page.url:
            print("    ERROR: Login failed!")
            page.screenshot(path="admin_02_login_failed.png")
            browser.close()
            return

        print("    Login successful!")
        page.screenshot(path="admin_02_dashboard.png")

        # Get admin sections
        print("\n[3] Scanning admin sections...")

        # Get app modules
        app_modules = page.locator(".app-module").all()
        print(f"    Found {len(app_modules)} app modules:")

        admin_data = {
            "apps": [],
            "models_count": 0,
            "total_links": 0
        }

        for i, module in enumerate(app_modules, 1):
            module_name = module.locator("caption").inner_text() or "Unnamed"
            print(f"      {i}. {module_name}")

            # Count models in this module
            models = module.locator("tr.model").all()
            admin_data["apps"].append({
                "name": module_name,
                "model_count": len(models)
            })
            admin_data["models_count"] += len(models)

        print("\n[4] Admin Statistics:")
        print(f"    Total Apps: {len(admin_data['apps'])}")
        print(f"    Total Models: {admin_data['models_count']}")

        # Check for common admin features
        print("\n[5] Checking admin features...")

        features = {
            "Recent Actions": page.locator("#recent-actions-module").count() > 0,
            "Search box": page.locator("input[type='search'], input[name='q']").count() > 0,
            "User info": page.locator("#user-tools").count() > 0,
        }

        for feature, exists in features.items():
            status = "✓" if exists else "✗"
            print(f"    {status} {feature}")

        page.screenshot(path="admin_03_full_page.png", full_page=True)
        print("\n[6] Full page screenshot: admin_03_full_page.png")

        # Check for any console errors
        console_errors = []
        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)

        # Test navigating to a model (if any exists)
        if admin_data["models_count"] > 0:
            print("\n[7] Testing model list view...")

            # Try to find and click first model link
            first_model = page.locator("tr.model a").first
            if first_model.count() > 0:
                model_name = first_model.inner_text()
                print(f"    Navigating to: {model_name}")
                first_model.click()
                page.wait_for_load_state("networkidle")

                print(f"    URL: {page.url}")
                page.screenshot(path="admin_04_model_list.png")
                print("    Screenshot: admin_04_model_list.png")

                # Check for list elements
                if "#result_list" in page.content() or page.locator("table").count() > 0:
                    rows = page.locator("tbody tr").count()
                    print(f"    Records in list: {rows}")

        # Logout
        print("\n[8] Logging out...")
        logout_link = page.locator("a[href='/admin/logout/']")
        if logout_link.count() > 0:
            logout_link.click()
            page.wait_for_load_state("networkidle")
            print(f"    Logged out, URL: {page.url}")

        browser.close()

        print(f"\n{'=' * 60}")
        print("Test Summary")
        print(f"{'=' * 60}")
        print(f"Admin URL: {admin_url}")
        print(f"Login: {'SUCCESS' if '/admin/login/' not in page.url else 'FAILED'}")
        print(f"App Modules: {len(admin_data['apps'])}")
        print(f"Total Models: {admin_data['models_count']}")
        print(f"Console Errors: {len(console_errors)}")

        if console_errors:
            print("\nConsole Errors:")
            for err in console_errors:
                print(f"  - {err}")
        else:
            print("\nNo console errors detected.")

        print("\nScreenshots saved:")
        print("  - admin_01_login.png")
        print("  - admin_02_dashboard.png")
        print("  - admin_03_full_page.png")
        print("  - admin_04_model_list.png")
        print(f"{'=' * 60}")

        return admin_data


if __name__ == "__main__":
    try:
        test_admin()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
