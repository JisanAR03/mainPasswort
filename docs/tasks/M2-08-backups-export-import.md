# M2-08 Backups view, restore, export and import

Milestone: M2 · Sensitive: no · Depends on: M2-07

## Goal
A backups view that lists backups and restores one (after confirmation); encrypted KDBX
export as the default (optionally under a new password); plaintext CSV export only behind
I8 (master password again + typed confirmation); KDBX and CSV import parsed as untrusted
input with size limits, landing in a new group for review.

## Files you may change

- app/src/personal_vault/services.py
- app/src/personal_vault/core/transfer.py (export/import parsing, no UI)
- app/src/personal_vault/ui/backups_view.py, app/src/personal_vault/ui/transfer_dialogs.py
- app/tests/ui/test_backups_view.py, app/tests/ui/test_transfer_dialogs.py (pytest-qt)
- app/tests/integration/test_transfer.py
- app/tests/security/test_invariants.py (I8 canary)

## Spec references

- docs/specs/data-model.md — Import and export
- docs/specs/threat-model.md — invariant I8
- docs/specs/milestones.md — M2-08

## Acceptance tests (write these first, show them failing)

- [x] The backups view lists backups newest first and restore works after confirmation
- [x] Restore replaces the vault with the chosen backup and reopens it
- [x] Encrypted KDBX export opens with the chosen password and contains the entries
- [x] Plaintext CSV export refuses until the master password is entered again AND a
      typed confirmation matches (I8)
- [x] CSV export contains one row per entry and no other secret data
- [x] KDBX import lands entries in a new group; a wrong password is refused
- [x] CSV import parses title/username/password/urls; oversized or malformed files are
      refused with a message, never a crash
- [x] No export or import writes anything outside the chosen paths

## Out of scope

- Sync state files, Recycle Bin restore UI (M6), merging imported duplicates
