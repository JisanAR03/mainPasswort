# M2-02 Unlock screen

Milestone: M2 · Sensitive: no · Depends on: M2-01

## Goal
Picking a profile leads to an unlock window: master password entry, at least 12 characters
required to proceed, a passphrase recommendation, and the distinct errors for a wrong
password and a damaged vault. Unlock opens the vault view and closes the unlock window.

## Files you may change

- app/src/personal_vault/services.py (unlock path)
- app/src/personal_vault/ui/unlock.py
- app/tests/ui/test_unlock.py (pytest-qt)

## Spec references

- docs/specs/threat-model.md — known limits (master password ≥ 12)
- docs/specs/architecture.md — unlock flow
- docs/specs/milestones.md — M2-02

## Acceptance tests (write these first, show them failing)

- [x] The unlock button stays disabled until the password is at least 12 characters
- [x] A hint recommends a passphrase
- [x] A wrong password shows the `InvalidPassword` message and keeps the window open
- [x] A damaged vault shows the `VaultCorrupted` message and never crashes
- [x] The correct password opens the vault view (a stub in this card) and closes the
      unlock window
- [x] The entered password is not visible on screen (echo mode) and the field is cleared
      after a failed attempt

## Out of scope

- The real vault view (M2-03), idle lock (M2-06)
