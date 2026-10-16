# M5-04 engine.py: triggers, single-flight, backoff, executor

Milestone: M5 · Sensitive: yes · Depends on: M5-03

## Goal

The part that acts. It runs `decide` and then does exactly one thing with it:

- **upload** — re-read the remote md5 immediately before uploading, upload only bytes whose
  SHA-256 matches the file `storage` verified, then list the revisions since the last synced
  version: a revision that is not ours means another device wrote first, so that copy is
  downloaded to `conflicts/` and the result is a conflict, never an overwrite (I6, I10).
- **download** — into `sync/incoming/`, verify it decrypts with the current master password,
  back up the local file, adopt atomically; a file that does not decrypt stays in `incoming/`
  and is never adopted (I7).
- **conflict** — keep the remote copy in `conflicts/`, upload nothing, raise the banner.
- **first-time link** — ADR-010: search, then ask; nothing is adopted or overwritten without
  that choice.

Plus the boring parts the spec pins down: one sync at a time per profile, backoff of 30 s, 1,
2, 4, 8, 16 then 30 minutes with jitter, one token refresh on 401, and the triggers (unlock,
10 s after a save, every `sync_interval_minutes`, network return, Sync now).

## Files you may change

- app/src/personal_vault/sync/engine.py (new)
- app/src/personal_vault/sync/state.py (write side)
- app/tests/sync/test_engine.py
- app/tests/security/test_invariants.py (I6, I7, I10 canaries)

## Spec references

- docs/specs/sync.md — the decision rule, closing the race window, when sync runs, errors
- docs/specs/threat-model.md — I6, I7, I10

## Acceptance tests (write these first, show them failing)

- [x] an edit made offline uploads by itself once the network is back
- [x] a write injected between the check and the upload becomes a conflict: the remote copy
      is kept in `conflicts/`, the local file is untouched, nothing is overwritten (I6)
- [x] a corrupted download is never adopted: it stays in `incoming/`, the local vault is
      unchanged, and the status says the remote file is unreadable (I7)
- [x] the bytes uploaded are the bytes on disk, and their SHA-256 matches the verified file;
      the canary secret never appears in them (I10)
- [x] a download that would replace the vault is atomic and backed up first
- [x] two sync runs never overlap; a second request while one is running is coalesced
- [x] the backoff schedule is exactly 30 s, 1, 2, 4, 8, 16, 30 min (capped) with jitter, and
      a success resets it
- [x] a 401 refreshes the token once and retries; `invalid_grant` stops and says Reconnect
- [x] the remote file missing or trashed stops sync and asks, in both first-link and
      steady-state cases
- [x] state.json records what the spec's example shows, atomically

## Out of scope

The conflict UI (M5-05), status text (M5-06)
