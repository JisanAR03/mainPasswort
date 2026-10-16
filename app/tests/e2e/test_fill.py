"""M4-03: the one-click fill — top frame only, visible fields only, no submit."""

from __future__ import annotations

import pytest
from conftest import Bridge
from playwright.sync_api import BrowserContext, Page
from support import PASSWORD_LOCAL, fill_button, open_login_page, open_popup, status

pytestmark = pytest.mark.e2e


def _fill(browser: BrowserContext, page: Page) -> Page:
    popup = open_popup(browser)
    fill_button(popup)
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Filled.'", timeout=30_000
    )
    return popup


def test_fill_fills_the_visible_pair_and_never_submits(
    browser: BrowserContext, bridge: Bridge
) -> None:
    url = bridge.url("login.html")
    page = open_login_page(browser, url)
    before = set(page.evaluate("() => Object.getOwnPropertyNames(window)"))
    _fill(browser, page)
    assert page.input_value("#username") == "dev@example.com"
    assert page.input_value("#password") == PASSWORD_LOCAL
    assert page.url == url, "the fill must not submit the form"
    assert page.evaluate("() => window.__submits") == 0
    # the injected function runs in the extension's own world and writes nothing
    # to the page, so the page's scripts cannot see it and it leaves no copy
    assert set(page.evaluate("() => Object.getOwnPropertyNames(window)")) == before
    assert page.evaluate("() => [localStorage.length, sessionStorage.length]") == [0, 0]


def test_hostile_fields_are_never_filled(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("hostile-fields.html"))
    _fill(browser, page)
    assert page.input_value("#username") == "dev@example.com"
    assert page.input_value("#password") == PASSWORD_LOCAL
    for hostile in ("#hidden-field", "#invisible-field", "#transparent-field", "#zero-field"):
        assert page.input_value(hostile) == "", f"{hostile} must stay empty"


def test_the_fill_stays_in_the_top_frame(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("framed.html"))
    frame = page.frame_locator("#frame")
    frame.locator("#frame-password").wait_for(state="visible")  # the frame has loaded
    _fill(browser, page)
    assert page.input_value("#password") == PASSWORD_LOCAL
    assert frame.locator("#frame-username").input_value() == ""
    assert frame.locator("#frame-password").input_value() == ""


def test_a_page_that_changed_since_listing_is_never_filled(
    browser: BrowserContext, bridge: Bridge
) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    popup = open_popup(browser)
    page.goto(bridge.url("framed-login.html"))  # the tab moved on
    fill_button(popup)
    popup.wait_for_function(
        "() => document.getElementById('status').textContent.includes('page changed')",
        timeout=30_000,
    )
    assert status(popup).startswith("The page changed")
    assert page.input_value("#frame-password") == ""
    assert page.input_value("#frame-username") == ""
