# M1-03 Atomic save

Milestone: M1 · Sensitive: yes · Depends on: M1-02

## Goal
Saving a vault can never leave a broken or half-written file, and recovery from the
newest good backup always works.

## Files you may change

- app/src/personal_vault/core/storage.py
- app/tests/integration/test_storage.py
- app/tests/slow/test_kill_save.py (marked `slow`)

## Spec references

- docs/specs/data-model.md — On-disk layout
- docs/specs/threat-model.md — invariant I3

## Acceptance tests (write these first, show them failing)

- [x] Save writes a temp file in the same folder, then renames it over the vault
- [x] A failure before the rename leaves the old vault untouched
- [x] The new file is re-opened and verified before the rename
- [x] Flipping bytes at 200 random offsets, or truncating, raises `VaultCorrupted` and
      never overwrites the file
- [x] Backup rotation keeps the newest 20 plus one per day for 30 days
- [x] Recovery restores the newest good backup when every newer one is corrupt
- [x] Kill-during-save loop (marked slow) always leaves a vault that decrypts (I3)

## Out of scope

- UI for backups/restore (M2-08)
