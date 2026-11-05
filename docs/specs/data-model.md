# Data model and file formats

> Rewritten 2026-11-05 for the extension-only product (ADR-012). The vault format, the entry fields
> and the matching rules are unchanged from the original design, so a vault made by the old desktop
> app opens here and the reverse.

The extension stores three things: one encrypted KDBX 4 vault per profile, bookkeeping about each
(sync state, status), and a profile list with settings. Only the vault holds secrets. Everything
else is safe to read but must never gain a secret field (I1).

## Where it lives

IndexedDB `personal-vault`, version 1 (`extension/idb.js`):

| Store | Key | Holds |
| --- | --- | --- |
| `vaults` | `profileId` | `{profileId, bytes, sha256, md5, savedAt}`: the encrypted KDBX file |
| `backups` | auto id, index `profileId` | `{profileId, bytes, savedAt}`: the 20 newest previous files |
| `sync` | `profileId` | the sync state below |
| `conflicts` | auto id, index `profileId` | `{profileId, bytes, keptAt, remote_md5, remote_version}`: Drive copies kept after a conflict |

`chrome.storage.local`: `profiles` (`[{id, name, createdAt, googleEmail}]`), `settings`
(`googleClientId`, `lockOnScreenLock`), `last_profile_id`, `offer_to_save`, `never_save` (site
origins), `sync_status:<profileId>`. Older versions also wrote `mode` and `pairing_key`; they are
ignored, not deleted.

`chrome.storage.session` (memory only): `unlocked`, `drive_token:<profileId>`, `menu_<tabId>`,
`pending_save`, `username_step`, `login_seen`.

**The schema is a contract.** The extension ID and these names do not change without a migration
and a test for it (`app/tests/e2e/test_upgrade.py`).

The profile id is random, `p_` plus six random bytes in URL-safe base64, so renaming a profile
changes nothing stored. It is also the vault's `pm_profile_id` on Drive. Profile names are visible
to anyone who can read the browser profile. Profiles are labels for one person's own accounts
(Work, School), not a separation between people.

## Inside each vault (KDBX 4)

| Setting | Value |
| --- | --- |
| Format | KDBX 4.0 |
| Key derivation | Argon2id, 128 MiB, parallelism 2, iterations calibrated at creation (about a second in the browser); a vault made elsewhere keeps its own settings |
| Cipher | AES-256 |
| History per entry | 10 previous versions |
| Groups | `Logins`, `Recycle Bin`, and a hidden `.app` group |

The `.app` group is the original desktop app's: it held `drive-sync` (a Drive refresh token) and
`browser-pairing`. The extension never reads or writes it and keeps it intact when a vault that has
one is opened and saved. (The old desktop app's refresh token inside a vault is one reason to treat
every copy of such a vault as sensitive.)

## Login entry

| Field | Stored in KDBX as | Rules |
| --- | --- | --- |
| `id` | Entry UUID | Never changes; the merge key |
| `title` | Title | 1 to 200 characters |
| `username` | UserName | Up to 500 characters |
| `password` | Password (protected field) | Up to 4,096 characters |
| `urls` | URL, then extra URLs as `KP2A_URL_1`, `KP2A_URL_2`, … | `http` or `https` only; up to 20; the same convention KeePassXC uses |
| `notes` | Notes | Up to 64 KiB |
| `tags` | Tags | Up to 20 |
| `match_subdomains` | Custom field `PM_MATCH_SUBDOMAINS` | `"true"` or `"false"`; default false |
| `created_at`, `updated_at` | Times | UTC |
| deleted | Moved to the Recycle Bin; the move is time-stamped | |

A login saved from a page is stored with the page's origin only (`https://host[:port]/`, never the
path or the query string, which can carry tokens) and titled with the host.

## Site matching rules

`extension/matching.js`, equal to `app/src/personal_vault/core/matching.py` (tested on a table of
URLs):

1. Lower-case the hostname, convert international names to punycode, drop a trailing dot.
2. Match when the page hostname equals an entry hostname.
3. If `match_subdomains` is on, also match `*.entry-hostname`, never the parent domain.
4. Never fill an `https` entry into an `http` page. An `http` entry fills only on `http`, with a
   warning shown.
5. Ports must match when the entry URL names one.

`http` on `localhost` and `127.0.0.1` is treated as secure for the purposes of offering to save
(it never leaves the machine); any other plain `http` page is never offered for saving.

## Sync state (the `sync` store)

```json
{
  "profileId": "p_4kq7m2xw",
  "drive_folder_id": "1Fold3r...",
  "drive_file_id": "1F1le...",
  "last_synced_remote_version": 42,
  "last_synced_remote_md5": "9e107d9d372bb6826bd81d3542a419d6",
  "last_synced_local_sha256": "e3b0c442...",
  "local_dirty": true,
  "last_success_at": "2026-10-15T10:20:00Z",
  "last_error": null,
  "conflict": null,
  "linked_from": "adopt"
}
```

When a conflict exists, `conflict` holds the detection time, the remote version and md5, and the
id of the kept copy in the `conflicts` store.

## Settings and fixed values

| Setting | Value |
| --- | --- |
| Unlock lasts | 6 hours, absolute (`config.js` `UNLOCK_HOURS`) |
| Upload quiet period | 10 seconds |
| Sync interval | 60 minutes while unlocked |
| Backups kept | 20 per profile |
| Clipboard clear | 30 seconds after Copy on the vault page |
| Generator | Length 20; upper, lower, digits, symbols; look-alike characters (`0Oo1lI\|`) excluded; randomness from `crypto.getRandomValues` |
| Master password | At least 12 characters |
| Lock when the screen locks | Off by default; needs the optional `idle` permission |

## Export

The vault page's **Export encrypted copy** downloads the stored `.kdbx` as it is (the same master
password opens it in KeePassXC). There is no plaintext export and no import from a file; a vault
comes in through Google Drive.
