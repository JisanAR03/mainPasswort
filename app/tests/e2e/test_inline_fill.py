"""The suggestion menu on login fields: what it offers, where it never appears,
and that the page around it can read none of it."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from conftest import Bridge
from playwright.sync_api import BrowserContext, Page
from support import (
    EXTENSION_ORIGIN,
    PASSWORD_INSECURE,
    PASSWORD_LOCAL,
    frame_closed,
    menu_frame,
    no_extension_frame,
    open_login_page,
)

pytestmark = pytest.mark.e2e

BridgeFactory = Callable[..., Bridge]


def _items(page: Page) -> list[str]:
    return menu_frame(page).locator("#menu button").all_inner_texts()


def _choose(page: Page, index: int = 0) -> None:
    menu_frame(page).locator("#menu button").nth(index).click()


def test_focusing_the_username_offers_the_saved_login_and_a_click_fills_it(
    browser: BrowserContext, bridge: Bridge
) -> None:
    url = bridge.url("login.html")
    page = open_login_page(browser, url)
    page.click("#username")
    assert _items(page) == ["Local Dev\ndev@example.com"]
    # the menu lists who, never a password
    assert PASSWORD_LOCAL not in menu_frame(page).inner_text("body")
    assert page.input_value("#password") == "", "nothing is filled before the click"

    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#username") == "dev@example.com"
    assert page.input_value("#password") == PASSWORD_LOCAL
    assert page.url == url, "the fill must not submit the form"
    assert page.evaluate("() => window.__submits") == 0
    assert frame_closed(page, "menu.html"), "the menu closes once it has filled"


def test_the_password_field_offers_it_too(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    page.click("#password")
    assert _items(page) == ["Local Dev\ndev@example.com"]


def test_the_page_cannot_read_the_menu(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    page.click("#username")
    menu_frame(page)
    seen = page.evaluate(
        "() => {"
        "  const host = document.querySelector('personal-vault');"
        "  return {"
        "    host: Boolean(host),"
        "    shadow: host ? host.shadowRoot : 'no host',"
        "    frames: document.querySelectorAll('iframe').length,"
        "    text: document.documentElement.innerText,"
        "    html: document.documentElement.outerHTML,"
        "  };"
        "}"
    )
    assert seen["host"] is True
    assert seen["shadow"] is None, "the shadow root is closed to the page"
    assert seen["frames"] == 0, "the menu frame is not reachable from the page's DOM"
    for leak in ("dev@example.com", "Local Dev", PASSWORD_LOCAL, "menu.html"):
        assert leak not in seen["text"]
        assert leak not in seen["html"]


def test_a_page_that_frames_the_menu_itself_gets_nothing(
    browser: BrowserContext, bridge: Bridge
) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    page.evaluate(
        "(origin) => {"
        "  const frame = document.createElement('iframe');"
        "  frame.id = 'forged';"
        "  frame.src = origin + '/menu.html#' + '0'.repeat(32);"
        "  document.body.append(frame);"
        "}",
        EXTENSION_ORIGIN,
    )
    forged = page.frame_locator("#forged")
    forged.locator("body").wait_for()
    page.wait_for_timeout(1_000)
    assert forged.locator("#menu button").count() == 0
    assert page.input_value("#password") == ""


def test_a_site_with_no_saved_login_shows_no_menu(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html", host="other.test"))
    page.click("#username")
    page.click("#password")
    assert no_extension_frame(page, "menu.html")


def test_a_look_alike_host_is_offered_only_its_own_login(
    browser: BrowserContext, bridge: Bridge
) -> None:
    # localhost and 127.0.0.1 are different sites, and the https entry for
    # 127.0.0.1 is never offered on an http page
    page = open_login_page(browser, bridge.url("login.html", host="localhost"))
    page.click("#username")
    assert _items(page) == ["Local Dev Alias\nalias@example.com"]


def test_hidden_fields_are_never_filled(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("hostile-fields.html"))
    page.click("#username")
    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#password") == PASSWORD_LOCAL
    for hostile in ("#hidden-field", "#invisible-field", "#transparent-field", "#zero-field"):
        assert page.input_value(hostile) == "", f"{hostile} must stay empty"


@pytest.mark.parametrize("query", ["", "?same=1"], ids=["cross-origin", "same-origin"])
def test_no_menu_and_no_fill_inside_an_iframe(
    browser: BrowserContext, bridge: Bridge, query: str
) -> None:
    page = open_login_page(browser, bridge.url(f"iframe-login.html{query}"))
    frame = page.frame_locator("#frame")
    frame.locator("#frame-username").click()
    frame.locator("#frame-password").click()
    assert no_extension_frame(page, "menu.html")
    assert frame.locator("#frame-password").input_value() == ""


def test_a_form_built_by_script_gets_the_menu(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("js-form.html"))
    page.wait_for_selector("#username")
    page.click("#username")
    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#username") == "dev@example.com"


def test_a_page_without_a_form_gets_the_menu(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("spa.html"))
    page.click("#username")
    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#username") == "dev@example.com"
    assert page.input_value("#password") == PASSWORD_LOCAL


def test_a_two_step_login_fills_each_step(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("multi-step.html"))
    page.click("#username")
    _choose(page)
    page.wait_for_function("() => document.getElementById('username').value !== ''")
    assert page.input_value("#username") == "dev@example.com"
    assert frame_closed(page, "menu.html")
    page.click("#next")
    page.click("#password")
    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#password") == PASSWORD_LOCAL


def test_a_page_that_changed_since_the_menu_opened_is_not_filled(
    browser: BrowserContext, bridge: Bridge
) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    page.click("#username")
    menu = menu_frame(page)
    page.evaluate("() => history.pushState({}, '', 'elsewhere.html')")
    menu.locator("#menu button").first.click()
    menu.wait_for_selector("#message:not([hidden])")
    assert "page changed" in menu.inner_text("#message")
    assert page.input_value("#password") == ""


def test_plain_http_fills_only_with_a_warning(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html", host="insecure.test"))
    page.click("#username")
    menu = menu_frame(page)
    assert menu.is_visible("#insecure")
    assert _items(page) == ["Plain HTTP Site\nplain@example.com"]
    _choose(page)
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#password") == PASSWORD_INSECURE


def test_a_locked_vault_offers_unlock_instead(
    browser: BrowserContext, bridge_factory: BridgeFactory
) -> None:
    bridge = bridge_factory(locked=True)
    page = open_login_page(browser, bridge.url("login.html"))
    page.click("#password")
    assert _items(page) == ["Unlock Personal Vault\nOpens the desktop app"]
    _choose(page)
    menu = menu_frame(page)
    menu.wait_for_selector("#message:not([hidden])")
    assert "Unlock in the desktop app" in menu.inner_text("#message")
    assert bridge.unlock_requests() == 1
    assert page.input_value("#password") == ""


def test_without_the_app_the_menu_says_so(browser: BrowserContext, page_server: str) -> None:
    page = open_login_page(browser, f"{page_server}/login.html")
    page.click("#password")
    assert "Start the Personal Vault desktop app" in menu_frame(page).inner_text("#message")


def test_an_unpaired_browser_is_told_to_pair(
    browser: BrowserContext, bridge_factory: BridgeFactory
) -> None:
    bridge = bridge_factory(unpaired=True)
    page = open_login_page(browser, bridge.url("login.html"))
    page.click("#password")
    assert "not paired" in menu_frame(page).inner_text("#message")
