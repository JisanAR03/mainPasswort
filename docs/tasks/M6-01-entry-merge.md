# M6-01 Entry-level merge

Milestone: M6 · Sensitive: yes · Depends on: M5-05

## Goal

A conflict no longer has to end in a whole-file choice. Both copies are opened, and the
entries are merged one by one: for each entry UUID the later change wins, the losing version
goes to history, and a deletion recorded as a tombstone is respected.

The rule is deliberately one rule — **later change wins** — and it is symmetric, so neither
device can produce a different vault than the other would have. A change is:

| The UUID is | Its "changed at" |
| --- | --- |
| a live login | `updated_at` (the entry's KDBX `mtime`) |
| in the Recycle Bin | the moment it was trashed (see below) |
| a tombstone in `<DeletedObjects>` | its `DeletionTime` |

When both sides changed at the same instant, the deletion wins, and between two live entries
the greater content decides (never the side), so a tie cannot make the result depend on which
copy is "local". ADR-006 asks for exactly this and nothing more.

Two supporting changes make that rule possible:

- **A trashed entry records when.** `trash_entry()` moves the entry and leaves `mtime` at the
  last edit, so a deletion had no time. `delete()` now stamps `mtime` at the moment of
  deletion, which is what the merge compares.
- **Tombstones are readable.** pykeepass has no API for `<DeletedObjects>`, so `vault.py`
  reads and writes that element through the payload XML (the M0 spike confirmed it survives
  save/reopen). A merge carries the winning tombstones into the merged file, so a later merge
  against a stale copy cannot resurrect what was deleted.

The merge itself is pure: `merge_sides(ours, theirs) -> MergePlan` takes two sides and
returns the actions, with no clock, no disk and no vault. `VaultSession.merge_from(other)`
applies a plan to a real vault and is the only part that writes.

## Files you may change

- app/src/personal_vault/core/merge.py (new, [S])
- app/src/personal_vault/core/vault.py ([S]: `merge_side()`, `merge_from()`, tombstones,
  the deletion time on `delete()`)
- app/src/personal_vault/services.py (`SyncController.merge_both()`)
- app/src/personal_vault/ui/sync_banner.py, ui/sync_status.py (the "Merge both" button)
- scripts/check_sensitive_review.py (add core/merge.py to `[S]` — it moves passwords)
- app/tests/unit/test_merge.py, app/tests/integration/test_merge_vault.py,
  app/tests/ui/test_merge_button.py

Not changed, because AGENTS.md rule 7 forbids it: `docs/specs/milestones.md`. The tick it
earns is proposed at the end of this card, for the owner to apply.

## Spec references

- docs/adr/0006-conflicts.md — "the newer `updated_at` wins, the loser goes to history, and
  deletions recorded as tombstones are respected"
- docs/specs/sync.md — resolving a conflict; "automatic merge replaces this in M6"
- docs/specs/data-model.md — the `deleted` row ("emptying the Recycle Bin records a tombstone")
- docs/spikes/2026-10-15-kdbx-spike.md — `<DeletedObjects>` survives save/reopen untouched

## Acceptance tests (write these first, show them failing)

Ticked by a test that ran (`app/tests/unit/test_merge.py` for the rule,
`app/tests/integration/test_merge_vault.py` for real files,
`app/tests/ui/test_merge_button.py` for the button and the whole path).

- [x] an entry edited only on their side arrives; an entry edited only here is left alone
      (`test_an_entry_edited_only_on_their_side_arrives`, `..._only_here_is_left_alone`,
      `test_an_entry_only_they_changed_arrives_and_our_old_version_is_kept`)
- [x] an entry edited on both sides takes the later `updated_at`, and the version that lost is
      in that entry's history afterwards
      (`test_an_entry_we_both_changed_keeps_the_later_and_histories_the_loser`)
- [x] an entry deleted on their side and untouched here is gone from the Logins group here
      (`test_an_entry_they_deleted_and_nobody_touched_here_goes_to_the_bin`,
      `test_what_they_deleted_is_in_our_recycle_bin_after_the_merge`)
- [x] an entry deleted on their side and edited *later* here survives, because the edit is
      later — and the other way round, an edit older than a tombstone does not resurrect it
      (`test_an_edit_newer_than_a_deletion_here_brings_the_entry_back`,
      `test_an_edit_older_than_their_deletion_does_not_resurrect_the_entry`)
- [x] an entry deleted here and untouched there is not brought back by the merge
      (`test_an_entry_deleted_here_is_not_brought_back_by_their_copy`)
- [x] a tombstone that wins is written into the merged file, so merging again against the
      stale copy still does not resurrect the entry
      (`test_an_edit_older_than_their_deletion_does_not_resurrect_the_entry`)
- [x] an entry that exists only on their side is added, with its history left empty
      (`test_an_entry_only_they_have_is_added`)
- [x] property test: merging twice gives the same vault as merging once
      (`test_property_merging_twice_changes_nothing_more`,
      `test_merging_twice_changes_nothing_the_second_time`)
- [x] property test: `merge(A, B)` applied to B holds exactly what `merge(B, A)` applied to A
      holds — the result does not depend on which side is local
      (`test_property_neither_side_is_told_a_different_vault`)
- [x] property test: no entry that is live on either side, and not deleted later, is missing
      from the result (`test_property_nothing_live_and_left_alone_is_lost`)
- [x] property test: no password, notes or username is ever logged while merging
      (`test_property_the_merge_never_logs_an_entry_field`)
- [x] the conflict banner offers **Merge both**, and merging ends the conflict and uploads
      (`test_the_banner_offers_merge_both_beside_the_other_choices`,
      `test_a_merge_ends_the_conflict_and_puts_the_merged_file_on_drive`)
- [x] a merge of two copies that differ only in an entry's title succeeds and reports counts
      (`test_a_merge_of_two_copies_differing_only_in_a_title_reports_counts`,
      `test_a_merge_keeps_both_sides_edits_and_the_entry_only_they_had`)

Two more, not on the list but worth having: a merge never copies the hidden `.app` group
(the Drive token must not travel, `test_a_merge_never_copies_the_hidden_app_group`), and a
merge called after the conflict is over changes nothing
(`test_merge_both_after_the_conflict_is_over_changes_nothing`).

The property test for the side-independence caught a real bug while it was being written:
two versions that differed only in `updated_at` compared equal, so the winning timestamp was
never copied and the two directions disagreed. `_sort_key` now includes it.

## Out of scope

Merging more than two copies at once, merging attachments, and any UI for picking a winner
entry by entry (the other three choices stay for that)

## Proposed change to docs/specs (rule 7: the owner applies this)

In `docs/specs/milestones.md`, the first M6 "Done when" box becomes:

```markdown
- [x] Property tests show merge loses no entry, gives the same result twice, and does not
      depend on which side is "local" (`test_property_nothing_live_and_left_alone_is_lost`,
      `test_property_merging_twice_changes_nothing_more`,
      `test_property_neither_side_is_told_a_different_vault`)
```

and the M6-01 task bullet becomes:

```markdown
- **M6-01** Entry-level merge: the newer `updated_at` wins, the loser goes to history, and
  tombstones are respected. *(built 2026-10-16; see [M6-01](tasks/M6-01-entry-merge.md))*
```

`docs/specs/sync.md` says "automatic merge replaces this in M6" about the conflict choices.
That is now true in the sense that a fourth choice exists; the three manual ones stay, so the
sentence could become "automatic entry-level merge is offered alongside these choices". That
one is the owner's call too.
