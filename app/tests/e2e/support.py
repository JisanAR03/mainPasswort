"""Shared constants and small helpers for the e2e suite (no pytest here)."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[3]
EXTENSION_DIR = ROOT / "extension"
TEST_PAGES = EXTENSION_DIR / "test-pages"
MANIFEST_PATH = EXTENSION_DIR / "manifest.json"
BRIDGE_APP = Path(__file__).parent / "bridge_app.py"
HOST_NAME = "com.personalvault.host"
EXTENSION_ID = "pkmjgefocdecdncjcpdlohfnahebkkpi"
POPUP_URL = f"chrome-extension://{EXTENSION_ID}/popup.html"

# what the tests type or seed; never anything anyone uses for real
PASSWORD_LOCAL = "test password for 127.0.0.1"
PASSWORD_ALIAS = "test password for localhost"
PASSWORD_SECURE = "test password for the https entry"
PASSWORD_TYPED = "a password typed in the test popup"
PASSWORD_SUBMITTED = "a password submitted in the test page"
PASSWORD_UPDATED = "a replacement password submitted in the test page"
SEEDED_TITLES = ("Local Dev", "Local Dev Alias", "Secure Only")

STATUS_READY = "() => !document.getElementById('status').textContent.startsWith('Checking')"


def open_popup(browser: BrowserContext, wait_for: str | None = None) -> Page:
    """The popup as a tab, once its first status round trip has finished.

    With ``wait_for``, a popup whose refresh shows that selector — the popup
    reads its state once per load, so a state that is still being written
    (a save candidate, say) needs another open.
    """
    for _ in range(3):
        page = browser.new_page()
        page.goto(POPUP_URL)
        page.wait_for_function(STATUS_READY, timeout=30_000)
        if wait_for is None:
            return page
        try:
            page.wait_for_selector(wait_for, state="visible", timeout=5_000)
        except PlaywrightTimeoutError:
            page.close()
            continue
        return page
    raise AssertionError(f"the popup never showed {wait_for}")


def status(page: Page) -> str:
    return page.inner_text("#status")


def wait_for_matches(page: Page) -> None:
    """The popup renders its list after the status line, so anything the list
    shows (or does not show) is only decided once one row is there."""
    try:
        page.wait_for_selector("#matches .match", timeout=30_000)
    except PlaywrightTimeoutError:
        raise AssertionError(f"the popup lists no matches; it says {status(page)!r}") from None


def titles(page: Page) -> list[str]:
    return page.locator("#matches .title").all_inner_texts()


def usernames(page: Page) -> list[str]:
    return page.locator("#matches .username").all_inner_texts()


def fill_button(page: Page, index: int = 0) -> None:
    page.locator("#matches .match button").nth(index).click()


def open_login_page(browser: BrowserContext, url: str) -> Page:
    page = browser.new_page()
    page.goto(url)
    return page


def submit_login(page: Page, username: str, password: str) -> None:
    """Fill and really submit the test page's form (detect.js territory)."""
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#submit")
    page.wait_for_load_state()


def storage_dump(page: Page) -> str:
    """Everything extension storage holds, as one string to search in."""
    return page.evaluate(
        "async () => JSON.stringify({"
        "  local: await chrome.storage.local.get(null),"
        "  session: await chrome.storage.session.get(null)"
        "})"
    )


def watched_script_ids(page: Page) -> list[str]:
    return page.evaluate(
        "async () => (await chrome.scripting.getRegisteredContentScripts()).map((s) => s.id)"
    )
