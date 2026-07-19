import sys
from playwright.sync_api import sync_playwright

APP_URL = "https://biosetu-hackcore-2026-npbvrytmfqfpxtczxgdncq.streamlit.app/"
WAKE_BUTTON_TEXT = "Yes, get this app back up!"
TIMEOUT_MS = 60_000


def keep_awake(url: str) -> bool:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)
            if wake_button.count() > 0:
                print(f"[{url}] Sleep screen detected — clicking wake-up button.")
                wake_button.first.click()
                page.wait_for_timeout(15_000)
                print(f"[{url}] Wake-up triggered.")
            else:
                print(f"[{url}] App already awake — no action needed.")

            return True
        except Exception as e:
            print(f"[{url}] ERROR: {e}", file=sys.stderr)
            return False
        finally:
            browser.close()


if __name__ == "__main__":
    success = keep_awake(APP_URL)
    sys.exit(0 if success else 1)
