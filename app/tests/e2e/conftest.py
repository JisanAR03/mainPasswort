"""End-to-end fixtures: a real browser with the unpacked extension, running in
extension-only mode against a fake Google.

The browser is Playwright's Chromium unless ``PV_E2E_BROWSER`` names another:
``chrome`` (the installed Google Chrome, which no longer takes --load-extension,
so the extension is installed over the DevTools protocol) or ``brave`` (the
installed Brave; ``PV_BRAVE_PATH`` overrides where it is looked for). CI runs
Chromium; the owner runs the other two locally.

The extension under test is a copy of extension/ whose only changes are in
config.js: weak key-derivation settings so vaults open in milliseconds, Google's
endpoints pointed at fake_google.py, and short timers — the way weak KDF
settings exist only in test fixtures. test_extension_basics asserts that the
file that ships holds the real values.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable, Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fake_google import FakeGoogle
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from support import (
    EXTENSION_DIR,
    PASSWORD_ALIAS,
    PASSWORD_INSECURE,
    PASSWORD_LOCAL,
    PASSWORD_SECURE,
    POPUP_URL,
    TEST_PAGES,
)

E2E_BROWSER = os.environ.get("PV_E2E_BROWSER", "chromium")
BRAVE_PATHS = {
    "nt": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "posix": "/usr/bin/brave-browser",
}
EXT_PASSWORD = "an extension-only test passphrase"


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
def playwright_instance() -> Iterator[Playwright]:
    """One Playwright for the run: the sync API allows one per thread."""
    with sync_playwright() as playwright:
        yield playwright


def _rewrite(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        assert old in text, f"{path.name} no longer contains {old!r}"
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def fake_google() -> Iterator[FakeGoogle]:
    google = FakeGoogle()
    yield google
    google.close()


@pytest.fixture(scope="session")
def ext_extension(tmp_path_factory: pytest.TempPathFactory, fake_google: FakeGoogle) -> Path:
    """A copy of the extension with weak KDF settings, the fake Google and short
    timers — config.js is the one file it rewrites."""
    target = tmp_path_factory.mktemp("ext-extension") / "extension"
    shutil.copytree(
        EXTENSION_DIR,
        target,
        ignore=shutil.ignore_patterns("key.pem", "test-pages"),
    )
    base = fake_google.base
    _rewrite(
        target / "config.js",
        {
            "KDF_MEMORY_MIB = 128;": "KDF_MEMORY_MIB = 8;",
            "KDF_MIN_MEMORY_MIB = 64;": "KDF_MIN_MEMORY_MIB = 8;",
            "KDF_TARGET_MS = 1000;": "KDF_TARGET_MS = 1;",
            "KDF_MIN_ITERATIONS = 2;": "KDF_MIN_ITERATIONS = 1;",
            '"https://www.googleapis.com/drive/v3/files"': f'"{base}/drive/v3/files"',
            '"https://www.googleapis.com/upload/drive/v3/files"': (
                f'"{base}/upload/drive/v3/files"'
            ),
            '"https://www.googleapis.com/drive/v3/about"': f'"{base}/drive/v3/about"',
            '"https://accounts.google.com/o/oauth2/v2/auth"': f'"{base}/auth"',
            "UPLOAD_QUIET_MS = 10 * 1000;": "UPLOAD_QUIET_MS = 300;",
            "BACKOFF_SECONDS = [30, 60, 120, 240, 480, 960, 1800];": (
                "BACKOFF_SECONDS = [1, 1, 2, 2, 2, 2, 2];"
            ),
        },
    )
    return target


@pytest.fixture(scope="session")
def ext_profile_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("ext-profile")


def _seed_settings(context: BrowserContext) -> None:
    seed = context.new_page()
    seed.goto(POPUP_URL)
    seed.evaluate(
        "() => chrome.storage.local.set({ settings: { googleClientId: 'fake-client-id' } })"
    )
    seed.close()


@pytest.fixture(scope="session")
def browser(
    playwright_instance: Playwright, ext_extension: Path, ext_profile_dir: Path
) -> Iterator[BrowserContext]:
    """One headless browser for the whole e2e run, the extension loaded."""
    context = _launch(playwright_instance, ext_profile_dir, ext_extension)
    _seed_settings(context)
    yield context
    context.close()


@pytest.fixture(scope="session")
def control_page(browser: BrowserContext) -> Page:
    """An extension page kept around to read and reset extension storage."""
    page = browser.new_page()
    page.goto(POPUP_URL)
    return page


_DUMP_STORAGE = """async () => {
  const local = await chrome.storage.local.get(null);
  const session = await chrome.storage.session.get(null);
  const db = await new Promise((ok, no) => {
    const r = indexedDB.open('personal-vault');
    r.onsuccess = () => ok(r.result);
    r.onerror = no;
  });
  const rows = {};
  for (const name of db.objectStoreNames) {
    rows[name] = await new Promise((ok) => {
      const r = db.transaction(name).objectStore(name).getAll();
      r.onsuccess = () => ok(r.result);
    });
  }
  db.close();
  const text = JSON.stringify({ local, session, rows }, (k, v) =>
    v instanceof ArrayBuffer ? `<${v.byteLength} encrypted bytes>` : v);
  const bytes = [];
  for (const list of Object.values(rows)) {
    for (const row of list) {
      if (row && row.bytes instanceof ArrayBuffer) {
        bytes.push(new TextDecoder('latin1').decode(row.bytes));
      }
    }
  }
  return text + '\\n' + bytes.join('\\n');
}"""

_RESET = """async () => {
  await chrome.runtime.sendMessage({ type: 'ext_lock', args: {} });
  const docs = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  if (docs.length) await chrome.offscreen.closeDocument();
  await chrome.storage.session.clear();
  await chrome.storage.local.clear();
  await chrome.storage.local.set({ settings: { googleClientId: 'fake-client-id' } });
  await chrome.action.setBadgeText({ text: '' });
  await new Promise((ok, no) => {
    const r = indexedDB.deleteDatabase('personal-vault');
    r.onsuccess = ok;
    r.onerror = no;
    r.onblocked = ok;
  });
  for (const alarm of await chrome.alarms.getAll()) await chrome.alarms.clear(alarm.name);
}"""


@pytest.fixture(autouse=True)
def _clean_slate(
    control_page: Page, browser: BrowserContext, fake_google: FakeGoogle
) -> Iterator[None]:
    """Every test starts from the same state: no profiles, no vaults, no sync
    state, nothing unlocked, saving offered, no "never" sites, no save
    candidate, an empty fake Drive — and the tabs a test opens are closed again."""
    fake_google.reset()
    control_page.evaluate(_RESET)
    before = {id(page) for page in browser.pages}
    yield
    for page in browser.pages:
        if id(page) not in before:
            page.close()


class Ext:
    """Drives the extension the way its own pages do."""

    def __init__(self, browser: BrowserContext, control: Page, google: FakeGoogle) -> None:
        self.browser = browser
        self.control = control
        self.google = google

    def call(self, type_: str, args: dict[str, object] | None = None) -> dict:
        return self.control.evaluate(
            "([type, args]) => chrome.runtime.sendMessage({ type, args })", [type_, args or {}]
        )

    def ok(self, type_: str, args: dict[str, object] | None = None) -> dict:
        reply = self.call(type_, args)
        assert reply.get("ok"), f"{type_} failed: {reply.get('error')}"
        return reply.get("result") or {}

    def state(self) -> dict:
        return self.ok("ext_state")

    def create_profile(self, name: str, password: str = EXT_PASSWORD) -> str:
        result = self.ok("ext_create_profile", {"name": name, "password": password})
        return str(result["profileId"])

    def add_login(self, **fields: object) -> str:
        entry = {
            "title": "Example",
            "username": "user@example.com",
            "password": "an example password",
            "urls": [],
            "notes": "",
            "tags": [],
            "match_subdomains": False,
            **fields,
        }
        return str(self.ok("ext_save_entry", {"entry": entry})["id"])

    def sync_status(self, profile_id: str) -> dict:
        return self.state()["statuses"].get(profile_id) or {}

    def wait_status(self, profile_id: str, wanted: set[str], timeout_ms: int = 60_000) -> dict:
        waited = 0
        status: dict = {}
        while waited <= timeout_ms:
            status = self.sync_status(profile_id)
            if status.get("state") in wanted:
                return status
            self.control.wait_for_timeout(250)
            waited += 250
        raise AssertionError(f"status never became {wanted}; last: {status}")

    def dump_storage(self) -> str:
        """Everything in extension storage and IndexedDB as text to search for
        canaries — the vault files included, as raw bytes."""
        return str(self.control.evaluate(_DUMP_STORAGE))


@pytest.fixture
def ext(browser: BrowserContext, control_page: Page, fake_google: FakeGoogle) -> Ext:
    return Ext(browser, control_page, fake_google)


class SeededVault:
    """A profile in the extension's own vault, seeded with the logins the e2e
    pages use. The page server's port is part of every address, so the entries
    always match the test pages."""

    def __init__(self, ext: Ext, port: int, profile_id: str) -> None:
        self.ext = ext
        self.port = port
        self.profile_id = profile_id

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}/{path}"

    def logins(self) -> dict[str, str]:
        """title -> password, read back from the unlocked vault."""
        entries = self.ext.ok("ext_list", {"query": ""})["entries"]
        return {
            entry["title"]: self.ext.ok("ext_get", {"entryId": entry["id"]})["entry"]["password"]
            for entry in entries
        }


@pytest.fixture
def vault_factory(ext: Ext, page_server: str) -> Callable[..., SeededVault]:
    """Builds the seeded vault; ``locked=True`` leaves it locked."""
    port = int(page_server.rsplit(":", 1)[1])

    def make(*, locked: bool = False) -> SeededVault:
        profile = ext.create_profile("E2E")
        for title, username, password, address in (
            ("Local Dev", "dev@example.com", PASSWORD_LOCAL, f"http://127.0.0.1:{port}"),
            ("Local Dev Alias", "alias@example.com", PASSWORD_ALIAS, f"http://localhost:{port}"),
            ("Secure Only", "secure@example.com", PASSWORD_SECURE, f"https://127.0.0.1:{port}"),
            (
                "Plain HTTP Site",
                "plain@example.com",
                PASSWORD_INSECURE,
                f"http://insecure.test:{port}",
            ),
        ):
            ext.add_login(
                title=title, username=username, password=password, urls=[f"{address}/login.html"]
            )
        if locked:
            ext.ok("ext_lock")
        return SeededVault(ext, port, profile)

    return make


@pytest.fixture
def vault(vault_factory: Callable[..., SeededVault]) -> SeededVault:
    return vault_factory()
