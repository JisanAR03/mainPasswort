"""M4-04: the save prompt — detection is on only while watching, and nothing
reaches the vault without a click."""

from __future__ import annotations

import json

import pytest
from conftest import Bridge
from playwright.sync_api import BrowserContext, Page
from support import (
    PASSWORD_SUBMITTED,
    PASSWORD_UPDATED,
    SEEDED_TITLES,
    open_login_page,
    open_popup,
    storage_dump,
    submit_login,
    wait_for_matches,
    watched_script_ids,
)

pytestmark = pytest.mark.e2e


def test_the_detector_is_registered_only_while_watching(control_page: Page) -> None:
    assert watched_script_ids(control_page) == []
    control_page.evaluate("() => chrome.runtime.sendMessage({ type: 'watch_on' })")
    assert watched_script_ids(control_page) == ["detect-submits"]
    control_page.evaluate("() => chrome.runtime.sendMessage({ type: 'watch_off' })")
    assert watched_script_ids(control_page) == []


def _watch_and_submit(
    browser: BrowserContext,
    bridge: Bridge,
    control_page: Page,
    password: str,
    username: str = "dev@example.com",
) -> None:
    """Turn watching on from the popup, then submit a login on a fresh page."""
    popup = open_popup(browser)
    popup.check("#watch")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Watching')",
        timeout=30_000,
    )
    assert "detect-submits" in watched_script_ids(control_page)
    page = open_login_page(browser, bridge.url("login.html"))
    submit_login(page, username, password)


def test_a_submitted_login_is_saved_only_after_the_click(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    _watch_and_submit(browser, bridge, control_page, PASSWORD_SUBMITTED)
    # nothing was written: the submit only offered, it did not save
    assert set(bridge.logins()) == set(SEEDED_TITLES)
    # the offer sits in session storage (gone when the browser closes) with a badge
    dump = json.loads(storage_dump(control_page))
    assert dump["session"]["pending_save"]["password"] == PASSWORD_SUBMITTED
    assert "pending_save" not in dump["local"]
    assert control_page.evaluate("() => chrome.action.getBadgeText({})") == "1"

    popup = open_popup(browser, wait_for="#save-prompt")
    assert "Save the login for 127.0.0.1?" in popup.inner_text("#save-question")
    popup.click("#save-new")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Saved.'", timeout=30_000
    )
    popup.wait_for_selector("#save-prompt", state="hidden")
    logins = bridge.logins()
    assert len(logins) == len(SEEDED_TITLES) + 1
    assert PASSWORD_SUBMITTED in logins.values()
    # with no title typed, the entry is named after the page it was saved from
    assert bridge.url("login.html") in logins


def test_update_replaces_the_stored_password(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    _watch_and_submit(browser, bridge, control_page, PASSWORD_UPDATED)
    popup = open_popup(browser, wait_for="#save-prompt")
    assert popup.inner_text("#save-update") == "Update Local Dev"
    popup.click("#save-update")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Updated.'", timeout=30_000
    )
    assert bridge.logins()["Local Dev"] == PASSWORD_UPDATED
    assert PASSWORD_UPDATED not in bridge.logins()["Local Dev Alias"]


def test_dismiss_saves_nothing(browser: BrowserContext, bridge: Bridge, control_page: Page) -> None:
    _watch_and_submit(browser, bridge, control_page, PASSWORD_SUBMITTED)
    before = bridge.logins()
    popup = open_popup(browser, wait_for="#save-prompt")
    popup.click("#save-dismiss")
    popup.wait_for_selector("#save-prompt", state="hidden")
    assert bridge.logins() == before


def test_an_expired_candidate_is_not_offered(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    open_login_page(browser, bridge.url("login.html"))
    control_page.evaluate(
        "async (url) => chrome.storage.session.set({"
        "  pending_save: {"
        "    url, username: 'dev@example.com', password: 'stale',"
        "    at: Date.now() - 3 * 60 * 1000"
        "  }"
        "})",
        bridge.url("login.html"),
    )
    popup = open_popup(browser)
    wait_for_matches(popup)  # the popup decides about the offer in that same pass
    popup.wait_for_selector("#save-prompt", state="hidden", timeout=5_000)
    assert set(bridge.logins()) == set(SEEDED_TITLES)
