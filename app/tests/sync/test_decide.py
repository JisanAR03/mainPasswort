"""M5-03: every row of the sync decision table (docs/specs/sync.md)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from personal_vault.core.errors import SchemaTooNewError
from personal_vault.sync.decide import Action, LocalState, RemoteState, decide
from personal_vault.sync.state import SyncState, load_state, save_state

pytestmark = pytest.mark.sync

LOCAL_SHA = "a" * 64
LOCAL_MD5 = "b" * 32
REMOTE_MD5 = "c" * 32


def _state(**overrides: object) -> SyncState:
    values: dict[str, object] = {
        "drive_file_id": "file-1",
        "last_synced_remote_version": 7,
        "last_synced_remote_md5": REMOTE_MD5,
        "last_synced_local_sha256": LOCAL_SHA,
        "local_dirty": False,
    }
    values.update(overrides)
    return SyncState(**values)  # type: ignore[arg-type]


def _local(
    *, sha: str | None = LOCAL_SHA, md5: str | None = LOCAL_MD5, dirty: bool = False
) -> LocalState:
    return LocalState(exists=True, sha256=sha, md5=md5, dirty=dirty)


def _remote(
    *,
    md5: str | None = REMOTE_MD5,
    version: int | None = 7,
    exists: bool = True,
    trashed: bool = False,
) -> RemoteState:
    return RemoteState(exists=exists, trashed=trashed, md5=md5, version=version)


def test_row_no_changes_is_nothing() -> None:
    assert decide(_local(), _remote(), _state()) is Action.NOTHING


def test_row_local_changed_uploads() -> None:
    assert decide(_local(sha="d" * 64, md5="e" * 32), _remote(), _state()) is Action.UPLOAD


def test_row_dirty_flag_alone_counts_as_local_changed() -> None:
    assert decide(_local(dirty=True), _remote(), _state()) is Action.UPLOAD


def test_row_remote_changed_downloads() -> None:
    assert decide(_local(), _remote(md5="f" * 32, version=8), _state()) is Action.DOWNLOAD


def test_row_both_changed_is_a_conflict() -> None:
    action = decide(_local(sha="d" * 64, md5="e" * 32), _remote(md5="f" * 32, version=8), _state())
    assert action is Action.CONFLICT


def test_row_same_content_on_both_sides_updates_state_only() -> None:
    # both sides changed, but the bytes are the same: no transfer, just bookkeeping
    action = decide(_local(sha="d" * 64, md5="f" * 32), _remote(md5="f" * 32, version=8), _state())
    assert action is Action.UPDATE_STATE


def test_row_same_content_and_nothing_recorded_is_nothing() -> None:
    state = _state(last_synced_remote_md5="f" * 32, last_synced_local_sha256="d" * 64)
    assert (
        decide(_local(sha="d" * 64, md5="f" * 32), _remote(md5="f" * 32), state) is Action.NOTHING
    )


def test_row_remote_file_missing_asks() -> None:
    assert decide(_local(), _remote(exists=False, md5=None, version=None), _state()) is Action.ASK


def test_row_remote_file_trashed_asks() -> None:
    assert decide(_local(), _remote(trashed=True), _state()) is Action.ASK


def test_a_missing_state_file_is_the_first_link_flow() -> None:
    # ADR-010: a file is on Drive but this device has no state.json
    assert decide(_local(), _remote(), None) is Action.ASK_FIRST_LINK


def test_first_link_with_nothing_on_drive_uploads() -> None:
    assert decide(_local(), _remote(exists=False, md5=None, version=None), None) is Action.UPLOAD


def test_first_link_with_a_trashed_file_asks_instead_of_recreating() -> None:
    assert decide(_local(), _remote(trashed=True), None) is Action.ASK_FIRST_LINK


def test_a_local_file_that_cannot_be_read_asks() -> None:
    # the vault is missing or unreadable: never upload, never overwrite
    assert (
        decide(LocalState(exists=False, sha256=None, md5=None, dirty=True), _remote(), _state())
        is Action.ASK
    )


@given(  # type: ignore[misc]
    local_sha=st.sampled_from([LOCAL_SHA, "d" * 64, None]),
    local_md5=st.sampled_from([LOCAL_MD5, "e" * 32, None]),
    dirty=st.booleans(),
    remote_md5=st.sampled_from([REMOTE_MD5, "f" * 32, None]),
    remote_version=st.sampled_from([7, 8, None]),
    remote_exists=st.booleans(),
    remote_trashed=st.booleans(),
    state_seen_md5=st.sampled_from([REMOTE_MD5, "0" * 32, None]),
)
def test_i6_no_upload_of_a_remote_version_we_have_not_seen(
    local_sha: str | None,
    local_md5: str | None,
    dirty: bool,
    remote_md5: str | None,
    remote_version: int | None,
    remote_exists: bool,
    remote_trashed: bool,
    state_seen_md5: str | None,
) -> None:
    state = _state(last_synced_remote_md5=state_seen_md5)
    action = decide(
        LocalState(exists=True, sha256=local_sha, md5=local_md5, dirty=dirty),
        RemoteState(
            exists=remote_exists, trashed=remote_trashed, md5=remote_md5, version=remote_version
        ),
        state,
    )
    if action is Action.UPLOAD:
        assert not remote_exists or remote_md5 == state_seen_md5, (
            "an upload must never run over a remote version we have not seen"
        )


@given(  # type: ignore[misc]
    local_sha=st.sampled_from([LOCAL_SHA, "d" * 64, None]),
    local_md5=st.sampled_from([LOCAL_MD5, "e" * 32, None]),
    dirty=st.booleans(),
    remote_md5=st.sampled_from([REMOTE_MD5, "f" * 32, None]),
    remote_version=st.sampled_from([7, 8, None]),
    remote_exists=st.booleans(),
    remote_trashed=st.booleans(),
    state_seen_md5=st.sampled_from([REMOTE_MD5, "0" * 32, None]),
)
def test_the_decision_never_looks_at_anything_but_its_arguments(
    local_sha: str | None,
    local_md5: str | None,
    dirty: bool,
    remote_md5: str | None,
    remote_version: int | None,
    remote_exists: bool,
    remote_trashed: bool,
    state_seen_md5: str | None,
) -> None:
    """Same inputs, same answer: a pure function has no clock, no disk, no os.environ."""
    args = (
        LocalState(exists=True, sha256=local_sha, md5=local_md5, dirty=dirty),
        RemoteState(
            exists=remote_exists, trashed=remote_trashed, md5=remote_md5, version=remote_version
        ),
        _state(last_synced_remote_md5=state_seen_md5),
    )
    assert decide(*args) is decide(*args)


def test_every_combination_of_the_table_is_covered() -> None:
    """A blunt sweep: no input combination raises, and the answer is one of the actions."""
    seen = set()
    for sha, md5, dirty, remote_md5, exists, trashed, state in itertools.product(
        [LOCAL_SHA, None],
        [LOCAL_MD5, None],
        [True, False],
        [REMOTE_MD5, None],
        [True, False],
        [True, False],
        [_state(), None],
    ):
        action = decide(
            LocalState(exists=True, sha256=sha, md5=md5, dirty=dirty),
            RemoteState(exists=exists, trashed=trashed, md5=remote_md5, version=7),
            state,
        )
        seen.add(action)
    assert seen <= set(Action)


# --- state.json (data model: sync/state.json) ---


def test_state_round_trips_through_the_file(tmp_path: Path) -> None:
    path = tmp_path / "sync" / "state.json"
    original = _state(last_success_at="2026-10-15T10:20:00Z", linked_from="new")
    save_state(path, original)
    assert load_state(path) == original


def test_a_missing_state_file_is_none(tmp_path: Path) -> None:
    assert load_state(tmp_path / "sync" / "state.json") is None


def test_an_unreadable_state_file_is_none(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_state(path) is None


def test_a_newer_state_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(SchemaTooNewError):
        load_state(path)


def test_conflict_details_survive_the_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    conflict = {
        "detected_at": "2026-10-15T10:20:00Z",
        "remote_version": 8,
        "kept_path": "conflicts/vault-remote.kdbx",
    }
    save_state(path, _state(conflict=conflict))
    loaded = load_state(path)
    assert loaded is not None
    assert loaded.conflict == conflict


def test_state_is_written_atomically(tmp_path: Path) -> None:
    """No temporary file is left behind and the file is complete JSON."""
    path = tmp_path / "state.json"
    save_state(path, _state(drive_file_id="file-9"))
    assert json.loads(path.read_text(encoding="utf-8"))["drive_file_id"] == "file-9"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
