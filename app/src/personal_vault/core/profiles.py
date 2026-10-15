"""Profile list: profiles.json with schema versioning.

No secrets live here. A file with a newer schema_version than this app
understands loads read-only and is never overwritten.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from personal_vault.core import storage
from personal_vault.core.errors import SchemaTooNewError

SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 100


class _ProfileItem(TypedDict):
    id: str
    display_name: str
    created_at: str
    sync_enabled: bool


class _ProfilesFile(TypedDict):
    schema_version: int
    last_used_profile_id: str | None
    profiles: list[_ProfileItem]


@dataclass(frozen=True)
class Profile:
    id: str
    display_name: str
    created_at: str
    sync_enabled: bool


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_profile_id() -> str:
    return "p_" + secrets.token_urlsafe(6)


class ProfileStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "profiles.json"
        self._readonly = False

    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._readonly = False
            return
        version = raw.get("schema_version", SCHEMA_VERSION)
        self._readonly = bool(isinstance(version, int) and version > SCHEMA_VERSION)

    def _read(self) -> _ProfilesFile:
        try:
            raw: _ProfilesFile = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "schema_version": SCHEMA_VERSION,
                "last_used_profile_id": None,
                "profiles": [],
            }
        return raw

    def _ensure_writable(self) -> None:
        if self._readonly:
            raise SchemaTooNewError("profiles.json has a newer schema_version; opened read-only")

    def list(self) -> list[Profile]:
        raw = self._read()
        return [
            Profile(
                id=item["id"],
                display_name=item["display_name"],
                created_at=item["created_at"],
                sync_enabled=item["sync_enabled"],
            )
            for item in raw["profiles"]
        ]

    def last_used(self) -> str | None:
        value = self._read().get("last_used_profile_id")
        return str(value) if value else None

    def create(self, display_name: str) -> Profile:
        self._ensure_writable()
        name = display_name.strip()
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f"display name must be 1-{MAX_NAME_LENGTH} characters")
        raw = self._read()
        existing_ids = {item["id"] for item in raw["profiles"]}
        profile_id = _new_profile_id()
        while profile_id in existing_ids:
            profile_id = _new_profile_id()
        item: _ProfileItem = {
            "id": profile_id,
            "display_name": name,
            "created_at": _now_iso(),
            "sync_enabled": False,
        }
        raw["profiles"] = [*raw["profiles"], item]
        self._write(raw)
        return Profile(
            id=item["id"],
            display_name=item["display_name"],
            created_at=item["created_at"],
            sync_enabled=item["sync_enabled"],
        )

    def rename(self, profile_id: str, display_name: str) -> None:
        self._ensure_writable()
        name = display_name.strip()
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f"display name must be 1-{MAX_NAME_LENGTH} characters")
        raw = self._read()
        for item in raw["profiles"]:
            if item["id"] == profile_id:
                item["display_name"] = name
                break
        else:
            raise KeyError(profile_id)
        self._write(raw)

    def delete(self, profile_id: str) -> None:
        self._ensure_writable()
        raw = self._read()
        raw["profiles"] = [p for p in raw["profiles"] if p["id"] != profile_id]
        if raw.get("last_used_profile_id") == profile_id:
            raw["last_used_profile_id"] = None
        self._write(raw)

    def set_last_used(self, profile_id: str) -> None:
        self._ensure_writable()
        raw = self._read()
        if not any(p["id"] == profile_id for p in raw["profiles"]):
            raise KeyError(profile_id)
        raw["last_used_profile_id"] = profile_id
        self._write(raw)

    def _write(self, raw: _ProfilesFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        storage.atomic_write_json(self._path, raw)
