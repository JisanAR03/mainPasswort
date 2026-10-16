"""M4-01: the shipped manifest, the pinned extension ID, and status/pairing."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import pytest
from conftest import Bridge
from personal_vault.bridge.pairing import pairing_code
from playwright.sync_api import BrowserContext, Page
from support import (
    EXTENSION_ID,
    MANIFEST_PATH,
    open_popup,
    status,
    titles,
    usernames,
    wait_for_matches,
)

pytestmark = pytest.mark.e2e

BridgeFactory = Callable[..., Bridge]


def test_shipped_manifest_asks_only_for_what_the_page_features_need() -> None:
    """Web pages only (http and https, no file:// or other schemes), the two
    content scripts in the top frame only, and nothing a web page can load but
    the two frame pages. Site access is declared rather than optional because
    the suggestion menu and the save prompt work on every site from install
    (docs/tasks/fix-extension-inline-fill-save.md)."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    web = ["http://*/*", "https://*/*"]
    assert manifest["manifest_version"] == 3
    # offscreen, alarms and identity are extension-only mode's (EXT-00, approved
    # by the owner): the vault engine's document, the timers that outlive the
    # service worker, and Google sign-in
    assert sorted(manifest["permissions"]) == [
        "activeTab",
        "alarms",
        "identity",
        "nativeMessaging",
        "offscreen",
        "scripting",
        "storage",
    ]
    assert manifest["optional_permissions"] == ["idle"]  # asked for only on a click
    # WebAssembly for Argon2, nothing more: no eval, no remote scripts
    assert manifest["content_security_policy"] == {
        "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"
    }
    assert set(manifest["commands"]) == {"lock-vault"}
    assert manifest["host_permissions"] == web
    assert "optional_host_permissions" not in manifest
    assert manifest["content_scripts"] == [
        {
            "matches": web,
            "js": ["detect.js", "inline.js"],
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


def test_status_reaches_the_desktop_app(browser: BrowserContext, bridge: Bridge) -> None:
    browser.new_page().goto(bridge.url("login.html"))
    popup = open_popup(browser)
    assert status(popup) == "Unlocked: E2E"
    assert popup.is_visible("#lock")


def test_without_the_app_the_popup_says_so(browser: BrowserContext) -> None:
    popup = open_popup(browser)
    assert status(popup) == "The desktop app is not running."
    assert popup.is_visible("#not-running")


def test_a_locked_vault_points_at_the_app(
    browser: BrowserContext, bridge_factory: BridgeFactory
) -> None:
    bridge_factory(locked=True)
    popup = open_popup(browser)
    assert status(popup) == "E2E is locked."
    assert popup.is_visible("#locked")
    popup.click("#unlock")
    assert status(popup) == "Bringing the desktop window forward…"


def test_an_unpaired_browser_can_pair_and_then_list(
    browser: BrowserContext, bridge_factory: BridgeFactory, control_page: Page
) -> None:
    # the app holds its answer back for a moment, as its dialog does while it
    # waits for the click, so the popup's code can be read while it waits
    bridge = bridge_factory(unpaired=True, pair_delay_ms=2000)
    browser.new_page().goto(bridge.url("login.html"))
    popup = open_popup(browser)
    assert status(popup) == "Not paired yet."
    assert popup.is_visible("#unpaired")
    popup.click("#pair")
    popup.wait_for_selector("#pair-code", state="visible", timeout=30_000)
    shown = popup.inner_text("#pair-code")
    assert len(shown) == 6

    popup.wait_for_function(
        "() => document.getElementById('status').textContent.startsWith('Unlocked')",
        timeout=30_000,
    )
    wait_for_matches(popup)
    assert titles(popup) == ["Local Dev"]
    assert usernames(popup) == ["dev@example.com"]
    assert not popup.is_visible("#pair-code"), "the code goes once the browser is paired"

    # the key the browser made and stored, run through the app's own derivation:
    # the two sides must show the same code, or pairing confirms nothing
    stored = control_page.evaluate(
        "async () => (await chrome.storage.local.get('pairing_key')).pairing_key"
    )
    assert shown == pairing_code(base64.b64decode(stored))
