# Install and update (M6-04)

How to build the desktop app into a folder that runs on a machine with no Python, no `uv` and
no checkout — and how to replace it with a newer build without touching your vault.

The browser extension still comes from this repository: there is no published extension, so
[setup-browser.md](setup-browser.md) is still the page for that half.

## What the build makes

`dist/PersonalVault/` — one folder holding two programs and everything they need:

| In the folder | What it is |
| --- | --- |
| `PersonalVault.exe` | the desktop app; windowed, so no console opens behind it |
| `personal-vault-host.exe` | the native messaging host the browser starts; a console program, because Chrome talks to it over stdio |
| `_internal/` | the Python runtime, Qt, and the libraries both programs use |

It is a folder, not an installer. There is nothing to run to "install" it: copy it where you
want it and run the `.exe`. On Linux the two executables have no `.exe` suffix.

PyInstaller builds for the OS it runs on. A build on Windows is a Windows folder; build on
Linux for Linux.

## Build it

You need `uv` (it fetches Python 3.12 itself), and about 300 MB of free disk: 25 MB of
scratch in `build/pyinstaller/` and 144 MB of output in `dist/`. From the repository root:

```
uv sync --group build
uv run --group build python scripts/build_app.py
```

The build takes a few minutes and ends with (the size moves with the OS and the PySide6
version; this is a Windows x64 build in October 2026):

```
built D:\PasswordManager\dist\PersonalVault (142.9 MiB)
  app:  D:\PasswordManager\dist\PersonalVault\PersonalVault.exe
  host: D:\PasswordManager\dist\PersonalVault\personal-vault-host.exe
```

The `build` group is PyInstaller and its community hooks, and nothing else uses it. `uv sync`
without `--group build` does not install it, so CI and the audits are unchanged, and none of
it ends up inside the app.

`build/pyinstaller/` is PyInstaller's scratch folder and `dist/` is the output; both are
git-ignored. To start over, delete them.

## Install it

1. Copy `dist/PersonalVault/` — the whole folder, `_internal/` included; the `.exe` on its
   own will not start — somewhere permanent. For one user, with no administrator rights,
   `%LOCALAPPDATA%\Programs\PersonalVault` works well. Do not run it from `dist/`: the next
   build deletes that folder.
2. Run `PersonalVault.exe`. Nothing else on the machine has to change — no service, no
   scheduled task, no PATH entry. If the folder arrived as a download or a zip from someone
   else, Windows may warn once because the build is not code-signed: **More info → Run
   anyway**. A folder you built and copied locally carries no such mark and normally just
   starts.
3. Your data does **not** live in that folder. It is in `%LOCALAPPDATA%\PersonalVault`
   (`~/.local/share/PersonalVault` on Linux, and whatever `PV_DATA_DIR` says if you set it).
   That is where `profiles/`, `backups/` and `sync/` are, and it is why replacing the program
   folder never touches your vault.
4. The first run shows the profile picker with no profiles. Create one — that is where the
   vault file and its backups are made.

## Point the browser at it

The extension is unchanged by packaging, but the browser cannot start `uv run` on a machine
without this checkout, so on a packaged install the host registration must start
`personal-vault-host.exe` instead. Two ways, depending on the machine:

**On a machine that has this checkout and `uv`** — the script with one option:

```
uv run python scripts/install_native_host.py --host-exe "%LOCALAPPDATA%\Programs\PersonalVault\personal-vault-host.exe"
```

**On the machine that has only the copied folder** — the same three things by hand, because
running the script there would need `uv` (which is the whole point of the packaged build):

1. `launcher.bat` beside the app, holding one line — the path to the host binary. A `.bat`
   expands `%LOCALAPPDATA%` itself; the JSON in step 2 needs the spelled-out absolute path:

   ```
   @echo off
   "%LOCALAPPDATA%\Programs\PersonalVault\personal-vault-host.exe"
   ```

2. `<HOST_DIR>\com.personalvault.host.json`, where `<HOST_DIR>` is any folder you keep:

   ```json
   {
     "name": "com.personalvault.host",
     "description": "Personal Vault browser bridge",
     "path": "<absolute path to launcher.bat>",
     "type": "stdio",
     "allowed_origins": ["chrome-extension://pkmjgefocdecdncjcpdlohfnahebkkpi/"]
   }
   ```

3. Tell the browser where that manifest is — the same value under two keys:

   ```
   reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.personalvault.host" /ve /t REG_SZ /d "<absolute path to the .json>" /f
   reg add "HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.personalvault.host" /ve /t REG_SZ /d "<absolute path to the .json>" /f
   ```

   Brave on Windows reads the first (Chrome's) key, not the second — the Chrome key is
   needed even on a machine with only Brave ([setup-browser.md](setup-browser.md) step 1).

   On Linux, the same JSON goes to
   `~/.config/google-chrome/NativeMessagingHosts/com.personalvault.host.json` (and the Brave
   twin), and `launcher.sh` replaces the `.bat`.

`allowed_origins` names this project's extension ID, which `manifest.json`'s key pins; a
different ID in the address bar means Chrome loaded a different folder and the host will
refuse it. Everything downstream — loading the extension, pairing, the settings in
[setup-browser.md](setup-browser.md) sections 5 to 7 — is the same in both cases.
**Restart the browser afterwards**: Chrome and Brave read the native-host registration once,
at startup.

Copying the `extension/` folder itself to the new machine needs no tools — it is a folder of
text files, loaded unpacked. There is no published extension (M6-04 packaged the desktop app
only), and that is a known limitation, not a step you missed.

## Update it

The program folder holds no data of yours, and the vault is an ordinary KDBX file, so an
update is a folder replacement, not a migration:

1. Close the app (a build cannot replace files that are running).
2. Build the new version: `uv run --group build python scripts/build_app.py`.
3. Replace the old folder with the new one, keeping the same path so the host registration
   and any shortcut still point at it.
4. Start it and unlock.

A newer build reads an older data folder, and the vault format itself is untouched, so moving
forward is always a folder swap. Going *back* is the one case that does not just work: once a
newer build has written `profiles.json`, an older one treats the data folder as newer than it
understands and raises (`SchemaTooNewError`) the moment it tries to write one — and no window
catches that yet, so it surfaces as an error dialog rather than a message. Keep the previous
program folder if you want a way back, and use it *before* you run a newer build, not after.

Your data folder is untouched by all of this, and the old folder is still there until you
delete it — which is the cheapest rollback there is. If a *vault* is damaged rather than the
program, that is [recovery.md](recovery.md), not this page.

Two things to know before relying on it:

- **Nothing updates itself.** There is no auto-update, no version check and no installer
  database entry; you are the updater. `CHANGELOG.md` in the repository is the version log.
- **`pip-audit` and `gitleaks` are run on the repository, not on the built folder.** The
  folder contains the pinned versions from `uv.lock`, so the audit in
  [known-limitations.md](known-limitations.md) is what applies to a given build.

## Uninstall it

Delete the program folder, and delete the native-host files with it: on Windows remove the
`com.personalvault.host` key under both
`HKCU\Software\Google\Chrome\NativeMessagingHosts\` and
`HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\`; on Linux remove
`~/.config/google-chrome/NativeMessagingHosts/com.personalvault.host.json` and its Brave
twin. Then remove the extension at `chrome://extensions`.

Delete `%LOCALAPPDATA%\PersonalVault` **last, and only if you mean it** — the vault, its
backups and the Drive token are all in there, and deleting it is not recoverable by this app.
If you want the entries and not the app, export them first (the **Export…** and **Backups**
buttons in the vault window) or keep a copy of `profiles/<id>/vault.kdbx`; it opens in
KeePassXC without this program at all.

## Before you give the folder to someone else

Building and running it yourself is private use and needs no decision. Handing it to another
person is distribution, and two things are not settled: the project has no license (**Q6**,
ADR-007, open), and the folder embeds **pykeepass**, which is GPL-3.0 — verified from the
license file the build itself carries in `_internal/pykeepass-4.2.0.dist-info/`. So "here is a
folder, it's mine, all rights reserved" is not a thing you can hand over yet. That is the
owner's decision to make, with a lawyer, and it is written down in
[known-limitations.md](known-limitations.md).

## What this build is not

No installer, no `.msi`/`.deb`, no code signing certificate, no icon, no auto-update, and no
single-file executable — deliberately: a one-file build unpacks the whole app into a temp
folder on every start, and a password manager should not do that. `docs/known-limitations.md`
has the rest of what is missing.
