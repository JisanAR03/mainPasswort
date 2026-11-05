# Known limitations

What this extension does not do, does not protect against, and has not had checked. Read it before
you trust it with a password you would miss. Where this page and the code disagree, the code is what
runs.

## It has not been reviewed by anyone outside this project

No independent security review has happened. `docs/manual-tests.md` has an `[S]` read-through that
the owner performs, and CI refuses a change to a sensitive file without a `Security-Reviewed-By:`
trailer — both are the owner reviewing their own work, which is not the same thing. **Gate G2** (a
signed `[S]` read-through) and **gate G5** (a public release, after an outside review) are open.

## What it cannot protect you from

These are limits of the design, not bugs waiting to be fixed:

- **The browser holding the vault.** The master password is typed into the browser and the unlocked
  vault lives in its memory (the extension's offscreen document). A compromised browser, another
  program that can read the browser's memory, or a malicious copy of this extension exposes it.
- **Malware running as your OS user.** A keylogger reads the master password as you type it;
  anything that can read your clipboard can read a password on its way out.
- **A weak master password.** Argon2id makes guessing expensive, not impossible.
- **Anyone who shares your browser profile.** Profiles are labels, not accounts.
- **Losing the master password.** There is no recovery, no backdoor and no reset.
- **An unattended unlocked browser.** An unlock lasts up to **6 hours** (or until the browser
  closes). "Lock when the screen locks" shortens it; it needs the optional `idle` permission.
- **A password you paste somewhere.** Copying puts it in the OS clipboard for 30 seconds; the
  extension clears it afterwards on a best-effort basis.

## Where your data lives

- **Removing the extension, or clearing its data, deletes the vaults kept in the browser.** Drive
  copies and exported `.kdbx` files survive. Keep sync on or export a copy.
- **The vault is encrypted at rest, but its sync state and your profile names are not.** Profile
  names, linked Google account addresses and the list of "never save" sites are readable by anyone
  who can read the browser profile.
- **The extension can read every `http` and `https` page you visit.** It needs that to find login
  fields and notice sign-ins, and asks for it at install. It reads only login fields, only when you
  focus or submit one, and nothing leaves the browser except the encrypted vault to your own Drive.
- **A failed sign-in can be offered for saving.** The extension cannot tell whether the site
  accepted the password; choose **Not now**.

## Not in this version

TOTP codes, passkeys, attachments, shared vaults, a phone app, autofill on page load, biometrics,
breach checks, Firefox, and auto-update. The extension fills only the top frame and only when you
click a login; logins inside iframes get no menu and are never offered for saving.

**Present in the old desktop app, not here** (ADR-013):

- **Restoring a backup from the interface.** The 20 previous copies per profile are kept in the
  browser's storage, but nothing restores one. The recovery path is Google Drive's version history
  (`docs/recovery.md`).
- **Changing the master password.**
- **Importing a vault or a CSV from disk.** A vault comes in through Google Drive. The encrypted
  export is the only export; there is no plaintext export.
- **Merging both sides of a conflict.** The extension offers keep this computer's copy or take
  Drive's; the other copy stays in Drive's version history.
- **Emptying the Recycle Bin.** A deleted login stays in the vault until you remove it in
  KeePassXC.

## Behaviour that is deliberate but will surprise you

- **A reload, an update or a restart locks the vault.** The key is kept in memory only
  (`chrome.storage.session`), so none of those can leave it behind on disk.
- **Unlocks are slower than a desktop manager's.** Argon2 runs in WebAssembly, single-threaded. A
  vault the extension creates is calibrated to about a second; a vault made elsewhere keeps its own
  settings and takes about three seconds to unlock and twice that to save (in the background).
- **The vault file inside the browser is not the only place secrets hide.** A vault made by the
  old desktop app carries a hidden `.app` group that may hold that app's Google refresh token. The
  extension keeps it intact and never reads it; treat every copy of such a vault as sensitive.
- **Sync is whole-file.** One device writes at a time; a change on two devices at once becomes a
  conflict rather than being resolved silently.
- **Open a vault from Google Drive lists only what this client can see.** `drive.file` shows a
  client only the files it created, so a vault made by a different Google client (the old desktop
  app's) may not be listed. (Not checked against every setup; see `docs/manual-tests.md` §4.)
- **No installer, no store listing.** The extension is loaded unpacked from the repository folder
  and updated with a `git pull` and a reload.
- **kdbxweb has had no release since 2021** and has one maintainer. Two libraries (kdbxweb and
  hash-wasm) are part of the trusted base; they are copied byte for byte and pinned by hash, and the
  tests open every file the extension writes in pykeepass and KeePassXC.
- **No license has been chosen** (ADR-007, open). Until one is added, all rights are reserved.
