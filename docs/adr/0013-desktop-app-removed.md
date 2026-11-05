# ADR-013 The desktop app is removed; the extension is the product

Status: Accepted
Date: 2026-11-05
Supersedes: ADR-008 (host install paths), the PyInstaller packaging of M6-04, and the desktop
parts of ADR-002 (PySide6) and ADR-004 (sync running in the desktop app).

## Context

After ADR-012 the extension does everything the desktop app did for daily use. The owner has
used the extension alone for more than three weeks and decided that nothing else is needed.
Keeping a second product costs a second set of tests, a native-messaging host, a packaging
build, a GPL-3.0 dependency in what would be distributed (pykeepass, the open Q6 licence
blocker) and a mode switch in the extension.

## Decision

Deleted: the Qt windows (`ui/`), the browser link (`bridge/`, `host/`, pairing, the native-host
installer and its registry keys), the Google sync engine and OAuth for the desktop, packaging,
the desktop-only parts of the core (profiles, settings, import and export, the password
generator, the logging filter), the tests for all of it, and the extension's desktop mode.

Kept, as the **Python reference implementation used only by the tests** (`app/`): the vault
reader and writer on pykeepass (`core/vault`, `storage`, `kdf`, `models`, `matching`, `merge`,
`errors`) and the sync decision table (`sync/decide`, `sync/state`). The extension is tested
against it: its vaults must open in pykeepass and in KeePassXC with every field intact, its
URL matching and sync decisions must equal the reference on every input. pykeepass is a
development dependency, not a shipped one.

Unchanged on purpose: the extension's ID (the manifest `key`), its IndexedDB schema and its
`chrome.storage` keys, so the vault of a browser that already runs the extension keeps working.
`app/tests/e2e/test_upgrade.py` seeds the stored format of the previous version and fails if it
stops working; on 2026-11-05 the real previous version of the extension (git 254a275) also wrote a
vault and synced it, and the browser was restarted on the new code (12 checks, in Chromium, Chrome
and Brave), once, by hand, because CI cannot fetch the old code. Old `mode` and `pairing_key` keys
are ignored, not deleted.

## Consequences

- Features the desktop app had and the extension does not: restoring a backup from the UI (the
  20 backups are kept in IndexedDB but nothing restores one), changing the master password,
  importing or exporting `.kdbx` and CSV files from disk (export of an encrypted copy exists),
  merging both sides of a conflict, and plaintext CSV export (I8 is gone with it).
- Nothing outside the repository is touched: an installed packaged app, the
  `%LOCALAPPDATA%\PersonalVault` data folder and the `com.personalvault.host` registry keys
  stay until the owner removes them. A desktop vault still opens in the extension through "Open a
  vault that is already on Google Drive".
- The shipped extension contains no GPL code; the licence question (Q6, ADR-007) no longer
  blocks handing the extension to someone else, though a licence is still undecided.
