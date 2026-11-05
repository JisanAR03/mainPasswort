# mainPasswort

A personal password manager that **lives in your browser**: a Chrome and Brave extension that
keeps your encrypted vault in the browser, fills and saves logins on any site, and syncs the
encrypted file to your own Google Drive. There is no server, no account with us and no desktop
program to run. The extension is called **Personal Vault**.

> **Status:** extension-only since 2026-11-05 ([ADR-012](docs/adr/0012-extension-only.md),
> [ADR-013](docs/adr/0013-desktop-app-removed.md)). Gates G2 (a signed `[S]` read-through) and G5 (an
> outside security review) are still open, so read
> [Known limitations](docs/known-limitations.md) before you trust it with a password you
> would miss.

## Security limits: read this first

The extension protects your vault files at rest (browser storage, backups, Google Drive) and limits
what a web page can extract. It **cannot** protect you from:

- malware running as your OS user, such as keyloggers or memory and clipboard readers,
- a compromised browser, or a malicious copy of this extension (the vault is decrypted **inside
  the browser** while unlocked, for up to six hours),
- a weak master password.

There is no backdoor: if you forget the master password, the vault cannot be opened. Removing the
extension or clearing its data **deletes the vaults kept in the browser**; keep Google Drive sync on
or export a copy. See [docs/specs/threat-model.md](docs/specs/threat-model.md).

## Features

- **Several profiles**, each with its own vault, its own master password and its own Google
  account. Only the unlocked profile's logins are ever shown or filled.
- **Standard KeePass vaults** (KDBX 4: Argon2id, 128 MiB, AES-256), so KeePassXC can open any
  vault if this extension ever breaks.
- **A suggestion menu** under login fields: click a saved login to fill it. It fills only after
  your click, in the top frame, on the exact site (no look-alike domains), and never submits.
- **A "Save this login?" / "Update saved password?" prompt** after you sign in, with Save, Not now
  and Never for this site. Works for plain forms, two-step logins and single-page apps.
- **Lock** with one click or **Alt+Shift+L**; an unlock lasts at most six hours and ends when the
  browser closes. Optionally lock when the screen locks.
- **Google Drive sync** of the encrypted file with the `drive.file` scope only: it uploads about 10
  seconds after a change, and also on unlock, hourly and when the network returns. Every failure is
  shown and explained; a change is never lost because an upload failed; a copy it has not seen is
  never overwritten.
- A password **generator**, search, edit and delete (to a Recycle Bin), and an encrypted export.

Not included: TOTP codes, passkeys, attachments, shared vaults, a phone app, fill on page load,
biometrics, breach checks, Firefox, restoring a backup from the interface, changing the master
password, and importing a file from disk. See [Known limitations](docs/known-limitations.md).

## Install

You need Chrome or Brave (Chromium 116 or newer, which the engine's `getContexts` call needs) and, for sync, a Google Cloud project of your own.
The extension is loaded unpacked from this repository; there is no store listing.

1. Clone the repository: `git clone https://github.com/JisanAR03/mainPasswort.git`
2. Open `chrome://extensions` (Brave: `brave://extensions`), turn on **Developer mode**, click
   **Load unpacked** and choose the `extension` folder. The extension ID is
   `pkmjgefocdecdncjcpdlohfnahebkkpi`; it is fixed by the key in `manifest.json`, so your data
   survives a reload.
3. Pin it (puzzle-piece icon), open it, and **Create a vault**.
4. Optional but recommended: connect Google Drive and turn off the browser's own password manager.
   [docs/setup-browser.md](docs/setup-browser.md) has every step.

## Develop and test

The product is `extension/`: plain JavaScript, no build step, no npm. `app/` is a Python reference
implementation of the vault format that the tests check the extension against; nothing in it ships.

```sh
uv sync --all-groups                    # Python tools, pykeepass and Playwright
uv run playwright install chromium      # once
uv run python scripts/check.py          # ruff, mypy, bandit, vendored-code and logging checks, unit tests
uv run pytest -m e2e                    # the extension in a real browser, against a fake Google
PV_E2E_BROWSER=chrome uv run pytest -m e2e   # or brave (the installed browsers)
```

Tests use fake vaults, a fake Google and temporary browser profiles; they never touch a real vault.
`KEEPASSXC_CLI` can point at `keepassxc-cli` (it is found automatically on a default Windows or
Linux install) so the KeePassXC compatibility tests run.

## Documentation

| Document | Contents |
| --- | --- |
| [Setup](docs/setup-browser.md) | Install, Google Drive, using it, the browser settings that make it your primary manager, troubleshooting |
| [Known limitations](docs/known-limitations.md) | What it does not do, does not protect against, and has not had checked |
| [Recovery](docs/recovery.md) | Getting your passwords back: backups, Drive versions, KeePassXC |
| [Manual tests](docs/manual-tests.md) | The checks only a person can do, and the `[S]` review list |
| [Architecture](docs/specs/architecture.md), [threat model](docs/specs/threat-model.md), [data model](docs/specs/data-model.md), [sync](docs/specs/sync.md), [messaging](docs/specs/browser-protocol.md) | The design |
| [Decisions](docs/adr/) | Why each choice was made (ADR-012 and ADR-013 are the current shape) |
| [Task cards and spikes](docs/tasks/), [docs/spikes/](docs/spikes/) | The history of how it was built |

## License

No license has been chosen yet (ADR-007), so all rights are reserved and you may read but not reuse
this code. The extension ships no GPL code (kdbxweb and hash-wasm are MIT); the Python reference
uses pykeepass (GPL-3.0) in the tests only.
