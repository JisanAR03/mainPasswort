# mainPasswort

A personal, local-first password manager for the desktop, with a browser extension and
optional Google Drive sync. The design spec calls it **Personal Vault**.

> **Status: M0–M5 merged, M6 in progress (2026-10-16).** The desktop app, the browser
> extension and Drive sync are built and covered by the test suite. Gates **G2** (a signed
> `[S]` read-through) and **G4** (the two-device Drive test) are still open, so do not put a
> real password in it yet, and do not turn sync on for a real vault. See
> [Known limitations](docs/known-limitations.md) before you trust it with anything.

## Security limits: read this first

This app protects vault files at rest (on disk, in backups and on Google Drive) and limits
what a web page can extract. It **cannot** protect you from:

- malware running as your OS user, such as keyloggers or memory and clipboard readers,
- a compromised operating system,
- a weak master password.

Profiles do not separate people who share one OS login. Anyone with that login can install a
keylogger, so give each person their own OS account. There is no backdoor: if you forget the
master password, the vault cannot be opened. See
[docs/specs/threat-model.md](docs/specs/threat-model.md), and
[docs/known-limitations.md](docs/known-limitations.md) for everything else this app does not
do — including the parts that have not been reviewed by anyone outside this project.

## Features

Built and tested through M5:

- Separate **profiles** (labels for your own accounts, e.g. Work, Social Media, School),
  each stored as a standard KeePass **KDBX 4** file, so KeePassXC can always open a vault if
  this app breaks
- Add, edit, delete and search logins, plus a password **generator**
- Manual lock, idle auto-lock, lock on sleep, and clipboard auto-clear
- Safe saves with a read-back check and rotating encrypted backups
- A minimal **desktop app** (PySide6)
- A **browser extension** for Chrome and Brave that fills a login only after you click it,
  in the top frame only, with exact site matching
- **Google Drive sync** of the encrypted file that detects conflicts and keeps both copies

Not in v1: TOTP codes, passkeys, attachments, shared vaults, a mobile app, in-page autofill
dropdowns, autofill on page load, unlocking from the browser, biometrics, breach checks,
Firefox and auto-update.

## Tech stack

Python 3.12+, PySide6, pykeepass (KDBX 4), the Google Drive REST API with the `drive.file`
scope, and a plain-JavaScript Manifest V3 extension with no build step. Tooling: uv, ruff,
mypy, pytest, pip-audit and gitleaks. The reasons for each choice are in
[docs/adr/](docs/adr/).

## Setup

Prerequisites.

- Git
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- [KeePassXC](https://keepassxc.org/), which includes `keepassxc-cli`
- Google Chrome and/or Brave

```sh
git clone https://github.com/JisanAR03/mainPasswort.git
cd mainPasswort
cp .env.example .env    # local only, never committed
uv sync                 # create the virtual env from pyproject.toml
```

## How to run

```sh
uv sync                                                  # create the virtual env from uv.lock
uv run --env-file .env python -m personal_vault          # start the desktop app
uv run python scripts/check.py                           # run every lint, type and test check
uv run pytest -m "not e2e and not slow"                  # quick test loop
```

Development and test runs must always set `PV_DATA_DIR` to a throwaway folder (see
`.env.example`), so they never touch a real vault. Real passwords go into the app only after
gate G2.

The browser extension and Drive sync each have their own setup:
[docs/setup-browser.md](docs/setup-browser.md) and
[docs/setup-google-drive.md](docs/setup-google-drive.md).

## Documentation

| Document | Contents |
| --- | --- |
| [Architecture](docs/specs/architecture.md) | Components, layer rules, key flows and the planned project structure |
| [Threat model](docs/specs/threat-model.md) | What is protected, trust boundaries, threats and security invariants I1–I10 |
| [Data model](docs/specs/data-model.md) | On-disk layout, file formats, vault contents, domain types and site matching |
| [Sync spec](docs/specs/sync.md) | Google Drive sync: permissions, decision table, race handling |
| [Browser protocol](docs/specs/browser-protocol.md) | Extension design, native host, message envelope and message list |
| [Milestones](docs/specs/milestones.md) | Gates G0–G5, milestones M0–M6 and the development workflow |
| [ADRs](docs/adr/) | Architecture decision records and the owner's decision log |
| [References](docs/specs/references.md) | External references and source material |
| [Known limitations](docs/known-limitations.md) | What it does not do, does not protect against, and has not had checked |
| [Recovery](docs/recovery.md) | Getting a vault back: local backup, Drive revision, KeePassXC |
| [Manual tests](docs/manual-tests.md) | The owner's test script (gate G2) and the recovery drill (G5) |
| [Task cards](docs/tasks/) | One card per task: what was built, and what proves it |

## License

No license has been chosen yet (open decision, ADR-007). Until a license file is added, all
rights are reserved.
