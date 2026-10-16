# M5-05 Conflict banner and the three resolution choices

Milestone: M5 · Sensitive: no · Depends on: M5-04

## Goal

When sync stops on a conflict, the vault view says so plainly and offers the spec's three
choices, each of which is the engine's method and nothing more:

- **Keep mine** — upload local; the remote copy stays in `conflicts/` and in Drive's history.
- **Take theirs** — adopt remote; the local file goes to `backups/` first.
- **Open both** — open the kept remote copy read-only beside yours, to copy entries by hand.

Nothing is uploaded, adopted or deleted by *showing* the banner; the choices are the only
paths, and each one ends with the banner gone and the status line telling the truth.

## Files you may change

- app/src/personal_vault/ui/sync_banner.py (new)
- app/src/personal_vault/ui/vault_view.py
- app/tests/ui/test_sync_banner.py

## Spec references

- docs/specs/sync.md — resolving a conflict (v1)
- docs/specs/milestones.md — "never silently loses an edit"

## Acceptance tests (write these first, show them failing)

- [x] with no conflict the banner is not in the window at all
- [x] a conflict shows the banner with all three choices and the time it was detected
- [x] Keep mine uploads and clears the conflict; the remote copy is still in `conflicts/`
- [x] Take theirs backs the local file up before adopting, and clears the conflict
- [x] Open both opens the kept copy read-only and leaves the conflict standing
- [x] a resolution that fails (offline, rejected) leaves the banner up and reports the error

## Out of scope

Automatic entry-level merge (M6)
