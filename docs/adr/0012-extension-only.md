# ADR-012 The vault lives in the browser extension

Status: Accepted
Date: 2026-11-05
Supersedes: ADR-003 (browser integration over native messaging), decision D5 (unlock only in the
desktop app) and invariant I9 (the master password never leaves the desktop process).
Amends: ADR-002 (the stack), ADR-004 (where the Drive credential lives).

## Context

ADR-003 kept the vault out of the browser: the extension was a remote control for a desktop
app, "the app must be running". The owner asked for the extension to be the whole product in
October 2026 (the EXT-00 proposal, approved 2026-10-17), has used it daily since, and on
2026-11-05 decided the desktop app is not needed (ADR-013). That reverses ADR-003's premise,
so this record replaces it.

## Decision

- **Where the vault lives.** Each profile's vault is one KDBX 4 file (Argon2id, 128 MiB,
  parallelism 2, iterations calibrated to about a second in the browser; AES-256 with HMAC),
  read and written by **kdbxweb 2.1.1** with Argon2 and MD5 from **hash-wasm 4.12.0**, both
  vendored byte for byte and pinned by SHA-256 (`extension/vendor/VENDOR.md`,
  `scripts/check_vendor.py`). No other cryptography: randomness from
  `crypto.getRandomValues`, SHA-256 from WebCrypto.
- **The engine.** All KDBX work happens in one offscreen document (`engine.js`), because kdbxweb
  needs the browser's own XML parser and its other option, `@xmldom/xmldom 0.7.x`, has
  unpatched advisories and is not shipped.
- **Storage.** The encrypted vault, its 20 newest backups, conflict copies and sync state live
  in the extension's IndexedDB (`personal-vault`); the profile list, settings and sync status in
  `chrome.storage.local`. Nothing in them is plaintext except names and bookkeeping (I1, I12).
- **Unlock.** The master password is typed only into extension pages. An unlock keeps one record
  in `chrome.storage.session` (memory only, cleared when the browser closes or the extension is
  reloaded, updated or disabled): the profile, `SHA-256(password)` (the KDBX password hash, which
  is password-equivalent for that vault; the password itself is never kept), and an expiry six
  hours after the unlock. Lock, expiry, a browser restart and an extension reload all end it.
  One profile is unlocked at a time.
- **Sync.** Google Drive with the `drive.file` scope, the `PersonalVault/` folder, the file name
  `vault.kdbx` and the `appProperties` `{pm_profile_id, pm_schema: "1"}` that the original
  desktop app used, so a vault made there opens here with its profile id. The decision table is
  `decide.js`, a port of the Python `decide()` that an e2e test proves equal on every input
  (I13). The Google credential is an access token from `chrome.identity.launchWebAuthFlow`
  with the owner's own Web-application OAuth client, kept in `storage.session` and renewed
  silently; no refresh token and no client secret exist anywhere.
- **Permissions.** `offscreen`, `alarms`, `identity`; optional `idle` (lock when the screen
  locks, asked for on a click); a content-security-policy that allows WebAssembly and nothing
  else new. `nativeMessaging` is gone.

## Consequences

- The browser now holds the master password while it is typed and the decrypted vault while
  unlocked. A compromised browser, or a malicious build of this extension, exposes the vault.
  I9 no longer holds; `threat-model.md` replaces it with I9' and adds I11 to I13.
- An unlocked vault stays usable for up to six hours unattended (shorter with "lock when the
  screen locks").
- Removing the extension or clearing its data deletes the local vaults. Drive copies and
  exported `.kdbx` files survive.
- Two third-party libraries are part of the trusted base; kdbxweb has had no release since
  2021 and one maintainer. The Python reference code (`app/`) opens everything the extension
  writes with pykeepass, and the tests run it through KeePassXC, on every change.
- Argon2 in WebAssembly is single-threaded: a vault made by the old desktop app unlocks in about
  three seconds and saves in about six (in the background).
- Conflicts follow ADR-006: kept, never merged silently; the extension offers keep-mine or
  take-theirs only.
