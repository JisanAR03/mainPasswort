# M2-05 Clipboard copy with auto-clear

Milestone: M2 · Sensitive: yes · Depends on: M2-03

## Goal
`ui/clipboard.py`: copy a password with a timer that clears the clipboard after
`clipboard_clear_seconds` (default 30) and, where the OS allows, marks the content so
clipboard history and cloud-clipboard skip it. Locking the vault clears it immediately.

## Files you may change

- app/src/personal_vault/ui/clipboard.py [S]
- app/src/personal_vault/services.py (settings read)
- app/tests/ui/test_clipboard.py (pytest-qt)

## Spec references

- docs/specs/threat-model.md — clipboard auto-clear
- docs/specs/data-model.md — `clipboard_clear_seconds`
- docs/specs/milestones.md — M2-05

## Acceptance tests (write these first, show them failing)

- [x] Copy puts the value on the clipboard and starts a timer for the configured seconds
- [x] The timer clears the clipboard; a second copy replaces the value and restarts
- [x] Explicit clear stops the timer and empties the clipboard
- [x] The clipboard value never appears in logs (canary through the RedactionFilter)
- [x] Copying an empty password does nothing

## Out of scope

- OS-level clipboard-history suppression APIs that need native code (documented in the
  file if unavailable via Qt)
