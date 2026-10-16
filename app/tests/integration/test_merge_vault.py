"""M6-01: merging two copies of a vault, on real files ([S])."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fixtures.weak_vault import WEAK_PASSWORD, build_weak_vault, make_login
from personal_vault.core.models import LoginEntry
from personal_vault.core.vault import VaultSession, open_vault

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)

Copies = tuple[VaultSession, VaultSession]


@pytest.fixture
def copies(tmp_path: Path) -> Iterator[Copies]:
    """Two copies of one vault, as two devices would hold them."""
    mine_path = build_weak_vault(tmp_path / "here" / "vault.kdbx")
    theirs_path = tmp_path / "there" / "vault.kdbx"
    theirs_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mine_path, theirs_path)
    mine = VaultSession.open(mine_path, WEAK_PASSWORD, tmp_path / "here" / "backups")
    theirs = VaultSession.open(theirs_path, WEAK_PASSWORD, tmp_path / "there" / "backups")
    try:
        yield mine, theirs
    finally:
        mine.close()
        theirs.close()


def _both(copies: Copies, entry: LoginEntry) -> None:
    """The same entry, added on both devices."""
    for session in copies:
        session.add(entry)
        session.save()


def _edit(session: VaultSession, entry_id: object, title: str, when: datetime) -> None:
    changed = session.get(entry_id)  # type: ignore[arg-type]
    changed.title = title
    changed.updated_at = when
    session.edit(changed)
    session.save()


def test_an_entry_only_they_changed_arrives_and_our_old_version_is_kept(
    copies: Copies,
) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    _edit(theirs, entry.id, "Changed there", LATER)

    report = mine.merge_from(theirs)

    assert report.updated == 1
    assert mine.get(entry.id).title == "Changed there"
    # Taken in by an ordinary edit, so the version replaced here is kept too.
    assert [item.title for item in mine.history(entry.id)] == ["Example Site"]


def test_an_entry_we_both_changed_keeps_the_later_and_histories_the_loser(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    _edit(mine, entry.id, "Ours", T0 + timedelta(minutes=30))
    _edit(theirs, entry.id, "Theirs", LATER)

    report = mine.merge_from(theirs)

    assert mine.get(entry.id).title == "Theirs"
    assert report.updated == 1
    assert [item.title for item in mine.history(entry.id)][-1] == "Ours"  # the loser


def test_an_entry_they_deleted_and_nobody_touched_here_goes_to_the_bin(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    theirs.delete(entry.id)
    theirs.save()

    report = mine.merge_from(theirs)

    assert report.deleted == 1
    assert [summary.id for summary in mine.list_logins()] == []
    assert entry.id in mine.merge_side().tombstones


def test_an_edit_older_than_their_deletion_does_not_resurrect_the_entry(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    theirs.delete(entry.id)
    theirs.save()

    mine.merge_from(theirs)

    # The tombstone is in the merged file now, so the same stale copy merged
    # again still cannot bring the entry back.
    again = mine.merge_from(theirs)

    assert [summary.id for summary in mine.list_logins()] == []
    assert again.total == 0
    assert entry.id in mine.tombstones()


def test_an_entry_deleted_here_is_not_brought_back_by_their_copy(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    mine.delete(entry.id)  # stamped with now, which is later than T0
    mine.save()

    report = mine.merge_from(theirs)

    assert report.total == 0
    assert [summary.id for summary in mine.list_logins()] == []
    assert entry.id in mine.tombstones()


def test_an_edit_newer_than_a_deletion_here_brings_the_entry_back(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    mine.delete(entry.id)
    mine.save()
    _edit(theirs, entry.id, "Edited after the delete", datetime.now(UTC) + timedelta(hours=1))

    report = mine.merge_from(theirs)

    assert mine.get(entry.id).title == "Edited after the delete"
    assert [summary.id for summary in mine.list_logins()] == [entry.id]
    assert entry.id not in mine.merge_side().tombstones
    assert report.updated == 1


def test_an_entry_only_they_have_is_added(copies: Copies) -> None:
    mine, theirs = copies
    fresh = make_login(title="Only there")
    theirs.add(fresh)
    theirs.save()

    report = mine.merge_from(theirs)

    assert report.added == 1
    assert mine.get(fresh.id).title == "Only there"
    assert mine.history(fresh.id) == []


def test_a_merge_of_two_copies_differing_only_in_a_title_reports_counts(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    _edit(theirs, entry.id, "Renamed", LATER)

    report = mine.merge_from(theirs)

    assert (report.added, report.updated, report.deleted) == (0, 1, 0)
    assert report.total == 1
    assert mine.get(entry.id).title == "Renamed"


def test_merging_twice_changes_nothing_the_second_time(copies: Copies) -> None:
    mine, theirs = copies
    shared = make_login(updated_at=T0)
    _both(copies, shared)
    _edit(theirs, shared.id, "Theirs", LATER)
    only_there = make_login(title="Added there")
    theirs.add(only_there)
    theirs.save()

    first = mine.merge_from(theirs)

    assert first.total == 2
    assert mine.get(shared.id).title == "Theirs"
    assert {summary.id for summary in mine.list_logins()} == {shared.id, only_there.id}

    second = mine.merge_from(theirs)

    assert second.total == 0
    assert {summary.id for summary in mine.list_logins()} == {shared.id, only_there.id}


def test_a_merge_never_copies_the_hidden_app_group(copies: Copies) -> None:
    """The Drive token and the pairing key live in .app, and must not travel."""
    mine, theirs = copies
    theirs.set_app_value("google_drive_token", "a-token-that-must-not-travel")
    theirs.save()

    mine.merge_from(theirs)

    assert mine.get_app_value("google_drive_token") is None


def test_what_they_deleted_is_in_our_recycle_bin_after_the_merge(copies: Copies) -> None:
    mine, theirs = copies
    entry = make_login(updated_at=T0)
    _both(copies, entry)
    theirs.delete(entry.id)
    theirs.save()

    mine.merge_from(theirs)
    reopened = open_vault(mine.path, WEAK_PASSWORD)  # the file on disk, not the session

    assert [item.uuid for item in reopened.recyclebin_group.entries] == [entry.id]
