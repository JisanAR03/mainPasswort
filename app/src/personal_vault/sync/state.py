"""sync/state.json: what this device last saw on both sides ([S]-adjacent).

Bookkeeping only — no secrets, no vault contents (data-model.md). The file
lives at ``<profile>/sync/state.json`` and is written atomically, like every
other JSON file in the app. A file from a newer app is refused rather than
rewritten, so an older build can never damage a newer one's sync history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from personal_vault.core import storage
from personal_vault.core.errors import SchemaTooNewError

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SyncState:
    """The last synced versions. ``None`` means "not recorded yet"."""

    drive_folder_id: str | None = None
    drive_file_id: str | None = None
    last_synced_remote_version: int | None = None
    last_synced_remote_md5: str | None = None
    last_synced_local_sha256: str | None = None
    local_dirty: bool = False
    last_success_at: str | None = None
    last_error: str | None = None
    conflict: dict[str, object] | None = None
    linked_from: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "drive_folder_id": self.drive_folder_id,
            "drive_file_id": self.drive_file_id,
            "last_synced_remote_version": self.last_synced_remote_version,
            "last_synced_remote_md5": self.last_synced_remote_md5,
            "last_synced_local_sha256": self.last_synced_local_sha256,
            "local_dirty": self.local_dirty,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "conflict": self.conflict,
            "linked_from": self.linked_from,
        }


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def from_json(raw: dict[str, object]) -> SyncState:
    """Read the fields we understand; anything malformed reads as unset."""
    version = raw.get("schema_version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise SchemaTooNewError("sync state was written by a newer version of this app")
    remote_version = raw.get("last_synced_remote_version")
    conflict = raw.get("conflict")
    return SyncState(
        drive_folder_id=_text(raw.get("drive_folder_id")),
        drive_file_id=_text(raw.get("drive_file_id")),
        last_synced_remote_version=remote_version if isinstance(remote_version, int) else None,
        last_synced_remote_md5=_text(raw.get("last_synced_remote_md5")),
        last_synced_local_sha256=_text(raw.get("last_synced_local_sha256")),
        local_dirty=raw.get("local_dirty") is True,
        last_success_at=_text(raw.get("last_success_at")),
        last_error=_text(raw.get("last_error")),
        conflict=dict(conflict) if isinstance(conflict, dict) else None,
        linked_from=_text(raw.get("linked_from")),
    )


def load_state(path: str | Path) -> SyncState | None:
    """The stored state, or None when there is none we can use.

    A missing, unreadable or damaged file reads as None, which is the
    first-time-link flow (ADR-010); a newer schema raises instead, because
    this build must not touch it.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return from_json(raw)


def save_state(path: str | Path, state: SyncState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_json(path, state.to_json())
