"""The popup — which logins it offers, and the add, lock and generate actions."""

from __future__ import annotations

import pytest
from conftest import SeededVault
from playwright.sync_api import BrowserContext
from support import (
    PASSWORD_ALIAS,
    PASSWORD_LOCAL,
    PASSWORD_TYPED,
    open_login_page,
    open_popup,
    status,
    storage_dump,
    titles,
    usernames,
    wait_for_matches,
)

pytestmark = pytest.mark.e2e


def test_only_the_exact_host_is_offered(browser: BrowserContext, vault: SeededVault) -> None:
    page = open_login_page(browser, vault.url("login.html"))
    popup = open_popup(browser)
    wait_for_matches(popup)
    assert titles(popup) == ["Local Dev"]
    assert usernames(popup) == ["dev@example.com"]

    # the look-alike host is a different site: its entry is not offered
    page.goto(vault.url("login.html", host="localhost"))
    look_alike = open_popup(browser)
    wait_for_matches(look_alike)
    assert titles(look_alike) == ["Local Dev Alias"]
    # and neither list holds a password
    text = look_alike.inner_text("body")
    assert PASSWORD_LOCAL not in text
    assert PASSWORD_ALIAS not in text


def test_an_https_entry_is_never_offered_on_http(
    browser: BrowserContext, vault: SeededVault
) -> None:
    open_login_page(browser, vault.url("login.html"))
    popup = open_popup(browser)
    wait_for_matches(popup)
    assert "Secure Only" not in titles(popup)
    assert popup.is_visible("#insecure")


def test_lock_then_status(browser: BrowserContext, vault: SeededVault) -> None:
    open_login_page(browser, vault.url("login.html"))
    popup = open_popup(browser)
    assert status(popup) == "Unlocked: E2E"
    popup.click("#lock")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Locked.'",
        timeout=30_000,
    )
    assert status(popup) == "Locked."


def test_the_add_form_saves_into_the_vault_only(
    browser: BrowserContext, vault: SeededVault, control_page
) -> None:
    open_login_page(browser, vault.url("login.html"))
    popup = open_popup(browser)
    before = vault.logins()

    popup.fill("#add-username", "new@example.com")
    popup.fill("#add-password", PASSWORD_TYPED)
    popup.fill("#add-title", "Added In The Popup")
    popup.click("#add-save")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Saved.'", timeout=30_000
    )

    assert popup.input_value("#add-password") == ""
    after = vault.logins()
    assert set(after) - set(before) == {"Added In The Popup"}
    assert after["Added In The Popup"] == PASSWORD_TYPED
    assert PASSWORD_TYPED not in storage_dump(control_page)


def test_suggest_generates_a_password_without_storing_it(
    browser: BrowserContext, vault: SeededVault, control_page
) -> None:
    open_login_page(browser, vault.url("login.html"))
    popup = open_popup(browser)
    popup.click("#add-suggest")
    popup.wait_for_function(
        "() => document.getElementById('add-password').value.length > 0", timeout=30_000
    )
    suggested = popup.input_value("#add-password")
    assert len(suggested) >= 16
    assert suggested not in storage_dump(control_page)
