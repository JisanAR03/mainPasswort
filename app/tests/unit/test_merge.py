"""M6-01: the entry-level merge rule, tested as the pure function it is.

The properties here are the milestone's "Done when" items: merging twice
changes nothing more, neither side reaches a different vault than the other
would, and nothing that was live and left alone disappears.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fixtures.weak_vault import make_login
from hypothesis import given
from hypothesis import strategies as st
from personal_vault.core.merge import (
    MergePlan,
    MergeSide,
    merge_sides,
    merged_side,
)
from personal_vault.core.models import LoginEntry, SecretStr

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)
LATEST = T0 + timedelta(hours=2)


def _side(entries: list[LoginEntry] | None = None, deleted: dict | None = None) -> MergeSide:
    return MergeSide(
        entries={entry.id: entry for entry in entries or []},
        tombstones=deleted or {},
    )


def _entry(
    entry_id: uuid.UUID,
    *,
    title: str = "Example Site",
    password: str = "correct horse battery staple",
    updated_at: datetime = T0,
) -> LoginEntry:
    return make_login(
        id=entry_id,
        title=title,
        password=SecretStr(password),
        updated_at=updated_at,
    )


# --- one entry at a time ---------------------------------------------------


def test_an_entry_edited_only_on_their_side_arrives() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id)])
    theirs = _side([_entry(entry_id, title="Changed", updated_at=LATER)])

    plan = merge_sides(ours, theirs)

    assert [action.id for action in plan.actions] == [entry_id]
    assert plan.actions[0].entry is not None
    assert plan.actions[0].entry.title == "Changed"


def test_an_entry_edited_only_here_is_left_alone() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id, title="Mine", updated_at=LATER)])
    theirs = _side([_entry(entry_id, title="Theirs")])

    plan = merge_sides(ours, theirs)

    assert plan.actions == ()
    assert plan.tombstones == {}


def test_the_later_edit_wins_whichever_side_it_is_on() -> None:
    entry_id = uuid.uuid4()
    older = _entry(entry_id, title="Older", updated_at=T0)
    newer = _entry(entry_id, title="Newer", updated_at=LATER)

    take_theirs = merge_sides(_side([older]), _side([newer]))
    keep_ours = merge_sides(_side([newer]), _side([older]))

    assert take_theirs.actions[0].entry is not None
    assert take_theirs.actions[0].entry.title == "Newer"
    assert keep_ours.actions == ()


def test_two_edits_at_the_same_instant_are_decided_by_content_not_side() -> None:
    entry_id = uuid.uuid4()
    alpha = _entry(entry_id, title="Alpha", updated_at=T0)
    beta = _entry(entry_id, title="Beta", updated_at=T0)

    ours_side, theirs_side = _side([alpha]), _side([beta])
    won_here = merged_side(ours_side, merge_sides(ours_side, theirs_side))
    won_there = merged_side(theirs_side, merge_sides(theirs_side, ours_side))

    assert won_here.entries[entry_id].title == won_there.entries[entry_id].title
    assert won_here.entries[entry_id].title == max("Alpha", "Beta")


def test_an_entry_that_is_only_on_their_side_is_added() -> None:
    fresh = uuid.uuid4()
    plan = merge_sides(_side(), _side([_entry(fresh)]))

    assert len(plan.actions) == 1
    assert plan.actions[0].id == fresh
    assert plan.actions[0].entry is not None
    assert plan.actions[0].entry.id == fresh


def test_an_entry_that_is_only_here_is_untouched() -> None:
    plan = merge_sides(_side([_entry(uuid.uuid4())]), _side())

    assert plan.actions == ()
    assert plan.tombstones == {}


# --- deletions -------------------------------------------------------------


def test_an_entry_deleted_on_their_side_and_untouched_here_goes() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id, updated_at=T0)])
    theirs = _side(deleted={entry_id: LATER})

    plan = merge_sides(ours, theirs)

    assert [action.id for action in plan.deletions] == [entry_id]
    assert plan.tombstones == {entry_id: LATER}


def test_an_entry_deleted_here_is_not_brought_back() -> None:
    entry_id = uuid.uuid4()
    ours = _side(deleted={entry_id: LATEST})
    theirs = _side([_entry(entry_id, updated_at=LATER)])

    plan = merge_sides(ours, theirs)

    assert plan.actions == ()
    assert plan.tombstones == {entry_id: LATEST}


def test_an_edit_newer_than_a_deletion_survives() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id, title="Edited after", updated_at=LATEST)])
    theirs = _side(deleted={entry_id: LATER})

    plan = merge_sides(ours, theirs)

    assert plan.actions == ()
    assert plan.tombstones == {}  # the entry is live, so the tombstone is spent


def test_an_edit_older_than_a_deletion_does_not_resurrect_the_entry() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id, updated_at=T0)])
    theirs = _side(deleted={entry_id: LATER})

    plan = merge_sides(ours, theirs)

    assert plan.deletions[0].deleted_at == LATER


def test_a_deletion_beats_a_live_entry_at_the_same_instant() -> None:
    entry_id = uuid.uuid4()
    ours = _side([_entry(entry_id, updated_at=LATER)])
    theirs = _side(deleted={entry_id: LATER})

    assert merge_sides(ours, theirs).deletions  # theirs deletes it
    assert merge_sides(theirs, ours).actions == ()  # and ours does not undo that


def test_a_deletion_recorded_here_survives_the_merge() -> None:
    """A stale copy must not be able to bring back what was deleted."""
    gone = uuid.uuid4()
    fresh = uuid.uuid4()
    ours = _side([_entry(fresh)], deleted={gone: LATER})
    theirs = _side([_entry(fresh), _entry(gone)])

    plan = merge_sides(ours, theirs)

    assert plan.tombstones == {gone: LATER}
    assert plan.actions == ()  # their copy of the deleted entry is not taken


def test_both_sides_deleting_the_same_entry_keeps_one_tombstone() -> None:
    entry_id = uuid.uuid4()
    ours = _side(deleted={entry_id: T0})
    theirs = _side(deleted={entry_id: LATER})

    plan = merge_sides(ours, theirs)

    assert plan.actions == ()
    assert plan.tombstones == {entry_id: LATER}  # the later deletion is the one kept


# --- what the vault holds afterwards ---------------------------------------


def test_the_merged_side_holds_the_winner_and_drops_the_deleted() -> None:
    kept = uuid.uuid4()
    changed = uuid.uuid4()
    gone = uuid.uuid4()
    ours = _side(
        [_entry(kept), _entry(changed), _entry(gone)],
        deleted={uuid.uuid4(): T0},
    )
    theirs = _side(
        [_entry(changed, title="Theirs", updated_at=LATER)],
        deleted={gone: LATER},
    )

    result = merged_side(ours, merge_sides(ours, theirs))

    assert set(result.entries) == {kept, changed}
    assert result.entries[changed].title == "Theirs"
    assert gone in result.tombstones


# --- properties ------------------------------------------------------------


_times = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(UTC),
)


@st.composite
def _entries(draw: st.DrawFn, entry_id: uuid.UUID) -> LoginEntry:
    return make_login(
        id=entry_id,
        title=draw(st.text(min_size=1, max_size=8)),
        username=draw(st.text(max_size=8)),
        password=SecretStr(draw(st.text(max_size=8))),
        urls=draw(st.lists(st.text(max_size=12), max_size=2)),
        notes=draw(st.text(max_size=12)),
        tags=draw(st.lists(st.text(min_size=1, max_size=6), max_size=2)),
        match_subdomains=draw(st.booleans()),
        created_at=draw(_times),
        updated_at=draw(_times),
    )


@st.composite
def _sides(draw: st.DrawFn) -> tuple[MergeSide, MergeSide]:
    """Two random copies of a vault that share a set of entry UUIDs."""
    ids = draw(st.lists(st.uuids(), max_size=4, unique=True))
    entries: list[dict[uuid.UUID, LoginEntry]] = [{}, {}]
    tombstones: list[dict[uuid.UUID, datetime]] = [{}, {}]
    for entry_id in ids:
        for which in (0, 1):
            kind = draw(st.sampled_from(["absent", "live", "deleted"]))
            if kind == "live":
                entries[which][entry_id] = draw(_entries(entry_id))
            elif kind == "deleted":
                tombstones[which][entry_id] = draw(_times)
    return MergeSide(entries[0], tombstones[0]), MergeSide(entries[1], tombstones[1])


@given(_sides())
def test_property_merging_twice_changes_nothing_more(sides: tuple[MergeSide, MergeSide]) -> None:
    ours, theirs = sides
    once = merged_side(ours, merge_sides(ours, theirs))
    again = merged_side(once, merge_sides(once, theirs))

    assert dict(again.entries) == dict(once.entries)
    assert dict(again.tombstones) == dict(once.tombstones)


@given(_sides())
def test_property_neither_side_is_told_a_different_vault(
    sides: tuple[MergeSide, MergeSide],
) -> None:
    ours, theirs = sides
    from_here = merged_side(ours, merge_sides(ours, theirs))
    from_there = merged_side(theirs, merge_sides(theirs, ours))

    assert dict(from_here.entries) == dict(from_there.entries)
    assert dict(from_here.tombstones) == dict(from_there.tombstones)


@given(_sides())
def test_property_nothing_live_and_left_alone_is_lost(sides: tuple[MergeSide, MergeSide]) -> None:
    ours, theirs = sides
    plan: MergePlan = merge_sides(ours, theirs)
    result = merged_side(ours, plan)

    for side in (ours, theirs):
        for entry_id, entry in side.entries.items():
            deleted_at = max(
                (
                    other.tombstones[entry_id]
                    for other in (ours, theirs)
                    if entry_id in other.tombstones
                ),
                default=None,
            )
            if deleted_at is None or deleted_at < entry.updated_at:
                assert entry_id in result.entries, "an edit was lost"
                assert result.entries[entry_id].updated_at == max(
                    entry.updated_at,
                    result.entries[entry_id].updated_at,
                )


class _CaptureLogs(logging.Handler):
    """Every message logged while the merge runs, whatever the logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.text = ""

    def emit(self, record: logging.LogRecord) -> None:
        self.text += record.getMessage()
        if record.exc_info is not None:
            self.text += "\n" + logging.Formatter().formatException(record.exc_info)


@given(_sides())
def test_property_the_merge_never_logs_an_entry_field(sides: tuple[MergeSide, MergeSide]) -> None:
    ours, theirs = sides
    # One- and two-character fields match unrelated log text, so only fields long
    # enough to mean something are searched for.
    secrets = {
        field
        for side in (ours, theirs)
        for entry in side.entries.values()
        for field in (entry.title, entry.username, entry.password.reveal(), entry.notes)
        if len(field) >= 4
    }
    capture = _CaptureLogs()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        merged_side(ours, merge_sides(ours, theirs))
    finally:
        root.removeHandler(capture)

    leaked = sorted(value for value in secrets if value in capture.text)
    assert leaked == [], "an entry field reached the log"
