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

### Security

- M6: the encrypted KDBX export no longer carries the hidden `.app` group, so an export of a
  Drive-linked vault no longer hands over the Drive refresh token or the pairing key.

### Changed

- M6: `log.debug("saved entry %s", entry)` became `entry.id`, and pykeepass is held at
  `WARNING` — neither an entry's fields nor the XPath behind a search can reach a log.
