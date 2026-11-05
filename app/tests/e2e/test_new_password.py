"""The new-password offer: on a sign-up or change-password field (autocomplete
"new-password") of an unlocked vault, the menu offers "Suggest a strong password";
a click fills that field and its confirmation, never submits, and the login is
then offered for saving like any other."""

from __future__ import annotations

import re

import pytest
from conftest import Ext, SeededVault
from playwright.sync_api import BrowserContext, Page
from support import (
    menu_frame,
    no_extension_frame,
    open_login_page,
    prompt_frame,
)

pytestmark = pytest.mark.e2e

SUGGEST = "Suggest a strong password"


def _items(page: Page) -> list[str]:
    return menu_frame(page).locator("#menu button").all_inner_texts()


def _signup(browser: BrowserContext, vault: SeededVault) -> Page:
    # a site the vault has no login for: the signup page on the look-alike host
    return open_login_page(browser, vault.url("signup.html", host="other.test"))


def test_a_new_password_field_offers_a_suggestion_and_a_click_fills_both_boxes(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = _signup(browser, vault)
    page.click("#password")
    assert _items(page) == [f"{SUGGEST}\nFills this field and its confirmation"]

    menu_frame(page).locator("#menu button").first.click()
    page.wait_for_function("() => document.getElementById('confirm').value !== ''", timeout=15_000)
    first, second = page.input_value("#password"), page.input_value("#confirm")
    assert first == second and len(first) == 20
    assert page.evaluate("() => window.__submits") == 0, "never submits"
    assert page.evaluate("() => window.__inputs") >= 2, "the page heard it like typing"
    assert page.input_value("#username") == "", "the username box is left alone"
    assert no_extension_frame(page, "menu.html"), "the menu closes after the suggestion"


def test_the_suggested_password_is_offered_for_saving_when_the_form_is_sent(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    # a loopback address: saving is never offered on plain http to another machine,
    # and the suggestion is the first row even where a saved login also matches
    page = open_login_page(browser, vault.url("signup.html"))
    page.click("#password")
    menu_frame(page).locator("#menu button").first.click()
    page.wait_for_function("() => document.getElementById('confirm').value !== ''", timeout=15_000)
    password = page.input_value("#password")
    page.fill("#username", "fresh@example.com")
    page.click("#submit")
    page.wait_for_load_state()

    prompt = prompt_frame(page)
    assert prompt.inner_text("#question") == "Save this login?"
    prompt.click("#save")
    prompt.wait_for_function(
        "() => document.getElementById('message').textContent.includes('Saved')", timeout=30_000
    )
    saved = next(
        e
        for e in ext.ok("ext_list", {"query": ""})["entries"]
        if e["username"] == "fresh@example.com"
    )
    assert ext.ok("ext_get", {"entryId": saved["id"]})["entry"]["password"] == password


def test_the_suggestion_follows_the_generator_options(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    ext.ok(
        "ext_settings",
        {
            "generator": {
                "length": 33,
                "upper": True,
                "lower": True,
                "digits": False,
                "symbols": False,
                "excludeLookalikes": True,
            }
        },
    )
    page = _signup(browser, vault)
    page.click("#password")
    menu_frame(page).locator("#menu button").first.click()
    page.wait_for_function("() => document.getElementById('password').value !== ''", timeout=15_000)
    assert re.fullmatch(r"[A-Za-z]{33}", page.input_value("#password"))


def test_an_ordinary_login_field_gets_no_suggestion(
    browser: BrowserContext, vault: SeededVault
) -> None:
    page = open_login_page(browser, vault.url("login.html"))
    page.click("#password")  # autocomplete="current-password"
    assert SUGGEST not in " ".join(_items(page))


def test_a_locked_vault_offers_unlock_not_a_suggestion(
    browser: BrowserContext, vault_factory
) -> None:
    vault = vault_factory(locked=True)
    page = _signup(browser, vault)
    page.click("#password")
    items = _items(page)
    assert items == ["Unlock Personal Vault\nOpens the unlock page"]
    assert all(SUGGEST not in item for item in items)


def test_a_new_password_field_on_a_site_with_a_login_offers_both(
    browser: BrowserContext, vault: SeededVault
) -> None:
    """A change-password page of a site you have a login for: the suggestion comes
    first, the saved login stays one click away."""
    page = open_login_page(browser, vault.url("signup.html"))  # 127.0.0.1: "Local Dev" matches
    page.click("#password")
    items = _items(page)
    assert items[0].startswith(SUGGEST)
    assert "Local Dev\ndev@example.com" in items
    # every row is on show: the frame is as tall as its content (it used to be a few
    # pixels short per row, cutting off the last one)
    assert menu_frame(page).evaluate(
        "() => document.documentElement.scrollHeight <= document.documentElement.clientHeight"
    ), "the last row of the menu is cut off"
