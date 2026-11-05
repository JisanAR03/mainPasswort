# Threat model and security boundaries

> Rewritten 2026-11-05 for the extension-only product (ADR-012, ADR-013). The earlier model,
> which kept the master password and the decrypted vault out of the browser, is in the git
> history; its invariants I4 to I8 and I10 were about the desktop app and its bridge.

The product protects vault files at rest (browser storage, backups, Google Drive) and limits what a
web page can extract. It **cannot** protect you from malware running as your OS user, a
compromised browser, a malicious build of this extension, or a weak master password. The README
says so on its first page.

## What we protect

The master password, the decrypted vault, the key derived from the master password (kept as
`SHA-256(password)` while unlocked), the Google access token, and the encrypted vaults and
backups.

## Trust boundaries

| ID | Boundary | Assumption |
| --- | --- | --- |
| B1 | Disk and browser profile | Anything written there (IndexedDB, `storage.local`) is readable by an attacker later: stolen laptop, leaked profile. Only encrypted data goes there. |
| B2 | Google Drive | Google, or anyone who takes over the Google account, can read, delete or roll back files. |
| B3 | Web page | Every page is hostile: it controls the DOM, iframes and what fields look like. |
| B4 | Other extensions and programs | May try to message this extension. It has no `externally_connectable`, and every message is accepted by the browser-reported sender, never by what it claims. |
| B5 | OS user and the browser itself | Everything running as you, and the browser, can see browser memory. Outside what the product can defend. |
| B6 | The extension's own code | Whoever controls the code that is loaded controls the vault: it is loaded unpacked from the repository the owner reviews. |

## Threats and mitigations

| Threat | In scope | Mitigation | What remains |
| --- | --- | --- | --- |
| Vault file stolen from browser storage, a backup or Drive | Yes | KDBX 4, Argon2id at 128 MiB, AES-256 with HMAC | Offline guessing works against weak master passwords |
| Drive deletes, corrupts or rolls back the file | Yes | The browser copy is primary; 20 backups; sync refuses to go backwards silently | None, if a backup or an export exists |
| Malicious website | Yes | Fill only after a click in an extension-origin frame, top frame only, visible fields only, the engine re-matches the URL, no vault data in the page before the click | A page can read a password after it is filled (true of every manager) |
| Another extension or program messages this one | Yes | Sender checks by `MessageSender`; one-time tokens for frames; the engine answers only the service worker | Malware with debugger access to the browser reads anything |
| A malicious or compromised build of this extension | Yes | Loaded unpacked from the reviewed repository; vendored libraries pinned by hash and checked in CI; `[S]` files need the owner's review | Whoever controls the loaded code controls the vault |
| Malicious or compromised dependency | Yes | Two libraries only, vendored byte for byte; `@xmldom/xmldom` (vulnerable) is not shipped; no npm at all | Unknown zero-days |
| Browser compromise, memory or clipboard reader, keylogger | No | Short secret lifetimes, clipboard cleared after 30 s | Full compromise; documented |
| Unattended unlocked browser | Yes | Six-hour expiry, Lock button and shortcut, optional lock when the screen locks | Up to six hours of exposure |
| Uninstalling or clearing extension data deletes the vaults | Yes | Drive sync, encrypted export | An unsynced, unexported vault is gone |
| Forgotten master password | Yes, as recovery | No backdoor by design | The vault cannot be opened without it |
| kdbxweb corrupts or mis-writes a vault | Yes | Read-back check before every replace, 20 backups, KeePassXC and pykeepass open the output in every test run | Bugs the tests do not cover |
| Corrupted file, power loss mid-save, bad sync | Yes | One IndexedDB transaction per replace, verified before it, Drive revisions | None, if one backup is good |

## Security invariants

Each has an automated test. Tests of the extension run in a real browser (`app/tests/e2e/`).

| ID | Invariant | Where tested |
| --- | --- | --- |
| I1 | The browser never stores a plaintext secret: IndexedDB, `storage.local` and `storage.session` hold only encrypted bytes, names and bookkeeping (the password hash in `storage.session` is the one exception, I11). | `test_a8_no_plaintext_secret_in_any_storage`; `security/test_invariants.py` for the reference vault |
| I2 | No log, error or message carries an entry field, the master password, a key or a token. | `scripts/check_no_console.py` (no console call at all); error replies carry a code only |
| I3 | A weak key-derivation setting exists only in test fixtures; the shipped extension refuses less than 64 MiB. | `test_shipped_config_is_the_real_one`; `security/test_invariants.py` |
| I4 | A password is never returned for an entry whose URL does not match the requesting tab. | the engine's `secret` op; menu and fill tests with look-alike hosts |
| I5 | A locked vault answers every vault request with `locked` (or `no_vault`) and nothing else. | `test_a2_lock_ends_it_immediately_and_leaves_no_key` |
| I6 | Sync never uploads over a Drive copy it has not seen; a first link and a missing file ask instead of acting. | `test_a7_a_write_from_another_device_is_a_conflict_never_an_overwrite`, `test_i6_a_first_link_never_overwrites_what_it_finds`, `test_a7_a_trashed_file_asks_instead_of_recreating` |
| I7 | A downloaded file is never adopted until it decrypts with this vault's key. | `test_i7_a_download_that_does_not_open_is_never_adopted` |
| I9' | The master password is typed only into extension pages and is never stored, sent to a page, a content script, Drive or disk. | `test_a8_no_plaintext_secret_in_any_storage` (the session record holds the hash, not the password) |
| I10 | Drive receives exactly the bytes the engine verified and stored. | `test_i10_drive_receives_exactly_the_stored_vault` |
| I11 | The key lives only in `chrome.storage.session` and the engine's memory, for at most six hours, and is gone after Lock, expiry, a browser restart and an extension reload. | `test_a2_*` |
| I12 | A locked profile's titles, usernames, notes and URLs exist only inside its encrypted file: no index, cache, badge or message carries them. | `test_a3_a_locked_profile_is_unreachable_everywhere` |
| I13 | `decide.js` returns the same action as the reference `decide()` for every input; `matching.js` agrees with the reference matching rules. | `test_a7_decide_js_agrees_with_python_on_every_input`, `test_a7_matching_js_agrees_with_python` |
| U1 | Data written by an earlier version keeps working: the extension ID, the IndexedDB schema and the storage keys do not change without a migration. | `test_upgrade.py` |

(I8, plaintext export behind a re-typed password, went with the desktop app; the extension exports
an encrypted `.kdbx` only.)

## Known limits

- **Memory:** JavaScript cannot erase secrets from memory. Lifetimes are kept short and the limit
  is documented rather than hidden.
- **Profiles are labels**, not a wall between people. Anyone using the same browser profile can
  open the extension; give each person their own browser profile or OS account.
- **A weak master password** cannot be fixed by design. The vault page requires 12 characters and
  recommends a passphrase.
