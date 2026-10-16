# Getting a vault back

Three paths back into a vault that has gone wrong, in the order to try them. Every one of
them works on a **copy** first; nothing here asks you to overwrite the only file you have.

## Where the files are

A profile's files all live in one folder:

```
<data>/profiles/<profile-id>/
  vault.kdbx                        the vault itself — the only store of the entries
  backups/vault-<stamp>-<n>.kdbx    one per save, newest last by name
  sync/state.json                   what sync last saw on Drive
  sync/conflicts/vault-<stamp>.kdbx what another device had, at the moment of a conflict
```

`<data>` is `PV_DATA_DIR` when that is set, otherwise the platform data folder — on Windows
`%LOCALAPPDATA%\PersonalVault`. The `profile-id` is the profile's id as `profiles.json`
records it; the Profiles window lists profiles, and the ids are the folder names.

A backup is a full KDBX file, not a diff: restoring one loses everything saved after it.
Backup names sort by time, so the newest is the last one in the `backups` folder.

## 1. From a local backup

**In the app.** Unlock the vault, open **Backups**, and pick a copy — newest first. Nothing is
overwritten until you confirm, and a backup that will not open is refused with a message
rather than restored. The app then reopens the vault from the restored file.

A restore **replaces** the current `vault.kdbx` and does not keep a copy of what it replaced,
so restore backwards, newest first, and if you are not sure, take a copy by hand (below)
before you confirm.

**By hand, with the app closed** (the app will not open, or a backup is newer than anything
the app will show you):

1. Copy the damaged `vault.kdbx` somewhere safe. Do not delete it; it may hold entries the
   backup does not.
2. Copy the backup you want over it, under the same name:

   ```
   copy backups\vault-20261016T094107Z-0003.kdbx vault.kdbx
   ```

3. Start the app and unlock with the same master password — the backup is an ordinary KDBX
   file, so the password has not changed.

Restores what: everything up to the moment that backup was written. Does not restore: entries
added or edited after it, and the change history of anything newer. KeePassXC opens a backup
directly if you would rather look before you copy.

## 2. From Google Drive

**The conflict copy.** When a merge cannot be settled automatically, the app saves Drive's
bytes under `sync/conflicts/` and shows the conflict banner. **Take theirs** adopts that copy
in place of this vault; **Keep mine** uploads this one; **Merge both** (M6-01) merges the two
and uploads the result. Either way their bytes stay in `sync/conflicts/` afterwards, so a
wrong choice can be undone by repeating the choice you meant.

**An older revision.** Drive keeps the file's version history, so a copy from before the
conflict is not lost. In Drive's web UI: open the file → **Version history** (or right-click →
**Manage versions**) → download the revision you want. Open it in KeePassXC to look at it, or
put it back by hand as in path 1. If it should become the vault, remember to give it the name
`vault.kdbx`.

The app does not offer "restore an arbitrary Drive revision": the only file it writes is the
vault, and the console-free way to get an older copy into it is the Backups window.

Restores what: whichever revision you picked, and only when you pick it. Does not restore:
Drive revisions that were never downloaded — the app does not keep a second copy of them.

## 3. In KeePassXC

The vault is KDBX 4 with Argon2id, and the master password is the master password — no key
file, no YubiKey, nothing this project invented. So another KeePass client opens it directly.
This is the path that does not depend on this project at all, and it is what a rescue from a
broken build looks like.

- **GUI:** *Database → Open Database…*, pick `vault.kdbx`, type the master password. Groups,
  entries, change history and the Recycle Bin are all ordinary KeePass things and are there.
- **Command line:**

  ```
  keepassxc-cli ls "C:\Users\you\AppData\Local\PersonalVault\profiles\p1\vault.kdbx"
  keepassxc-cli show -s "…\vault.kdbx" "Logins/example.com"
  ```

  (`keepassxc-cli` asks for the master password; `-s` prints the password field, so do not
  run that where the output is logged.)

Restores what: nothing to restore — it reads the same file. Does not restore: the parts that
are this app's, not the file's — the browser extension, clipboard clearing, sync. Manual test
sections 10.1 and 10.2 are the owner's check that the files line up on both sides.

## When the vault will not open at all

The unlock window says **"The vault file is damaged and could not be read."** That message
means the file failed before decryption: a missing KDBX signature, an unsupported version, a
truncated header or a header checksum mismatch. A wrong password says something different
("Wrong master password"), so the two are not confused.

What to do:

1. **Do not let the app write to it again.** It cannot — a vault that will not open is never
   saved — but do not delete it either.
2. Restore a backup by hand (path 1). The newest backup that opens is almost always good.
3. If no backup opens, the `sync/conflicts/` copies are the next place to look (path 2).
4. Keep the damaged file. Nothing here repairs a KDBX; if the entries in it matter, it is a
   file for a KeePass recovery tool or a person, not for this app.

## What the app does not do

- It does not repair or salvage a damaged KDBX.
- It does not automatically restore a backup when a vault fails to open. The storage layer has
  a tested `recover()` that finds the newest backup which still decrypts, but no window calls
  it: the choice of which backup to go back to is the owner's, and the Backups window is where
  it is made.
- It does not keep a second copy of Drive's history, and it does not empty the Recycle Bin, so
  a trashed entry stays in the file until you delete it in KeePassXC or a later version adds
  that.
