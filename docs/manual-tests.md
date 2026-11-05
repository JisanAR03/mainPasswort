# Manual test script

The automated suite (`uv run pytest -m e2e`, in Chromium, Chrome and Brave) covers the extension
against a fake Google. This script is for what only a person can check: a real Google account, a
real site, the keyboard shortcut, the OS screen lock. Tick every box; a step that behaves
differently is a bug to report.

Use a **throwaway browser profile** and **fake logins** only: never type a real password into a page
during this script, and never use your real vault.

## 1. Install and first run

- [ ] 1.1 In a new browser profile (Chrome: profile picture → Add → Continue without an account;
      Brave: menu → Profiles → Add profile), load the extension unpacked from the `extension`
      folder ([setup-browser.md](setup-browser.md) step 1). The ID is
      `pkmjgefocdecdncjcpdlohfnahebkkpi`. Pin it.
- [ ] 1.2 Click the toolbar icon: the popup says "No vault in this browser yet." and offers
      **Create a vault**.
- [ ] 1.3 Create a profile `Test` with a throwaway master password (12 characters or more). It
      takes a few seconds. The vault page shows the empty list and "Test — unlocked until …" about
      six hours ahead.
- [ ] 1.4 Add a fake login: title `Fake Site`, a username, **Generate** a password, **Save**. It
      appears in the list.

## 2. Fill, save, update

- [ ] 2.1 Serve the test pages:
      `uv run python -m http.server 8765 --bind 127.0.0.1 --directory extension/test-pages`
- [ ] 2.2 Open `http://127.0.0.1:8765/login.html`. Click Username: no menu (nothing is saved for
      this site yet). Type `alice@example.com` and `fake-pass-1`, click **Sign in**. A prompt in the
      top-right corner asks **Save this login?** with `127.0.0.1:8765` and the username, no
      password. Click **Save**: "Saved to Personal Vault." and it closes.
- [ ] 2.3 Open `login.html` again and click Username: a menu opens under it with the login. Click
      it: both fields fill and the page is not submitted (the address does not change).
- [ ] 2.4 The same menu and fill work on `spa.html` (no form), `js-form.html` (wait for the form)
      and `multi-step.html` (the menu fills the username; **Next**; click the password field; the
      menu fills the password).
- [ ] 2.5 On `login.html` sign in with the same username and `fake-pass-2`: **Update saved
      password?** → **Update**. Sign in again with `fake-pass-2`: no prompt.
- [ ] 2.6 Sign in as `bob@example.com` and click **Not now**: nothing saved. On
      `http://localhost:8765/login.html` (a different site) click **Never for this site**, then sign
      in there again: no prompt.
- [ ] 2.7 `iframe-login.html`: clicking the fields inside the frame shows no menu and signing in
      shows no prompt (top frame only).
- [ ] 2.8 A real sign-in page (for example `https://github.com/login`), with a **made-up** username
      and password: the prompt still asks to save it (a failed sign-in cannot be told apart).
      Click **Not now**.

## 3. Lock and unlock

- [ ] 3.1 Press **Alt+Shift+L**: the popup says Locked. On a password field the menu says **Unlock
      Personal Vault**; clicking it opens the vault page.
- [ ] 3.2 Unlock from the popup. Click **Lock** in the popup: locked again.
- [ ] 3.3 Close the browser completely and start it again: the vault is locked, the profile is
      still there, the master password opens it.
- [ ] 3.4 Reload the extension at `chrome://extensions`: locked, nothing lost.
- [ ] 3.5 Vault page → Settings → tick **Lock when the screen locks** and accept the permission.
      Lock the OS screen (Win+L) and come back: the vault is locked.
- [ ] 3.6 Create a second profile; unlocking it locks the first, and the first profile's logins
      never show while the second is unlocked.

## 4. Google Drive with a real account (Chrome, then Brave)

Follow [setup-browser.md](setup-browser.md) section 4 with a **throwaway Google account**.

- [ ] 4.1 **Connect Google Drive** reaches **Synced with Google Drive** with the account and the
      time. On drive.google.com, `PersonalVault/vault.kdbx` exists. Do this in Chrome and in Brave.
- [ ] 4.2 Edit a login; within a minute Drive shows a new version of the file (Manage versions).
- [ ] 4.3 Turn the network off (airplane mode) and edit a login: the panel says Google Drive cannot
      be reached, the change is only on this computer, and when it will try next. Turn the network
      on: it uploads without a click.
- [ ] 4.4 At myaccount.google.com → Security → Third-party access, remove the app's access, then
      edit a login: the panel says the sign-in needs renewing and never says Synced; the last
      successful upload time does not move. **Reconnect Google Drive**: it syncs.
- [ ] 4.5 Download `vault.kdbx` from Drive and open it in KeePassXC with the master password: the
      logins are there.
- [ ] 4.6 With a vault made by the old desktop app on the same Drive: on the vault page while
      nothing is unlocked, **Open a vault that is already on Google Drive** → is it listed? (It is
      only if this OAuth client can see the file.) Record the answer. If it opens, edits made in the
      browser show up when the other side syncs.

## 5. The browser's own manager

- [ ] 5.1 With the browser's password saving and autofill off ([setup-browser.md](setup-browser.md)
      section 5) and other managers off, sign in on a page: only Personal Vault offers anything.

## 6. Recovery drill

Follow [recovery.md](recovery.md) "The three paths to practise".

- [ ] 6.1 Export an encrypted copy and open it in KeePassXC.
- [ ] 6.2 Delete the profile, then bring it back from Drive.
- [ ] 6.3 Download an older version from Drive and open it in KeePassXC.

## 7. Cleanup

- [ ] 7.1 Stop the `http.server`. Delete the test profiles on the vault page, the throwaway
      account's `PersonalVault` folder on Drive, and the test browser profile.

---

## [S] review (gate G2)

Read these files line by line and tick each one. CI requires a `Security-Reviewed-By:` trailer on a
change to any of them (`scripts/check_sensitive_review.py`).

The vault and the key:

- [ ] `extension/engine.js` — the only KDBX reader and writer; `normalize()`
- [ ] `extension/local.js` — profiles, unlock, lock, the session record
- [ ] `extension/idb.js` — storage
- [ ] `extension/config.js` — the shipped values (weak settings exist only in tests)
- [ ] `extension/vendor/VENDOR.md` and `scripts/check_vendor.py` — what is pinned and how

The service worker and the page-facing parts:

- [ ] `extension/background.js` — sender checks, tokens, classification, save and update
- [ ] `extension/inline.js`, `extension/menu.js`, `extension/prompt.js` — no vault data in the page
- [ ] `extension/detect.js`, `extension/fill.js` — sign-in detection; what a fill touches
- [ ] `extension/matching.js`, `extension/generator.js`, `extension/vault.js`
- [ ] `extension/manifest.json` — permissions, CSP, the pinned key

Sync and Google:

- [ ] `extension/sync.js`, `extension/decide.js`, `extension/drive.js`, `extension/oauth.js`

The Python reference (it is the test oracle):

- [ ] `app/src/personal_vault/core/vault.py`, `storage.py`, `kdf.py`, `models.py`, `matching.py`,
      `merge.py`, and `sync/decide.py`

When every box is ticked and section 4 has passed in Chrome and Brave, gate G2 can be signed off.
