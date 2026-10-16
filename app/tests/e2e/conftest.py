"""End-to-end fixtures: a real browser, the unpacked extension, the real native
host and a real bridge process in front of a weak test vault.

The browser is Playwright's Chromium unless ``PV_E2E_BROWSER`` names another:
``chrome`` (the installed Google Chrome, which no longer takes --load-extension,
so the extension is installed over the DevTools protocol) or ``brave`` (the
installed Brave; ``PV_BRAVE_PATH`` overrides where it is looked for). CI runs
Chromium; the owner runs the other two locally.

The extension under test is a copy of extension/ whose one change is the native
host name it connects to: the copy asks for ``com.personalvault.e2e``, which
these fixtures register for the test bridge. The real name stays registered for
the installed app, so a run in the browser you use every day can never reach
your real vault.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.bridge.pairing import PAIRING_ENTRY
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from support import (
    BRIDGE_APP,
    E2E_HOST_NAME,
    EXTENSION_DIR,
    EXTENSION_ID,
    HOST_NAME,
    PASSWORD_ALIAS,
    PASSWORD_INSECURE,
    PASSWORD_LOCAL,
    PASSWORD_SECURE,
    POPUP_URL,
    TEST_PAGES,
)

PAIRING_KEY = base64.b64encode(bytes(range(32))).decode()
E2E_BROWSER = os.environ.get("PV_E2E_BROWSER", "chromium")
BRAVE_PATHS = {
    "nt": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "posix": "/usr/bin/brave-browser",
}
# where each browser reads its user-level native hosts from: a registry key on
# Windows, a folder under ~/.config on Linux. Brave on Windows reads Chrome's
# key, not one of its own: a host registered only under
# Software\BraveSoftware\Brave-Browser is "not found" (checked with Brave 1.97,
# 2026-10-16) — the installer's Chrome key is what makes Brave work.
_WINDOWS_HOST_KEYS = {
    "chromium": r"Software\Chromium\NativeMessagingHosts",
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "brave": r"Software\Google\Chrome\NativeMessagingHosts",
}
_POSIX_HOST_DIRS = ("chromium", "google-chrome", "BraveSoftware/Brave-Browser")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # the test output is noisy enough without request logs


@pytest.fixture(scope="session")
def page_server() -> Iterator[str]:
    """The test pages over plain HTTP on 127.0.0.1; returns the base URL."""
    handler = partial(_QuietHandler, directory=str(TEST_PAGES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _windows_key() -> str:
    return rf"{_WINDOWS_HOST_KEYS[E2E_BROWSER]}\{E2E_HOST_NAME}"


def _posix_manifest_paths(profile_dir: Path) -> list[Path]:
    """Everywhere the Linux browser may look for a user-level host.

    Playwright's Linux Chromium build is branded Chrome for Testing, which
    reads Chrome's directory rather than Chromium's; Brave reads its own; a
    browser started with ``--user-data-dir`` also looks inside that directory.
    Writing all of them is cheaper than guessing which one this build uses.
    """
    brands = [
        Path.home() / ".config" / brand / "NativeMessagingHosts" for brand in _POSIX_HOST_DIRS
    ]
    return [
        *(brand / f"{E2E_HOST_NAME}.json" for brand in brands),
        profile_dir / "NativeMessagingHosts" / f"{E2E_HOST_NAME}.json",
    ]


def _launcher_text(socket_name: str) -> tuple[str, str]:
    command = f'"{sys.executable}" -m personal_vault.host.pm_host'
    if os.name == "nt":
        return (
            "launcher.bat",
            f"@echo off\r\nset PERSONAL_VAULT_SOCKET={socket_name}\r\n{command}\r\n",
        )
    return "launcher.sh", f"#!/bin/sh\nexport PERSONAL_VAULT_SOCKET={socket_name}\nexec {command}\n"


@pytest.fixture(scope="session")
def chromium_profile(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The browser's user-data-dir, so the host can register inside it too."""
    return tmp_path_factory.mktemp("chromium-profile")


@pytest.fixture(scope="session")
def host_socket(tmp_path_factory: pytest.TempPathFactory, chromium_profile: Path) -> Iterator[str]:
    """Register the e2e native host for the browser under test and hand back
    the socket name its launcher points at."""
    name = f"pv-e2e-{uuid.uuid4().hex}"
    home = tmp_path_factory.mktemp("native-host")
    filename, text = _launcher_text(name)
    launcher = home / filename
    launcher.write_text(text, encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    manifest = home / f"{HOST_NAME}.json"
    manifest.write_text(
        json.dumps(
            {
                "name": E2E_HOST_NAME,
                "description": "Personal Vault e2e host",
                "path": str(launcher),
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
            }
        ),
        encoding="utf-8",
    )
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _windows_key()) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest))
    else:
        for target in _posix_manifest_paths(chromium_profile):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    yield name
    if os.name == "nt":
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _windows_key())
        except FileNotFoundError:
            pass
    else:
        for target in _posix_manifest_paths(chromium_profile):
            target.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def test_extension(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of the extension that connects to the e2e host, not the real one."""
    target = tmp_path_factory.mktemp("extension") / "extension"
    shutil.copytree(
        EXTENSION_DIR,
        target,
        ignore=shutil.ignore_patterns("key.pem", "native-host", "test-pages"),
    )
    api = target / "api.js"
    text = api.read_text(encoding="utf-8")
    assert f'"{HOST_NAME}"' in text, "api.js no longer names the host the way this copy expects"
    api.write_text(text.replace(f'"{HOST_NAME}"', f'"{E2E_HOST_NAME}"'), encoding="utf-8")
    return target


def _launch(playwright: Playwright, profile: Path, extension: Path) -> BrowserContext:
    # deterministic look-alike host: localhost must land on the server bound to
    # 127.0.0.1, not on a refused ::1; insecure.test is a plain-http site that,
    # as far as the extension can tell, is not this machine; other.test is a
    # site the vault has no login for
    rules = (
        "--host-resolver-rules=MAP localhost 127.0.0.1, MAP insecure.test 127.0.0.1,"
        " MAP other.test 127.0.0.1"
    )
    load = [f"--disable-extensions-except={extension}", f"--load-extension={extension}"]
    if E2E_BROWSER == "chrome":
        # branded Chrome ignores --load-extension; install over DevTools instead
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=True,
            args=[rules, "--enable-unsafe-extension-debugging"],
            ignore_default_args=["--disable-extensions"],
        )
        assert context.browser is not None
        cdp = context.browser.new_browser_cdp_session()
        cdp.send("Extensions.loadUnpacked", {"path": str(extension)})
    elif E2E_BROWSER == "brave":
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=os.environ.get("PV_BRAVE_PATH", BRAVE_PATHS[os.name]),
            headless=True,
            args=[rules, *load],
            ignore_default_args=["--disable-extensions"],
        )
    else:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), channel="chromium", headless=True, args=[rules, *load]
        )
    if not context.service_workers:
        context.wait_for_event("serviceworker", timeout=30_000)
    return context


@pytest.fixture(scope="session")
def browser(
    test_extension: Path, host_socket: str, chromium_profile: Path
) -> Iterator[BrowserContext]:
    """One headless browser for the whole e2e run, extension loaded and the
    pairing key already in extension storage."""
    with sync_playwright() as playwright:
        context = _launch(playwright, chromium_profile, test_extension)
        seed = context.new_page()
        seed.goto(POPUP_URL)
        seed.evaluate("(key) => chrome.storage.local.set({ pairing_key: key })", PAIRING_KEY)
        seed.close()
        yield context
        context.close()


@pytest.fixture(scope="session")
def control_page(browser: BrowserContext) -> Page:
    """An extension page kept around to read and reset extension storage."""
    page = browser.new_page()
    page.goto(POPUP_URL)
    return page


@pytest.fixture(autouse=True)
def _clean_slate(control_page: Page, browser: BrowserContext) -> Iterator[None]:
    """Every test starts from the same extension state: the key the seeded
    vaults are paired with (a pairing test changes it), saving offered, no
    "never" sites, no save candidate — and the tabs a test opens are closed
    again."""
    before = {id(page) for page in browser.pages}
    control_page.evaluate(
        "async (key) => {"
        "  await chrome.storage.session.clear();"
        "  await chrome.storage.local.remove(['offer_to_save', 'never_save']);"
        "  await chrome.storage.local.set({ pairing_key: key });"
        "  await chrome.action.setBadgeText({ text: '' });"
        "}",
        PAIRING_KEY,
    )
    yield
    for page in browser.pages:
        if id(page) not in before:
            page.close()


class Bridge:
    """A running bridge process over one test vault."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        vault_path: Path,
        backups_dir: Path,
        port: int,
        unlock_marker: Path,
    ) -> None:
        self.process = process
        self.vault_path = vault_path
        self.backups_dir = backups_dir
        self.port = port
        self.unlock_marker = unlock_marker

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}/{path}"

    def unlock_requests(self) -> int:
        """How many times the extension asked the app to show its unlock window."""
        if not self.unlock_marker.exists():
            return 0
        return len(self.unlock_marker.read_text(encoding="utf-8").splitlines())

    def logins(self) -> dict[str, str]:
        """title -> password, read back from the vault file on disk."""
        session = VaultSession.open(self.vault_path, WEAK_PASSWORD, self.backups_dir)
        try:
            return {
                summary.title: session.get(summary.id).password.reveal()
                for summary in session.list_logins()
            }
        finally:
            session.close()


def _seed_entries(vault_path: Path, backups_dir: Path, port: int, pairing_key: str | None) -> None:
    session = VaultSession.open(vault_path, WEAK_PASSWORD, backups_dir)
    try:
        session.add(
            make_login(
                title="Local Dev",
                username="dev@example.com",
                password=SecretStr(PASSWORD_LOCAL),
                urls=[f"http://127.0.0.1:{port}/login.html"],
            )
        )
        session.add(
            make_login(
                title="Local Dev Alias",
                username="alias@example.com",
                password=SecretStr(PASSWORD_ALIAS),
                urls=[f"http://localhost:{port}/login.html"],
            )
        )
        session.add(
            make_login(
                title="Secure Only",
                username="secure@example.com",
                password=SecretStr(PASSWORD_SECURE),
                urls=[f"https://127.0.0.1:{port}/login.html"],
            )
        )
        session.add(
            make_login(
                title="Plain HTTP Site",
                username="plain@example.com",
                password=SecretStr(PASSWORD_INSECURE),
                urls=[f"http://insecure.test:{port}/login.html"],
            )
        )
        if pairing_key is not None:
            session.set_app_value(PAIRING_ENTRY, pairing_key)
        session.save()
    finally:
        session.close()


@pytest.fixture
def bridge_factory(
    tmp_path: Path, page_server: str, host_socket: str
) -> Iterator[Callable[..., Bridge]]:
    """Builds (and cleans up) bridge processes over fresh seeded vaults."""
    processes: list[subprocess.Popen[str]] = []
    port = int(page_server.rsplit(":", 1)[1])

    def make(*, locked: bool = False, unpaired: bool = False, pair_delay_ms: int = 0) -> Bridge:
        vault_path = build_weak_vault(tmp_path / f"vault-{uuid.uuid4().hex}.kdbx")
        backups_dir = tmp_path / "backups"
        unlock_marker = tmp_path / f"unlock-{uuid.uuid4().hex}.log"
        _seed_entries(vault_path, backups_dir, port, None if unpaired else PAIRING_KEY)
        env = {
            **os.environ,
            "PV_VAULT_PATH": str(vault_path),
            "PV_VAULT_PASSWORD": WEAK_PASSWORD,
            "PV_BRIDGE_SOCKET": host_socket,
            "PV_BACKUPS_DIR": str(backups_dir),
            "PV_UNLOCK_MARKER": str(unlock_marker),
        }
        if locked:
            env["PV_START_LOCKED"] = "1"
        if pair_delay_ms:
            env["PV_PAIR_DELAY_MS"] = str(pair_delay_ms)
        process = subprocess.Popen(
            [sys.executable, str(BRIDGE_APP)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        assert process.stdout is not None
        line = process.stdout.readline().strip()
        assert line == "READY", f"bridge did not start: {line!r}"
        return Bridge(process, vault_path, backups_dir, port, unlock_marker)

    yield make
    for process in processes:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def bridge(bridge_factory: Callable[..., Bridge]) -> Bridge:
    return bridge_factory()
