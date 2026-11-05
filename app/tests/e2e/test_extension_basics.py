"""The shipped manifest and config, the pinned extension ID, and the popup's states."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from conftest import EXT_PASSWORD, SeededVault
from playwright.sync_api import BrowserContext, Page
from support import (
    EXTENSION_ID,
    MANIFEST_PATH,
    open_popup,
    status,
)

pytestmark = pytest.mark.e2e

VaultFactory = Callable[..., SeededVault]


def test_shipped_manifest_asks_only_for_what_the_page_features_need() -> None:
    """Web pages only (http and https, no file:// or other schemes), the two
    content scripts in the top frame only, and nothing a web page can load but
    the two frame pages. Site access is declared rather than optional because
    the suggestion menu and the save prompt work on every site from install
    (docs/tasks/fix-extension-inline-fill-save.md)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    web = ["http://*/*", "https://*/*"]
    assert manifest["manifest_version"] == 3
    # offscreen, alarms and identity: the vault engine's document, the timers
    # that outlive the service worker, and Google sign-in. clipboardRead: the
    # engine looks at the clipboard 30 seconds after a Copy, so it clears only
    # a password it copied (the owner approved clipboardRead on 2026-11-05), and
    # clipboardWrite, without which that clear cannot write.
    # No nativeMessaging: nothing talks to another program.
    assert sorted(manifest["permissions"]) == [
        "activeTab",
        "alarms",
        "clipboardRead",
        "clipboardWrite",
        "identity",
        "offscreen",
        "scripting",
        "storage",
    ]
    assert manifest["optional_permissions"] == ["idle"]  # asked for only on a click
    # WebAssembly for Argon2, nothing more: no eval, no remote scripts
    assert manifest["content_security_policy"] == {
        "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"
    }
    # Alt+Shift+L locks; Alt+Shift+P opens the toolbar popup (browsers may reassign either)
    assert set(manifest["commands"]) == {"lock-vault", "_execute_action"}
    assert manifest["host_permissions"] == web
    assert "optional_host_permissions" not in manifest
    assert manifest["content_scripts"] == [
        {
            "matches": web,
            "js": ["deep.js", "detect.js", "inline.js"],  # deep.js: search inside shadow roots
            "run_at": "document_end",
            "all_frames": False,
        }
    ]
    assert manifest["web_accessible_resources"] == [
        {"resources": ["menu.html", "prompt.html"], "matches": web}
    ]
    assert "key" in manifest, "the ID must stay pinned for the native-host registration"


def test_shipped_config_is_the_real_one() -> None:
    """config.js is what the e2e copy rewrites (weak KDF, fake Google, short
    timers); the file that ships must hold the real values."""
    config = (MANIFEST_PATH.parent / "config.js").read_text(encoding="utf-8")
    for line in (
        "export const UNLOCK_HOURS = 6;",
        "export const CLIPBOARD_CLEAR_MS = 30 * 1000;",
        "export const KDF_MEMORY_MIB = 128;",
        "export const KDF_MIN_MEMORY_MIB = 64;",
        "export const KDF_PARALLELISM = 2;",
        "export const KDF_TARGET_MS = 1000;",
        "export const KDF_MIN_ITERATIONS = 2;",
        'export const DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files";',
        'export const DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files";',
        'export const DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about";',
        'export const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";',
        'export const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";',
        "export const UPLOAD_QUIET_MS = 10 * 1000;",
        "export const SYNC_INTERVAL_MINUTES = 60;",
        "export const BACKOFF_SECONDS = [30, 60, 120, 240, 480, 960, 1800];",
    ):
        assert line in config, f"config.js does not ship {line!r}"


def test_the_loaded_extension_has_the_pinned_id(control_page: Page) -> None:
    assert control_page.evaluate("() => chrome.runtime.id") == EXTENSION_ID


def test_the_popup_shows_the_unlocked_profile(browser: BrowserContext, vault: SeededVault) -> None:
    browser.new_page().goto(vault.url("login.html"))
    popup = open_popup(browser)
    assert status(popup) == "Unlocked: E2E"
    assert popup.is_visible("#lock")


def test_with_no_vault_the_popup_offers_to_create_one(browser: BrowserContext) -> None:
    popup = open_popup(browser)
    assert status(popup) == "No vault in this browser yet."
    assert popup.is_visible("#setup")
    assert not popup.is_visible("#unlock-form")


def test_a_locked_vault_is_unlocked_from_the_popup(
    browser: BrowserContext, vault_factory: VaultFactory
) -> None:
    vault = vault_factory(locked=True)
    browser.new_page().goto(vault.url("login.html"))
    popup = open_popup(browser)
    assert status(popup) == "Locked."
    assert popup.is_visible("#unlock-form")
    popup.fill("#password", EXT_PASSWORD)
    popup.click("#unlock-button")
    popup.wait_for_function(
        "() => document.getElementById('status').textContent === 'Unlocked: E2E'",
        timeout=60_000,
    )
    assert popup.is_visible("#lock")
