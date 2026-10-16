# Manual test script (gate G2)

Run this after M2 is built and self-reviewed. It exercises the real desktop app on
fake data. Tick every box; a step that behaves differently is a bug to report.

Start the app with:

```
uv run python -m personal_vault
```

Use a **throwaway** master password for this test vault, not a real one. Real
passwords may go into the app only after this script passes and the [S] review below
is signed off.

## 1. Create and unlock

- [ ] 1.1 The unlock window offers "Create a new vault". Create one in a temp folder
      (e.g. `%TEMP%\pv-test\vault.kdbx`) with a strong throwaway password. The vault
      opens to the entry list. A single `vault.kdbx` file exists; no other files
      beside it.
- [ ] 1.2 Lock (Lock button) and unlock again with the same password. Wrong password
      shows "wrong master password" and stays locked.
- [ ] 1.3 Close the app, reopen it, pick the same vault, unlock. The entries you added
      in step 2 are still there (KDBX file is the only store).

## 2. Entries

- [ ] 2.1 Add an entry: title `Manual Test`, username `owner@example.com`, password
      `manual-test-password-123`, URL `https://example.com`. It appears in the list.
- [ ] 2.2 Edit the entry (change the password) and save. The list refreshes and shows
      no leftover error text.
- [ ] 2.3 The entry form refuses an empty title and an empty password (validation
      message, nothing saved).
- [ ] 2.4 Delete the entry and confirm. It is gone; re-lock and unlock — still gone.

## 3. Matching and picker

- [ ] 3.1 Open the picker (the browse/search window) and search "manual": entries whose
      title or URL matches appear; entries that don't match are filtered out.
- [ ] 3.2 The URL `https://example.com` matches an entry whose URL is
      `https://example.com/` (or vice versa) in the list of matching entries.

## 4. Generator

- [ ] 4.1 In the entry form, press Generate…, change the length and flags; the preview
      updates on every change and the masked dots toggle with Show.
- [ ] 4.2 Set a password length below the minimum: Regenerate and Use are disabled and
      an error is shown. Restore a valid length: both work again.
- [ ] 4.3 "Use this password" fills the entry form's password field.

## 5. Clipboard

- [ ] 5.1 Copy a password to the clipboard, paste it somewhere: the value arrives.
- [ ] 5.2 Wait the configured clear delay (default 30 s, see Settings): the clipboard
      is cleared. Copy again, press Lock: the clipboard is cleared immediately.

## 6. Idle lock

- [ ] 6.1 Set the idle lock to 1 minute in Settings. Stop using the mouse and keyboard
      for a minute: the app locks itself.
- [ ] 6.2 With lock-on-sleep enabled, put the machine to sleep and wake it: the app is
      locked. (If it is not, note the Windows version — Qt does not deliver sleep
      events everywhere, and this is a known manual-test check.)

## 7. Settings

- [ ] 7.1 Change clipboard-clear seconds and idle-lock minutes, save, reopen Settings:
      the new values are shown.
- [ ] 7.2 Enter an out-of-range value (e.g. clipboard clear 0): the dialog warns and
      stays open; nothing is saved.
- [ ] 7.3 (Skip if your schema is current.) Settings from a newer app version show all
      controls disabled with a note instead of crashing.

## 8. Backups and restore

- [ ] 8.1 After several edits, open Backups: backups are listed newest first, one per
      save.
- [ ] 8.2 Restore the second-newest backup after confirming: the app reopens the vault
      with that backup's entries. Cancelling the confirmation changes nothing.

## 9. Export and import (I8)

- [ ] 9.1 Export → KDBX with a new password (at least 12 characters): the file opens
      in KeePassXC with the new password, not with the old one. A shorter password is
      refused with a message.
- [ ] 9.2 Export → CSV: with the correct master password but the wrong typed
      confirmation, the export is refused. Type `EXPORT` exactly: a CSV is written
      with one row per entry (title, username, password, urls) and nothing else — no
      notes. Open it in a text editor to check, then delete it.
- [ ] 9.3 Import the CSV from 9.2 into the vault: a new group named
      `Imported <date> UTC` appears with those entries; the originals stay in place.
      Delete the group afterwards.
- [ ] 9.4 Import a text file that is not a CSV: a message says the import failed, the
      app does not crash, and nothing changes.
- [ ] 9.5 Import a KDBX file with the wrong password: refused with a message; with the
      right password the entries land in an Imported group.

## 10. KeePassXC cross-check

- [ ] 10.1 Open the test vault in KeePassXC (GUI) with the throwaway master password:
      all groups and entries match what the app shows.
- [ ] 10.2 A vault the app created opens in KeePassXC with no warnings about the file
      format.

## 11. Recovery drill (M6-02, gate G5)

Walk all three paths in [recovery.md](recovery.md) on the throwaway vault from step 1. Use
`%TEMP%\pv-recovery\` as the data folder (`set PV_DATA_DIR=%TEMP%\pv-recovery` before
starting the app) so nothing here can reach a real vault.

- [ ] 11.1 Add an entry named `before`, then edit an entry so a second backup exists. In
      `%TEMP%\pv-recovery\profiles\<id>\backups\` there are now several
      `vault-<stamp>-<n>.kdbx` files, and the newest is the last by name.
- [ ] 11.2 **Backups window.** Add an entry named `after`, then open Backups and restore the
      backup from *before* it. The entry named `after` is gone and `before` is there: the
      restore really did roll the file back. Note that the file it replaced was not kept —
      this is the step that shows it.
- [ ] 11.3 **By hand.** Close the app. Copy the newest backup over `vault.kdbx`, restart,
      unlock with the same throwaway password: it opens, and it holds what that backup held.
      (No entry added since that backup is present — that is what "a backup is a full file"
      means.)
- [ ] 11.4 **Corrupt file.** With the app closed, overwrite `vault.kdbx` with a text file
      renamed to `vault.kdbx`. Start the app and unlock: the message is "The vault file is
      damaged and could not be read.", not "Wrong master password.", and the app does not
      crash. Restore a backup by hand (11.3) and check the vault opens again.
- [ ] 11.5 **Drive conflict copy.** With sync linked, force a conflict (a second device, or
      the method in [setup-google-drive.md](setup-google-drive.md)). The banner appears and a
      file lands in `sync\conflicts\`. Press **Take theirs**: the vault becomes their copy,
      and their bytes are still in `sync\conflicts\` afterwards.
- [ ] 11.6 **Drive revision.** In Drive's web UI, open the vault file → version history →
      download a revision from before that conflict. It opens in KeePassXC with the
      throwaway master password.
- [ ] 11.7 **KeePassXC GUI.** Open the drill vault in KeePassXC: groups and entries match the
      app, including the Recycle Bin after a deletion. (This repeats 10.1 on the drill vault
      and is the point of the drill — it is the path that does not need this project.)
- [ ] 11.8 **KeePassXC CLI.** `keepassxc-cli ls "<path to vault.kdbx>"` lists the groups;
      it accepts the same password.

## 12. Packaged install (M6-04, M6's "Done when")

This is the one step that has to be run on a **different machine** from the one that built
the app — "a fresh machine installs, unlocks, fills and syncs following only the docs". The
data folder for this drill is a fresh `%TEMP%\pv-packaged\` (`set PV_DATA_DIR=%TEMP%\pv-packaged`),
so nothing here can reach a real vault.

- [ ] 12.1 Build on the machine with the checkout: `uv sync --group build` then
      `uv run --group build python scripts/build_app.py`. It ends with `built … (… MiB)` and
      two executables. Copy `dist\PersonalVault\` to the fresh machine —
      [install.md](install.md) step 1.
- [ ] 12.2 The fresh machine has no Python and no uv. Start `PersonalVault.exe` there. It
      opens to the profile picker, alive and with no error dialog (SmartScreen may warn once:
      More info → Run anyway). Nothing else has to be installed, and nothing is written yet —
      the data folder is made by the first profile.
- [ ] 12.3 Create a profile and unlock. `%TEMP%\pv-packaged\` now holds `profiles.json` and
      the new profile's folder. Add two entries. Close the app and start it again:
      both entries are there and the master password is the one you set. This is the part
      that proves the freeze did not break pykeepass or the vault encryption.
- [ ] 12.4 Register the packaged host on the fresh machine by hand — the launcher, manifest
      and registry value in [install.md](install.md) "Point the browser at it", because the
      fresh machine has no `uv` for the script. Copy the `extension` folder over, load it
      unpacked, restart the browser, pair (code comparison in the app), and **fill** a login
      on a real page from the extension.
- [ ] 12.5 Sync: follow [setup-google-drive.md](setup-google-drive.md) on the packaged build.
      This is also gate **G4**'s two-device test if the other device is the first machine —
      the vault that travels is the same KDBX either way.
- [ ] 12.6 Update: on the building machine make any change, rebuild, copy the new folder over
      the old one on the fresh machine (app closed, same path). Unlock: the entries from 12.3
      are still there, because they were never in the program folder.
- [ ] 12.7 Uninstall drill, on the throwaway data only: delete the program folder, the host
      registration and the extension. `%TEMP%\pv-packaged\profiles\<id>\vault.kdbx` still
      opens in KeePassXC with the throwaway password — deleting the app does not delete the
      vault.

## 13. Browser: fill and save in the page (Chrome and Brave)

Run it once in each browser. Use a **throwaway profile** and fake logins only: in the desktop
app create a profile named `Browser test` with a throwaway master password, and never type a
real password into any page during this section.

Setup:

- [ ] 13.1 Load or reload the extension: `chrome://extensions` (Brave: `brave://extensions`),
      Developer mode on. If Personal Vault is listed, click its reload arrow; if not, **Load
      unpacked** → this repository's `extension` folder. In its **Details**, *Site access*
      reads **On all sites**. Pin it (puzzle icon → pin). **Reload any tab that was already
      open.**
- [ ] 13.2 Turn off the browser's own password saving and other managers —
      [setup-browser.md](setup-browser.md) section 6.
- [ ] 13.3 Start the desktop app, open `Browser test`, unlock. Click the toolbar icon →
      **Pair this browser** → click **Pair** in the app only if the codes match.
- [ ] 13.4 In a terminal in this repository, serve the test pages:
      `uv run python -m http.server 8765 --bind 127.0.0.1 --directory extension/test-pages`

Save, fill, update:

- [ ] 13.5 Open `http://127.0.0.1:8765/login.html`. Click into Username: no menu (the vault
      has nothing for this site yet). Type `alice@example.com` and `fake-pass-1`, click
      **Sign in**. A prompt in the top-right corner asks **Save this login?** and shows
      `127.0.0.1:8765` and `alice@example.com` — no password. Click **Save**: it says "Saved to
      Personal Vault." and closes. The app's entry list now has `127.0.0.1:8765`.
- [ ] 13.6 Open `login.html` again and click into Username. A Personal Vault menu opens under
      it with `127.0.0.1:8765` / `alice@example.com`. Click it: both fields are filled, and the
      page is not submitted (the address does not change).
- [ ] 13.7 The same menu and fill work on `spa.html` (no form), `js-form.html` (wait for the
      form to appear) and `multi-step.html` (the menu fills the username; click **Next**;
      click the password field; the menu fills the password).
- [ ] 13.8 On `login.html` sign in with `alice@example.com` and `fake-pass-2`. The prompt asks
      **Update saved password?** with **Update 127.0.0.1:8765**. Click it. In the app the
      entry's password is now `fake-pass-2`.
- [ ] 13.9 Sign in again with `fake-pass-2`: no prompt (it is the saved password).
- [ ] 13.10 Sign in as `bob@example.com` / `fake-pass-3` and click **Not now**: nothing is
      saved. Then open `http://localhost:8765/login.html` (a different site), sign in as
      `bob@example.com`, click **Never for this site**, and sign in there once more: no prompt.

Locked, not running, iframes:

- [ ] 13.11 Lock the app. On `login.html` click the Password field: the menu says **Unlock
      Personal Vault**. Click it: the app's window comes forward. Unlock, click the field
      again: the menu lists the login.
- [ ] 13.12 Lock the app, then sign in on `login.html` as `carol@example.com` /
      `fake-pass-4`. The prompt says the vault is locked. Click **Save**: the app comes forward.
      Unlock, click **Save** again: saved.
- [ ] 13.13 Quit the app. Click the Password field: the menu says to start the desktop app.
- [ ] 13.14 Open `iframe-login.html`: clicking the fields inside the frame shows no menu, and
      signing in there shows no prompt (the extension works in the top frame only).

A real site, detection only:

- [ ] 13.15 With the app running and unlocked, open a real sign-in page (for example
      `https://github.com/login`). Type a **made-up** email and a **made-up** password and
      click Sign in. The site rejects it, and the prompt still asks to save it — the extension
      cannot tell a failed sign-in. Click **Not now**. Never use a real password here.

Cleanup:

- [ ] 13.16 Stop the `http.server` (Ctrl+C). In the app, delete the `Browser test` profile.

## Cleanup

- [ ] Delete the test vault, its backups and the exported files. Do not keep the
      throwaway password anywhere.

---

## [S] review (gate G2, before any real passwords)

Read these files line by line, in this order, and tick each one:

- [ ] `app/src/personal_vault/core/models.py`
- [ ] `app/src/personal_vault/core/kdf.py`
- [ ] `app/src/personal_vault/core/storage.py`
- [ ] `app/src/personal_vault/core/vault.py`
- [ ] `app/src/personal_vault/core/matching.py`
- [ ] `app/src/personal_vault/core/generator.py`
- [ ] `app/src/personal_vault/core/redaction.py`
- [ ] `app/src/personal_vault/ui/clipboard.py`
- [ ] `app/src/personal_vault/ui/idle.py`

When both sections are fully ticked, M2 is done and real passwords may go into the
app — with a KeePassXC-readable backup kept elsewhere (invariant I3/G2 rule). A CI job
(ADR-009) requires a `Security-Reviewed-By:` trailer on any future change to these
files.
