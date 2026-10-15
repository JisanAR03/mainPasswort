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
import uuid
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
from personal_vault.core.vault import VaultSession, open_vault  # noqa: F401 (re-export)

# Re-exported so ui/ can use these types without importing core/ directly.
__all__ = [
    "InvalidPassword",
    "LoginEntry",
    "LoginSummary",
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
    "export_csv",
    "generate_password",
    "generator_defaults",
    "get_login",
    "idle_lock_minutes",
    "import_csv",
    "import_kdbx",
    "list_backups",
    "list_logins",
    "lock_on_sleep",
    "open_profile_vault",
    "open_vault",
    "profile_vault_dir",
    "profiles",
    "restore_backup",
    "save_vault",
    "search_logins",
    "settings_readonly",
    "settings_values",
    "update_login",
    "update_settings",
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
