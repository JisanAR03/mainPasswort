"""App settings: settings.json with defaults and schema versioning.

No secrets live here. A file with a newer schema_version than this app
understands loads read-only and is never overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path

from personal_vault.core import storage
from personal_vault.core.errors import SchemaTooNewError

SCHEMA_VERSION = 1

DEFAULTS: dict[str, object] = {
    "idle_lock_minutes": 5,
    "lock_on_sleep": True,
    "clipboard_clear_seconds": 30,
    "backups_keep_recent": 20,
    "backups_keep_daily": 30,
    "sync_interval_minutes": 60,
    "upload_quiet_seconds": 10,
    "generator": {
        "length": 20,
        "upper": True,
        "lower": True,
        "digits": True,
        "symbols": True,
        "exclude_lookalikes": True,
    },
}

_INT_KEYS = {
    "idle_lock_minutes",
    "clipboard_clear_seconds",
    "backups_keep_recent",
    "backups_keep_daily",
    "sync_interval_minutes",
    "upload_quiet_seconds",
}
_BOOL_KEYS = {"lock_on_sleep"}


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "settings.json"
        self._readonly = False

    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._readonly = False
            return
        version = raw.get("schema_version", SCHEMA_VERSION)
        self._readonly = bool(isinstance(version, int) and version > SCHEMA_VERSION)

    def _read(self) -> dict[str, object]:
        try:
            raw: dict[str, object] = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        return raw

    def _ensure_writable(self) -> None:
        if self._readonly:
            raise SchemaTooNewError("settings.json has a newer schema_version; opened read-only")

    def get(self, key: str) -> object:
        if key not in DEFAULTS:
            raise KeyError(key)
        raw = self._read()
        if key in raw:
            return raw[key]
        default = DEFAULTS[key]
        return dict(default) if isinstance(default, dict) else default

    def set(self, key: str, value: object) -> None:
        self._ensure_writable()
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        if key in _INT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        else:  # generator
            if not isinstance(value, dict):
                raise ValueError("generator must be a dict")
            length = value.get("length")
            if not isinstance(length, int) or not 4 <= length <= 4096:
                raise ValueError("generator.length must be an integer from 4 to 4096")
            for flag in ("upper", "lower", "digits", "symbols", "exclude_lookalikes"):
                if not isinstance(value.get(flag), bool):
                    raise ValueError(f"generator.{flag} must be a boolean")
        raw = self._read()
        raw[key] = value
        raw["schema_version"] = SCHEMA_VERSION
        self._write(raw)

    def _write(self, raw: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        storage.atomic_write_json(self._path, raw)
