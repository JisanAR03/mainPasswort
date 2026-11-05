"""Data written by an earlier version of the extension must keep working.

The browser holding a real vault runs the extension from a folder that is
updated in place, so every release is also an upgrade of someone's data. This
test seeds the storage in exactly the shape version 0.1.0 wrote (see idb.js and
local.js at 254a275: IndexedDB ``personal-vault`` v1 with its four stores,
``storage.local`` keys ``profiles``, ``settings``, ``last_profile_id``,
``sync_status:<id>`` and the old ``mode`` key), closes the browser, relaunches
it on the same profile directory with the code under test, and checks that
nothing was lost or reset.

If a change to the stored format is ever wanted, this test fails first: write a
migration, add a test for it, and only then update the seed here.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from conftest import EXT_PASSWORD, Ext, _launch
from fake_google import FakeGoogle
from fixtures.weak_vault import build_weak_vault, make_login
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from playwright.sync_api import Playwright
from support import POPUP_URL, menu_frame, open_login_page

pytestmark = pytest.mark.e2e

PROFILE_ID = "p_olddata1"
SITE_PASSWORD = "the password saved by the old version"
LAST_SUCCESS = "2026-10-16T15:10:42.000Z"

# what 0.1.0 wrote: the stores and keys exactly as idb.js created them
_SEED = """async ({ profile, vaultB64, record, sync, status }) => {
  const bytes = Uint8Array.from(atob(vaultB64), (c) => c.charCodeAt(0)).buffer;
  const db = await new Promise((ok, no) => {
    const r = indexedDB.open('personal-vault', 1);
    r.onupgradeneeded = () => {
      const d = r.result;
      d.createObjectStore('vaults', { keyPath: 'profileId' });
      d.createObjectStore('sync', { keyPath: 'profileId' });
      d.createObjectStore('backups', { keyPath: 'id', autoIncrement: true })
        .createIndex('profileId', 'profileId');
      d.createObjectStore('conflicts', { keyPath: 'id', autoIncrement: true })
        .createIndex('profileId', 'profileId');
    };
    r.onsuccess = () => ok(r.result);
    r.onerror = no;
  });
  await new Promise((ok, no) => {
    const tx = db.transaction(['vaults', 'sync'], 'readwrite');
    tx.objectStore('vaults').put({ profileId: profile.id, bytes, ...record });
    tx.objectStore('sync').put({ profileId: profile.id, ...sync });
    tx.oncomplete = ok;
    tx.onerror = no;
  });
  db.close();
  await chrome.storage.local.set({
    mode: 'extension',
    profiles: [profile],
    last_profile_id: profile.id,
    settings: { googleClientId: 'fake-client-id', lockOnScreenLock: false },
    [`sync_status:${profile.id}`]: status,
  });
}"""


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Drive's own checksum


def test_data_from_version_0_1_0_survives_a_restart_and_keeps_syncing(
    playwright_instance: Playwright,
    ext_extension: Path,
    fake_google: FakeGoogle,
    page_server: str,
    tmp_path: Path,
) -> None:
    # a vault as the old version stored it, one login for the test page
    port = page_server.rsplit(":", 1)[1]
    path = build_weak_vault(tmp_path / "old.kdbx", EXT_PASSWORD)
    session = VaultSession.open(path, EXT_PASSWORD, tmp_path / "backups")
    session.add(
        make_login(
            title="Saved Before",
            username="old@example.com",
            password=SecretStr(SITE_PASSWORD),
            urls=[f"http://127.0.0.1:{port}/login.html"],
        )
    )
    session.save()
    session.close()
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    md5 = _md5(data)

    # the same file already on Drive, synced: the state a long-running install has
    drive_file = fake_google.put_vault(PROFILE_ID, data)
    resource = drive_file.resource()
    assert resource["md5Checksum"] == md5
    seed = {
        "profile": {
            "id": PROFILE_ID,
            "name": "Altaf",
            "createdAt": "2026-10-16T14:00:00.000Z",
            "googleEmail": "owner@example.com",
        },
        "vaultB64": base64.b64encode(data).decode(),
        "record": {"sha256": sha256, "md5": md5, "savedAt": LAST_SUCCESS},
        "sync": {
            "drive_file_id": drive_file.id,
            "drive_folder_id": drive_file.parents[0],
            "last_synced_remote_md5": md5,
            "last_synced_remote_version": int(resource["version"]),
            "last_synced_local_sha256": sha256,
            "local_dirty": False,
            "last_success_at": LAST_SUCCESS,
            "last_error": None,
            "conflict": None,
            "linked_from": "adopt",
        },
        "status": {
            "state": "synced",
            "message": "Synced with Google Drive.",
            "localOnly": False,
            "lastAttemptAt": LAST_SUCCESS,
            "lastSuccessAt": LAST_SUCCESS,
            "attempts": 0,
            "nextRetryAt": None,
            "failed": None,
        },
    }

    profile_dir = tmp_path / "browser-profile"
    old = _launch(playwright_instance, profile_dir, ext_extension)
    control = old.new_page()
    control.goto(POPUP_URL)
    control.evaluate(_SEED, seed)
    old.close()

    # the browser starts again on the same profile with the code under test
    new = _launch(playwright_instance, profile_dir, ext_extension)
    try:
        control = new.new_page()
        control.goto(POPUP_URL)
        ext = Ext(new, control, fake_google)

        state = ext.state()
        assert state["profiles"] == [
            {"id": PROFILE_ID, "name": "Altaf", "googleEmail": "owner@example.com"}
        ]
        assert state["unlocked"] is None, "a restart locks; nothing else is lost"
        assert state["lastProfileId"] == PROFILE_ID
        assert state["settings"]["googleClientId"] == "fake-client-id"
        assert state["statuses"][PROFILE_ID]["lastSuccessAt"] == LAST_SUCCESS, "status kept"

        wrong = ext.call("ext_unlock", {"profileId": PROFILE_ID, "password": "not it"})
        assert wrong == {"ok": False, "error": {"code": "bad_password"}}
        ext.ok("ext_unlock", {"profileId": PROFILE_ID, "password": EXT_PASSWORD})
        entries = ext.ok("ext_list", {"query": ""})["entries"]
        assert [e["title"] for e in entries] == ["Saved Before"]
        entry = ext.ok("ext_get", {"entryId": entries[0]["id"]})["entry"]
        assert entry["password"] == SITE_PASSWORD

        # filling works from the old data
        page = open_login_page(new, f"http://127.0.0.1:{port}/login.html")
        page.click("#username")
        menu_frame(page).locator("#menu button").first.click()
        page.wait_for_function("() => document.getElementById('password').value !== ''")
        assert page.input_value("#password") == SITE_PASSWORD

        # the next sync is a normal one: not a first link, not a conflict,
        # nothing uploaded when nothing changed
        revisions = len(fake_google.vault_of(PROFILE_ID).revisions)
        ext.ok("ext_sync_now")
        status = ext.wait_status(PROFILE_ID, {"synced"})
        assert status["localOnly"] is False
        assert len(fake_google.vault_of(PROFILE_ID).revisions) == revisions

        # and a new edit goes up as a new revision of the same file
        ext.ok("ext_save_entry", {"entry": {**entry, "notes": "edited after the upgrade"}})
        waited = 0
        while len(fake_google.vault_of(PROFILE_ID).revisions) == revisions and waited < 60_000:
            control.wait_for_timeout(250)
            waited += 250
        assert len(fake_google.vault_of(PROFILE_ID).revisions) == revisions + 1
        assert len([f for f in fake_google.files.values() if f.name == "vault.kdbx"]) == 1
        assert ext.wait_status(PROFILE_ID, {"synced"})["localOnly"] is False
    finally:
        new.close()
