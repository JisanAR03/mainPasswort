"""End-to-end fixtures: real Chromium, the unpacked extension, the real native
host and a real bridge process in front of a weak test vault.

The extension under test is a copy of extension/ whose manifest grants
``<all_urls>`` up front, because a loaded extension can only be granted an
optional permission through a browser prompt no test can click. The shipped
manifest is asserted separately (test_extension_basics) to carry no host
permissions and to keep ``<all_urls>`` optional.
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
from playwright.sync_api import BrowserContext, Page, sync_playwright
from support import (
    BRIDGE_APP,
    EXTENSION_DIR,
    EXTENSION_ID,
    HOST_NAME,
    PASSWORD_ALIAS,
    PASSWORD_LOCAL,
    PASSWORD_SECURE,
    POPUP_URL,
    TEST_PAGES,
)

PAIRING_KEY = base64.b64encode(bytes(range(32))).decode()


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
    return rf"Software\Chromium\NativeMessagingHosts\{HOST_NAME}"


def _posix_manifest_path() -> Path:
    return Path.home() / ".config" / "chromium" / "NativeMessagingHosts" / f"{HOST_NAME}.json"


def _launcher_text(socket_name: str) -> tuple[str, str]:
    command = f'"{sys.executable}" -m personal_vault.host.pm_host'
    if os.name == "nt":
        return (
            "launcher.bat",
            f"@echo off\r\nset PERSONAL_VAULT_SOCKET={socket_name}\r\n{command}\r\n",
        )
    return "launcher.sh", f"#!/bin/sh\nexport PERSONAL_VAULT_SOCKET={socket_name}\nexec {command}\n"


@pytest.fixture(scope="session")
def host_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Register the native host for Playwright's Chromium and hand back the
    socket name its launcher points at."""
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
                "name": HOST_NAME,
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
        target = _posix_manifest_path()
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
        _posix_manifest_path().unlink(missing_ok=True)


@pytest.fixture(scope="session")
def test_extension(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of the extension, with all-sites granted in the manifest."""
    target = tmp_path_factory.mktemp("extension") / "extension"
    shutil.copytree(EXTENSION_DIR, target, ignore=shutil.ignore_patterns("key.pem", "native-host"))
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("optional_host_permissions", None)
    manifest["host_permissions"] = ["<all_urls>"]
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


@pytest.fixture(scope="session")
def browser(
    test_extension: Path, host_socket: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[BrowserContext]:
    """One headless Chromium for the whole e2e run, extension loaded and the
    pairing key already in extension storage."""
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(tmp_path_factory.mktemp("chromium-profile")),
            channel="chromium",
            headless=True,
            args=[
                f"--disable-extensions-except={test_extension}",
                f"--load-extension={test_extension}",
                # deterministic look-alike host: localhost must land on the
                # server bound to 127.0.0.1, not on a refused ::1
                "--host-resolver-rules=MAP localhost 127.0.0.1",
            ],
        )
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
    vaults are paired with (a pairing test changes it), no watch flag, no save
    candidate — and the tabs a test opens are closed again."""
    before = {id(page) for page in browser.pages}
    control_page.evaluate(
        "async (key) => {"
        # watch_off also unregisters the detector, which storage alone would not
        "  await chrome.runtime.sendMessage({ type: 'watch_off' });"
        "  await chrome.storage.session.clear();"
        "  await chrome.storage.local.set({ pairing_key: key });"
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
        self, process: subprocess.Popen[str], vault_path: Path, backups_dir: Path, port: int
    ) -> None:
        self.process = process
        self.vault_path = vault_path
        self.backups_dir = backups_dir
        self.port = port

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}/{path}"

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
        _seed_entries(vault_path, backups_dir, port, None if unpaired else PAIRING_KEY)
        env = {
            **os.environ,
            "PV_VAULT_PATH": str(vault_path),
            "PV_VAULT_PASSWORD": WEAK_PASSWORD,
            "PV_BRIDGE_SOCKET": host_socket,
            "PV_BACKUPS_DIR": str(backups_dir),
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
        return Bridge(process, vault_path, backups_dir, port)

    yield make
    for process in processes:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def bridge(bridge_factory: Callable[..., Bridge]) -> Bridge:
    return bridge_factory()
