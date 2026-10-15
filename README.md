# mainPasswort

A personal, local-first password manager for the desktop, with a browser extension and
optional Google Drive sync. The design spec calls it **Personal Vault**.

> **Status: G0 approved (2026-10-15), M0 in progress.** There is no application code yet.
> The design is draft v0.1 of the pre-build design pack.

## Security limits: read this first

This app protects vault files at rest (on disk, in backups and on Google Drive) and limits
what a web page can extract. It **cannot** protect you from:

- malware running as your OS user, such as keyloggers or memory and clipboard readers,
- a compromised operating system,
- a weak master password.

Profiles do not separate people who share one OS login. Anyone with that login can install a
keylogger, so give each person their own OS account. There is no backdoor: if you forget the
master password, the vault cannot be opened. See
[docs/specs/threat-model.md](docs/specs/threat-model.md).

## Features

Planned for v1, the minimum viable version:

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

## Planned tech stack

Python 3.12+, PySide6, pykeepass (KDBX 4), the Google Drive REST API with the `drive.file`
scope, and a plain-JavaScript Manifest V3 extension with no build step. Tooling: uv, ruff,
mypy, pytest, pip-audit and gitleaks. The reasons for each choice are in
[docs/adr/](docs/adr/).

## Setup

Prerequisites. [docs/specs/milestones.md](docs/specs/milestones.md) shows when each one is
first needed.

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

There is nothing to run yet. From milestone M0-01 onward, these commands are planned:

```sh
uv sync                                                  # create the virtual env from uv.lock
uv run --env-file .env python -m personal_vault          # start the desktop app
uv run python scripts/check.py                           # run every lint, type and test check
uv run pytest -m "not e2e and not slow"                  # quick test loop
```

Development and test runs must always set `PV_DATA_DIR` to a throwaway folder (see
`.env.example`), so they never touch a real vault. Real passwords go into the app only after
gate G2.

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

## License

No license has been chosen yet (open decision, ADR-007). Until a license file is added, all
rights are reserved.
