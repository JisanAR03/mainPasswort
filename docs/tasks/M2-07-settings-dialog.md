# M2-07 Settings dialog

Milestone: M2 · Sensitive: no · Depends on: M2-06

## Goal
A settings dialog that edits every setting from `settings.json`: idle lock, lock on
sleep, clipboard clear seconds, backup retention, sync interval and quiet period, and
generator options (the generator dialog reads these defaults). Values validate before
save; a newer-schema file is shown read-only.

## Files you may change

- app/src/personal_vault/services.py
- app/src/personal_vault/ui/settings_dialog.py
- app/src/personal_vault/ui/generator_dialog.py (defaults from settings)
- app/tests/ui/test_settings_dialog.py (pytest-qt)

## Spec references

- docs/specs/data-model.md — settings.json defaults
- docs/specs/milestones.md — M2-07

## Acceptance tests (write these first, show them failing)

- [x] The dialog shows the current settings, including defaults on first run
- [x] Changing a value and saving persists it; reopening shows the new value
- [x] Invalid values (zero minutes, bad generator length) are refused with a message
- [x] A settings.json with a newer schema_version shows the dialog read-only
- [x] Generator options changed here are the defaults the generator dialog opens with

## Out of scope

- Sync settings UI effects (they only matter from M5)
