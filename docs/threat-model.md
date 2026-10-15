# Threat model and security boundaries

> Source: design pack draft v0.1, section 5. Status: proposed until gate G0.

The app protects vault files at rest (on disk, in backups and on Google Drive) and limits what
a web page can extract. It cannot protect you from malware running as your OS user, from a
compromised operating system, or from a weak master password. The README states this on its
first page.

## What we protect

- The master password
- The decrypted vault contents
- The derived key
- Each profile's OAuth refresh token
- The backups

## Trust boundaries

| ID | Boundary | Assumption |
| --- | --- | --- |
| B1 | Disk | Anything written to disk is assumed readable by an attacker later (stolen laptop, leaked backup). |
| B2 | Google Drive | Google, or anyone who takes over your Google account, can read, delete or roll back files. |
| B3 | Web page | Every page is hostile. It controls the DOM, the iframes, and what fields look like. |
| B4 | Browser → native host → app | Another extension or local process may try to talk to the host or the socket. |
| B5 | OS user | The OS trusts everything running as you, so it is outside what the app can defend. |

## Threats and mitigations

| Threat | In scope | Mitigation | What remains |
| --- | --- | --- | --- |
| Vault file stolen from disk, backup or Drive | Yes | KDBX 4, Argon2id at 128 MiB, ChaCha20 or AES-256 with HMAC | Offline guessing works against weak master passwords |
| Drive deletes, corrupts or rolls back a file | Yes | The local file is primary; local backups; sync remembers the last version it saw and refuses to go backwards silently | None, if local backups exist |
| Malicious website | Yes | Click-to-fill only, top frame only, the app re-checks the hostname, no vault data in the page before the click | A page can read a password after it is filled (true of every manager) |
| Another extension or local program calls the host or socket | Partly | The host manifest's `allowed_origins` lists only our extension ID; only your user can read the socket; every request must carry a pairing key stored in the vault; there is no "list everything" message | Malware running as you can read the pairing key |
| Malware, keylogger, or memory or clipboard reader running as you | No | Short secret lifetimes, clipboard auto-clear | Full compromise; documented |
| Another person on the same OS account | No | Use separate OS accounts | Documented |
| Unattended unlocked computer | Yes | Idle lock (default 5 minutes), lock on sleep and screen lock, passwords hidden by default | The window before the timer fires |
| Forgotten master password | Yes, as recovery | No backdoor by design; a printed emergency sheet stored offline | The vault cannot be recovered without the password |
| Corrupted file, power loss mid-save, bad sync | Yes | Atomic write with read-back check, rotating verified backups, Drive revisions | None, if one backup is good |
| Malicious or compromised dependency | Yes | Few dependencies, a hash-pinned lock file, pip-audit in CI, no npm packages in the extension | Unknown zero-days |
| AI-generated code with a subtle security bug | Yes | The owner reviews security-sensitive files; invariant tests run on every commit | Bugs the tests do not cover, hence an outside review before real use |

## Security invariants

Each invariant gets an automated test, starting in the milestone where it first applies.
Several tests use a canary password (`CANARY-<random>`) and then search logs, temp folders,
crash output and uploaded bytes for it.

| ID | Invariant | First tested |
| --- | --- | --- |
| I1 | The app never writes a plaintext secret to disk. | M1 |
| I2 | Logs, exceptions and tracebacks never contain entry fields or the master password. | M1 |
| I3 | A save interrupted at any point leaves either the old file or the new file, and it decrypts. | M1 |
| I4 | The bridge never returns a password for an entry whose hostname does not match the requesting tab. | M3 |
| I5 | A locked vault answers every bridge request with `locked` and nothing else. | M3 |
| I6 | Sync never uploads over a remote version it has not seen. | M5 |
| I7 | Sync never adopts a downloaded file until it decrypts with the current key. | M5 |
| I8 | Plaintext export requires the master password again and an explicit confirmation; the default export is encrypted. | M2 |
| I9 | The master password never leaves the desktop process: not to the extension, not to Drive, not to disk. | — |
| I10 | Drive receives only bytes whose SHA-256 equals a file that storage has verified. | M5 |

The "First tested" column comes from the milestone "Done when" lists. The spec does not name
a milestone for I9.

## Known limits

- **Memory:** Python cannot reliably erase secrets from memory. The app keeps secret lifetimes
  short and documents this limit instead of claiming "safe memory handling".
- **Profiles:** profiles are not a wall between people. Anyone using the same OS login can
  install a keylogger. Real separation between people requires separate OS accounts.
- **Master password:** no design can fix a weak one. The desktop app requires at least
  12 characters and recommends a passphrase.
