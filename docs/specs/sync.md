# Google Drive sync specification

> Updated 2026-11-05 for the extension-only product (ADR-012). The decision rule, the race
> handling and the conflict choices are unchanged from the original design; sign-in, storage and
> triggers describe the extension.

Sync copies already-encrypted vault files to and from Drive under one rule: it never overwrites
a version it has not seen. A true conflict stops sync and keeps both copies; the extension
offers keep-mine or take-theirs (ADR-006).

## Permissions and sign-in

- Scope: `https://www.googleapis.com/auth/drive.file` only. The extension sees only files its
  OAuth client created or was given. Google classes this scope as non-sensitive.
- OAuth client type: **Web application**, created by the owner in their own Google Cloud project,
  with `https://<extension-id>.chromiumapp.org/` as its authorized redirect URI (the vault page's
  Settings shows the exact address). Sign-in is `chrome.identity.launchWebAuthFlow` with
  `response_type=token`.
- **No refresh token and no client secret exist.** Google returns an access token of about an
  hour, kept in `chrome.storage.session` under `drive_token:<profileId>` and dropped on lock. It is
  renewed silently (`prompt=none`, `login_hint` = the profile's account) while the browser is
  signed in to that Google account. When silent renewal fails, the status says the sign-in needs
  renewing and the owner clicks **Reconnect Google Drive**.
- The consent screen must be **In production**; in Testing mode Google expires grants after 7 days.
- Sync runs only while the profile is unlocked (the token is dropped on lock).
- **`drive.file` is per OAuth client.** The extension's client can open a vault the original
  desktop app made only if it can see that file; the vault page's "Open a vault that is already on
  Google Drive" lists what it can see.

## Drive layout

```text
My Drive/PersonalVault/vault.kdbx        # one file per profile; all are named vault.kdbx
```

Files are told apart by `appProperties` `{"pm_profile_id": "...", "pm_schema": "1"}`, not by name
or folder, so a profile finds its file again if its sync state is lost.

## First-time link and a lost sync state

ADR-010 governs what happens when a profile has no sync state but a file for it may already exist
on Drive:

- The extension searches for a file whose `appProperties.pm_profile_id` matches and that is not
  trashed (a trashed one counts as found).
- If one is found, sync stops with the status "a vault for this profile is already on Google
  Drive" and the owner chooses: **Keep this computer's copy** (upload over it; the Drive copy stays
  in its revision history) or **Take the Google Drive copy** (download, verify it decrypts, replace
  the local vault; the old one becomes the newest backup).
- If none is found, the folder and file are created and uploaded.
- Nothing is adopted or overwritten without that choice; a trashed file always stops sync.

## The decision rule

`decide(local, remote, state)` is a pure function with no network, storage or clock
(`extension/decide.js`, equal to `app/src/personal_vault/sync/decide.py`; an e2e test feeds both
the same 11,520 inputs).

| Local changed since last sync | Remote changed since last sync | Action |
| --- | --- | --- |
| No | No | Nothing |
| Yes | No | Upload, and record the new remote version |
| No | Yes | Download, verify it decrypts, back up local, adopt |
| Yes | Yes | Conflict: keep the remote copy, upload nothing, ask |
| Either | File missing or trashed | Stop and ask; never recreate silently |
| Either | Same content on both sides | Update the sync state only |
| (no state) | A file exists | Ask: the first link |
| (no state) | No file | Upload |

"Remote changed" means Drive's `md5Checksum` differs from `last_synced_remote_md5`. "Local
changed" means `local_dirty` is set or the local SHA-256 differs from `last_synced_local_sha256`.

## Closing the race window

Drive v3 has no atomic "upload only if unchanged" call, so another device could write between our
check and our upload. The engine handles it in three steps:

1. Re-read the remote checksum immediately before uploading.
2. After uploading, list the file's revisions (newest first by `modifiedTime`).
3. If a revision newer than the one we saw, and not ours, appeared, download it to the conflict
   store and raise a conflict. Drive keeps earlier revisions, so nothing is lost silently.

## Resolving a conflict

- **Keep this computer's copy:** upload local over the remote; their copy stays in Drive's
  revision history and in the extension's conflict store.
- **Take the Google Drive copy:** adopt the kept remote copy (it must decrypt); local goes to the
  backups; the adopted copy is then uploaded so it wins on Drive too.

Merging both sides is not available in the extension.

## When sync runs

On unlock, 10 seconds after the last save, every 60 minutes while unlocked, when the browser
reports the network is back, on "Sync now", and when a retry is due. One sync at a time per
profile. The service worker sleeps after about 30 seconds, so every timer is also a
`chrome.alarms` alarm (at most every 30 seconds).

## Errors and retries

A change is committed to IndexedDB before any upload is tried, so an upload that fails never
touches it.

| Error | Behaviour |
| --- | --- |
| No network, timeout, HTTP 5xx, 429, Drive full | Retry with backoff of 30 s, 1, 2, 4, 8, 16 and 30 min (the cap), with jitter; the change stays local |
| HTTP 401 | Drop the token, renew it silently once, then retry |
| Silent renewal refused | Status "the sign-in needs renewing"; local use continues; never a success status |
| HTTP 403 (not quota) | Status "Google Drive refused access" |
| Downloaded file fails to decrypt | Do not adopt it; status "the copy on Google Drive could not be opened" |

Statuses shown on the vault page and in the popup: Synced, Waiting to upload, Syncing, Offline
(with the next try), Google Drive is full, Sign-in needs renewing, Both copies changed (choose),
The vault file is missing or in the bin, A vault is already on Google Drive (choose), Not
connected. Every status shows the last successful upload and whether the latest change is only on
this computer.

## How it is tested

`app/tests/e2e/fake_google.py` is an in-memory Drive v3 and OAuth redirect that the test copy of
the extension points at (through `config.js`). Tests inject a write from "another device", drop
the network, revoke the sign-in, fill the Drive, trash the file, or corrupt a download, and check
the status text, that the local change is kept, and what Drive holds. Real Google gets a manual
smoke test with a throwaway account (`docs/manual-tests.md`).
