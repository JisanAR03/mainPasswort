# M2-03 Entry list and forms

Milestone: M2 · Sensitive: no · Depends on: M2-02

## Goal
The vault view: a searchable entry list, an add/edit form with every field from the data
model and its limits, show/copy password buttons, delete to the Recycle Bin with
confirmation, and history shown per entry.

## Files you may change

- app/src/personal_vault/services.py
- app/src/personal_vault/ui/vault_view.py
- app/src/personal_vault/ui/entry_form.py
- app/tests/ui/test_vault_view.py, app/tests/ui/test_entry_form.py (pytest-qt)

## Spec references

- docs/specs/data-model.md — Login entry table
- docs/specs/milestones.md — M2-03
- docs/spikes/2026-10-15-kdbx-spike.md — trash, never permanent delete

## Acceptance tests (write these first, show them failing)

- [x] The list shows titles and usernames, never passwords
- [x] Search filters by title, username and notes
- [x] The add form saves a valid entry; every field round-trips
- [x] Form validation rejects an empty title, an over-long username, and a non-http(s) URL
- [x] Show/hide toggles password visibility; passwords are hidden by default
- [x] Edit updates the entry and stores a history version (old title readable in history)
- [x] Delete asks for confirmation, moves the entry to the Recycle Bin, and the entry
      leaves the list
- [x] Password fields never log (canary check through the RedactionFilter)

## Out of scope

- Copy-to-clipboard mechanics (M2-05), generator integration in the form (M2-04),
  Recycle Bin browsing and restore (M6)
