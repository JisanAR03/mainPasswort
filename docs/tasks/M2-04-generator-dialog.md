# M2-04 Generator dialog

Milestone: M2 · Sensitive: no · Depends on: M2-03

## Goal
A generator dialog reachable from the entry form: every generator option as a control,
a preview, a regenerate button, and "Use this password" fills the form's password field.

## Files you may change

- app/src/personal_vault/ui/generator_dialog.py
- app/src/personal_vault/ui/entry_form.py (a Generate… button)
- app/tests/ui/test_generator_dialog.py (pytest-qt)

## Spec references

- docs/specs/data-model.md — settings.json defaults (generator row)
- docs/specs/milestones.md — M2-04
- app/src/personal_vault/core/generator.py (M1-07)

## Acceptance tests (write these first, show them failing)

- [x] The dialog previews a generated password matching the current options
- [x] Regenerate changes the value; "Use this password" fills the form field
- [x] Disabling a class removes its characters from the preview
- [x] Invalid options (length out of bounds, no class) disable the buttons and show why
- [x] The preview is hidden behind show/hide, and never logs (canary)

## Out of scope

- Persisting generator options (they follow settings.json in M2-07)
