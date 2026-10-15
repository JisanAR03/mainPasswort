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
