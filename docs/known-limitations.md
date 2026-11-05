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
  closes). You can choose a shorter time, "Lock when the screen locks" and "Lock after the computer
  has been idle"; the last two need the optional `idle` permission.
- **A password you paste somewhere.** Copying puts it in the OS clipboard. After 30 seconds the
  extension takes it off again, but only if the clipboard still holds it (something you copied
  meanwhile is left alone); locking does the same at once. To tell, it reads the clipboard then
  (the `clipboardRead` permission) and keeps only a hash of what it copied; `clipboardWrite` lets
  it clear without a click. Clipboard managers that keep a history (Windows Win+V) may still hold
  the copy.
- **A one-time-code secret kept next to the password.** A TOTP secret in the vault means anyone who
  opens the vault gets both factors. Keep the secret in a separate vault profile if that matters.

## Where your data lives

- **Removing the extension, or clearing its data, deletes the vaults kept in the browser.** Drive
  copies and exported `.kdbx` files survive. Keep sync on or export a copy.
- **The vault is encrypted at rest, but its sync state and your profile names are not.** Profile
  names, linked Google account addresses and the list of "never save" sites are readable by anyone
  who can read the browser profile.
- **The extension can read every `http` and `https` page you visit.** It needs that to find login
  fields and notice sign-ins, and asks for it at install. It reads only login fields, only when you
  focus or submit one, and nothing leaves the browser except the encrypted vault to your own Drive.
- **Closed shadow DOM.** Fields inside *open* shadow roots (web components, as on Reddit's login)
  work like any other. A site that builds its login inside a *closed* shadow root hides it from every
  page script and every extension; there the menu does not open, the popup's Fill says "No login
  fields found on this page.", and nothing is offered for saving.
- **A failed sign-in can be offered for saving.** The extension cannot tell whether the site
  accepted the password; choose **Not now**.

## Not in this version

Passkeys, attachments, shared vaults, a phone app, autofill on page load, biometrics, breach
checks (they would send hash prefixes to an outside service; the owner chose not to), Firefox (the
engine needs Chrome's `offscreen` API), a plaintext export (the data model says there is none) and
auto-update. The extension fills only the top frame and only when you click a login; logins inside
iframes get no menu and are never offered for saving.

## Things that work but have limits

- **Changing the master password.** The vault and new backups use the new password at once. Older
  backups and the copy on another device keep the old one until they sync or are restored: a
  restore asks for the old password and re-keys the copy to the current one; a device that finds
  the re-keyed copy on Drive asks for the new password. Forget the new password and nothing opens.
- **Importing.** A CSV holds your passwords in plain text on disk: delete it afterwards. Only
  `http`/`https` addresses are kept (an app link is dropped, the login stays); logins already here
  (same title, username and site) are skipped. A `.kdbx` import leaves out its Recycle Bin and the
  old desktop app's hidden `.app` group.
- **Password health** estimates strength from the length and the kinds of characters and a short
  list of the most common passwords. It is a hint, not a guarantee, and it does not know about
  breaches.
- **Merging after the other device changed the master password** cannot open its copy. The panel
  then asks for the new password and takes that copy; what you changed here since the last sync
  stays in the newest backup (Backups → Restore) and can be brought back from there.
- **Merging a conflict** uses the library's merge: both sides' logins survive, the newer edit of
  a login wins and the older goes to its history, and a login deleted for good on one side stays
  deleted. If Drive changed again after the copy was kept, the conflict comes back instead.
- **Lock after idle** follows the operating system's idea of idle (keyboard and mouse), not use of
  the extension.
- **The keyboard shortcuts** (Alt+Shift+L, Alt+Shift+P) can be taken by another extension or the
  browser; change them at `chrome://extensions/shortcuts` (Brave: `brave://extensions/shortcuts`).

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
