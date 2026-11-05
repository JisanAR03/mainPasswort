"""Login fields inside shadow DOM (web components, as on Reddit's login).

The inputs live in shadow roots, so an ordinary document query cannot see them. The
menu, the popup's Fill and the save prompt must all work on them; a closed shadow root
(which no extension can see into) must fail honestly and without harm."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from conftest import SeededVault
from playwright.sync_api import BrowserContext, Page
from support import (
    PASSWORD_LOCAL,
    PASSWORD_SUBMITTED,
    PASSWORD_UPDATED,
    fill_button,
    frame_closed,
    menu_frame,
    no_extension_frame,
    open_login_page,
    open_popup,
    prompt_frame,
    status,
    wait_for_matches,
)

pytestmark = pytest.mark.e2e

VaultFactory = Callable[..., SeededVault]
NEW_USER = "shadow-user@example.com"
HIDDEN = ("h-display", "h-visibility", "h-opacity", "h-zero")


def _value(page: Page, name: str) -> str:
    """The input's value, read through the page's own reference (works for closed roots)."""
    return str(page.evaluate("(name) => window.__inputs[name].value", name))


def _menu_items(page: Page) -> list[str]:
    return menu_frame(page).locator("#menu button").all_inner_texts()


def _wait_filled(page: Page) -> None:
    page.wait_for_function("() => window.__inputs.password.value !== ''")


def _sign_in(page: Page, username: str, password: str) -> None:
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("fake-button button")
    page.wait_for_selector("#done")


@pytest.mark.parametrize("mode", ["flat", "nested"])
def test_the_menu_opens_on_a_username_inside_shadow_dom_and_fills_both_fields(
    browser: BrowserContext, vault: SeededVault, mode: str
) -> None:
    url = vault.url(f"shadow-login.html?mode={mode}")
    page = open_login_page(browser, url)
    page.click("input[name=username]")
    assert _menu_items(page) == ["Local Dev\ndev@example.com"]
    menu_frame(page).locator("#menu button").first.click()
    _wait_filled(page)
    assert _value(page, "username") == "dev@example.com"
    assert _value(page, "password") == PASSWORD_LOCAL
    assert page.url == url, "the fill must not submit"
    assert page.evaluate("() => window.__logins") == 0
    # `input` is composed, as a typed one is: the page hears the fill outside the shadow roots
    assert page.evaluate("() => window.__docInputs") >= 2
    for name in HIDDEN:
        assert _value(page, name) == "", f"{name} must stay empty"
    assert frame_closed(page, "menu.html")


def test_the_password_field_inside_shadow_dom_offers_the_login_too(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("shadow-login.html"))
    page.click("input[name=password]")
    assert _menu_items(page) == ["Local Dev\ndev@example.com"]
    menu_frame(page).locator("#menu button").first.click()
    _wait_filled(page)
    assert _value(page, "username") == "dev@example.com"


def test_the_popup_fill_works_on_fields_inside_shadow_dom(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("shadow-login.html"))
    popup = open_popup(browser)
    wait_for_matches(popup)
    fill_button(popup)
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Filled.'", timeout=30_000
    )
    assert _value(page, "username") == "dev@example.com"
    assert _value(page, "password") == PASSWORD_LOCAL
    for name in HIDDEN:
        assert _value(page, name) == ""


def test_a_new_login_signed_in_through_shadow_dom_is_offered_and_saved(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("shadow-login.html"))
    _sign_in(page, NEW_USER, PASSWORD_SUBMITTED)
    prompt = prompt_frame(page)
    assert "Save this login?" in prompt.inner_text("body")
    assert NEW_USER in prompt.inner_text("body")
    assert PASSWORD_SUBMITTED not in prompt.inner_text("body")
    prompt.click("#save")
    prompt.wait_for_function(
        "() => document.getElementById('message').textContent.includes('Saved')"
    )
    assert vault.logins()[f"127.0.0.1:{vault.port}"] == PASSWORD_SUBMITTED


def test_a_changed_password_through_shadow_dom_offers_the_update(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("shadow-login.html?mode=nested"))
    _sign_in(page, "dev@example.com", PASSWORD_UPDATED)
    prompt = prompt_frame(page)
    assert "Update saved password?" in prompt.inner_text("body")
    prompt.click("#save")
    prompt.wait_for_function(
        "() => document.getElementById('message').textContent.includes('updated')"
    )
    assert vault.logins()["Local Dev"] == PASSWORD_UPDATED


def test_a_closed_shadow_root_is_out_of_reach_and_says_so(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("shadow-login.html?mode=closed"))
    box = page.evaluate(
        "() => { const r = window.__inputs.username.getBoundingClientRect();"
        " return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }"
    )
    page.mouse.click(box["x"], box["y"])
    assert no_extension_frame(page, "menu.html"), "no menu on a field the extension cannot see"
    # the popup's Fill reports the truth instead of claiming success
    popup = open_popup(browser)
    wait_for_matches(popup)
    fill_button(popup)
    popup.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('No login fields')",
        timeout=30_000,
    )
    assert status(popup) == "No login fields found on this page."
    assert _value(page, "username") == "" and _value(page, "password") == ""
