# M5-06 Sync status in the UI, setup-google-drive.md, milestone close-out

Milestone: M5 · Sensitive: no · Depends on: M5-01..05

## Goal

The owner-facing half: link and unlink a profile to Drive from the app, a status line that
says exactly which of the spec's six states sync is in, and a settings entry for the interval
that already exists in settings.json. `docs/setup-google-drive.md` grows from the M0 Cloud
setup into the M5 walkthrough (link, first link on a second device, what the statuses mean,
what to do about a conflict), and the M5 "Done when" items in the milestone list are ticked
against tests that ran.

## Files you may change

- app/src/personal_vault/ui/sync_status.py (new), ui/vault_view.py, ui/settings_dialog.py
- app/src/personal_vault/services.py (settings the dialog needs)
- docs/setup-google-drive.md, docs/specs/milestones.md (M5 ticks)
- app/tests/ui/test_sync_status.py

## Spec references

- docs/specs/sync.md — statuses shown in the UI; when sync runs
- docs/specs/architecture.md — ui talks to core only through services

## Acceptance tests (write these first, show them failing)

- [x] the status line shows each of: Synced, Waiting to upload, Offline (retrying at a shown
      time), Conflict (action needed), Reconnect Google, Sync off
- [x] a profile that has never been linked shows Sync off and a "Link Google Drive" button
- [x] linking asks for the file, calls oauth.connect, stores the token, and starts sync
- [x] unlinking removes the token and stops the engine; the vault still works
- [x] the sync interval is editable and lands in settings.json
- [x] setup-google-drive.md covers the Cloud setup, linking, a second device, the statuses
      and conflicts, in plain words
- [x] the M5 "Done when" items are ticked against tests that ran, and G4 is flagged

## What was added beyond the card

The first link to a Drive that already holds this profile's vault used to end at "Needs
attention" with no way for the owner to answer it (ADR-010 asks, and `adopt_remote` /
`upload_local` are the answer, but no UI reached them). The status line now carries **Use
Drive's copy** and **Keep this vault** for that one state; the ask is recognised by
`sync.FIRST_LINK_ASK`.

## Out of scope

Merge (M6), packaging (M6)
