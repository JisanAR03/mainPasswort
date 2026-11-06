"""The vault page screens for the new features, driven the way a person drives
them: clicking the tabs and buttons, typing in the forms, choosing a file. The
engine behind each is tested in test_vault_features.py."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import EXT_PASSWORD, Ext
from playwright.sync_api import BrowserContext, Page
from pykeepass import PyKeePass
from support import EXTENSION_ORIGIN

pytestmark = pytest.mark.e2e

NEW_PASSWORD = "a brand new master passphrase"


def _vault_page(browser: BrowserContext) -> Page:
    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())  # confirm("…") means yes
    page.goto(f"{EXTENSION_ORIGIN}/vault.html")
    page.wait_for_selector("#view-vault", state="visible", timeout=30_000)
    return page


def _notice(page: Page, text: str) -> None:
    page.wait_for_function(
        "(text) => document.getElementById('notice').textContent.includes(text)",
        arg=text,
        timeout=30_000,
    )


def _open_entry(page: Page, title: str) -> None:
    page.locator("#entries li[data-id]", has_text=title).first.click()
    page.wait_for_selector("#entry-form", state="visible")


def test_the_recycle_bin_tab_restores_and_deletes_for_good(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Alpha")
    ext.add_login(title="Bravo")
    page = _vault_page(browser)

    _open_entry(page, "Alpha")
    page.click("#f-delete")
    _notice(page, "Moved to the Recycle Bin")
    page.click('.tab[data-tab="bin"]')
    page.wait_for_selector("#bin-list li .title", timeout=15_000)
    assert page.locator("#bin-list li .title").all_inner_texts() == ["Alpha"]
    assert page.locator("#entries li[data-id]").count() == 1, "the login list no longer shows it"

    page.locator("#bin-list button", has_text="Restore").click()
    _notice(page, "Restored")
    page.click('.tab[data-tab="logins"]')
    assert sorted(page.locator("#entries li .title").all_inner_texts()) == ["Alpha", "Bravo"]

    _open_entry(page, "Bravo")
    page.click("#f-delete")
    page.click('.tab[data-tab="bin"]')
    page.locator("#bin-list button", has_text="Delete for good").click()
    _notice(page, "Deleted for good")
    assert page.locator("#bin-list li", has_text="empty").count() == 1


def test_emptying_the_bin_asks_first_and_removes_everything(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    for title in ("One", "Two"):
        ext.ok("ext_delete_entry", {"entryId": ext.add_login(title=title)})
    page = _vault_page(browser)
    seen: list[str] = []
    page.on("dialog", lambda dialog: seen.append(dialog.message))
    page.click('.tab[data-tab="bin"]')
    page.wait_for_selector("#bin-list li .title")
    page.click("#bin-empty")
    _notice(page, "Removed 2 logins for good")
    assert any("for good" in message for message in seen), "the page asked before deleting"
    assert ext.ok("ext_bin_list")["entries"] == []


def test_the_master_password_form_changes_it(browser: BrowserContext, ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Keep me")
    page = _vault_page(browser)
    page.locator("summary", has_text="Change the master password").click()

    page.fill("#pw-current", EXT_PASSWORD)
    page.fill("#pw-new", NEW_PASSWORD)
    page.fill("#pw-repeat", NEW_PASSWORD + " typo")
    page.click("#pw-form button[type=submit]")
    _notice(page, "differ")

    page.fill("#pw-current", "not the current one")
    page.fill("#pw-new", NEW_PASSWORD)
    page.fill("#pw-repeat", NEW_PASSWORD)
    page.click("#pw-form button[type=submit]")
    _notice(page, "does not open this vault")

    page.fill("#pw-current", EXT_PASSWORD)
    page.fill("#pw-new", NEW_PASSWORD)
    page.fill("#pw-repeat", NEW_PASSWORD)
    page.click("#pw-form button[type=submit]")
    _notice(page, "master password was changed")
    for field in ("#pw-current", "#pw-new", "#pw-repeat"):
        assert page.input_value(field) == "", "the typed passwords are cleared"

    ext.ok("ext_lock")
    assert ext.call("ext_unlock", {"profileId": profile, "password": EXT_PASSWORD})["ok"] is False
    ext.ok("ext_unlock", {"profileId": profile, "password": NEW_PASSWORD})


def test_choosing_a_csv_file_imports_it(browser: BrowserContext, ext: Ext) -> None:
    ext.create_profile("Personal")
    page = _vault_page(browser)
    page.locator("summary", has_text="Import logins from another password manager").click()
    page.set_input_files(
        "#import-csv-file",
        {
            "name": "passwords.csv",
            "mimeType": "text/csv",
            "buffer": b"name,url,username,password\nShop,https://shop.example,me,pw-1\nBank,https://bank.example,me,pw-2\n",
        },
    )
    page.click("#import-csv")
    _notice(page, "Imported 2 logins")
    assert sorted(page.locator("#entries li .title").all_inner_texts()) == ["Bank", "Shop"]
    assert page.input_value("#import-csv-file") == "", "the chosen file is let go"

    page.set_input_files(
        "#import-csv-file", {"name": "bad.csv", "mimeType": "text/csv", "buffer": b"a,b\n1,2\n"}
    )
    page.click("#import-csv")
    _notice(page, "not a CSV this page can read")


def test_the_password_health_tab_lists_what_to_fix_and_opens_it(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Common", password="password")
    ext.add_login(title="Twin A", password="a long shared passphrase 7!")
    ext.add_login(title="Twin B", password="a long shared passphrase 7!")
    ext.add_login(title="Fine", password="Xk9#mQ2$vL7@pR4!zT6&")
    page = _vault_page(browser)
    page.click('.tab[data-tab="health"]')
    page.click("#health-run")
    page.wait_for_selector("#health-out h2")
    headings = page.locator("#health-out h2").all_inner_texts()
    assert headings == [
        "Weak passwords (1)",
        "Reused passwords (2)",
        "Not changed in over a year (0)",
    ]
    page.locator("#health-out li", has_text="Common").locator("button").click()
    page.wait_for_selector("#entry-form", state="visible")
    assert page.input_value("#f-title") == "Common"


def test_a_login_with_a_secret_shows_a_live_code_that_matches_the_engine(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    entry = ext.add_login(title="Two factor", otp="JBSWY3DPEHPK3PXP")
    page = _vault_page(browser)
    _open_entry(page, "Two factor")
    page.wait_for_selector("#f-totp", state="visible", timeout=15_000)
    assert re.fullmatch(r"\d{6}", page.inner_text("#f-totp-code").replace(" ", ""))
    assert re.fullmatch(r"\d+ s", page.inner_text("#f-totp-left"))
    # the page shows the very code the engine computes (a 30-second window can roll over
    # between the two reads, so a mismatch is retried once the page has refreshed)
    for _ in range(4):
        shown = page.inner_text("#f-totp-code").replace(" ", "")
        if shown == ext.ok("ext_totp", {"entryId": entry})["code"]:
            break
        page.wait_for_timeout(1_500)
    else:
        raise AssertionError("the page and the engine never agreed on the code")


def test_a_new_login_can_get_its_secret_and_a_bad_one_is_explained(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    page = _vault_page(browser)
    page.click("#add")
    page.fill("#f-title", "With secret")
    page.fill("#f-password", "a password")
    page.fill("#f-otp", "definitely not base32 !")
    page.click("#f-save")
    _notice(page, "Base32")
    page.fill("#f-otp", "JBSWY3DPEHPK3PXP")
    page.click("#f-save")
    _notice(page, "Saved")
    _open_entry(page, "With secret")
    page.wait_for_selector("#f-totp", state="visible", timeout=15_000)


def test_an_earlier_version_can_be_viewed_and_restored_from_the_form(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    entry = ext.add_login(title="Versioned", password="first-password")
    saved = ext.ok("ext_get", {"entryId": entry})["entry"]
    ext.ok("ext_save_entry", {"entry": {**saved, "password": "second-password"}})
    page = _vault_page(browser)
    _open_entry(page, "Versioned")
    assert page.input_value("#f-password") == "second-password"

    page.locator("summary", has_text="Earlier versions").click()
    page.locator("#f-history-list button", has_text="View").click()
    page.wait_for_selector("#f-history-view", state="visible")
    assert "first-password" not in page.inner_text("#f-history-view"), "hidden until asked"
    page.click("#hv-show")
    assert page.inner_text("#hv-password") == "first-password"

    page.locator("#f-history-list button", has_text="Restore this version").click()
    _notice(page, "Earlier version restored")
    _open_entry(page, "Versioned")
    assert page.input_value("#f-password") == "first-password"


def test_the_backups_panel_lists_and_restores(browser: BrowserContext, ext: Ext) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="One")
    ext.add_login(title="Two")
    page = _vault_page(browser)
    page.locator("summary", has_text="Show backups").click()
    page.wait_for_selector("#backup-list li .title")
    assert page.locator("#backup-list li").count() == 2
    # newest first: [One], then the empty vault: restore the empty one
    page.locator("#backup-list li").nth(1).locator("button", has_text="Restore").click()
    _notice(page, "Backup restored")
    assert page.locator("#entries li[data-id]").count() == 0


def test_the_settings_form_saves_the_unlock_time_and_the_offer_switch(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    page = _vault_page(browser)
    page.select_option("#s-unlock-hours", "2")
    page.uncheck("#s-offer")
    page.click("#settings-form button[type=submit]")
    _notice(page, "Settings saved")
    assert ext.state()["settings"]["unlockHours"] == 2
    assert ext.state()["offerToSave"] is False
    page.reload()
    page.wait_for_selector("#view-vault", state="visible")
    assert page.input_value("#s-unlock-hours") == "2"
    assert page.is_checked("#s-offer") is False


def test_the_never_list_is_shown_and_a_site_can_be_allowed_again(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    ext.control.evaluate(
        "() => chrome.storage.local.set({ never_save: ['https://a.example', 'https://b.example'] })"
    )
    page = _vault_page(browser)
    page.locator("summary", has_text="Sites I chose").click()
    assert page.locator("#never-list li .title").all_inner_texts() == [
        "https://a.example",
        "https://b.example",
    ]
    page.locator("#never-list li", has_text="a.example").locator("button").click()
    page.wait_for_function("() => document.querySelectorAll('#never-list li').length === 1")
    assert ext.state()["neverSave"] == ["https://b.example"]
    page.click("#never-clear")
    page.wait_for_function("() => document.getElementById('never-clear').hidden")
    assert ext.state()["neverSave"] == []


def test_the_generator_options_change_what_generate_makes_and_can_be_kept(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    page = _vault_page(browser)
    page.click("#add")
    page.locator("summary", has_text="Password generator options").click()
    page.fill("#g-length", "40")
    page.uncheck("#g-symbols")
    page.uncheck("#g-digits")
    page.click("#f-generate")
    page.wait_for_function("() => document.getElementById('f-password').value.length === 40")
    assert re.fullmatch(r"[A-Za-z]{40}", page.input_value("#f-password"))
    page.click("#g-save")
    _notice(page, "from now on")
    assert ext.state()["settings"]["generator"]["length"] == 40


def test_a_conflict_offers_merge_and_a_password_changed_elsewhere_offers_the_new_password(
    browser: BrowserContext, ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Shared")
    ext.ok("ext_connect")
    ext.wait_status(profile, {"synced"})
    with ext.google.lock:
        remote = ext.google.vault_of(profile).content

    # another device edits (and keeps the password)
    path = tmp_path / "theirs.kdbx"
    path.write_bytes(remote)
    theirs = PyKeePass(str(path), password=EXT_PASSWORD)
    theirs.add_entry(theirs.find_groups(name="Logins", first=True), "Their Login", "them", "pw")
    theirs.save()
    ext.google.write_from_other_device(profile, path.read_bytes())
    ext.add_login(title="Mine")
    ext.wait_status(profile, {"conflict"})

    page = _vault_page(browser)
    page.wait_for_selector("#choice-merge", state="visible", timeout=15_000)
    assert page.is_visible("#choice-mine") and page.is_visible("#choice-theirs")
    assert not page.is_visible("#sync-rekey")
    page.click("#choice-merge")
    ext.wait_status(profile, {"synced"})
    page.wait_for_function(
        "() => [...document.querySelectorAll('#entries li .title')].length === 3", timeout=30_000
    )
    assert sorted(page.locator("#entries li .title").all_inner_texts()) == [
        "Mine",
        "Shared",
        "Their Login",
    ]

    # another device changes the master password
    other = PyKeePass(str(path), password=EXT_PASSWORD)
    other.password = NEW_PASSWORD
    other.save()
    ext.google.write_from_other_device(profile, path.read_bytes())
    ext.ok("ext_sync_now")
    ext.wait_status(profile, {"unreadable"})
    page.wait_for_selector("#sync-rekey", state="visible", timeout=15_000)
    page.fill("#rekey-password", "not the new password")
    page.click("#sync-rekey button[type=submit]")
    _notice(page, "does not open the copy")
    page.wait_for_selector("#sync-rekey", state="visible")
    page.fill("#rekey-password", NEW_PASSWORD)
    page.click("#sync-rekey button[type=submit]")
    page.wait_for_selector("#sync-rekey", state="hidden", timeout=30_000)
    # the form hides as soon as the copy is no longer "unreadable"; the sync that follows ends in
    # "synced", and only that end state is asserted (a moment earlier it still says "syncing")
    assert ext.wait_status(profile, {"synced"})["state"] == "synced"


def test_the_health_report_stays_while_the_page_refreshes_itself(
    browser: BrowserContext, ext: Ext
) -> None:
    """The page redraws on every sync status change; an open report must not vanish."""
    ext.create_profile("Personal")
    ext.add_login(title="Common", password="password")
    page = _vault_page(browser)
    page.click('.tab[data-tab="health"]')
    page.click("#health-run")
    page.wait_for_selector("#health-out h2")
    ext.control.evaluate(
        "() => chrome.storage.local.set({ 'sync_status:p_other': { state: 'off', message: 'x' } })"
    )
    ext.control.wait_for_timeout(1_500)  # long enough for the page's own refresh
    assert page.locator("#health-out h2").count() == 3, "the report was wiped by a refresh"
    page.click('.tab[data-tab="logins"]')
    page.click('.tab[data-tab="health"]')
    assert page.locator("#health-out h2").count() == 0, "an old report is not shown again"


def test_parts_of_the_page_that_should_be_hidden_are_hidden(
    browser: BrowserContext, ext: Ext
) -> None:
    """A rule that sets display (a row of buttons) must not defeat the hidden attribute:
    with nothing to decide, no choice buttons, no one-time-code row, no history."""
    ext.create_profile("Personal")
    ext.add_login(title="Plain login")
    page = _vault_page(browser)
    for selector in ("#sync-choice", "#sync-missing", "#choice-merge", "#sync-rekey"):
        assert not page.is_visible(selector), f"{selector} shows with nothing to decide"
    for button in (
        "Keep this computer's copy",
        "Take the Google Drive copy",
        "Upload this vault again",
    ):
        assert not page.get_by_role("button", name=button).is_visible(), button
    _open_entry(page, "Plain login")
    assert not page.is_visible("#f-totp"), "an empty one-time-code row is shown"
    assert not page.is_visible("#f-history")


def test_closing_a_login_form_leaves_the_settings_and_generator_options_alone(
    browser: BrowserContext, ext: Ext
) -> None:
    """Closing the entry form used to reset every form on the page, so the settings
    showed blank defaults and the next "Save settings" would have saved them."""
    ext.create_profile("Personal")
    ext.add_login(title="Some login")
    ext.ok(
        "ext_settings",
        {
            "unlockHours": 2,
            "generator": {
                "length": 31,
                "upper": True,
                "lower": True,
                "digits": False,
                "symbols": False,
                "excludeLookalikes": True,
            },
        },
    )
    ext.ok("ext_set_offer", {"value": False})
    page = _vault_page(browser)
    assert page.input_value("#s-client") == "fake-client-id"

    _open_entry(page, "Some login")
    page.click("#f-cancel")
    assert page.input_value("#s-client") == "fake-client-id"
    assert page.input_value("#s-unlock-hours") == "2"
    assert page.is_checked("#s-offer") is False
    assert page.input_value("#rename-name") == "Personal"

    page.click("#add")  # a new login: the generator options are the saved ones, not blank
    assert page.input_value("#g-length") == "31"
    assert page.is_checked("#g-upper") and page.is_checked("#g-lower")
    assert not page.is_checked("#g-digits") and not page.is_checked("#g-symbols")
    page.click("#f-cancel")
    page.click("#settings-form button[type=submit]")  # saving now keeps what was saved
    _notice(page, "Settings saved")
    assert ext.state()["settings"]["googleClientId"] == "fake-client-id"
    assert ext.state()["settings"]["unlockHours"] == 2
    assert ext.state()["offerToSave"] is False


# An update can leave the browser running the PREVIOUS release's background script for a
# while (observed in Brave after a restart). That script answers the page without the
# fields added since; the page used to throw before drawing anything and stayed blank.
_OLDER_BACKGROUND = """
(() => {
  const send = chrome.runtime.sendMessage.bind(chrome.runtime);
  chrome.runtime.sendMessage = async (...args) => {
    const reply = await send(...args);
    if (args[0] && args[0].type === 'ext_state' && reply && reply.result && reply.result.settings) {
      const { neverSave, offerToSave, ...rest } = reply.result;
      const { generator, lockAfterIdleMinutes, unlockHours, ...settings } = rest.settings;
      return { ...reply, result: { ...rest, settings } };
    }
    return reply;
  };
})();
"""


def test_the_vault_page_loads_without_errors(browser: BrowserContext, ext: Ext) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Bank")
    errors: list[str] = []
    page = browser.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{EXTENSION_ORIGIN}/vault.html")
    page.wait_for_selector("#view-vault", state="visible", timeout=30_000)
    page.wait_for_selector("#entries li[data-id]")
    assert errors == []


def test_the_vault_page_still_shows_when_the_background_script_is_older(
    browser: BrowserContext, ext: Ext
) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Bank", username="me@bank.example")
    errors: list[str] = []
    page = browser.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(_OLDER_BACKGROUND)
    page.goto(f"{EXTENSION_ORIGIN}/vault.html")

    page.wait_for_selector("#view-vault", state="visible", timeout=30_000)  # not a blank page
    assert page.locator("#entries li[data-id] .title").all_inner_texts() == ["Bank"]
    assert page.is_visible("#sync-panel") and page.is_visible("#settings-form")
    _notice(page, "older version")  # and it says what to do about it
    assert "reload" in page.inner_text("#notice").lower()
    assert errors == []
