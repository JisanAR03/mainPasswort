# Google Drive sync specification

> Source: design pack v0.1, section 7. Status: accepted at gate G0 (2026-10-15).

Sync copies already-encrypted vault files to and from Drive under one rule: it never
overwrites a version it has not seen. In v1 a true conflict stops sync and keeps both copies;
automatic entry-level merge arrives in M6.

## Permissions and sign-in

- Scope: `https://www.googleapis.com/auth/drive.file` only. The app sees only files it
  created. Google classes this scope as non-sensitive, so no security assessment is needed.
- OAuth client type: Desktop app, loopback redirect with PKCE, via `google-auth-oauthlib`.
- Each user creates their own Google Cloud project and OAuth client. `client_secret.json`
  is git-ignored, and [setup-google-drive.md](../setup-google-drive.md) walks through it.
- Set the consent screen to **In production**. In Testing mode, Google expires refresh
  tokens after 7 days, which looks like random sync breakage.
- The refresh token lives inside the profile's vault (`.app/drive-sync`), so sync runs only
  while that profile is unlocked.
- **`drive.file` is per OAuth client.** The app can only see files created through the same
  Google Cloud OAuth client, so every device must use the same `client_secret.json`.

## Drive layout

```text
My Drive/PersonalVault/<profile_id>/vault.kdbx
```

The file carries `appProperties` `{"pm_profile_id": "...", "pm_schema": "1"}`, so the app
can find it again if `state.json` is lost.

## First-time link and a lost state.json

ADR-010 governs what happens when `state.json` is missing but a file for this profile may
already exist on Drive (first-time link on a second device, or local state loss). In short:

- The app searches `My Drive/PersonalVault/` for a file whose `appProperties.pm_profile_id`
  matches the profile and that is not trashed.
- If one is found, sync stops and asks the owner to choose: **Adopt remote** (download,
  verify it decrypts, back up the local copy, adopt atomically) or **Upload local** (keep the
  remote copy in Drive's revision history and upload the local file).
- If none is found, the folder and the file are created and uploaded normally.
- Nothing is adopted or overwritten without that choice; a trashed file always stops sync.

## The decision rule

The sync engine is a pure function, `decide(local, remote, state) -> Action`, with no
network or disk access, so it can be tested exhaustively. A separate executor performs the
action.

| Local changed since last sync | Remote changed since last sync | Action |
| --- | --- | --- |
| No | No | Nothing |
| Yes | No | Upload, and record the new remote version |
| No | Yes | Download to `incoming/`, verify it decrypts, back up local, adopt atomically |
| Yes | Yes | Conflict: save remote to `conflicts/`, upload nothing, show a banner |
| Either | File missing or trashed | Stop and ask; never recreate silently |
| Either | Same content on both sides | Update `state.json` only |

"Remote changed" means the Drive `md5Checksum` differs from `last_synced_remote_md5`.
"Local changed" means `local_dirty` is set, or the local SHA-256 differs from
`last_synced_local_sha256`.

## Closing the race window

Drive v3 has no atomic "upload only if unchanged" call, so another device could write
between our check and our upload. The engine handles this in three steps:

1. Re-read the remote checksum immediately before uploading.
2. After uploading, list the file's revisions since the last synced version.
3. If any revision other than ours appears, download it to `conflicts/` and raise a
   conflict. Drive keeps earlier revisions, so nothing is lost silently.

## Resolving a conflict (v1)

- **Keep mine:** upload local. The remote copy stays in `conflicts/` and in Drive's revision
  history.
- **Take theirs:** adopt remote. Local goes to `backups/`.
- **Open both:** open the remote copy read-only beside yours, to copy entries by hand.
  Automatic merge replaces this in M6.

## When sync runs

Sync runs on unlock, 10 seconds after the last save, every 60 minutes while unlocked, when
the network returns, and on "Sync now". Only one sync runs at a time per profile.

## Errors and retries

| Error | Behaviour |
| --- | --- |
| No network, timeout, HTTP 5xx, 429 | Retry with backoff of 30 s, 1, 2, 4, 8, 16 and 30 min (the cap), with jitter |
| HTTP 401 | Refresh the access token once, then retry |
| `invalid_grant` on refresh | Status "Reconnect Google"; local use continues |
| Downloaded file fails to decrypt | Keep it in `incoming/` and do not adopt it; status "Remote file unreadable" |
| Disk full while adopting | Abort; by design the original vault is untouched |

Statuses shown in the UI: Synced, Waiting to upload, Offline (retrying at a shown time),
Conflict (action needed), Reconnect Google, Sync off.

## How it is tested

A `FakeDrive` class implements the same interface as the real client, in memory. Tests can
inject a write from "another device" at any step, drop the network, return 429s or corrupt a
download. The real client gets a small manual smoke test against a throwaway Google account.
