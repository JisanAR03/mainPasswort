"""M5-04: what the engine does with each decision, and how it fails."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.models import SecretStr
from personal_vault.core.vault import VaultSession, open_vault
from personal_vault.sync.engine import (
    BACKOFF_SECONDS,
    Status,
    SyncEngine,
    SyncWorker,
    backoff_seconds,
)
from personal_vault.sync.errors import AuthExpired, ReconnectRequired, ServerError
from personal_vault.sync.fake_drive import FakeDrive
from personal_vault.sync.state import SyncState, load_state

pytestmark = pytest.mark.sync

PROFILE = "9f2c1d3e4b5a69788796a5b4c3d2e1f0"
VAULT_NAME = "vault.kdbx"
MARKER = "correct horse battery staple"


def _verifier(password: str = WEAK_PASSWORD):
    """Does this file open with the master password? (The engine only wants a yes.)"""

    def verify(path: Path) -> bool:
        try:
            open_vault(path, password)
        except Exception:
            return False
        return True

    return verify


class _Home:
    """One profile: a real vault file, a sync folder and a fake Drive."""

    def __init__(self, tmp_path: Path, *, linked: bool = True) -> None:
        self.tmp_path = tmp_path
        self.vault_path = build_weak_vault(tmp_path / VAULT_NAME)
        self.backups_dir = tmp_path / "backups"
        self.sync_dir = tmp_path / "sync"
        self.fake = FakeDrive()
        self.refreshes = 0
        self.engine = SyncEngine(
            client=self.fake,
            vault_path=self.vault_path,
            backups_dir=self.backups_dir,
            sync_dir=self.sync_dir,
            profile_id=PROFILE,
            verify_decrypts=_verifier(),
            refresh_credentials=self._refresh,
        )
        if linked:
            self.link()

    def _refresh(self) -> None:
        self.refreshes += 1

    def link(self) -> None:
        """A profile that is already synced once: state.json describes that run."""
        result = self.engine.run_once()  # first link with an empty Drive: uploads
        assert result.status is Status.SYNCED

    # -- what the tests do to the world ---------------------------------

    def edit_locally(self) -> None:
        """Save a change in the vault, the way the UI does (and say so)."""
        session = VaultSession.open(self.vault_path, WEAK_PASSWORD, self.backups_dir)
        try:
            session.add(
                make_login(
                    title="New Site",
                    username="new@example.com",
                    password=SecretStr(MARKER),  # so the canary below has something to find
                )
            )
            session.save()
        finally:
            session.close()
        self.engine.mark_saved()

    def state(self) -> SyncState:
        loaded = load_state(self.sync_dir / "state.json")
        assert loaded is not None, "the engine should have written state.json"
        return loaded

    def conflicts(self) -> list[Path]:
        return sorted((self.sync_dir / "conflicts").glob("*.kdbx"))

    def incoming(self) -> list[Path]:
        return sorted((self.sync_dir / "incoming").glob("*.kdbx"))


@pytest.fixture
def home(tmp_path: Path) -> _Home:
    return _Home(tmp_path)


# --- the happy paths -------------------------------------------------------


def test_the_first_link_to_an_empty_drive_uploads(home: _Home) -> None:
    assert home.fake.find_vault_file(PROFILE) is not None
    state = home.state()
    assert state.last_synced_remote_md5
    assert state.local_dirty is False
    assert state.conflict is None


def test_a_second_run_with_nothing_changed_does_nothing(home: _Home) -> None:
    before = home.fake.calls.copy()
    result = home.engine.run_once()
    assert result.status is Status.SYNCED
    assert "upload" not in home.fake.calls[len(before) :]


def test_an_offline_edit_uploads_itself_when_the_network_returns(home: _Home) -> None:
    home.edit_locally()
    result = home.engine.run_once()
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    assert result.status is Status.SYNCED
    assert home.fake.stored_bytes(file_id.id) == home.vault_path.read_bytes()
    assert home.state().local_dirty is False


def test_the_uploaded_bytes_are_the_bytes_on_disk(home: _Home) -> None:
    home.edit_locally()
    before = home.vault_path.read_bytes()
    home.engine.run_once()
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    uploaded = home.fake.stored_bytes(file_id.id)
    assert uploaded == before  # exactly, byte for byte
    assert home.state().last_synced_local_sha256 == hashlib.sha256(uploaded).hexdigest()


def test_the_uploaded_bytes_never_hold_a_password_in_the_clear(home: _Home) -> None:
    home.edit_locally()
    home.engine.run_once()
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    assert MARKER.encode() not in home.fake.stored_bytes(file_id.id)


def test_a_remote_change_is_downloaded_and_adopted(home: _Home) -> None:
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE)

    result = home.engine.run_once()

    assert result.status is Status.SYNCED
    assert result.adopted is True  # the UI has to reload the vault
    assert home.vault_path.read_bytes() == theirs.read_bytes()
    assert home.incoming()  # the downloaded copy is kept
    backups = sorted(home.backups_dir.glob("vault-*.kdbx"))
    assert backups, "the old vault must be backed up before adopting"
    assert [p.name for p in home.tmp_path.glob("*.tmp")] == []  # no half-written file


# --- the race, and I6 ------------------------------------------------------


def test_a_write_between_the_check_and_the_upload_is_a_conflict(home: _Home) -> None:
    """Another device writes after our checksum check but before our upload."""
    home.edit_locally()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.before["upload"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE
    )

    result = home.engine.run_once()

    assert result.status is Status.CONFLICT
    assert home.conflicts(), "their copy must be kept in conflicts/"
    assert home.conflicts()[0].read_bytes() == theirs.read_bytes()
    assert home.vault_path.read_bytes() != theirs.read_bytes()  # we did not adopt it silently


def test_a_write_before_the_pre_upload_check_uploads_nothing(home: _Home) -> None:
    home.edit_locally()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.before["metadata"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE
    )
    before = home.fake.calls.copy()

    result = home.engine.run_once()

    assert result.status is Status.CONFLICT
    assert "upload" not in home.fake.calls[len(before) :]  # our edit was never sent
    assert home.conflicts()[0].read_bytes() == theirs.read_bytes()


def test_a_conflict_leaves_a_marker_in_state(home: _Home) -> None:
    home.edit_locally()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.before["upload"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE
    )
    home.engine.run_once()
    conflict = home.state().conflict
    assert conflict is not None
    assert conflict["remote_version"] is not None
    assert conflict["kept_path"]


# --- I7: never adopt what does not decrypt ---------------------------------


def test_a_corrupted_download_is_never_adopted(home: _Home) -> None:
    before = home.vault_path.read_bytes()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE)
    home.fake.corrupt_downloads = True

    result = home.engine.run_once()

    assert result.status is Status.UNREADABLE
    assert home.vault_path.read_bytes() == before  # untouched
    assert not sorted(home.backups_dir.glob("vault-*.kdbx"))  # nothing was adopted at all
    assert not home.incoming()  # the bytes never matched Drive's own checksum: none were kept


def test_a_download_that_does_not_decrypt_is_never_adopted(home: _Home) -> None:
    before = home.vault_path.read_bytes()
    other_password = build_weak_vault(home.tmp_path / "other.kdbx", password="a different password")
    home.fake.write_from_another_device(other_password.read_bytes(), profile_id=PROFILE)

    result = home.engine.run_once()

    assert result.status is Status.UNREADABLE
    assert home.vault_path.read_bytes() == before
    assert home.incoming()


# --- the owner's decisions (ADR-010, and the conflict banner) --------------


def test_the_first_link_to_a_drive_that_already_has_a_vault_asks(tmp_path: Path) -> None:
    home = _Home(tmp_path, linked=False)
    theirs = build_weak_vault(tmp_path / "theirs.kdbx")
    home.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE)
    before = home.vault_path.read_bytes()

    result = home.engine.run_once()

    assert result.status is Status.ATTENTION
    assert home.vault_path.read_bytes() == before  # nothing adopted
    assert "upload" not in home.fake.calls  # and nothing overwritten
    assert load_state(home.sync_dir / "state.json") is None


def test_adopt_remote_is_the_owners_choice(tmp_path: Path) -> None:
    home = _Home(tmp_path, linked=False)
    theirs = build_weak_vault(tmp_path / "theirs.kdbx")
    file_id = home.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE)
    home.engine.run_once()  # asks

    result = home.engine.adopt_remote()

    assert result.status is Status.SYNCED and result.adopted is True
    assert home.vault_path.read_bytes() == theirs.read_bytes()
    assert home.state().drive_file_id == file_id
    assert sorted(home.backups_dir.glob("vault-*.kdbx")), "the local copy is backed up first"


def test_upload_local_is_the_other_choice(tmp_path: Path) -> None:
    home = _Home(tmp_path, linked=False)
    theirs = build_weak_vault(tmp_path / "theirs.kdbx")
    file_id = home.fake.write_from_another_device(theirs.read_bytes(), profile_id=PROFILE)
    home.engine.run_once()  # asks
    ours = home.vault_path.read_bytes()

    result = home.engine.upload_local()

    assert result.status is Status.SYNCED
    assert home.fake.stored_bytes(file_id) == ours
    oldest = home.fake.list_revisions(file_id)[-1].id
    assert home.fake.download_revision(file_id, oldest) == theirs.read_bytes()


def test_a_trashed_remote_stops_sync_and_asks(home: _Home) -> None:
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    home.fake.trash(file_id.id)

    result = home.engine.run_once()

    assert result.status is Status.ATTENTION
    assert home.fake.files[file_id.id].trashed is True  # never recreated silently


def test_take_theirs_adopts_the_kept_copy_and_then_publishes_it(home: _Home) -> None:
    """After an upload race, Drive's head is ours: adopting it would be a lie."""
    home.edit_locally()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.before["upload"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE
    )
    assert home.engine.run_once().status is Status.CONFLICT

    result = home.engine.adopt_remote()

    assert result.status is Status.SYNCED and result.adopted is True
    assert home.vault_path.read_bytes() == theirs.read_bytes()  # their copy, not our upload
    assert home.state().conflict is None  # the banner's question is answered
    assert home.engine.run_once().status is Status.SYNCED  # and no immediate re-conflict
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    assert home.fake.stored_bytes(file_id.id) == theirs.read_bytes()  # theirs wins on Drive too


def test_a_conflict_whose_kept_copy_is_gone_falls_back_to_drives_copy(home: _Home) -> None:
    home.edit_locally()
    theirs = build_weak_vault(home.tmp_path / "theirs.kdbx")
    home.fake.before["upload"] = lambda fake: fake.write_from_another_device(
        theirs.read_bytes(), profile_id=PROFILE
    )
    assert home.engine.run_once().status is Status.CONFLICT
    state = home.state()
    assert state.conflict is not None
    Path(str(state.conflict["kept_path"])).unlink()  # somebody tidied the folder
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None

    result = home.engine.adopt_remote()

    assert result.status is Status.SYNCED  # it falls back to whatever Drive holds now
    assert home.vault_path.read_bytes() == home.fake.stored_bytes(file_id.id)


def test_a_deleted_remote_stops_sync_and_asks(home: _Home) -> None:
    file_id = home.fake.find_vault_file(PROFILE)
    assert file_id is not None
    del home.fake.files[file_id.id]  # somebody emptied the Drive bin

    result = home.engine.run_once()

    assert result.status is Status.ATTENTION
    assert home.fake.find_vault_file(PROFILE) is None  # nothing quietly recreated


# --- failures, retries and the backoff schedule ----------------------------


def test_the_backoff_schedule_is_exactly_the_specs() -> None:
    assert BACKOFF_SECONDS == (30, 60, 120, 240, 480, 960, 1800)
    delays = [backoff_seconds(attempt, jitter=0.0) for attempt in range(9)]
    assert delays[:7] == [30, 60, 120, 240, 480, 960, 1800]
    assert delays[7:] == [1800, 1800]  # capped


def test_the_backoff_has_jitter_but_keeps_the_order() -> None:
    for attempt in range(7):
        early = backoff_seconds(attempt, jitter=-1.0)
        late = backoff_seconds(attempt, jitter=1.0)
        assert early < BACKOFF_SECONDS[attempt] < late
        assert early >= BACKOFF_SECONDS[attempt] * 0.75
        assert late <= BACKOFF_SECONDS[attempt] * 1.25


def test_a_retryable_failure_says_when_to_try_again(home: _Home) -> None:
    home.fake.failures = [ServerError("500")]
    result = home.engine.run_once()
    assert result.status is Status.OFFLINE
    assert result.retry_at is not None
    assert "500" not in result.message  # the UI gets a sentence, not a status code hunt


def test_a_success_resets_the_backoff(home: _Home) -> None:
    home.fake.failures = [ServerError("500"), ServerError("500")]
    home.engine.run_once()
    home.engine.run_once()
    assert home.engine.attempts > 0
    home.engine.run_once()  # succeeds
    assert home.engine.attempts == 0


def test_a_401_refreshes_the_token_once_and_retries(home: _Home) -> None:
    home.edit_locally()
    home.fake.failures = [AuthExpired("401")]
    result = home.engine.run_once()
    assert result.status is Status.SYNCED
    assert home.refreshes == 1


def test_a_second_401_stops_and_asks_for_a_reconnect(home: _Home) -> None:
    home.fake.failures = [AuthExpired("401"), AuthExpired("401")]
    result = home.engine.run_once()
    assert result.status is Status.RECONNECT
    assert home.refreshes == 1  # once, not in a loop


def test_a_refresh_that_is_refused_asks_for_a_reconnect(home: _Home) -> None:
    def refuse() -> None:
        raise ReconnectRequired("invalid_grant")

    home.engine._refresh_credentials = refuse  # the engine only ever calls it
    home.fake.failures = [AuthExpired("401")]
    assert home.engine.run_once().status is Status.RECONNECT


def test_state_json_holds_what_the_data_model_shows(home: _Home) -> None:
    home.edit_locally()
    home.engine.run_once()
    raw = json.loads((home.sync_dir / "state.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["drive_file_id"]
    assert raw["drive_folder_id"]
    assert raw["last_synced_remote_version"] >= 1
    assert raw["last_synced_remote_md5"]
    assert raw["last_synced_local_sha256"]
    assert raw["local_dirty"] is False
    assert raw["last_success_at"]
    assert raw["last_error"] is None


# --- one at a time ---------------------------------------------------------


def test_a_second_run_while_one_is_running_is_coalesced(home: _Home) -> None:
    started = threading.Event()
    release = threading.Event()
    original = home.fake.metadata

    def slow_metadata(file_id: str) -> Any:
        started.set()
        release.wait(timeout=5)
        return original(file_id)

    home.fake.metadata = slow_metadata  # type: ignore[method-assign]
    runs: list[Any] = []

    def run() -> None:
        runs.append(home.engine.run_once())

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(timeout=5)
    assert home.engine.run_once().status is Status.BUSY  # never a second sync
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert runs and runs[0].status in {Status.SYNCED, Status.ATTENTION}


def test_the_worker_coalesces_a_burst_of_triggers(home: _Home) -> None:
    runs: list[str] = []
    original = home.engine.run_once

    def counted() -> Any:
        runs.append("run")
        return original()

    home.engine.run_once = counted  # type: ignore[method-assign]
    worker = SyncWorker(home.engine, interval_seconds=30.0, save_delay_seconds=0.01)
    worker.start()
    try:
        for _ in range(5):
            worker.notify_saved()
        deadline = time.monotonic() + 5
        while len(runs) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.3)  # give a runaway loop time to show itself
    finally:
        worker.stop()
    assert len(runs) == 1, "a burst of saves is one sync, not five"


def test_the_worker_runs_on_the_interval(home: _Home) -> None:
    runs: list[str] = []

    class Counting:
        """A stand-in engine: the worker is what is under test here."""

        def run_once(self) -> Any:
            runs.append("run")
            from personal_vault.sync.engine import SyncResult

            return SyncResult(Status.SYNCED, "Synced")

    worker = SyncWorker(Counting(), interval_seconds=0.05, save_delay_seconds=0.01)  # type: ignore[arg-type]
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while len(runs) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker.stop()
    assert len(runs) >= 3
