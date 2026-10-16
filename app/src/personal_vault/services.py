"""The only door from ui/ into core/.

Every window works through this module; ui/ never imports core/ or pykeepass
directly (import-linter enforces the contract). Services hold no state and
surface the same errors as core: ValueError for bad input, KeyError for unknown
ids, SchemaTooNewError for newer files, InvalidPassword/VaultCorrupted for
vault problems.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from personal_vault.core.errors import InvalidPassword, VaultCorrupted, VaultError  # noqa: F401
from personal_vault.core.generator import generate_password as core_generate
from personal_vault.core.models import LoginEntry, LoginSummary, SecretStr  # noqa: F401
from personal_vault.core.profiles import Profile, ProfileStore
from personal_vault.core.settings import DEFAULTS, SCHEMA_VERSION, SettingsStore
from personal_vault.core.transfer import export_csv as core_export_csv
from personal_vault.core.transfer import import_csv as core_import_csv
from personal_vault.core.transfer import import_kdbx as core_import_kdbx
from personal_vault.core.vault import MergeReport, VaultSession, open_vault  # noqa: F401 (re-export)
from personal_vault.sync.drive_client import DriveClient, HttpDriveClient
from personal_vault.sync.engine import (
    FIRST_LINK_ASK,
    Status,
    SyncEngine,
    SyncResult,
    SyncWorker,
)
from personal_vault.sync.errors import NotLinked, SyncError
from personal_vault.sync.oauth import (
    CLIENT_CONFIG_FILE,
    DRIVE_SYNC_ENTRY,
    GoogleAccount,
    load_client_config,
    refreshed_access_token,
)
from personal_vault.sync.oauth import connect as oauth_connect

# Re-exported so ui/ can use these types without importing core/ directly.
__all__ = [
    "InvalidPassword",
    "LoginEntry",
    "LoginSummary",
    "MergeReport",
    "Profile",
    "ProfileStore",
    "SecretStr",
    "VaultCorrupted",
    "VaultError",
    "VaultSession",
    "add_login",
    "clipboard_clear_seconds",
    "data_dir",
    "delete_login",
    "entry_history",
    "connect_google",
    "disconnect_google",
    "export_csv",
    "generate_password",
    "generator_defaults",
    "get_login",
    "google_access_token",
    "google_account",
    "google_client_secret_path",
    "idle_lock_minutes",
    "import_csv",
    "import_kdbx",
    "install_client_secret",
    "list_backups",
    "list_logins",
    "lock_on_sleep",
    "open_profile_vault",
    "open_vault",
    "profile_vault_dir",
    "profiles",
    "restore_backup",
    "review_copy",
    "save_vault",
    "search_logins",
    "settings_readonly",
    "settings_values",
    "sync_interval_minutes",
    "SyncController",
    "SyncReport",
    "Status",
    "SyncResult",
    "update_login",
    "update_settings",
    "upload_quiet_seconds",
]


def data_dir() -> Path:
    """The app data folder: PV_DATA_DIR when set, else the platform data dir.

    Tests and dev runs always set PV_DATA_DIR to a throwaway folder, so no
    development session can touch a real vault (architecture.md).
    """
    override = os.environ.get("PV_DATA_DIR")
    if override:
        return Path(override)
    from platformdirs import user_data_dir

    return Path(user_data_dir("PersonalVault", appauthor=False))


def profiles() -> ProfileStore:
    """The profile store for the data dir, loaded (schema version applied)."""
    store = ProfileStore(data_dir())
    store.load()
    return store


def _setting(key: str) -> object:
    """A setting from settings.json, or its built-in default when absent or corrupt.

    A value whose type does not match the default (e.g. a string where an int
    belongs) is treated as corrupt and the default is used. A newer-schema
    settings.json still reads here; only writes are refused.
    """
    store = SettingsStore(data_dir())
    store.load()
    value = store.get(key)
    default = DEFAULTS[key]
    return value if type(value) is type(default) else default


def clipboard_clear_seconds() -> int:
    """The clipboard auto-clear delay from settings.json (default 30)."""
    return max(1, cast(int, _setting("clipboard_clear_seconds")))


def idle_lock_minutes() -> int:
    """The idle-lock delay from settings.json (default 5)."""
    return max(1, cast(int, _setting("idle_lock_minutes")))


def lock_on_sleep() -> bool:
    """Whether a reported system sleep locks the vault (default True)."""
    return cast(bool, _setting("lock_on_sleep"))


def settings_values() -> dict[str, object]:
    """Every setting with defaults applied, exactly as the dialog shows them."""
    return {key: _setting(key) for key in DEFAULTS}


def update_settings(values: dict[str, object]) -> None:
    """Validate and persist settings; raises ValueError with a message."""
    store = SettingsStore(data_dir())
    store.load()
    for key, value in values.items():
        store.set(key, value)  # validates and writes per key


def settings_readonly() -> bool:
    """Whether settings.json has a newer schema_version (open read-only)."""
    try:
        raw = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    version = raw.get("schema_version", SCHEMA_VERSION)
    return isinstance(version, int) and version > SCHEMA_VERSION


def generator_defaults() -> dict[str, object]:
    """Generator options from settings.json; bad fields fall back to defaults."""
    value = _setting("generator")
    raw = dict(value) if isinstance(value, dict) else {}
    result: dict[str, object] = {}
    for key, default in cast(dict[str, object], DEFAULTS["generator"]).items():
        item = raw.get(key)
        result[key] = item if type(item) is type(default) else default
    return result


def profile_vault_dir(profile: Profile) -> Path:
    """Where a profile's vault and backups live: <data>/profiles/<id>/."""
    return data_dir() / "profiles" / profile.id


def open_profile_vault(profile: Profile, password: str) -> VaultSession:
    """Open a profile's vault for a session (the ui unlock path).

    Raises InvalidPassword for a wrong master password and VaultCorrupted for
    a damaged file; the ui shows those messages and never the cause.
    """
    folder = profile_vault_dir(profile)
    return VaultSession.open(folder / "vault.kdbx", password, folder / "backups")


def list_logins(session: VaultSession) -> list[LoginSummary]:
    return session.list_logins()


def generate_password(
    length: int = 20,
    *,
    upper: bool = True,
    lower: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_lookalikes: bool = True,
) -> SecretStr:
    """Generate a password from the core generator ([S])."""
    return core_generate(
        length,
        upper=upper,
        lower=lower,
        digits=digits,
        symbols=symbols,
        exclude_lookalikes=exclude_lookalikes,
    )


def search_logins(session: VaultSession, query: str) -> list[LoginSummary]:
    return session.search(query)


def get_login(session: VaultSession, entry_id: uuid.UUID) -> LoginEntry:
    return session.get(entry_id)


def add_login(session: VaultSession, entry: LoginEntry) -> None:
    """Add an entry; raises ValueError with a field-rule message when invalid."""
    session.add(entry)


def update_login(session: VaultSession, entry: LoginEntry) -> None:
    """Edit an entry (a history snapshot is kept); raises ValueError when invalid."""
    session.edit(entry)


def delete_login(session: VaultSession, entry_id: uuid.UUID) -> None:
    """Move an entry to the Recycle Bin (never a permanent delete)."""
    session.delete(entry_id)


def entry_history(session: VaultSession, entry_id: uuid.UUID) -> list[LoginEntry]:
    return session.history(entry_id)


def save_vault(session: VaultSession) -> None:
    """Persist through storage: atomic write, verify, rotate backups."""
    session.save()


def list_backups(session: VaultSession) -> list[Path]:
    """The session's backup files, newest first."""
    return sorted(session.backups_dir.glob("vault-*.kdbx"), reverse=True)


def restore_backup(session: VaultSession, backup: Path) -> VaultSession:
    """Replace the vault with ``backup`` and return the reopened session."""
    return session.restore_backup(backup)


def export_csv(session: VaultSession, target: str | Path) -> None:
    """Plaintext CSV export (only the UI behind I8 may call this)."""
    core_export_csv(session, target)


def import_csv(source: str | Path, session: VaultSession) -> int:
    """Parse a CSV as untrusted input; entries land in a new group for review."""
    return core_import_csv(source, session)


def import_kdbx(source: str | Path, password: str, session: VaultSession) -> int:
    """Open a KDBX as untrusted input; entries land in a new group for review."""
    return core_import_kdbx(source, password, session)


# --- Google Drive sync: sign-in and the token in the vault ------------------


def google_client_secret_path() -> Path:
    """The owner's own OAuth client: <data>/client_secret.json (git-ignored)."""
    return data_dir() / CLIENT_CONFIG_FILE


def google_account(session: VaultSession) -> GoogleAccount | None:
    """The Drive account this profile is connected as, if any."""
    token = session.get_app_value(DRIVE_SYNC_ENTRY)
    if not token:
        return None
    return GoogleAccount(
        refresh_token=SecretStr(token), email=session.get_app_username(DRIVE_SYNC_ENTRY)
    )


def save_google_account(session: VaultSession, account: GoogleAccount) -> None:
    """Store the refresh token in the vault and save, so it never sits elsewhere."""
    session.set_app_value(
        DRIVE_SYNC_ENTRY, account.refresh_token.reveal(), username=account.email or ""
    )
    save_vault(session)


def connect_google(session: VaultSession) -> GoogleAccount:
    """Sign in with Google and store the token.

    Blocking, and it opens the system browser: call it off the UI thread
    (the sync worker, M5-05/M5-06).
    """
    config = load_client_config(google_client_secret_path())
    account = oauth_connect(config, email_lookup=_drive_account_email)
    save_google_account(session, account)
    return account


def disconnect_google(session: VaultSession) -> None:
    """Forget the account: the entry goes, the rest of the vault stays."""
    session.delete_app_entry(DRIVE_SYNC_ENTRY)
    save_vault(session)


def google_access_token(session: VaultSession) -> str:
    """A fresh access token for this profile, or the error the UI shows."""
    account = google_account(session)
    if account is None:
        raise NotLinked("this profile is not connected to Google Drive")
    return refreshed_access_token(account, load_client_config(google_client_secret_path()))


def _drive_account_email(access_token: str) -> str | None:
    """The account's address, only to label the connection.

    A failure here is not a failure to sign in: the token is already stored by
    the time this runs, so the email may simply stay unknown.
    """
    try:
        return HttpDriveClient(token=lambda: access_token).account_email()
    except SyncError:
        return None


def sync_interval_minutes() -> int:
    """How often an unlocked vault syncs, from settings.json (default 60)."""
    return max(1, cast(int, _setting("sync_interval_minutes")))


def upload_quiet_seconds() -> int:
    """How long a save waits before it is uploaded, from settings.json (default 10)."""
    return max(1, cast(int, _setting("upload_quiet_seconds")))


def install_client_secret(source: str | Path) -> Path:
    """Copy the owner's own OAuth client to <data>/client_secret.json.

    The file is the owner's (docs/setup-google-drive.md): copied, never read
    from wherever it was downloaded to, and never committed — the data folder
    is outside the repository and the name is git-ignored.
    """
    source = Path(source)
    load_client_config(source)  # refuse anything that is not a Desktop-app client
    target = google_client_secret_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return target


def vault_profile_id(session: VaultSession) -> str | None:
    """Which profile a session's file belongs to: <data>/profiles/<id>/vault.kdbx.

    None for a vault opened from anywhere else (tests, an import preview), which
    is the UI's signal that there is no profile to sync.
    """
    folder = session.path.parent
    if folder.parent.name != "profiles" or not folder.name:
        return None
    return folder.name


def review_copy(session: VaultSession, path: str | Path) -> VaultSession:
    """Open a file beside the vault read-only, with the master password in hand.

    This is what "Open both" shows: the kept conflict copy, to read and copy
    from by hand. It is never saved through.
    """
    return session.reopen(path)


def reload_vault(session: VaultSession) -> VaultSession:
    """Reopen the vault file: a sync replaced it with a newer copy from Drive."""
    return session.reopen()


def _merged_message(report: MergeReport) -> str:
    """What a merge did, in one sentence. Counts only: never an entry field."""
    if report.total == 0:
        return "both copies already held the same entries"
    return (
        f"merged {report.updated} changed, {report.added} added and "
        f"{report.deleted} deleted from Drive's copy"
    )


@dataclass(frozen=True)
class SyncReport:
    """What the status line shows: one of the spec's states, and why."""

    status: Status
    message: str
    retry_at: str | None = None
    conflict: dict[str, object] | None = None
    email: str | None = None
    first_link: bool = False  # Drive already holds this profile's vault (ADR-010)


class _AccessToken:
    """The token the Drive client reads, and the refresh a 401 triggers.

    The engine calls neither from the GUI thread, and neither ever raises
    anything but a SyncError: a locked vault means "not connected right now",
    which the engine reports and the status line shows as Sync off.
    """

    def __init__(self, session: VaultSession) -> None:
        self._session = session
        self._token: str | None = None

    def current(self) -> str:
        if self._token is None:
            self._token = _fresh_token(self._session)
        return self._token

    def refresh(self) -> None:
        self._token = _fresh_token(self._session)


def _fresh_token(session: VaultSession) -> str:
    try:
        return google_access_token(session)
    except VaultError as exc:
        raise NotLinked("the vault is locked") from exc


class SyncController:
    """One profile's sync, as the UI works with it.

    It owns the engine and its worker thread; every call here is safe from the
    GUI thread except ``link``, which opens a browser and blocks (the caller
    runs it on a thread of its own). Nothing here touches entry data: syncing
    moves whole files.
    """

    def __init__(
        self,
        session: VaultSession,
        *,
        client_factory: Callable[[Callable[[], str]], DriveClient] | None = None,
        interval_seconds: float | None = None,
        save_delay_seconds: float | None = None,
    ) -> None:
        folder = session.path.parent  # <data>/profiles/<id>/
        self._session = session
        self.profile_id = folder.name
        self._token = _AccessToken(session)
        # resolved here, not as a default argument: tests replace the name
        make_client = HttpDriveClient if client_factory is None else client_factory
        self.engine = SyncEngine(
            client=make_client(self._token.current),
            vault_path=session.path,
            backups_dir=folder / "backups",
            sync_dir=folder / "sync",
            profile_id=folder.name,
            verify_decrypts=session.opens_with_this_password,
            refresh_credentials=self._token.refresh,
        )
        self.worker = SyncWorker(
            self.engine,
            interval_seconds=(
                interval_seconds if interval_seconds is not None else sync_interval_minutes() * 60.0
            ),
            save_delay_seconds=(
                save_delay_seconds
                if save_delay_seconds is not None
                else upload_quiet_seconds() * 1.0
            ),
        )
        self._running = False

    # --- who this profile is ----------------------------------------------

    def account(self) -> GoogleAccount | None:
        """The Drive account this profile is connected as, if any."""
        try:
            return google_account(self._session)
        except VaultError:
            return None  # a vault that is closed is simply not connected any more

    def linked(self) -> bool:
        return self.account() is not None

    @property
    def running(self) -> bool:
        return self._running

    # --- the vault switched under us --------------------------------------

    def reload(self) -> VaultSession:
        """Reopen the vault (a sync adopted a newer copy) and follow it."""
        self._session = reload_vault(self._session)
        return self._session

    def session(self) -> VaultSession:
        """The session this controller follows, as of the last reload."""
        return self._session

    # --- start, stop, link, unlink ----------------------------------------

    def start(self) -> None:
        """Sync while unlocked: the unlock trigger. Does nothing if unlinked."""
        if self._running or not self.linked():
            return
        self.worker.start()
        self._running = True
        self.worker.notify_unlocked()

    def stop(self) -> None:
        """Stop syncing (lock, or unlink). Safe to call twice."""
        if self._running:
            self.worker.stop()
            self._running = False

    def link(self) -> GoogleAccount:
        """Sign in with Google and store the token. Blocking: run it off the GUI thread."""
        return connect_google(self._session)

    def unlink(self) -> None:
        """Forget the account and stop syncing; the vault itself is untouched."""
        self.stop()
        disconnect_google(self._session)

    # --- the triggers ------------------------------------------------------

    def notify_saved(self) -> None:
        if self._running:
            self.worker.notify_saved()

    def notify_online(self) -> None:
        if self._running:
            self.worker.notify_online()

    def sync_now(self) -> None:
        if self._running:
            self.worker.sync_now()

    # --- the owner's conflict choices (M5-05) ------------------------------

    def keep_mine(self) -> SyncResult:
        return self.engine.upload_local()

    def take_theirs(self) -> SyncResult:
        result = self.engine.adopt_remote()
        if result.status is Status.SYNCED:
            # adopting does not put their copy on Drive's head: ask for a run now
            self.sync_now()
        return result

    def merge_both(self) -> SyncResult:
        """Merge Drive's kept copy into this vault, then publish the result.

        Both sides keep what the other changed entry by entry (M6-01). The
        merged file is saved here through storage — atomic, verified, backed up
        — and then uploaded the way "Keep mine" uploads it, which is what ends
        the conflict. Nothing is lost if the upload fails: the merge is on disk,
        the conflict stands, and the next click merges the same copy again.
        """
        kept = self._kept_conflict_copy()
        if kept is None:
            return SyncResult(Status.ATTENTION, "the copy Drive sent is not here any more")
        try:
            theirs = review_copy(self._session, kept)  # read only, never saved through
        except (VaultError, ValueError) as exc:
            return SyncResult(Status.ATTENTION, f"Drive's copy could not be opened: {exc}")
        try:
            report = self._session.merge_from(theirs)
        except (VaultError, ValueError) as exc:
            return SyncResult(Status.ATTENTION, f"the two copies could not be merged: {exc}")
        finally:
            theirs.close()
        result = self.engine.upload_local()
        if result.status is not Status.SYNCED:
            return result
        return SyncResult(Status.SYNCED, _merged_message(report))

    def _kept_conflict_copy(self) -> Path | None:
        """The copy the conflict kept, as the state file recorded it."""
        state = self.engine.state()
        conflict = state.conflict if state is not None else None
        if not conflict:
            return None
        raw = conflict.get("kept_path")
        path = Path(str(raw)) if isinstance(raw, str) and raw else None
        return path if path is not None and path.exists() else None

    # --- what the status line reads ----------------------------------------

    def report(self) -> SyncReport:
        """The state to show, from the link, the last run and state.json."""
        account = self.account()
        if account is None:
            return SyncReport(Status.SYNC_OFF, "not connected to Google Drive")
        email = account.email
        state = self.engine.state()
        if state is not None and state.conflict:
            return SyncReport(
                Status.CONFLICT,
                "this vault and the copy on Drive both changed",
                conflict=state.conflict,
                email=email,
            )
        last = self.worker.last_result
        if last is not None and last.status in {
            Status.OFFLINE,
            Status.RECONNECT,
            Status.UNREADABLE,
            Status.ATTENTION,
        }:
            return SyncReport(
                last.status,
                last.message,
                retry_at=last.retry_at,
                email=email,
                first_link=last.message.startswith(FIRST_LINK_ASK),
            )
        if state is None:
            return SyncReport(Status.WAITING, "waiting for the first sync", email=email)
        if state.local_dirty:
            return SyncReport(Status.WAITING, "a change here is not on Drive yet", email=email)
        return SyncReport(Status.SYNCED, "everything is on Drive", email=email)
