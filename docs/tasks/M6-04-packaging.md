# M6-04 Packaging

Milestone: M6 · Sensitive: no (build tooling and documents; no runtime code path) · Depends on: M5

## Goal

A folder that runs the app on a machine with no Python, no `uv` and no checkout — and a page
that says how to build it, move it, point the browser at it and replace it.

Approved by the owner before anything was installed (rule 5): **PyInstaller**, in a `build`
dependency group, build-time only, never shipped inside the app. PyInstaller turns the app
into a folder of binaries; the alternative on the table was a full `installer`-style solution,
which is more moving parts than this project needs.

## Files you may change

- pyproject.toml (`[dependency-groups] build`)
- uv.lock (resolved by `uv sync --group build`)
- packaging/personal-vault.spec (new)
- scripts/build_app.py (new)
- scripts/install_native_host.py (`--host-exe`, so a packaged install can register the
  packaged host — the script's own tests are updated with it)
- app/tests/unit/test_install_native_host.py (one new test for the packaged launcher)
- docs/install.md (new), docs/setup-browser.md (one pointer to it), README.md,
  docs/known-limitations.md ("There is no installer yet" is no longer true)
- docs/tasks/M6-04-packaging.md (this card)

No `[S]` file is touched: the packaging build does not change `core/`, `bridge/` or `host/`,
it only freezes them.

## Spec references

- docs/specs/milestones.md — M6-04 "Packaging with PyInstaller for your OS; install and
  update guide", and M6's "Done when": *a fresh machine installs, unlocks, fills and syncs
  following only the docs*
- docs/specs/architecture.md — the data folder layout, which is what makes an update a
  folder replacement rather than a migration

## What it produces

`dist/PersonalVault/`, one onedir build holding two programs:

| Executable | Console | Why |
| --- | --- | --- |
| `PersonalVault.exe` | no | a console window behind a GUI is noise |
| `personal-vault-host.exe` | yes | Chrome and Brave speak native messaging over the host's stdio; a windowed build has no stdio to give |

They are analyzed separately. The host imports only the stdlib and `bridge/protocol.py`, so it
gets its own analysis with no Qt at all; the app's analysis is the one that carries Qt. Both
land in one `COLLECT`, which is why the folder carries Qt libraries the host will never load.

onedir, never onefile: onefile unpacks the whole app into a temp folder on every start. A
password manager should not leave copies of itself in `%TEMP%`, and startup would be seconds
slower every time.

PyInstaller does not cross-compile, so the build is per-OS. `scripts/build_app.py` refuses
platforms outside Windows and Linux (Q5) and refuses to run at all when PyInstaller is absent,
saying which command installs it.

## Acceptance tests

- [x] a clean build on this machine, from the repository root:

      ```
      $ uv sync --group build
      $ uv run --group build python scripts/build_app.py
      ...
      built D:\PasswordManager\dist\PersonalVault (142.9 MiB)
        app:  D:\PasswordManager\dist\PersonalVault\PersonalVault.exe
        host: D:\PasswordManager\dist\PersonalVault\personal-vault-host.exe
      ```

      271 files; the largest are Qt's `opengl32sw.dll` (19.7 MiB, the software OpenGL
      fallback), `Qt6Core.dll` (10.0 MiB) and `cryptography`'s Rust extension (9.4 MiB).
- [x] **the packaged host was run, not assumed.** Framed request in, framed reply out, with
      the app not running:

      ```
      host reply: {"v": 1, "id": "", "ok": false, "error": {"code": "app_not_running"}}
      host exit: 0
      ```

      which is the real native-messaging framing (`bridge/protocol.py`) surviving the freeze,
      and the by-design answer when the desktop app is closed.
- [x] **the packaged app was run**, offscreen, with `PV_DATA_DIR` pointed at a throwaway
      folder: still alive after 10 seconds, nothing on stderr, exit only on terminate. It
      created no profile because none was made — the picker does not make one for you.
- [x] **the frozen interpreter runs the whole vault path**, checked with a throwaway build
      (a spec in `%TEMP%` freezing a script that imports `core.vault`, never committed):
      `VaultSession.create` → `add` → `save` (with a backup) → reopen and list → `export_kdbx`
      → read the export back, on a temp folder that was then deleted:

      ```
      frozen: True
      python: 3.12.10
      created: vault.kdbx backups: 0
      saved; backups: 1
      reopened titles: ['Frozen One', 'Frozen Two']
      export titles: ['Frozen One', 'Frozen Two'] carries .app group: False
      cleaned up temp folder: True
      FREEZE CHECK OK
      ```

      That last line is also the M6-03 export fix working inside the freeze: the export
      carries no `.app` group. **The first run of this check failed** — see below.
- [x] `uv run python scripts/install_native_host.py --host-exe …` writes a launcher that
      starts the packaged host, with the repository command unchanged when it is omitted:

      ```
      '@echo off\r\n"D:\\PasswordManager\\dist\\PersonalVault\\personal-vault-host.exe"\r\n'
      '@echo off\r\nuv run --project "D:\\PasswordManager" python -m personal_vault.host.pm_host\r\n'
      ```

      and a `--host-exe` that is not a file exits 1 before writing or registering anything.
      The script was **not** re-run for real: that would rewrite the host registration on the
      owner's machine to point at `dist/`, and only the owner should make that change.
- [x] the by-hand route in install.md — the one a machine without `uv` and without this
      checkout has to take — was run against a throwaway key, and the key deleted afterwards:

      ```
      > reg add "HKCU\Software\PersonalVaultVerify\NativeMessagingHosts\com.personalvault.host" /ve /t REG_SZ /d "C:\Users\murad\AppData\Local\Programs\PersonalVault\com.personalvault.host.json" /f
      The operation completed successfully.
      > reg query "HKCU\Software\PersonalVaultVerify\NativeMessagingHosts\com.personalvault.host" /ve
          (Default)    REG_SZ    C:\Users\murad\AppData\Local\Programs\PersonalVault\com.personalvault.host.json
      ```

      `PersonalVaultVerify` under `HKCU\Software` was then removed; the real Chrome and Brave
      keys were never written to.
- [x] the documented build command works from the state a repository is normally in — after a
      plain `uv sync` has removed the group — because `uv run --group build` puts it back.
      Run again and it exited 0 with the same two executables.
- [x] docs/install.md covers build, install, browser host, update, uninstall and what the
      build deliberately is not
- [ ] **the owner builds and installs on a fresh machine, following only the docs** — M6's
      "Done when" line, and the one thing this card cannot do for itself
- [ ] the owner decides about code signing, an icon and an installer format (below)
- [ ] **Q6 (the licence) is decided before the folder goes to anyone else** — pykeepass is
      GPL-3.0 and the build embeds it (below)

## What the build does not solve (owner's calls, all recorded)

- **No code signing.** Windows SmartScreen warns on first run; the honest instruction is
  "More info → Run anyway", and docs/install.md says exactly that. A certificate costs money
  and needs an identity decision.
- **No icon.** Qt's default is what shows in the taskbar.
- **No installer** (`.msi`/`.deb`/AppImage). Copying a folder is the whole install; an
  installer adds a database entry nobody needs and an uninstall path that could delete data.
- **The extension is not packaged.** There is no published extension and no store listing, so
  `extension/` is still loaded unpacked from the checkout — packaging the desktop app did not
  change that, and docs/install.md says so rather than implying otherwise.
- **A fresh machine cannot run the host installer.** `scripts/install_native_host.py` is part
  of the checkout and runs under `uv`, and the fresh machine has neither; `--host-exe` fixes
  the *command* it writes, not the machine it runs on. So docs/install.md documents the same
  three files by hand, and manual-tests §12.4 uses that route. Making the packaged app offer
  to register the host itself is a feature, not packaging, and needs the owner's decision.

## Found by that check: the build could not create a vault

The first frozen check died on its first statement:

```
File "pykeepass\pykeepass.py", line 1065, in create_database
FileNotFoundError: [Errno 2] No such file or directory:
  '...\dist\freeze-check\_internal\pykeepass\blank_database.kdbx'
```

pykeepass ships its blank KDBX as package data and reads it every time a database is created.
No PyInstaller hook collects it, and nothing imports it, so the analysis never saw it: the
build reported success and would have shipped an app that starts, shows the profile picker and
**dies the moment anyone creates their first profile** — the exact first-run step of M6's
"Done when". The 10-second smoke test could not have caught it; only running the vault path
could.

The fix is one line in the spec, `datas=collect_data_files("pykeepass")`, and it is now in
both the app's analysis and the throwaway check. `scripts/build_app.py` also gained a guard —
`REQUIRED_RUNTIME_FILES` must be present in the built folder, or the build fails with a
message naming the spec file — because "PyInstaller succeeded" and "the app works" are not the
same claim, and this is the failure mode that hides between them.

Worth writing down for the next package: the same class of bug is waiting in any library that
reads data it ships. `certifi`'s `cacert.pem` (what Drive's HTTPS calls verify against) *is*
in the folder, because PyInstaller has a hook for certifi; pykeepass simply does not have one.

## Found by reading what the build carries: pykeepass is GPL-3.0

Collecting pykeepass's data files brought its `dist-info` with it, which is how the licence
became visible — the build itself now carries it:

```
$ grep -i "^License" dist/PersonalVault/_internal/pykeepass-4.2.0.dist-info/METADATA
License: GPL-3.0
Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)
```

The folder embeds pykeepass's code, so handing the folder to another person distributes
GPL-3.0 code, and the project currently has no license at all (Q6, ADR-007, open — "all rights
reserved"). Running a self-built folder is private use and raises nothing; *giving it away* is
the step that needs Q6 settled first. This changes Q6 from "nice to have before publishing the
repository" to "blocks the milestone's own goal — a release you would let a friend install" for
anything but a local build, and it is written into docs/install.md and
docs/known-limitations.md rather than left in this card. Not a legal opinion and not the
owner's decision made here: just the fact, and where it bites.

## Found while writing the update section

A *rollback* does not just work, and the doc first said it did. `ProfileStore.load()` marks
itself read-only when `profiles.json` carries a newer `schema_version`, and the next write
raises — verified on a throwaway folder:

```
$ store.create("Rollback")   # profiles.json holding "schema_version": 99
creating a profile: SchemaTooNewError - profiles.json has a newer schema_version; opened read-only
```

Nothing in `ui/` catches `SchemaTooNewError`, so on the packaged (windowed) build that is
PyInstaller's traceback dialog, not a sentence the user can act on. docs/install.md now says
the rollback caveat plainly instead of recommending the old folder as a safety net.

This is a **one-way** finding, not a bug in packaging: the version guard is doing its job, and
a friendlier message (or a refusal at startup) is a UI card of its own, not M6-04. Recorded
here so it is not lost with the drill.

## Measured, in the doc

142.9 MiB, 271 files, ~300 MB of disk needed to build (25 MB scratch + 144 MB output).

The `build` group is not installed by a plain `uv sync`, so CI jobs and both audits see
exactly what they saw before this card. Verified, not assumed — after a plain `uv sync`:

```
$ uv run python -c "import PyInstaller"
ModuleNotFoundError: No module named 'PyInstaller'
```

`uv run --group build` puts it back, which is why `scripts/build_app.py` prints
`uv sync --group build` when the import fails rather than a traceback.

`gitleaks detect --source . --config .gitleaks.toml` on the branch: `32 commits scanned …
no leaks found` — the build writes no secrets, and `dist/` and `build/` were already
git-ignored.

## Not in CI

There is no build job in `.github/workflows/`. The build takes minutes, needs no vault and
tests nothing the suite does not already cover; it is a release step for the machine that
will ship the folder, not a gate on every push. `scripts/build_app.py` is still linted and
format-checked like every other script.

## Out of scope

Code signing, an icon, auto-update (M6-05's known-limitations page says there is none),
`.crx`/store publishing for the extension, and any change to what the app writes at runtime —
the data folder stays `%LOCALAPPDATA%\PersonalVault` (or `PV_DATA_DIR`), and that is what
keeps an update to a folder swap.
