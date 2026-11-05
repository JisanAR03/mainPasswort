"""Bugs found in the audit of 2026-11-05 (docs/tasks/FEAT-02-audit-fixes-and-features.md).

Each test failed on the extension as it was on main (166dd7b) and passes now:
the menu inside a native modal <dialog>, the popup acting on the wrong window,
the popup's "Add a login" storing a whole URL, and Google Drive asking the
first-link question again after a Disconnect and Connect of the same account.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from conftest import EXT_PASSWORD, Ext, SeededVault
from personal_vault.core.vault import VaultSession
from playwright.sync_api import BrowserContext, Page
from support import (
    EXTENSION_ORIGIN,
    PASSWORD_LOCAL,
    POPUP_URL,
    STATUS_READY,
    extension_frame,
    open_login_page,
    open_popup,
    titles,
    wait_for_matches,
)

pytestmark = pytest.mark.e2e


# --- 1. a login inside a native modal <dialog> ------------------------------------------


@pytest.mark.parametrize("centered", [False, True], ids=["plain-dialog", "transformed-dialog"])
def test_the_menu_works_inside_a_native_modal_dialog(
    browser: BrowserContext, vault: SeededVault, centered: bool
) -> None:
    """showModal() makes the rest of the document inert and puts the dialog in the
    top layer, so a menu outside it is covered and cannot be clicked. The menu must
    sit inside the open dialog — and still land under the field when the dialog is
    centred with a transform (which changes what position: fixed is relative to)."""
    query = "?centered=1" if centered else ""
    page = open_login_page(browser, vault.url("dialog-login.html") + query)
    page.wait_for_selector("#username")
    page.click("#username")  # a real click on the field inside the dialog
    frame = extension_frame(page, "menu.html", timeout_ms=15_000)
    assert frame is not None, "no suggestion menu appeared inside the dialog"
    frame.wait_for_selector("#menu button", timeout=30_000)

    box = frame.frame_element().bounding_box()
    assert box is not None
    field = page.locator("#username").bounding_box()
    assert field is not None
    # the menu sits right under the field it belongs to, whatever the dialog's transform
    assert abs(box["x"] - field["x"]) < 40, (box, field)
    assert 0 <= box["y"] - (field["y"] + field["height"]) < 20, (box, field)

    cx, cy = box["x"] + box["width"] / 2, box["y"] + 40
    top = page.evaluate(
        "([x, y]) => { const e = document.elementFromPoint(x, y); return e ? e.tagName : null; }",
        [cx, cy],
    )
    assert top == "PERSONAL-VAULT", f"the menu is covered by {top}"

    page.mouse.click(cx, cy)  # a real click on the first menu row
    page.wait_for_function("() => document.getElementById('password').value !== ''", timeout=15_000)
    assert page.input_value("#password") == PASSWORD_LOCAL
    assert page.evaluate("() => window.location.search") == query  # nothing was submitted


# --- 2. the popup acts on the window it was opened in ----------------------------------


def _popup_in_window(browser: BrowserContext, control: Page, window_id: int) -> Page:
    with browser.expect_page() as opened:
        control.evaluate(
            "([windowId, url]) => chrome.tabs.create({ windowId, url, active: true })",
            [window_id, POPUP_URL],
        )
    popup = opened.value
    popup.wait_for_function(STATUS_READY, timeout=30_000)
    return popup


def test_the_popup_lists_the_logins_of_the_window_it_is_in(
    browser: BrowserContext, vault: SeededVault, control_page: Page
) -> None:
    """Two windows, two different sites, the second one focused. A popup opened in
    the first window must show that window's site, not whichever tab the browser
    happens to list first."""
    windows = []
    for url in (vault.url("login.html"), vault.url("login.html", host="localhost")):
        created = control_page.evaluate(
            "(url) => chrome.windows.create({ url, focused: true })", url
        )
        windows.append(created["id"])
        control_page.wait_for_timeout(800)

    first = _popup_in_window(browser, control_page, windows[0])
    wait_for_matches(first)
    assert titles(first) == ["Local Dev"]  # 127.0.0.1, the first window's page

    second = _popup_in_window(browser, control_page, windows[1])
    wait_for_matches(second)
    assert titles(second) == ["Local Dev Alias"]  # localhost, the second window's page


# --- 3. "Add a login" in the popup stores the site, not the whole URL ----------------------


def test_the_popup_add_form_stores_the_site_and_never_the_query(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    """The address bar can hold a token or a session in its query; the entry's
    title and web address must be the site only."""
    secret = "SECRET-TOKEN-123"
    open_login_page(browser, vault.url("login.html") + f"?token={secret}&next=/account")
    popup = open_popup(browser)
    popup.fill("#add-username", "queried@example.com")
    popup.fill("#add-password", "a password typed in the popup")
    popup.click("#add-save")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Saved.'", timeout=30_000
    )
    host = f"127.0.0.1:{vault.port}"
    added = [
        e
        for e in ext.ok("ext_list", {"query": ""})["entries"]
        if e["username"] == "queried@example.com"
    ]
    assert len(added) == 1
    entry = ext.ok("ext_get", {"entryId": added[0]["id"]})["entry"]
    assert entry["title"] == host
    assert entry["urls"] == [f"http://{host}/"]
    assert secret not in ext.dump_storage()  # nothing of the query reached the vault's own data


# --- 4. Disconnect, then Connect the same Google account -----------------------------------


def _decrypts_to(data: bytes, tmp_path: Path, password: str) -> dict[str, str]:
    path = tmp_path / f"from-drive-{uuid.uuid4().hex}.kdbx"
    path.write_bytes(data)
    session = VaultSession.open(path, password, tmp_path / "backups")
    try:
        return {s.title: session.get(s.id).password.reveal() for s in session.list_logins()}
    finally:
        session.close()


def test_reconnecting_the_same_account_resumes_instead_of_asking_again(
    ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Before", password="before pw", urls=["https://before.example/"])
    ext.ok("ext_connect")
    ext.wait_status(profile, {"synced"})

    ext.ok("ext_disconnect")
    assert ext.sync_status(profile)["state"] == "off"
    ext.add_login(title="While away", password="while-away pw", urls=["https://away.example/"])

    ext.ok("ext_connect")  # the same Google account
    status = ext.wait_status(profile, {"synced", "first_link", "conflict"})
    assert status["state"] == "synced", f"reconnecting asked a question again: {status}"
    with ext.google.lock:
        remote = ext.google.vault_of(profile).content
    assert set(_decrypts_to(remote, tmp_path, EXT_PASSWORD)) == {"Before", "While away"}


def test_connecting_another_account_still_asks_before_touching_anything(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Mine", password="mine pw", urls=["https://mine.example/"])
    ext.ok("ext_connect")
    ext.wait_status(profile, {"synced"})
    ext.ok("ext_disconnect")

    ext.google.email = "someone-else@example.com"  # a different account signs in now
    try:
        ext.ok("ext_connect")
        status = ext.wait_status(profile, {"synced", "first_link", "conflict"})
    finally:
        ext.google.email = "owner@example.com"
    assert status["state"] == "first_link", status


# --- 5. the clipboard after Copy ------------------------------------------------------------

COPIED = "a password copied from the vault page"


def _clipboard(reader: Page) -> str:
    reader.bring_to_front()
    return str(reader.evaluate("() => navigator.clipboard.readText()"))


def _clipboard_reader(browser: BrowserContext, vault: SeededVault) -> Page:
    """An ordinary web page that is allowed to read the clipboard (an extension
    page cannot be granted that), to see what a user would paste."""
    browser.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin=f"http://127.0.0.1:{vault.port}"
    )
    return open_login_page(browser, vault.url("login.html"))


def _copy_from_vault_page(browser: BrowserContext, ext: Ext, password: str = COPIED) -> Page:
    ext.add_login(title="Copy me", username="copy@example.com", password=password)
    page = open_login_page(browser, f"{EXTENSION_ORIGIN}/vault.html")
    page.click("#entries li[data-id]")
    page.click("#f-copy")
    page.wait_for_function(
        "() => document.getElementById('notice').textContent.includes('taken off the clipboard')",
        timeout=15_000,
    )
    return page


def _wait_until_clipboard_no_longer_holds(reader: Page, text: str, timeout_ms: int) -> bool:
    waited = 0
    while waited <= timeout_ms:
        if text not in _clipboard(reader):
            return True
        reader.wait_for_timeout(250)
        waited += 250
    return False


def test_copy_puts_the_password_on_the_clipboard_then_takes_it_off(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    reader = _clipboard_reader(browser, vault)
    _copy_from_vault_page(browser, ext)
    assert _clipboard(reader) == COPIED
    assert _wait_until_clipboard_no_longer_holds(reader, COPIED, 15_000), (
        "the password stayed on the clipboard"
    )
    assert _clipboard(reader).strip() == ""


def test_the_clear_still_happens_when_the_vault_page_is_closed(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    reader = _clipboard_reader(browser, vault)
    page = _copy_from_vault_page(browser, ext)
    page.close()  # the old timer lived in this page and died with it
    assert _wait_until_clipboard_no_longer_holds(reader, COPIED, 15_000), (
        "the password stayed on the clipboard"
    )


def test_something_copied_afterwards_is_never_wiped(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    reader = _clipboard_reader(browser, vault)
    _copy_from_vault_page(browser, ext)
    reader.bring_to_front()
    reader.evaluate("() => navigator.clipboard.writeText('my shopping list')")
    reader.wait_for_timeout(7_000)  # well past the 4 s of the test copy of the extension
    assert _clipboard(reader) == "my shopping list"


def test_locking_takes_a_copied_password_off_the_clipboard_at_once(
    browser: BrowserContext, vault: SeededVault, ext: Ext
) -> None:
    reader = _clipboard_reader(browser, vault)
    _copy_from_vault_page(browser, ext)
    assert _clipboard(reader) == COPIED
    ext.ok("ext_lock")
    # the test copy waits 4 s; a lock must not wait for that
    assert _wait_until_clipboard_no_longer_holds(reader, COPIED, 2_000), "locking left the password"
