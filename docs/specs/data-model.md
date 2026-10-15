# Data model and file formats

> Source: design pack v0.1, section 6. Status: accepted at gate G0 (2026-10-15).

The app stores four things: a plaintext profile list, one encrypted KDBX 4 vault per profile,
a plaintext sync-state file per profile, and plaintext settings. Only the vault holds
secrets. Every other file is safe to read, but must never gain a secret field.

## On-disk layout

The app folder comes from `platformdirs` (for example `%APPDATA%\PersonalVault` on Windows).
Development and test runs override it with `PV_DATA_DIR`.

```text
PersonalVault/
  profiles.json                          # profile list, no secrets
  settings.json                          # app settings, no secrets
  logs/app.log                           # redacted, rotated at 1 MB
  profiles/<profile_id>/
    vault.kdbx                           # the encrypted vault
    backups/                             # verified encrypted copies
      vault-20261015T101500Z-0042.kdbx
    sync/
      state.json                         # sync bookkeeping, no secrets
      incoming/                          # downloaded file waiting for verification
      conflicts/                         # remote copies kept after a conflict
```

Every JSON file and the vault are written atomically: write a temp file in the same folder,
flush it, then rename it over the original. Every JSON file carries `schema_version`. A file
with a newer version than the app understands is opened read-only and never overwritten.

## profiles.json

```json
{
  "schema_version": 1,
  "last_used_profile_id": "p_4kq7m2xw",
  "profiles": [
    {
      "id": "p_4kq7m2xw",
      "display_name": "Personal",
      "created_at": "2026-10-15T10:15:00Z",
      "sync_enabled": false
    }
  ]
}
```

The profile ID is random, so renaming a profile never moves files. Display names are visible
to anyone who can read your disk. Profiles are labels for one person's own accounts (for
example Work, Social Media, School) — not a separation between people.

## Inside each vault (KDBX 4)

| Setting | Value |
| --- | --- |
| Format | KDBX 4.x |
| Key derivation | Argon2id, 128 MiB, parallelism 2, iterations calibrated at creation |
| Cipher | ChaCha20 or AES-256, whichever pykeepass writes reliably (confirmed in M0) |
| History per entry | 10 previous versions |
| Groups | `Logins` (default), `Recycle Bin`, `.app` (hidden in our UI) |

Key derivation is calibrated for desktop use only (open question Q3: no phone access).

The hidden `.app` group holds two entries that the app manages:

- `drive-sync`: the refresh token in the protected Password field, plus the account email and
  the Drive file IDs.
- `browser-pairing`: the extension pairing key.

KeePassXC shows both with a "do not edit" note.

## Login entry

| App field | Stored in KDBX as | Rules |
| --- | --- | --- |
| `id` | Entry UUID | Never changes; the merge key for sync |
| `title` | Title | 1–200 characters |
| `username` | UserName | Up to 500 characters |
| `password` | Password (protected field) | Up to 4,096 characters; wrapped in `SecretStr` in Python |
| `urls` | URL, then extra URLs as `KP2A_URL_1`, `KP2A_URL_2`, … | `http` or `https` only; the same convention KeePassXC uses |
| `notes` | Notes | Up to 64 KiB |
| `tags` | Tags | Up to 20 |
| `match_subdomains` | Custom field `PM_MATCH_SUBDOMAINS` | Default `false` |
| `created_at`, `updated_at` | Times: creation, last modification | UTC; merge uses `updated_at` |
| `deleted` | Moved to Recycle Bin; emptying it records a tombstone | Tombstones support merge in M6 |

## Python domain model

The UI and the bridge use these types and never touch pykeepass objects, which keeps the
library replaceable.

```python
class SecretStr:
    """Holds a secret; repr() and str() print '***' so it never lands in logs."""

    def reveal(self) -> str: ...


@dataclass(frozen=True)  # what search results and the browser list get
class LoginSummary:
    id: UUID
    title: str
    username: str
    hosts: tuple[str, ...]


@dataclass  # what the edit form gets
class LoginEntry:
    id: UUID
    title: str
    username: str
    password: SecretStr
    urls: list[str]
    notes: str
    tags: list[str]
    match_subdomains: bool
    created_at: datetime
    updated_at: datetime
```

## Site matching rules

1. Lower-case the hostname, convert international names to punycode, and drop a trailing dot.
2. Match when the page hostname equals an entry hostname.
3. If `match_subdomains` is on, also match `*.entry-hostname`, but never the parent domain.
4. Never fill an `https` entry into an `http` page. An `http` entry fills only on `http`,
   with a warning in the popup.
5. Ports must match when the entry URL names one.

## sync/state.json

```json
{
  "schema_version": 1,
  "drive_folder_id": "1Fold3r...",
  "drive_file_id": "1F1le...",
  "last_synced_remote_version": 42,
  "last_synced_remote_md5": "9e107d9d372bb6826bd81d3542a419d6",
  "last_synced_local_sha256": "e3b0c442...",
  "local_dirty": true,
  "last_success_at": "2026-10-15T10:20:00Z",
  "last_error": null,
  "conflict": null
}
```

When a conflict exists, `conflict` holds the detection time, the remote version, and the path
of the kept copy.

## settings.json defaults

| Setting | Default |
| --- | --- |
| `idle_lock_minutes` | 5 |
| `lock_on_sleep` | `true` |
| `clipboard_clear_seconds` | 30 |
| `backups_keep_recent` | 20 saves |
| `backups_keep_daily` | 30 days |
| `sync_interval_minutes` | 60 |
| `upload_quiet_seconds` | 10 |
| `generator` | Length 20; upper, lower, digits, symbols; exclude look-alike characters |

## Import and export

- The default export is an encrypted KDBX copy, optionally under a new password.
- Plaintext CSV export exists only behind invariant I8: it needs the master password again
  and an explicit confirmation.
- Imports accept KDBX and CSV. They are parsed as untrusted input with size limits, and land
  in a new group for review.
