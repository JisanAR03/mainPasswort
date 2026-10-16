# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

0.1.0 is the desktop app, the browser extension and Drive sync, built through milestone M6.
Not released: gates G2 (the `[S]` read-through) and G4 (the two-device Drive test) are open,
and no outside security review has been done. Each milestone below has a card in
[docs/tasks/](docs/tasks/) saying what it built and what proves it.

### Added

- Initial project setup (2026-10-15): README, project documentation in `docs/`
  (architecture, threat model, decisions, data model, milestones, references),
  `.gitignore`, `.env.example` and this changelog.
- Desktop app through M2 (2026-10-15): KDBX vault core on pykeepass, Argon2id with a
  calibrated cost, atomic saves with a backup per save, the Qt UI (profile picker, unlock,
  entry list and forms, generator, clipboard guard, idle lock, settings), backup restore, and
  KDBX/CSV export and import.
- M3 bridge and native host (2026-10-15): the versioned local protocol, the app's loopback
  socket, browser pairing with a code the two sides compare, and the stdio host relay.
- M4 browser extension and M5 Google Drive sync (2026-10-16): the Chrome/Brave extension
  (match, fill, watch for logins to save), the OAuth flow, the Drive client, the sync engine
  with its decision table, and the conflict banner in the app.
- M6 (2026-10-16): entry-level merge for two-sided conflicts, the recovery guide and drill,
  the hardening audit (dependencies, browser permissions, logs, temp files, crash reports),
  the known-limitations page, and the PyInstaller build with its install and update guide.

- Extension-only mode (2026-10-17, EXT-00; proposed ADR-012 not yet accepted): the browser
  extension can be the whole product. Vaults live in the browser (KDBX 4 written by the
  vendored kdbxweb 2.1.1 with Argon2id from hash-wasm 4.12.0, in an offscreen document),
  several profiles each with its own master password and Google account, unlock from the
  popup or the new vault page, a 6-hour unlock kept only in `chrome.storage.session`
  (SHA-256 of the password, never the password), Lock button and Alt+Shift+L, optional lock
  with the screen. Google Drive sync from the extension with the desktop's scope, folder,
  file name and `appProperties`, driven by a port of `decide()` that the e2e suite proves
  equal to the Python one on all 11,520 inputs; every failure has a status (offline,
  sign-in needs renewing, Drive full, conflict, file missing) with the last successful upload
  and whether the latest change is only local. A vault the desktop app syncs can be opened
  from Drive and keeps its profile id. New permissions: `offscreen`, `alarms`, `identity`,
  optional `idle`; CSP allows WebAssembly. Desktop mode is unchanged and still the default.

### Security

- M6: the encrypted KDBX export no longer carries the hidden `.app` group, so an export of a
  Drive-linked vault no longer hands over the Drive refresh token or the pairing key.

### Changed

- M6: `log.debug("saved entry %s", entry)` became `entry.id`, and pykeepass is held at
  `WARNING` — neither an entry's fields nor the XPath behind a search can reach a log.

### Fixed

- The browser extension now does its job on login pages (2026-10-16). Before, nothing ever
  appeared in a page: filling needed the toolbar popup, and a submitted login only set a badge
  on the toolbar icon — and only after "Watch for logins" was turned on — while sites that
  sign in without submitting a form, and two-step logins, were never noticed at all. The
  extension now opens a menu under login fields with the site's saved logins (fill on click,
  "Unlock" when the vault is locked), and after you sign in shows a "Save this login?" /
  "Update saved password?" prompt in the page with Save, Not now and Never for this site. It
  notices form submits, Enter, and sign-in button clicks (fetch logins), and pairs a two-step
  login's username with its password. The popup's update offer now targets only the saved
  login with the same username. Site access to `http`/`https` pages is declared in the
  manifest rather than optional, because the menu and the prompt need every site. Details and
  the evidence in [docs/tasks/fix-extension-inline-fill-save.md](docs/tasks/fix-extension-inline-fill-save.md).
- The first unlock of a new profile creates its vault (2026-10-16). "New profile" writes the
  name into `profiles.json` and nothing else, and no code path ever made the vault file: every
  profile was unopenable, and the unlock window answered "the vault file is damaged and could
  not be read" forever. Found by the owner's first run of the packaged app; every test built its
  own vault, so none of them walked this path. The unlock window now says **Create** when the
  vault is absent, and that password becomes the vault's master password.
