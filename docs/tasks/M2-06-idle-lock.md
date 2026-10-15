# M2-06 Idle lock, manual lock, lock on sleep

Milestone: M2 · Sensitive: yes · Depends on: M2-05

## Goal
`ui/idle.py`: lock after `idle_lock_minutes` of inactivity (default 5), a manual Lock
button, and lock on system sleep where the OS reports it (when `lock_on_sleep` is on).
Locking drops the `VaultSession`, clears the clipboard, and returns to the unlock screen.

## Files you may change

- app/src/personal_vault/ui/idle.py [S]
- app/src/personal_vault/ui/vault_view.py, app/src/personal_vault/ui/app.py
- app/src/personal_vault/services.py
- app/tests/ui/test_idle.py (pytest-qt)

## Spec references

- docs/specs/threat-model.md — unattended unlocked computer
- docs/specs/architecture.md — lock flow
- docs/specs/milestones.md — M2-06

## Acceptance tests (write these first, show them failing)

- [x] Simulated inactivity for the configured minutes locks the app
- [x] Any user activity resets the idle timer
- [x] The manual Lock button locks immediately
- [x] A reported system sleep (or OS screen lock, if reported) locks the app when
      `lock_on_sleep` is on, and does not when it is off
- [x] Locking drops the session, clears the clipboard, and shows the unlock screen

## Out of scope

- Real OS sleep events (manual test covers what the OS reports)
