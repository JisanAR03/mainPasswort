# Known limitations

What this app does not do, does not protect against, and has not had checked. Read it before
you trust it with a password you would miss.

The design it is built to is in [docs/specs/](specs/); where this page and the code disagree,
the code is what runs.

## It has not been reviewed by anyone outside this project

No independent security review has happened. `docs/manual-tests.md` has an `[S]` read-through
the owner performs, and CI refuses a change to a sensitive file without a
`Security-Reviewed-By:` trailer — both are the owner reviewing their own work, which is not
the same thing. **Gate G5** (public release, after an outside review) is open, and so are:

| Gate | What it blocks |
| --- | --- |
| G2 | real passwords. Until the `[S]` read-through is signed off, every vault on this machine holds fake data |
| G4 | turning sync on for a real vault: the two-device Drive test has not been run |
| G5 | a public release, and any claim that someone else checked this |

## What it cannot protect you from

These are limits of the design, not bugs waiting to be fixed:

- **Malware running as your OS user.** A keylogger reads the master password as you type it,
  and anything that can read your memory or your clipboard can read a password on its way out.
- **A compromised operating system.** The app trusts the OS for its clock, its file system and
  its process isolation.
- **A weak master password.** Argon2id makes guessing expensive, not impossible; the vault's
  strength is the password's strength.
- **Anyone who shares your OS login.** Profiles are labels, not accounts. Someone else using
  your login can install a keylogger, so give each person their own OS account.
- **Losing the master password.** There is no recovery, no backdoor and no reset. Backups do
  not help: they are encrypted with the same password.
- **A password you paste somewhere.** Copying puts the password in the OS clipboard, where
  other programs can read it. The app clears the clipboard after the delay in Settings; it
  cannot stop what read it in the meantime.

## Not in this version

TOTP codes, passkeys, attachments, shared or team vaults, a mobile app, autofill on page
load, an in-page dropdown, unlocking from the browser, biometrics, breach checks, Firefox,
and auto-update. The browser extension fills only the top frame, and only when you click it.

## Behaviour that is deliberate but will surprise you

- **A restore replaces the vault file and does not keep what it replaced.**
  `VaultSession.restore_backup` writes the backup over `vault.kdbx` without a pre-restore
  copy, so restoring back and forth loses the states in between. Take a copy by hand first if
  you are unsure — [recovery.md](recovery.md) says how.
- **A damaged vault is never repaired.** The app refuses to open a KDBX that fails its header
  check and says so; it has no salvage mode. Recovery means restoring a backup.
- **Nothing restores a backup automatically.** `storage.recover` exists and is tested, but no
  window calls it: choosing which backup to go back to is yours.
- **The Recycle Bin is never emptied.** A deleted entry moves to the Recycle Bin and stays in
  the vault file until you remove it in KeePassXC. It is still in your backups either way.
- **Sync is whole-file.** One device writes at a time; a change on two devices at once becomes
  a conflict (keep mine, take theirs, merge both) rather than being resolved silently. A merge
  covers the Logins group and its deletions — not attachments, not the hidden `.app` group,
  and not more than two copies at once.
- **The vault file holds the app's own secrets.** The pairing key the extension uses and the
  Google Drive refresh token live in the hidden `.app` group inside the vault, so anyone who
  can open the vault can also drive that Drive account. One consequence is deliberate: if you
  move the vault file itself (a by-hand restore, or Dropbox instead of Drive) the link comes
  with it. Everything that leaves as a *copy* leaves them behind — a merge never carries them
  to another vault, a CSV export never contains them, and since M6 the encrypted KDBX export
  drops the `.app` group too (it did not before; M6-03 found it).
- **`<all_urls>` is requested for save detection.** The extension asks for it only when you
  turn watch-for-saves on, and drops it when you turn it off, but while it is on the extension
  can read the address of every page you visit.
- **There is no installer yet.** Running it means a checkout, `uv sync` and
  `python -m personal_vault` — see the [README](../README.md). Packaging is M6-04 and has not
  been decided.
- **No license has been chosen** (ADR-007, open). Until one is added, all rights are reserved
  and you should treat this as a personal project you may read but not reuse.
