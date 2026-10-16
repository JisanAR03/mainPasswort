"""Doing what ``decide()`` says, with the race closed ([S]).

The three guarantees this module exists for (docs/specs/sync.md, invariants):

* I6 — never upload over a copy we have not seen: the remote checksum is
  re-read immediately before the upload, and the revision list afterwards is
  checked for a write that is not ours. A foreign revision becomes a conflict
  with their bytes kept under ``conflicts/`` — never a silent overwrite.
* I7 — never adopt a file until it decrypts: a download is written to
  ``incoming/``, opened with the master password, and only then offered to
  ``storage`` for an atomic, backed-up replacement.
* I10 — Drive only ever receives the exact bytes of the local file, hashed by
  the same read that sends them, and only after that file verified.

The engine takes encrypted bytes and a token supplier: it never opens the
vault, never sees an entry and never sees a password (only "does this file
open", delegated to the caller's ``verify_decrypts``). A failure that is worth
retrying is retried on the schedule sync.md fixes; a 401 refreshes the token
once, and never in a loop.
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from personal_vault.core import storage
from personal_vault.core.errors import VaultError
from personal_vault.sync.decide import Action, LocalState, RemoteState, decide
from personal_vault.sync.digests import file_digests, md5_hex
from personal_vault.sync.drive_client import DriveClient, RemoteFile, Revision
from personal_vault.sync.errors import (
    AuthExpired,
    ReconnectRequired,
    RemoteMissing,
    RemoteUnreadable,
    RetryableSyncError,
    SyncError,
)
from personal_vault.sync.state import SyncState, load_state, save_state

VAULT_NAME = "vault.kdbx"
VAULT_FOLDER = "PersonalVault"
# sync.md: 30s, then doubling to the cap of 30 minutes, plus jitter
BACKOFF_SECONDS = (30, 60, 120, 240, 480, 960, 1800)
JITTER_FRACTION = 0.2

_RECONNECT = "Google no longer accepts this profile's sign-in: connect again"
_RETRYING = "Google Drive is not reachable right now; trying again later"
_CONFLICT = "both copies changed since the last sync"
_UNREADABLE = "the copy on Google Drive could not be read; nothing was adopted"
_ASK_MISSING = "the vault on Google Drive is missing or in the bin"
# the first link's question, and the message the status line recognises
FIRST_LINK_ASK = "a vault for this profile is already on Google Drive"


class Status(Enum):
    """What the UI shows (sync.md: the status line, M5-06)."""

    SYNCED = "synced"
    WAITING = "waiting"  # a local change is not on Drive yet
    OFFLINE = "offline"  # retrying, at the time retry_at gives
    CONFLICT = "conflict"
    UNREADABLE = "unreadable"
    RECONNECT = "reconnect"
    ATTENTION = "attention"  # the owner has to decide something
    BUSY = "busy"  # another sync is running: this request was folded into it
    SYNC_OFF = "off"  # not connected: nothing to sync with (the UI's sixth state)


@dataclass(frozen=True)
class SyncResult:
    """One run's outcome: a status, a sentence for the UI, and nothing secret."""

    status: Status
    message: str
    retry_at: str | None = None  # ISO, wall clock, for the status line
    retry_in_seconds: float | None = None  # the same, for the worker's timer
    adopted: bool = False  # the vault file on disk was replaced: reload the session
    error: str | None = None  # the SyncError code, for the UI's own wording


def backoff_seconds(attempt: int, *, jitter: float = 0.0) -> float:
    """The delay before attempt number ``attempt`` (0 is the first retry)."""
    base = BACKOFF_SECONDS[min(max(attempt, 0), len(BACKOFF_SECONDS) - 1)]
    return base * (1.0 + JITTER_FRACTION * jitter)


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class SyncEngine:
    """One profile's sync: the file on this disk, and the file on Drive."""

    def __init__(
        self,
        *,
        client: DriveClient,
        vault_path: Path,
        backups_dir: Path,
        sync_dir: Path,
        profile_id: str,
        verify_decrypts: Callable[[Path], bool],
        refresh_credentials: Callable[[], None],
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.client = client
        self.vault_path = Path(vault_path)
        self.backups_dir = Path(backups_dir)
        self.sync_dir = Path(sync_dir)
        self.profile_id = profile_id
        self.verify_decrypts = verify_decrypts
        # The engine never mints a token; it asks for a fresh one when Drive
        # says the current one is stale (one retry, then it gives up)
        self._refresh_credentials = refresh_credentials
        # jitter only spreads retries out, but there is no reason to draw it
        # from a generator bandit has to warn about
        self._jitter = jitter or (lambda: random.SystemRandom().uniform(-1.0, 1.0))
        self._lock = threading.Lock()
        self._attempts = 0

    # --- little things the UI and the tests look at -------------------------

    @property
    def attempts(self) -> int:
        """How many retries in a row have failed (0 means the last run worked)."""
        return self._attempts

    @property
    def state_path(self) -> Path:
        return self.sync_dir / "state.json"

    def state(self) -> SyncState | None:
        return load_state(self.state_path)

    def mark_saved(self) -> None:
        """The UI saved the vault: the next run has something to upload."""
        state = self.state()
        if state is not None:
            self._save(replace(state, local_dirty=True))

    # --- the runs -----------------------------------------------------------

    def run_once(self) -> SyncResult:
        """One sync, start to finish. Never overlaps another."""
        if not self._lock.acquire(blocking=False):
            return SyncResult(Status.BUSY, "a sync is already running")
        try:
            return self._guarded(self._sync)
        finally:
            self._lock.release()

    def adopt_remote(self) -> SyncResult:
        """ADR-010, "take that one": replace this file with the Drive copy."""
        return self._one_at_a_time(self._adopt_remote)

    def upload_local(self) -> SyncResult:
        """ADR-010, "keep this one": put this file on Drive over the old one."""
        return self._one_at_a_time(self._upload_local)

    def _one_at_a_time(self, run: Callable[[], SyncResult]) -> SyncResult:
        if not self._lock.acquire(blocking=False):
            return SyncResult(Status.BUSY, "a sync is already running")
        try:
            return self._guarded(run)
        finally:
            self._lock.release()

    def _guarded(self, run: Callable[[], SyncResult]) -> SyncResult:
        """Run, refreshing a stale token once, and turn failures into statuses."""
        try:
            try:
                result = run()
            except AuthExpired:
                self._refresh_credentials()  # raises if the sign-in is gone
                result = run()
        except (AuthExpired, ReconnectRequired) as exc:
            self._attempts = 0
            return SyncResult(Status.RECONNECT, _RECONNECT, error=exc.code)
        except RetryableSyncError as exc:
            return self._retry_later(exc)
        except SyncError as exc:
            return SyncResult(Status.ATTENTION, str(exc), error=exc.code)
        self._attempts = 0
        return result

    def _retry_later(self, exc: SyncError) -> SyncResult:
        delay = backoff_seconds(self._attempts, jitter=self._jitter())
        self._attempts += 1
        retry_at = _now() + timedelta(seconds=delay)
        state = self.state()
        if state is not None:
            self._save(replace(state, last_error=exc.code))
        return SyncResult(
            Status.OFFLINE,
            _RETRYING,
            retry_at=_stamp(retry_at),
            retry_in_seconds=delay,
            error=exc.code,
        )

    # --- the decision table, carried out ------------------------------------

    def _sync(self) -> SyncResult:
        state = self.state()
        local = self._local_state(state)
        if not local.exists:
            return SyncResult(Status.ATTENTION, "the vault file could not be read")
        remote = self._remote_file(state)
        action = decide(local, _remote_state(remote), state)
        if action is Action.NOTHING:
            if state is not None and state.last_error is not None:
                self._save(replace(state, last_error=None))
            return SyncResult(Status.SYNCED, "Synced")
        if action is Action.UPLOAD:
            return self._upload(local, remote, state)
        if remote is None:
            # every other action works on a copy, and decide() only chose one
            # when there was one: anything else is the missing-file ask
            return SyncResult(Status.ATTENTION, _ASK_MISSING)
        if action is Action.UPDATE_STATE:
            self._record(state, remote, local_sha256=local.sha256, local_md5=local.md5)
            return SyncResult(Status.SYNCED, "Synced")
        if action is Action.DOWNLOAD:
            return self._download(remote, state)
        if action is Action.CONFLICT:
            return self._conflict(remote, state)
        if action is Action.ASK_FIRST_LINK:
            return SyncResult(
                Status.ATTENTION,
                f"{FIRST_LINK_ASK}: keep this device's copy, or take that one",
            )
        return SyncResult(Status.ATTENTION, _ASK_MISSING)

    def _adopt_remote(self) -> SyncResult:
        """Take theirs: the copy the banner showed, downloaded if need be."""
        state = self.state()
        kept = self._kept_conflict_copy(state)
        if kept is not None:
            return self._adopt_kept_copy(kept, state)
        remote = self._remote_file(state)
        if remote is None or remote.trashed:
            return SyncResult(Status.ATTENTION, _ASK_MISSING)
        return self._download(remote, state)

    def _adopt_kept_copy(self, kept: Path, state: SyncState | None) -> SyncResult:
        """Adopt the conflict copy already on this disk.

        Drive's head may be our own upload (we wrote, then found their
        revision), so downloading it would hand back our file and quietly drop
        theirs. Their copy is what the owner was shown, so it is what they get;
        the next run publishes it, which is how their version wins on Drive.
        """
        try:
            data = kept.read_bytes()
        except OSError:
            return SyncResult(Status.ATTENTION, "the kept copy could not be read")
        if not self.verify_decrypts(kept):
            return SyncResult(Status.UNREADABLE, _UNREADABLE)
        storage.backup_current(self.vault_path, self.backups_dir)
        storage.atomic_write(self.vault_path, _write_bytes(data), verifier=self._require_decrypts)
        head = self._remote_file(state)  # what Drive holds now, so it is no surprise later
        base = state or SyncState()
        sha256, _ = _digests(data)
        self._save(
            replace(
                base,
                last_synced_remote_md5=(
                    head.md5 if head is not None else base.last_synced_remote_md5
                ),
                last_synced_remote_version=(
                    head.version if head is not None else base.last_synced_remote_version
                ),
                last_synced_local_sha256=sha256,
                local_dirty=True,  # their copy still has to go up to Drive
                last_error=None,
                conflict=None,
            )
        )
        return SyncResult(
            Status.SYNCED, "their copy is this device's copy now", adopted=True, error=None
        )

    def _kept_conflict_copy(self, state: SyncState | None) -> Path | None:
        """The copy a conflict put in ``conflicts/``, when there is one on disk."""
        if state is None or not state.conflict:
            return None
        raw = state.conflict.get("kept_path")
        if not isinstance(raw, str) or not raw:
            return None
        path = Path(raw)
        return path if path.exists() else None

    def _upload_local(self) -> SyncResult:
        state = self.state()
        local = self._local_state(state)
        if not local.exists:
            return SyncResult(Status.ATTENTION, "the vault file could not be read")
        return self._upload(local, self._remote_file(state), state, overwrite=True)

    # --- upload (I6, I10) ---------------------------------------------------

    def _upload(
        self,
        local: LocalState,
        seen: RemoteFile | None,
        state: SyncState | None,
        *,
        overwrite: bool = False,
    ) -> SyncResult:
        """Send this device's file to Drive, and never over a copy we have not seen."""
        try:
            data = self.vault_path.read_bytes()
        except OSError:
            return SyncResult(Status.ATTENTION, "the vault file could not be read")
        digest = _digests(data)
        if digest != (local.sha256, local.md5):
            # the file moved under us: the next run decides again from scratch
            return SyncResult(Status.WAITING, "the vault changed while syncing; trying again")

        current = seen
        if seen is not None and not overwrite:
            current = self.client.metadata(seen.id)  # immediately before uploading
            if (
                state is not None
                and state.last_synced_remote_md5 is not None
                and current.md5 != state.last_synced_remote_md5
            ):
                return self._conflict(current, state)

        if not self.verify_decrypts(self.vault_path):
            # I10: the file storage verified is the only thing Drive may receive
            return SyncResult(Status.WAITING, "the vault did not verify; nothing was sent")

        folder_id = self._ensure_folder(state)
        uploaded = self.client.upload(
            file_id=current.id if current is not None else None,
            name=VAULT_NAME,
            parent_id=folder_id,
            data=data,
            profile_id=self.profile_id,
        )
        foreign = self._foreign_revision(uploaded, current)
        if foreign is not None:
            # somebody wrote while we were uploading: their copy is kept and the
            # owner decides, and their revision is still in Drive's history
            return self._conflict(uploaded, state, revision=foreign, folder_id=folder_id)

        self._record(
            state,
            uploaded,
            local_sha256=digest[0],
            local_md5=digest[1],
            folder_id=folder_id,
        )
        return SyncResult(Status.SYNCED, "Synced")

    def _foreign_revision(self, uploaded: RemoteFile, seen: RemoteFile | None) -> Revision | None:
        """A revision newer than ours that we did not write, if there is one."""
        if seen is None or not seen.head_revision_id:
            return None
        revisions = self.client.list_revisions(uploaded.id)  # newest first
        ids = [revision.id for revision in revisions]
        if seen.head_revision_id not in ids:
            return None  # history pruned: nothing to compare, and nothing to claim
        ours = {uploaded.head_revision_id}
        newer = [r for r in revisions[: ids.index(seen.head_revision_id)] if r.id not in ours]
        return newer[0] if newer else None  # the newest write that is not ours

    # --- download and adoption (I7) -----------------------------------------

    def _download(self, remote: RemoteFile, state: SyncState | None) -> SyncResult:
        try:
            data = self.client.download(remote.id, expect_md5=remote.md5)
        except RemoteUnreadable:
            return SyncResult(Status.UNREADABLE, _UNREADABLE)

        incoming = self.sync_dir / "incoming" / VAULT_NAME
        incoming.parent.mkdir(parents=True, exist_ok=True)
        storage.atomic_write(incoming, _write_bytes(data))
        if not self.verify_decrypts(incoming):
            # I7: it stays in incoming/ for the owner to look at, and never
            # replaces a vault this device can open
            return SyncResult(Status.UNREADABLE, _UNREADABLE)

        storage.backup_current(self.vault_path, self.backups_dir)
        storage.atomic_write(self.vault_path, _write_bytes(data), verifier=self._require_decrypts)
        sha256, md5 = _digests(data)
        self._record(state, remote, local_sha256=sha256, local_md5=md5)
        return SyncResult(Status.SYNCED, "Synced from Google Drive", adopted=True)

    def _require_decrypts(self, path: Path) -> None:
        """The verifier storage wants: raise rather than rename a bad file."""
        if not self.verify_decrypts(path):
            raise VaultError("the downloaded vault did not verify")

    # --- conflict -----------------------------------------------------------

    def _conflict(
        self,
        remote: RemoteFile,
        state: SyncState | None,
        *,
        revision: Revision | None = None,
        folder_id: str | None = None,
    ) -> SyncResult:
        """Keep their copy, change nothing locally, and say so."""
        if revision is not None:
            theirs = self.client.download_revision(remote.id, revision.id)
        else:
            theirs = self.client.download(remote.id, expect_md5=remote.md5)
        kept = self._keep_conflict_copy(theirs)
        base = state or SyncState()
        self._save(
            replace(
                base,
                drive_file_id=remote.id,
                drive_folder_id=folder_id or base.drive_folder_id or remote.parent_id,
                last_error="conflict",
                conflict={
                    "detected_at": _stamp(_now()),
                    "remote_version": remote.version,
                    "remote_md5": remote.md5,
                    "kept_path": str(kept),
                },
            )
        )
        return SyncResult(Status.CONFLICT, _CONFLICT, error="conflict")

    def _keep_conflict_copy(self, data: bytes) -> Path:
        folder = self.sync_dir / "conflicts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"vault-{_now().strftime('%Y%m%dT%H%M%SZ')}.kdbx"
        index = 0
        while path.exists():  # never write over a copy somebody may still need
            index += 1
            path = folder / f"vault-{_now().strftime('%Y%m%dT%H%M%SZ')}-{index}.kdbx"
        storage.atomic_write(path, _write_bytes(data))
        return path

    # --- what this device knows about the two files -------------------------

    def _local_state(self, state: SyncState | None) -> LocalState:
        if not self.vault_path.exists():
            return LocalState(exists=False, sha256=None, md5=None, dirty=False)
        try:
            sha256, md5 = file_digests(self.vault_path)
        except OSError:
            return LocalState(exists=False, sha256=None, md5=None, dirty=False)
        return LocalState(
            exists=True, sha256=sha256, md5=md5, dirty=bool(state and state.local_dirty)
        )

    def _remote_file(self, state: SyncState | None) -> RemoteFile | None:
        """The Drive file for this profile, as the API reports it right now."""
        if state is not None and state.drive_file_id:
            try:
                return self.client.metadata(state.drive_file_id)
            except RemoteMissing:
                return None  # deleted or moved: decide() will ask, not recreate
        return self.client.find_vault_file(self.profile_id)

    def _ensure_folder(self, state: SyncState | None) -> str:
        if state is not None and state.drive_folder_id:
            return state.drive_folder_id
        return self.client.ensure_folder(VAULT_FOLDER)

    def _record(
        self,
        state: SyncState | None,
        remote: RemoteFile,
        *,
        local_sha256: str | None,
        local_md5: str | None,
        folder_id: str | None = None,
    ) -> None:
        """Both files agree again: write down the versions we saw."""
        base = state or SyncState()
        self._save(
            replace(
                base,
                drive_file_id=remote.id,
                drive_folder_id=folder_id or base.drive_folder_id or remote.parent_id,
                last_synced_remote_md5=remote.md5,
                last_synced_remote_version=remote.version,
                last_synced_local_sha256=local_sha256,
                local_dirty=False,
                last_success_at=_stamp(_now()),
                last_error=None,
                conflict=None,
            )
        )

    def _save(self, state: SyncState) -> None:
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        save_state(self.state_path, state)


def _write_bytes(data: bytes) -> Callable[[Path], None]:
    """A storage writer for bytes we already hold in memory."""

    def write(tmp: Path) -> None:
        tmp.write_bytes(data)

    return write


def _digests(data: bytes) -> tuple[str, str]:
    """(sha256, md5) of the bytes we are actually about to send."""
    return hashlib.sha256(data).hexdigest(), md5_hex(data)


def _remote_state(remote: RemoteFile | None) -> RemoteState:
    if remote is None:
        return RemoteState(exists=False, trashed=False, md5=None, version=None)
    if remote.trashed:
        return RemoteState(exists=False, trashed=True, md5=remote.md5, version=remote.version)
    return RemoteState(exists=True, trashed=False, md5=remote.md5, version=remote.version)


class SyncWorker:
    """The triggers sync.md lists, on one background thread, one run at a time.

    ``notify_saved`` waits a moment so a burst of saves is one sync; every
    other trigger runs now. A run that failed says when the next try is
    allowed, and nothing runs before then.
    """

    def __init__(
        self,
        engine: SyncEngine,
        *,
        interval_seconds: float = 3600.0,
        save_delay_seconds: float = 10.0,
    ) -> None:
        self._engine = engine
        self._interval = interval_seconds
        self._save_delay = save_delay_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._timing = threading.Lock()
        self._run_at: float | None = None
        self._thread: threading.Thread | None = None
        self.last_result: SyncResult | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="vault-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def notify_unlocked(self) -> None:
        self._schedule(0.0)

    def notify_online(self) -> None:
        self._schedule(0.0)

    def sync_now(self) -> None:
        self._schedule(0.0)

    def notify_saved(self) -> None:
        """A save just happened: wait for the owner to stop typing."""
        self._schedule(self._save_delay)

    def _schedule(self, delay: float) -> None:
        with self._timing:
            when = time.monotonic() + delay
            if self._run_at is None or when < self._run_at:
                self._run_at = when
        self._wake.set()

    def _due(self) -> float | None:
        with self._timing:
            return self._run_at

    def _loop(self) -> None:
        next_interval = time.monotonic() + self._interval
        while not self._stop.is_set():
            now = time.monotonic()
            when = self._due()
            wake_at = min(t for t in (when, next_interval) if t is not None)
            self._wake.clear()
            self._wake.wait(timeout=max(0.0, wake_at - now))
            if self._stop.is_set():
                break
            now = time.monotonic()
            with self._timing:
                requested = self._run_at is not None and self._run_at <= now
                if requested:
                    self._run_at = None
            on_time = next_interval <= now
            if on_time:
                next_interval = now + self._interval
            if not (requested or on_time):
                continue  # a trigger that arrived and was folded into a run
            self.last_result = self._engine.run_once()
            if self.last_result.retry_in_seconds is not None:
                self._schedule(self.last_result.retry_in_seconds)
