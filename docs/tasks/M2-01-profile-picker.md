# M2-01 Profile picker and app skeleton

Milestone: M2 · Sensitive: no · Depends on: M1-06

## Goal
The desktop app starts: `services.py` (the only door from ui/ into core/), `__main__.py`
(reads `PV_DATA_DIR`), and a profile picker that lists, creates, renames and deletes
profiles. Renaming never moves files; deleting asks for confirmation.

## Files you may change

- app/src/personal_vault/services.py
- app/src/personal_vault/__main__.py
- app/src/personal_vault/ui/picker.py
- app/src/personal_vault/ui/app.py (empty main window shell for later cards)
- app/tests/ui/test_picker.py (pytest-qt)

## Spec references

- docs/specs/architecture.md — planned structure, "ui/ talks to core only through
  services.py", `PV_DATA_DIR`
- docs/specs/data-model.md — profiles.json
- docs/specs/milestones.md — M2-01

## Acceptance tests (write these first, show them failing)

- [x] The app lists profiles from a `PV_DATA_DIR` test folder; none exist → empty state
- [x] Create shows a name prompt, then the picker lists the new profile
- [x] Rename changes only the display name; the profile folder path is untouched
- [x] Delete asks for confirmation and removes the profile from the list
- [x] `ui/` imports nothing from `core/` directly (import-linter keeps "ui talks to core
      only through services")

## Out of scope

- Unlock (M2-02), the vault view (M2-03), deleting the profile's vault files (M6)
