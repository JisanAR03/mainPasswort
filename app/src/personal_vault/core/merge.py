"""M6-01: entry-level merge of two vaults ([S]).

A conflict leaves two copies of the same vault. This decides, entry by entry,
which copy of each entry survives, so the everyday case — two devices editing
different entries — stops needing a whole-file choice.

There is one rule, the later change wins, and it is symmetric: merging A into B
and B into A land on the same entries rather than trading versions back and
forth on every sync. When two changes carry the same instant, a deletion beats
a live entry (nothing is resurrected by a tie) and two live entries are ordered
by their content, never by which side they came from.

Everything here is pure: no clock, no disk, no pykeepass, no vault.
``VaultSession.merge_side()`` reads a vault into a :class:`MergeSide` and
``VaultSession.merge_from()`` applies a :class:`MergePlan`; this module only
decides.

This file handles entry fields, passwords included, so it is an ``[S]`` file.
Values are compared and carried, never logged, printed or put in an exception;
the comparison key :func:`_sort_key` holds a revealed password for the length
of one comparison and never leaves this module.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from personal_vault.core.models import LoginEntry


@dataclass(frozen=True)
class MergeSide:
    """One vault as the merge sees it.

    ``entries`` are the live logins; ``tombstones`` are the deletions, whether
    the entry is sitting in a Recycle Bin or recorded in the KDBX
    ``<DeletedObjects>`` list, each mapped to the moment it was deleted.
    """

    entries: Mapping[uuid.UUID, LoginEntry]
    tombstones: Mapping[uuid.UUID, datetime]


@dataclass(frozen=True)
class MergeAction:
    """One entry's outcome. Exactly one of the last two fields is set.

    ``entry`` means their version wins: add it, or replace ours (ours goes to
    history first). ``deleted_at`` means the deletion wins: ours must go.
    """

    id: uuid.UUID
    entry: LoginEntry | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class MergePlan:
    """What merging their side into ours does, and the tombstones to carry.

    ``tombstones`` is the merged file's deletion list: the deletions that won.
    A stale copy merged against the result later reads them and does not bring
    anything back.
    """

    actions: tuple[MergeAction, ...]
    tombstones: Mapping[uuid.UUID, datetime]

    @property
    def deletions(self) -> tuple[MergeAction, ...]:
        return tuple(action for action in self.actions if action.deleted_at is not None)


@dataclass(frozen=True)
class _Change:
    """What one side has for one UUID: a live entry, a deletion, or nothing."""

    entry: LoginEntry | None = None
    deleted_at: datetime | None = None

    @property
    def present(self) -> bool:
        return self.entry is not None or self.deleted_at is not None

    @property
    def at(self) -> datetime:
        """When this side changed it; only meaningful for a present change."""
        if self.entry is not None:
            return self.entry.updated_at
        if self.deleted_at is None:  # pragma: no cover - guarded by present
            raise ValueError("this change has no time")
        return self.deleted_at


def _change(side: MergeSide, entry_id: uuid.UUID) -> _Change:
    entry = side.entries.get(entry_id)
    if entry is not None:
        return _Change(entry=entry)
    deleted_at = side.tombstones.get(entry_id)
    if deleted_at is not None:
        return _Change(deleted_at=deleted_at)
    return _Change()


def _sort_key(entry: LoginEntry) -> tuple[object, ...]:
    """Every field of an entry in a fixed order, for the tie-break only.

    Two changes at the same instant must still be decided the same way on both
    devices, so the content decides. The revealed password is in this key as a
    plain string so the tuple can be ordered at all; it is built, compared and
    dropped inside this function's caller, and never logged or returned.
    """
    return (
        entry.title,
        entry.username,
        entry.password.reveal(),
        tuple(entry.urls),
        entry.notes,
        tuple(entry.tags),
        entry.match_subdomains,
        entry.created_at,
        entry.updated_at,  # two versions can differ only in when they were saved
    )


def _theirs_wins(mine: _Change, yours: _Change) -> bool:
    """Which side's change survives. Swapping the arguments swaps the answer,
    so neither side can reach a different vault than the other would."""
    if not yours.present:
        return False
    if not mine.present:
        return True
    if yours.at != mine.at:
        return yours.at > mine.at
    # The same instant: a deletion beats a live entry, and two live entries are
    # ordered by content. Both answers are the same on either device.
    if mine.entry is None or yours.entry is None:
        return yours.entry is None
    return _sort_key(yours.entry) > _sort_key(mine.entry)


def merged_side(ours: MergeSide, plan: MergePlan) -> MergeSide:
    """Our side afterwards, as data.

    This is the definition of what the merge results in, and what
    ``VaultSession.merge_from`` reaches by adding, editing and deleting for
    real. The losing version of an updated entry is not here: the vault puts
    it in that entry's history on the way.
    """
    entries = dict(ours.entries)
    for action in plan.actions:
        if action.entry is not None:
            entries[action.id] = action.entry
        else:
            entries.pop(action.id, None)
    return MergeSide(entries=entries, tombstones=dict(plan.tombstones))


def merge_sides(ours: MergeSide, theirs: MergeSide) -> MergePlan:
    """Decide the merge. Pure, deterministic, and independent of call order."""
    actions: list[MergeAction] = []
    tombstones: dict[uuid.UUID, datetime] = {}
    every = set(ours.entries) | set(ours.tombstones) | set(theirs.entries) | set(theirs.tombstones)

    for entry_id in sorted(every, key=str):
        mine = _change(ours, entry_id)
        yours = _change(theirs, entry_id)
        if not _theirs_wins(mine, yours):
            if mine.entry is None and mine.deleted_at is not None:
                tombstones[entry_id] = mine.deleted_at
            continue
        if yours.entry is None:
            tombstones[entry_id] = yours.at
            if mine.entry is not None:
                actions.append(MergeAction(entry_id, deleted_at=yours.at))
            continue
        if mine.entry is None or _sort_key(mine.entry) != _sort_key(yours.entry):
            actions.append(MergeAction(entry_id, entry=yours.entry))

    return MergePlan(tuple(actions), tombstones)
