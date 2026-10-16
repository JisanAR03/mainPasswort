"""The save and update prompt: a login you submit is offered in the page, for
every kind of login form, and nothing reaches the vault without a click."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from conftest import Bridge
from playwright.sync_api import BrowserContext, Frame, Page
from support import (
    PASSWORD_LOCAL,
    PASSWORD_SUBMITTED,
    PASSWORD_UPDATED,
    SEEDED_TITLES,
    frame_closed,
    no_extension_frame,
    open_login_page,
    open_popup,
    prompt_frame,
    storage_dump,
    submit_login,
)

pytestmark = pytest.mark.e2e

BridgeFactory = Callable[..., Bridge]
NEW_USER = "new-user@example.com"


def _site(bridge: Bridge) -> str:
    return f"127.0.0.1:{bridge.port}"


def _saved_title(bridge: Bridge) -> str:
    return _site(bridge)  # a saved login is named after the site it came from


def _wait_message(prompt: Frame, text: str) -> None:
    prompt.wait_for_function(
        "(text) => document.getElementById('message').textContent.includes(text)", arg=text
    )


def _submit_new(browser: BrowserContext, bridge: Bridge) -> Page:
    page = open_login_page(browser, bridge.url("login.html"))
    submit_login(page, NEW_USER, PASSWORD_SUBMITTED)
    return page


def test_a_new_login_is_offered_in_the_page_and_saved_only_on_click(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    page = _submit_new(browser, bridge)
    prompt = prompt_frame(page)
    text = prompt.inner_text("body")
    assert "Save this login?" in text
    assert _site(bridge) in text
    assert NEW_USER in text
    assert PASSWORD_SUBMITTED not in text, "the prompt never shows the password"
    # nothing was written: the submit only offered
    assert set(bridge.logins()) == set(SEEDED_TITLES)
    # the offer sits in session storage (memory only), never in local storage
    dump = json.loads(storage_dump(control_page))
    assert dump["session"]["pending_save"]["username"] == NEW_USER
    assert PASSWORD_SUBMITTED not in json.dumps(dump["local"])

    prompt.click("#save")
    _wait_message(prompt, "Saved")
    logins = bridge.logins()
    assert logins[_saved_title(bridge)] == PASSWORD_SUBMITTED
    assert frame_closed(page, "prompt.html"), "the prompt goes once it has saved"
    assert "pending_save" not in json.loads(storage_dump(control_page))["session"]


def test_not_now_saves_nothing(browser: BrowserContext, bridge: Bridge) -> None:
    page = _submit_new(browser, bridge)
    prompt_frame(page).click("#later")
    assert frame_closed(page, "prompt.html")
    assert set(bridge.logins()) == set(SEEDED_TITLES)


def test_never_for_this_site_stops_offering(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    page = _submit_new(browser, bridge)
    prompt_frame(page).click("#never")
    assert frame_closed(page, "prompt.html")
    never = json.loads(storage_dump(control_page))["local"]["never_save"]
    assert never == [f"http://{_site(bridge)}"]

    again = open_login_page(browser, bridge.url("login.html"))
    submit_login(again, "another@example.com", PASSWORD_SUBMITTED)
    assert no_extension_frame(again, "prompt.html")
    assert set(bridge.logins()) == set(SEEDED_TITLES)


def test_a_changed_password_offers_update(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    submit_login(page, "dev@example.com", PASSWORD_UPDATED)
    prompt = prompt_frame(page)
    assert "Update saved password?" in prompt.inner_text("body")
    assert prompt.inner_text("#save") == "Update Local Dev"
    prompt.click("#save")
    _wait_message(prompt, "updated")
    logins = bridge.logins()
    assert logins["Local Dev"] == PASSWORD_UPDATED
    assert logins["Local Dev Alias"] != PASSWORD_UPDATED, "another site's login is untouched"
    assert len(logins) == len(SEEDED_TITLES), "an update adds no entry"


def test_the_saved_password_offers_nothing(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    submit_login(page, "dev@example.com", PASSWORD_LOCAL)
    assert no_extension_frame(page, "prompt.html")


def test_a_form_built_by_script_is_offered(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("js-form.html"))
    page.wait_for_selector("#username")
    page.fill("#username", NEW_USER)
    page.fill("#password", PASSWORD_SUBMITTED)
    page.click("#submit")
    page.wait_for_url("**/welcome.html")
    prompt = prompt_frame(page)  # on the page the login went on to
    assert NEW_USER in prompt.inner_text("body")
    prompt.click("#save")
    _wait_message(prompt, "Saved")
    assert bridge.logins()[_saved_title(bridge)] == PASSWORD_SUBMITTED


def test_a_login_without_a_form_or_reload_is_offered(
    browser: BrowserContext, bridge: Bridge
) -> None:
    page = open_login_page(browser, bridge.url("spa.html"))
    page.fill("#username", NEW_USER)
    page.fill("#password", PASSWORD_SUBMITTED)
    page.click("#submit")
    page.wait_for_selector("#done")
    prompt = prompt_frame(page)
    assert NEW_USER in prompt.inner_text("body")
    prompt.click("#save")
    _wait_message(prompt, "Saved")
    assert bridge.logins()[_saved_title(bridge)] == PASSWORD_SUBMITTED


def test_a_two_step_login_is_saved_with_its_username(
    browser: BrowserContext, bridge: Bridge
) -> None:
    page = open_login_page(browser, bridge.url("multi-step.html"))
    page.fill("#username", NEW_USER)
    page.click("#next")
    page.fill("#password", PASSWORD_SUBMITTED)
    page.click("#submit")
    page.wait_for_selector("#done")
    prompt = prompt_frame(page)
    assert NEW_USER in prompt.inner_text("body"), "the first screen's username is kept"
    prompt.click("#save")
    _wait_message(prompt, "Saved")
    assert bridge.logins()[_saved_title(bridge)] == PASSWORD_SUBMITTED


def test_a_login_inside_an_iframe_is_not_captured(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    page = open_login_page(browser, bridge.url("iframe-login.html"))
    frame = page.frame_locator("#frame")
    frame.locator("#frame-username").fill(NEW_USER)
    frame.locator("#frame-password").fill(PASSWORD_SUBMITTED)
    frame.locator("button").click()
    assert no_extension_frame(page, "prompt.html")
    assert PASSWORD_SUBMITTED not in storage_dump(control_page)


def test_plain_http_is_never_offered(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    page = open_login_page(browser, bridge.url("login.html", host="insecure.test"))
    submit_login(page, NEW_USER, PASSWORD_SUBMITTED)
    assert no_extension_frame(page, "prompt.html")
    assert PASSWORD_SUBMITTED not in storage_dump(control_page)


def test_turning_offers_off_stops_them(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    popup = open_popup(browser)
    popup.uncheck("#watch")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Will not offer')"
    )
    page = _submit_new(browser, bridge)
    assert no_extension_frame(page, "prompt.html")
    assert PASSWORD_SUBMITTED not in storage_dump(control_page)


def test_a_locked_vault_asks_for_unlock_and_saves_nothing(
    browser: BrowserContext, bridge_factory: BridgeFactory
) -> None:
    bridge = bridge_factory(locked=True)
    page = _submit_new(browser, bridge)
    prompt = prompt_frame(page)
    assert "locked" in prompt.inner_text("#message")
    prompt.click("#save")
    _wait_message(prompt, "Unlock")
    assert bridge.unlock_requests() == 1


def test_the_popup_offers_the_same_login(browser: BrowserContext, bridge: Bridge) -> None:
    page = open_login_page(browser, bridge.url("login.html"))
    submit_login(page, "dev@example.com", PASSWORD_UPDATED)
    popup = open_popup(browser, wait_for="#save-prompt")
    assert popup.inner_text("#save-question") == f"Update the saved password for {_site(bridge)}?"
    assert popup.is_hidden("#save-new"), "an update is never offered as a second login"
    popup.click("#save-update")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Updated.'", timeout=30_000
    )
    assert bridge.logins()["Local Dev"] == PASSWORD_UPDATED


def test_an_expired_candidate_is_not_offered(
    browser: BrowserContext, bridge: Bridge, control_page: Page
) -> None:
    control_page.evaluate(
        "async (port) => chrome.storage.session.set({"
        "  pending_save: {"
        "    tabId: -1, origin: `http://127.0.0.1:${port}`, url: `http://127.0.0.1:${port}/`,"
        "    username: 'dev@example.com', password: 'stale', kind: 'save', token: 'x',"
        "    at: Date.now() - 3 * 60 * 1000"
        "  }"
        "})",
        bridge.port,
    )
    open_login_page(browser, bridge.url("login.html"))
    popup = open_popup(browser)
    popup.wait_for_selector("#matches .match", timeout=30_000)
    popup.wait_for_selector("#save-prompt", state="hidden", timeout=5_000)
    assert "stale" not in storage_dump(control_page)
    assert set(bridge.logins()) == set(SEEDED_TITLES)
