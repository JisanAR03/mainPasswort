"""The sync decision table as one pure function ([S]).

``decide(local, remote, state) -> Action`` has no network, no disk and no
clock, so every row of docs/specs/sync.md is a small test, and invariant I6 is
decided here: an upload is only ever chosen for a remote version the state has
already seen. Doing what it says is engine.py's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from personal_vault.sync.state import SyncState


class Action(Enum):
    NOTHING = "nothing"
    UPDATE_STATE = "update_state"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    CONFLICT = "conflict"
    ASK = "ask"  # the remote copy is missing or trashed: never recreate silently
    ASK_FIRST_LINK = "ask_first_link"  # ADR-010: a file is on Drive, this device has no state


@dataclass(frozen=True)
class LocalState:
    """The vault file as it is on this disk right now."""

    exists: bool
    sha256: str | None
    md5: str | None
    dirty: bool  # saved since the last successful sync


@dataclass(frozen=True)
class RemoteState:
    """The Drive file as the API just reported it."""

    exists: bool
    trashed: bool
    md5: str | None
    version: int | None


def _local_changed(local: LocalState, state: SyncState) -> bool:
    return local.dirty or local.sha256 != state.last_synced_local_sha256


def _remote_changed(remote: RemoteState, state: SyncState) -> bool:
    return remote.md5 != state.last_synced_remote_md5


def decide(local: LocalState, remote: RemoteState, state: SyncState | None) -> Action:
    """What to do next, per the table in docs/specs/sync.md."""
    if not local.exists:
        return Action.ASK  # the vault cannot be read: never upload, never adopt

    if state is None:
        # ADR-010: a file is already there and we have no history — the owner
        # chooses; a trashed one is still "there", so it asks rather than
        # recreating a file somebody deleted on purpose
        if remote.exists or remote.trashed:
            return Action.ASK_FIRST_LINK
        return Action.UPLOAD

    if not remote.exists or remote.trashed:
        return Action.ASK

    if local.md5 is not None and local.md5 == remote.md5:
        # same bytes on both sides, whatever changed to get there
        if _local_changed(local, state) or _remote_changed(remote, state):
            return Action.UPDATE_STATE
        return Action.NOTHING

    local_changed = _local_changed(local, state)
    remote_changed = _remote_changed(remote, state)
    if local_changed and remote_changed:
        return Action.CONFLICT
    if local_changed:
        return Action.UPLOAD
    if remote_changed:
        return Action.DOWNLOAD
    return Action.NOTHING
