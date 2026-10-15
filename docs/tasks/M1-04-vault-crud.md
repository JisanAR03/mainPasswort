# M1-04 Vault CRUD, search and history

Milestone: M1 · Sensitive: yes · Depends on: M1-03

## Goal
A `VaultSession` that adds, edits, deletes, searches and reads history, mapping between
the domain model and KDBX entries, with every save going through M1-03's storage.

## Files you may change

- app/src/personal_vault/core/vault.py
- app/tests/integration/test_vault.py

## Spec references

- docs/specs/data-model.md — Login entry table, "Inside each vault"
- docs/specs/threat-model.md — invariants I1, I2
- docs/spikes/2026-10-15-kdbx-spike.md — `trash_entry`, never `delete_entry`

## Acceptance tests (write these first, show them failing)

- [x] Create, close and reopen returns identical entries
- [x] A wrong password raises `InvalidPassword` and leaves the file byte-identical
- [x] Add, edit, delete (to Recycle Bin) and search behave per the data model
- [x] `keepassxc-cli ls` lists our entries (skipped when the CLI is absent; CI installs it)
- [x] History keeps at most 10 previous versions, oldest first out
- [x] Two profiles' vaults cannot be opened with each other's passwords
- [x] Field length limits from the data model are enforced
- [x] URLs outside http/https are refused

## Out of scope

- Recycle Bin emptying and tombstones (M6), restore UI (M2)
