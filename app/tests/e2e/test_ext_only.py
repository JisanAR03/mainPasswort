"""Extension-only mode (docs/tasks/EXT-00-extension-only-mode.md): the vault
lives in the browser, the desktop app is never needed — and is unreachable
here: the extension under test connects to a native host nobody registers.

Acceptance tests A1-A8 of the card. Drive is the fake Google in fake_google.py;
vaults use weak KDF settings (test copy only, see conftest)."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import EXT_PASSWORD, Ext, _launch, _seed_extension_mode
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.matching import match_urls
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from personal_vault.sync.decide import LocalState, RemoteState, decide
from personal_vault.sync.state import SyncState
from playwright.sync_api import Page, Playwright
from support import EXTENSION_ORIGIN, frame_closed, menu_frame, no_extension_frame

pytestmark = pytest.mark.e2e

SITE_PASSWORD = "a site password kept in the browser vault"
CANARY = "CANARY-7f3a9c"


def _cli() -> str | None:
    return os.environ.get("KEEPASSXC_CLI") or shutil.which("keepassxc-cli")


def _site(page_server: str) -> str:
    return f"{page_server}/login.html"


def _items(page: Page) -> list[str]:
    return menu_frame(page).locator("#menu button").all_inner_texts()


def _open(ext: Ext, url: str) -> Page:
    page = ext.browser.new_page()
    page.goto(url)
    return page


def _connect(ext: Ext, profile_id: str) -> dict:
    ext.ok("ext_connect")
    return ext.wait_status(profile_id, {"synced"})


def _drive_bytes(ext: Ext, profile_id: str) -> bytes:
    with ext.google.lock:
        return ext.google.vault_of(profile_id).content


def _open_in_pykeepass(tmp_path: Path, data: bytes, password: str) -> dict[str, str]:
    path = tmp_path / f"from-drive-{uuid.uuid4().hex}.kdbx"
    path.write_bytes(data)
    session = VaultSession.open(path, password, tmp_path / "backups")
    try:
        return {s.title: session.get(s.id).password.reveal() for s in session.list_logins()}
    finally:
        session.close()


# --- A1: no desktop app anywhere --------------------------------------------------------


def test_a1_create_add_fill_lock_unlock_with_no_desktop_app(ext: Ext, page_server: str) -> None:
    vault = _open(ext, f"{EXTENSION_ORIGIN}/vault.html")
    vault.wait_for_selector("#view-create", state="visible")
    vault.fill("#create-name", "Personal")
    vault.fill("#create-password", EXT_PASSWORD)
    vault.fill("#create-repeat", EXT_PASSWORD)
    vault.click("#create-submit")
    vault.wait_for_selector("#view-vault", state="visible", timeout=60_000)
    assert "Personal" in vault.inner_text("#who")

    vault.click("#add")
    vault.fill("#f-title", "Local Site")
    vault.fill("#f-username", "me@example.com")
    vault.fill("#f-password", SITE_PASSWORD)
    vault.fill("#f-urls", _site(page_server))
    vault.click("#f-save")
    vault.wait_for_selector("#entries li[data-id]", timeout=60_000)

    page = _open(ext, _site(page_server))
    page.click("#username")
    assert _items(page) == ["Local Site\nme@example.com"]
    menu_frame(page).locator("#menu button").first.click()
    page.wait_for_function("() => document.getElementById('password').value !== ''")
    assert page.input_value("#password") == SITE_PASSWORD

    vault.click("#lock")
    vault.wait_for_selector("#view-unlock", state="visible")
    assert ext.state()["unlocked"] is None
    locked_page = _open(ext, _site(page_server))
    locked_page.click("#password")
    assert _items(locked_page) == ["Unlock Personal Vault\nOpens the desktop app"]

    popup = _open(ext, f"{EXTENSION_ORIGIN}/popup.html")
    popup.wait_for_selector("#ext-unlock", state="visible", timeout=30_000)
    popup.fill("#ext-password", EXT_PASSWORD)
    popup.click("#ext-unlock-button")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Unlocked')",
        timeout=60_000,
    )
    assert popup.inner_text("#status") == "Unlocked: Personal"
    again = _open(ext, _site(page_server))
    again.click("#username")
    assert _items(again) == ["Local Site\nme@example.com"]


def test_a1_a_wrong_master_password_opens_nothing(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.ok("ext_lock")
    reply = ext.call("ext_unlock", {"profileId": profile, "password": "not the master password"})
    assert reply == {"ok": False, "error": {"code": "bad_password"}}
    assert ext.state()["unlocked"] is None


# --- A2: how long an unlock lasts ----------------------------------------------------------


def _unlocked_list(ext: Ext) -> list[str]:
    return [e["title"] for e in ext.ok("ext_list")["entries"]]


def test_a2_unlock_survives_a_service_worker_stop(ext: Ext, page_server: str) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Local Site", urls=[_site(page_server)])
    session = ext.browser.new_cdp_session(ext.control)
    session.send("ServiceWorker.enable")
    session.send("ServiceWorker.stopAllWorkers")
    ext.control.wait_for_timeout(1_000)
    assert _unlocked_list(ext) == ["Local Site"]
    page = _open(ext, _site(page_server))
    page.click("#username")
    assert _items(page) == ["Local Site\nuser@example.com"]


def test_a2_unlock_survives_the_engine_document_closing(ext: Ext) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Kept")
    ext.control.evaluate("() => chrome.offscreen.closeDocument()")
    assert _unlocked_list(ext) == ["Kept"], "reopened from the session key"


def test_a2_an_expired_unlock_is_locked(ext: Ext) -> None:
    ext.create_profile("Personal")
    ext.control.evaluate(
        "async () => { const { unlocked } = await chrome.storage.session.get('unlocked');"
        "  unlocked.expiresAt = Date.now() - 1;"
        "  await chrome.storage.session.set({ unlocked }); }"
    )
    assert ext.call("ext_list") == {"ok": False, "error": {"code": "locked"}}
    assert ext.state()["unlocked"] is None
    assert "unlocked" not in ext.control.evaluate("() => chrome.storage.session.get(null)")


def test_a2_lock_ends_it_immediately_and_leaves_no_key(ext: Ext, page_server: str) -> None:
    ext.create_profile("Personal")
    ext.add_login(title="Local Site", urls=[_site(page_server)])
    page = _open(ext, _site(page_server))
    page.click("#username")
    menu_frame(page)  # a menu session (titles, usernames) now exists
    ext.ok("ext_lock")
    session = ext.control.evaluate("() => chrome.storage.session.get(null)")
    assert [k for k in session if k == "unlocked" or k.startswith(("menu_", "drive_token:"))] == []
    assert ext.call("ext_list") == {"ok": False, "error": {"code": "locked"}}
    assert ext.call("ext_get", {"entryId": "x"}) == {"ok": False, "error": {"code": "locked"}}


def test_a2_the_shipped_unlock_lasts_six_hours(ext: Ext) -> None:
    ext.create_profile("Personal")
    record = ext.control.evaluate(
        "async () => (await chrome.storage.session.get('unlocked')).unlocked"
    )
    assert record["expiresAt"] - record["unlockedAt"] == 6 * 60 * 60 * 1000
    assert set(record) == {"profileId", "passwordHash", "unlockedAt", "expiresAt"}
    alarm = ext.control.evaluate("() => chrome.alarms.get('unlock-expiry')")
    assert alarm and abs(alarm["scheduledTime"] - record["expiresAt"]) < 1_000


def test_a2_closing_the_browser_ends_the_unlock(
    playwright_instance: Playwright, ext_extension: Path, tmp_path: Path
) -> None:
    profile_dir = tmp_path / "browser-profile"
    first = _launch(playwright_instance, profile_dir, ext_extension)
    _seed_extension_mode(first)
    control = first.new_page()
    control.goto(f"{EXTENSION_ORIGIN}/popup.html")
    ext = Ext(first, control, None)  # type: ignore[arg-type]
    profile = ext.create_profile("Personal")
    ext.add_login(title="Survives Restart")
    assert ext.state()["unlocked"]["profileId"] == profile
    first.close()

    second = _launch(playwright_instance, profile_dir, ext_extension)
    try:
        control = second.new_page()
        control.goto(f"{EXTENSION_ORIGIN}/popup.html")
        ext = Ext(second, control, None)  # type: ignore[arg-type]
        state = ext.state()
        assert state["unlocked"] is None, "a browser restart must lock"
        assert [p["id"] for p in state["profiles"]] == [profile], "the vault is still there"
        ext.ok("ext_unlock", {"profileId": profile, "password": EXT_PASSWORD})
        assert _unlocked_list(ext) == ["Survives Restart"]
    finally:
        second.close()


# --- A3: one profile's data never reaches another --------------------------------------------


def test_a3_a_locked_profile_is_unreachable_everywhere(ext: Ext, page_server: str) -> None:
    other = f"http://localhost:{page_server.rsplit(':', 1)[1]}/login.html"
    profile_b = ext.create_profile("Profile B")
    b_entry = ext.add_login(
        title=f"{CANARY}-title",
        username=f"{CANARY}-user",
        password=f"{CANARY}-password",
        notes=f"{CANARY}-notes",
        urls=[other],
    )
    profile_a = ext.create_profile("Profile A")  # creating A locks B
    ext.add_login(title="A Only", urls=[_site(page_server)])
    state = ext.state()
    assert state["unlocked"]["profileId"] == profile_a

    # the popup and the in-page menu on B's site
    page = _open(ext, other)
    page.click("#username")
    page.click("#password")
    assert no_extension_frame(page, "menu.html"), "A has nothing for B's site"
    popup = _open(ext, f"{EXTENSION_ORIGIN}/popup.html")
    popup.wait_for_function(
        "() => !document.getElementById('status').textContent.startsWith('Checking')",
        timeout=30_000,
    )
    # messaging the extension directly
    assert [e["title"] for e in ext.ok("ext_list")["entries"]] == ["A Only"]
    assert ext.call("ext_get", {"entryId": b_entry}) == {
        "ok": False,
        "error": {"code": "not_found"},
    }
    everything = json.dumps(
        [
            ext.call("ext_state"),
            ext.call("ext_list", {"query": CANARY}),
            ext.control.evaluate(
                "(url) => chrome.runtime.sendMessage({ type: 'get_logins', url })", other
            ),
            popup.inner_text("body"),
            page.content(),
        ]
    )
    assert CANARY not in everything
    # and nothing in storage or IndexedDB holds it in plaintext (I12)
    assert CANARY not in ext.dump_storage()
    assert profile_b in json.dumps(state["profiles"])  # B exists: only its name shows


def test_a3_unlocking_another_profile_locks_the_first(ext: Ext) -> None:
    profile_a = ext.create_profile("Profile A")
    ext.add_login(title=f"{CANARY}-a")
    profile_b = ext.create_profile("Profile B")
    assert ext.state()["unlocked"]["profileId"] == profile_b
    assert CANARY not in json.dumps(ext.ok("ext_list"))
    ext.ok("ext_unlock", {"profileId": profile_a, "password": EXT_PASSWORD})
    assert [e["title"] for e in ext.ok("ext_list")["entries"]] == [f"{CANARY}-a"]


# --- A4: Google Drive ----------------------------------------------------------------------


def test_a4_an_edit_reaches_drive_and_the_desktop_app_opens_it(ext: Ext, tmp_path: Path) -> None:
    profile = ext.create_profile("Personal")
    entry = ext.add_login(title="Synced Site", password="first password")
    status = _connect(ext, profile)
    assert status["localOnly"] is False
    file = ext.google.vault_of(profile)
    assert file.name == "vault.kdbx"
    assert file.app_properties == {"pm_profile_id": profile, "pm_schema": "1"}
    revisions = len(file.revisions)

    edited = ext.ok("ext_get", {"entryId": entry})["entry"]
    ext.ok("ext_save_entry", {"entry": {**edited, "password": "second password"}})
    waited = 0
    while len(ext.google.vault_of(profile).revisions) == revisions and waited < 60_000:
        ext.control.wait_for_timeout(250)
        waited += 250
    assert len(ext.google.vault_of(profile).revisions) == revisions + 1, (
        "a new revision within a minute"
    )
    assert ext.wait_status(profile, {"synced"})["localOnly"] is False

    # the desktop app's library opens what the extension uploaded
    logins = _open_in_pykeepass(tmp_path, _drive_bytes(ext, profile), EXT_PASSWORD)
    assert logins == {"Synced Site": "second password"}


@pytest.mark.skipif(not _cli(), reason="keepassxc-cli not installed")
def test_a4_keepassxc_opens_what_the_extension_uploaded(ext: Ext, tmp_path: Path) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="For KeePassXC")
    _connect(ext, profile)
    path = tmp_path / "uploaded.kdbx"
    path.write_bytes(_drive_bytes(ext, profile))
    shown = subprocess.run(
        [str(_cli()), "ls", "-R", str(path)],
        input=EXT_PASSWORD + "\n",
        capture_output=True,
        text=True,
    )
    assert shown.returncode == 0, shown.stderr
    assert "For KeePassXC" in shown.stdout
    assert "Logins/" in shown.stdout


def test_a4_a_desktop_vault_on_drive_opens_here_and_stays_shared(ext: Ext, tmp_path: Path) -> None:
    # the desktop app's vault, with its hidden .app entries, already on Drive
    desktop = build_weak_vault(tmp_path / "desktop.kdbx")
    session = VaultSession.open(desktop, WEAK_PASSWORD, tmp_path / "backups")
    session.add(make_login(title="From Desktop", password=SecretStr("desktop password")))
    session.set_app_value("browser-pairing", "pairing-key-from-desktop")
    session.set_app_value("drive-sync", "desktop-refresh-token", username="owner@example.com")
    session.save()
    session.close()
    ext.google.put_vault("p_desktop1", desktop.read_bytes())

    listed = ext.ok("ext_drive_list")
    assert [v["profileId"] for v in listed["vaults"]] == ["p_desktop1"]
    ext.ok(
        "ext_drive_open",
        {"fileId": listed["vaults"][0]["fileId"], "name": "Desktop", "password": WEAK_PASSWORD},
    )
    state = ext.state()
    assert state["unlocked"]["profileId"] == "p_desktop1", "it keeps the desktop's profile id"
    assert [e["title"] for e in ext.ok("ext_list")["entries"]] == ["From Desktop"]

    ext.add_login(title="From Browser", password="browser password")
    waited = 0
    while len(ext.google.vault_of("p_desktop1").revisions) < 2 and waited < 60_000:
        ext.control.wait_for_timeout(250)
        waited += 250
    path = tmp_path / "shared.kdbx"
    path.write_bytes(_drive_bytes(ext, "p_desktop1"))
    reopened = VaultSession.open(path, WEAK_PASSWORD, tmp_path / "backups2")
    try:
        titles = {s.title: reopened.get(s.id).password.reveal() for s in reopened.list_logins()}
        assert titles == {"From Desktop": "desktop password", "From Browser": "browser password"}
        # the desktop's own entries came through untouched
        assert reopened.get_app_value("browser-pairing") == "pairing-key-from-desktop"
        assert reopened.get_app_value("drive-sync") == "desktop-refresh-token"
    finally:
        reopened.close()
    cli = _cli()
    if cli:
        shown = subprocess.run(
            [cli, "ls", "-R", str(path)], input=WEAK_PASSWORD + "\n", capture_output=True, text=True
        )
        assert shown.returncode == 0, shown.stderr


# --- A5 / A6: offline and a revoked sign-in -------------------------------------------------------


def test_a5_offline_saves_locally_with_a_reason_and_uploads_when_back(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Before")
    _connect(ext, profile)
    revisions = len(ext.google.vault_of(profile).revisions)

    ext.google.offline = True
    ext.add_login(title="Made Offline")
    status = ext.wait_status(profile, {"offline"})
    assert status["localOnly"] is True
    assert "saved on this computer" in status["message"]
    assert status["nextRetryAt"]
    assert "Made Offline" in [e["title"] for e in ext.ok("ext_list")["entries"]]
    assert len(ext.google.vault_of(profile).revisions) == revisions

    ext.google.offline = False  # no click: the retry finds the network back
    status = ext.wait_status(profile, {"synced"})
    assert status["localOnly"] is False
    assert len(ext.google.vault_of(profile).revisions) == revisions + 1


def test_a6_a_revoked_sign_in_says_so_and_never_claims_synced(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Before")
    first = _connect(ext, profile)
    ext.google.revoked = True
    ext.add_login(title="After Revoke")
    status = ext.wait_status(profile, {"reconnect"})
    assert "sign-in needs renewing" in status["message"]
    assert status["lastSuccessAt"] == first["lastSuccessAt"]
    assert status["localOnly"] is True
    for _ in range(8):  # nothing later turns it into a success
        ext.control.wait_for_timeout(500)
        assert ext.sync_status(profile)["state"] != "synced"


# --- A7: the desktop's sync rules ---------------------------------------------------------------


def test_a7_a_full_drive_is_explained_and_the_change_kept(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    _connect(ext, profile)
    ext.google.quota_full = True
    ext.add_login(title="No Room")
    status = ext.wait_status(profile, {"quota"})
    assert "Google Drive is full" in status["message"]
    assert status["localOnly"] is True
    assert "No Room" in [e["title"] for e in ext.ok("ext_list")["entries"]]


def test_a7_a_write_from_another_device_is_a_conflict_never_an_overwrite(
    ext: Ext, tmp_path: Path
) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Shared")
    _connect(ext, profile)
    # "another device": a different version of the same vault (one more login),
    # written to Drive after this browser last synced
    extra = ext.add_login(title="Their Login")
    ext.wait_status(profile, {"synced"})
    theirs = _drive_bytes(ext, profile)
    ext.ok("ext_delete_entry", {"entryId": extra})
    ext.wait_status(profile, {"synced"})
    ext.google.write_from_other_device(profile, theirs)
    head_before = ext.google.vault_of(profile).revisions[-1].id

    ext.add_login(title="Mine")
    status = ext.wait_status(profile, {"conflict"})
    assert "Both copies changed" in status["message"]
    assert ext.google.vault_of(profile).revisions[-1].id == head_before, "never overwritten (I6)"
    assert ext.state()["statuses"][profile]["localOnly"] is True

    ext.ok("ext_choose", {"choice": "keep_mine"})
    status = ext.wait_status(profile, {"synced"})
    logins = _open_in_pykeepass(tmp_path, _drive_bytes(ext, profile), EXT_PASSWORD)
    assert set(logins) == {"Shared", "Mine"}


def test_a7_take_theirs_adopts_their_copy(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    ext.add_login(title="Original")
    _connect(ext, profile)
    # their copy: the same vault with one more login, made by "another device"
    ext.add_login(title="Theirs")
    ext.wait_status(profile, {"synced"})
    theirs = _drive_bytes(ext, profile)
    entry = next(e for e in ext.ok("ext_list")["entries"] if e["title"] == "Theirs")
    ext.ok("ext_delete_entry", {"entryId": entry["id"]})
    ext.wait_status(profile, {"synced"})
    ext.google.write_from_other_device(profile, theirs)
    ext.add_login(title="Mine Only")
    ext.wait_status(profile, {"conflict"})

    ext.ok("ext_choose", {"choice": "take_theirs"})
    ext.wait_status(profile, {"synced"})
    assert sorted(e["title"] for e in ext.ok("ext_list")["entries"]) == ["Original", "Theirs"]


def test_a7_a_trashed_file_asks_instead_of_recreating(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    _connect(ext, profile)
    with ext.google.lock:
        ext.google.vault_of(profile).trashed = True
    ext.add_login(title="After Trash")
    status = ext.wait_status(profile, {"missing"})
    assert "missing or in the bin" in status["message"]
    files = [f for f in ext.google.files.values() if f.name == "vault.kdbx"]
    assert len(files) == 1, "never recreated silently"


_STATES: list[SyncState | None] = [None] + [
    SyncState(last_synced_remote_md5=remote, last_synced_local_sha256=local)
    for remote, local in itertools.product([None, "m1", "m2"], [None, "s1", "s2"])
]


def _decide_table() -> list[dict]:
    table = []
    for exists, sha, md5, dirty in itertools.product(
        [True, False], [None, "s1", "s2"], [None, "m1", "m2"], [True, False]
    ):
        local = LocalState(exists=exists, sha256=sha, md5=md5, dirty=dirty)
        for r_exists, trashed, r_md5, version in itertools.product(
            [True, False], [True, False], [None, "m1", "m2", "m3"], [None, 1]
        ):
            remote = RemoteState(exists=r_exists, trashed=trashed, md5=r_md5, version=version)
            for state in _STATES:
                table.append(
                    {
                        "local": {"exists": exists, "sha256": sha, "md5": md5, "dirty": dirty},
                        "remote": {
                            "exists": r_exists,
                            "trashed": trashed,
                            "md5": r_md5,
                            "version": version,
                        },
                        "state": None
                        if state is None
                        else {
                            "last_synced_remote_md5": state.last_synced_remote_md5,
                            "last_synced_local_sha256": state.last_synced_local_sha256,
                        },
                        "expected": decide(local, remote, state).value,
                    }
                )
    return table


def test_a7_decide_js_agrees_with_python_on_every_input(ext: Ext) -> None:
    table = _decide_table()
    assert len(table) == 36 * 32 * 10
    differences = ext.control.evaluate(
        """async (table) => {
          const { decide } = await import(chrome.runtime.getURL('decide.js'));
          const differs = (row) => decide(row.local, row.remote, row.state) !== row.expected;
          return table.filter(differs).length;
        }""",
        table,
    )
    assert differences == 0  # I13: one rulebook in two languages


_URLS = [
    "https://example.com",
    "https://example.com/login?next=1",
    "https://example.com:8443/x",
    "https://example.com:443",
    "http://example.com",
    "https://login.example.com",
    "https://evil-example.com",
    "https://example.com.evil.net",
    "https://EXAMPLE.com.",
    "https://münchen.de",
    "https://xn--mnchen-3ya.de",
    "https://127.0.0.1:5000",
    "http://localhost",
    "https://user:pw@example.com",
    "https://example.com:99999",
    "ftp://example.com",
    "not a url",
    "",
]


def test_a7_matching_js_agrees_with_python(ext: Ext) -> None:
    table = [
        {
            "entry": entry,
            "page": page,
            "subdomains": subdomains,
            "expected": match_urls([entry], page, match_subdomains=subdomains),
        }
        for entry, page, subdomains in itertools.product(_URLS, _URLS, [False, True])
    ]
    differences = ext.control.evaluate(
        """async (table) => {
          const { matchUrls } = await import(chrome.runtime.getURL('matching.js'));
          return table
            .filter((r) => matchUrls([r.entry], r.page, r.subdomains) !== r.expected)
            .map((r) => [r.entry, r.page, r.subdomains, r.expected]);
        }""",
        table,
    )
    assert differences == []


# --- A8: security ------------------------------------------------------------------------------


def test_a8_no_plaintext_secret_in_any_storage(ext: Ext) -> None:
    profile = ext.create_profile("Personal")
    entry = ext.add_login(title=f"{CANARY}-t", username=f"{CANARY}-u", password=f"{CANARY}-p")
    edited = ext.ok("ext_get", {"entryId": entry})["entry"]
    ext.ok("ext_save_entry", {"entry": {**edited, "notes": f"{CANARY}-n"}})
    _connect(ext, profile)
    dump = ext.dump_storage()
    assert CANARY not in dump, "IndexedDB, storage.local and storage.session hold no plaintext (I1)"
    assert CANARY.encode() not in _drive_bytes(ext, profile), "Drive gets ciphertext only"
    session = ext.control.evaluate("() => chrome.storage.session.get('unlocked')")
    assert EXT_PASSWORD not in json.dumps(session), "the master password itself is never kept"


def test_a8_the_engine_answers_only_the_service_worker(ext: Ext) -> None:
    ext.create_profile("Personal")
    ext.add_login(title=f"{CANARY}-only")
    # an extension page (not the service worker) asking the engine directly
    reply = ext.control.evaluate(
        "() => chrome.runtime.sendMessage({ target: 'engine', op: 'list', args: {} })"
    )
    assert CANARY not in json.dumps(reply)


def test_a8_the_page_never_sees_the_vault(ext: Ext, page_server: str) -> None:
    ext.create_profile("Personal")
    ext.add_login(title=f"{CANARY}-title", username=f"{CANARY}-user", urls=[_site(page_server)])
    page = _open(ext, _site(page_server))
    page.click("#username")
    menu_frame(page)
    assert CANARY not in page.content()
    assert page.evaluate("() => document.querySelector('personal-vault').shadowRoot") is None
    page.keyboard.press("Escape")
    assert frame_closed(page, "menu.html")
