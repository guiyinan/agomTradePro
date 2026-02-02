"""Headless browser test script for AgomSAAF development server."""
import subprocess
import sys
import time
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def install_playwright():
    """Install playwright if not already installed."""
    try:
        import playwright
        from playwright.sync_api import sync_playwright
        print("Playwright is installed")
        return True
    except ImportError:
        print("Installing playwright...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "--quiet", "--user"])
        print("Installing chromium browser...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium", "--quiet"])
        return True

def test_website():
    """Test the development website with headless browser."""
    from playwright.sync_api import sync_playwright

    base_url = "http://127.0.0.1:8000"

    with sync_playwright() as p:
        print("Launching headless browser...")
        browser = p.chromium.launch(headless=True)

        print(f"Navigating to {base_url}...")
        page = browser.new_page()

        # Capture console messages
        console_messages = []
        def on_console(msg):
            console_messages.append(f"[{msg.type}] {msg.text}")
        page.on("console", on_console)

        # Navigate and wait for load
        response = page.goto(base_url, wait_until="networkidle", timeout=10000)

        print(f"Status: {response.status}")
        print(f"URL: {page.url}")

        # Get page title
        title = page.title()
        print(f"Title: {title}")

        # Check for any console errors
        errors = [msg for msg in console_messages if "error" in msg.lower()]
        if errors:
            print("\nConsole Errors:")
            for err in errors:
                print(f"  {err}")
        else:
            print("\nNo console errors detected.")

        # Take a screenshot
        screenshot_path = "test_screenshot.png"
        page.screenshot(path=screenshot_path)
        print(f"\nScreenshot saved to: {screenshot_path}")

        # Get page content summary
        body_text = page.evaluate("() => document.body.innerText")
        print(f"\nPage text length: {len(body_text)} chars")
        print(f"Page preview (first 200 chars):\n{body_text[:200]}...")

        # Check for common elements
        links = page.locator("a").count()
        forms = page.locator("form").count()
        buttons = page.locator("button").count()

        print(f"\nElement counts:")
        print(f"  Links: {links}")
        print(f"  Forms: {forms}")
        print(f"  Buttons: {buttons}")

        browser.close()
        print("\nTest completed!")

def main():
    """Main entry point."""
    try:
        install_playwright()
        test_website()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
