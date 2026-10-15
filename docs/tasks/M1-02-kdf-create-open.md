# M1-02 KDF calibration; create and open a vault

Milestone: M1 · Sensitive: yes · Depends on: M1-01

## Goal
Argon2id at the D9 settings with calibrated iterations, vault creation and opening, and a
distinct error for a wrong password. Production refuses KDF memory below 64 MiB; only the
test fixture may pass the weak override (8 MiB, 1 iteration).

## Files you may change

- app/src/personal_vault/core/kdf.py
- app/src/personal_vault/core/errors.py
- app/src/personal_vault/core/vault.py (create/open/save skeleton; CRUD comes in M1-04)
- app/tests/integration/test_kdf.py
- app/tests/fixtures/weak_vault.py (the only place allowed to pass `weak_override`)

## Spec references

- docs/specs/data-model.md — "Inside each vault (KDBX 4)"
- docs/specs/milestones.md — "Test-only settings"
- docs/spikes/2026-10-15-kdbx-spike.md

## Acceptance tests (write these first, show them failing)

- [x] A created vault reopens in KeePassXC with Argon2id, 128 MiB, parallelism 2
- [x] A wrong password raises `InvalidPassword`; a damaged file raises `VaultCorrupted`
- [x] `apply_kdf` refuses memory below 64 MiB without the override, and sets the exact
      Argon2id parameters with it
- [x] `calibrate_iterations` returns ≥ 1 from real pykeepass unlock timings

## Out of scope

- Backups (M1-03), entry CRUD (M1-04)
