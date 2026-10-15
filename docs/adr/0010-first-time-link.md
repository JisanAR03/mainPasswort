# ADR-010 First-time link and a lost state.json

Status: Accepted
Date: 2026-10-15

## Context
The sync decision table does not cover linking a device that has no `state.json` to a
profile that already exists on Drive, or recovering after `state.json` is lost. The owner
asked for the simplest reasonable resolution, specified before M5.

## Decision
When a profile is linked to Drive but `sync/state.json` is missing, sync runs a first-time
link flow before the normal decision table:

1. Search `My Drive/PersonalVault/` for a non-trashed file whose
   `appProperties.pm_profile_id` matches this profile.
2. **A file is found:** sync stops and asks the owner to choose, once:
   - **Adopt remote** — download to `incoming/`, verify it decrypts with the current master
     password, back up the local copy, adopt atomically, then continue syncing.
   - **Upload local** — upload the local file over the remote one; the remote copy stays
     in Drive's revision history and the local previous version in `backups/`.
3. **No file is found:** create the folder and upload the local file normally.
4. **The file is trashed or in Drive's trash:** stop and ask; never recreate silently.

Nothing is downloaded, adopted or overwritten without the owner's choice, and the choice is
remembered in `state.json` (`linked_from: "adopt" | "upload" | "new"`).

## Consequences
A second device can be linked safely, and losing `state.json` no longer risks a blind
overwrite or a silent adoption. The one manual step (choosing adopt or upload) only happens
on first link or after state loss, which matches the v1 conflict policy of asking rather
than guessing. `drive.file` is per OAuth client, so all devices use the same
`client_secret.json` (recorded in `docs/specs/sync.md`).
