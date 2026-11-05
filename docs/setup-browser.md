# Setup and use

Personal Vault is a Chrome and Brave extension. Your vault is kept encrypted in the browser and,
if you connect it, synced to your own Google Drive. Nothing else needs to run.

**What you should know first:**

- The master password is typed into the browser and the unlocked vault is held in the browser's
  memory. A compromised browser, or a malicious copy of this extension, exposes the vault.
- An unlock lasts up to **6 hours** or until the browser closes. Lock it when you step away
  (popup → Lock, or **Alt+Shift+L**), or turn on "Lock when the screen locks".
- The vault file lives in the extension's storage in this browser profile. **Removing the
  extension, or clearing its data, deletes it.** Keep Google Drive sync on, or export an encrypted
  copy (vault page → Profile → Export).
- Two third-party libraries read and write the vault: kdbxweb and hash-wasm (pinned in
  `extension/vendor/VENDOR.md`).

## 1. Install the extension

You need Chrome or Brave, version 116 or newer.

1. Go to `chrome://extensions` (Brave: `brave://extensions`) and turn on **Developer mode**.
2. **Load unpacked** and choose the `extension` folder of this repository. The extension appears
   with the ID `pkmjgefocdecdncjcpdlohfnahebkkpi`. That ID is fixed by the key in `manifest.json`
   and is where your data is stored, so keep loading the extension from the same folder and keep
   the ID.
3. Pin it: puzzle-piece icon → pin **Personal Vault**.
4. **Reload the tabs that were already open.** The browser adds the extension's page scripts only
   to pages loaded afterwards.

When you update the code (a `git pull`), click the reload arrow on the extension's card. A reload
**locks** the vault (the unlock is kept in memory only) but loses nothing.

## 2. Create a vault

Click the toolbar icon → **Create a vault**. Give the profile a name and a master password of at
least 12 characters; a passphrase of several random words is best. **There is no way to recover a
forgotten master password.** Creating takes a few seconds: the key-derivation work (Argon2id, 128
MiB) is calibrated to about a second in your browser.

You can make more profiles (**New profile…** on the unlock screen). Each has its own vault, master
password and Google account; one is unlocked at a time, and unlocking another locks the first.

## 3. Use it

- **Fill.** Click into a username or password field of a site you have a login for. A Personal
  Vault menu opens under it (titles and usernames, never a password). Click one, or press ↓ then
  Enter: the username and password are filled and the form is **not** submitted. On a two-step login
  the menu fills whichever field is there. The popup does the same with a **Fill** button.
- **Save.** After you sign in with a login the vault does not have, a prompt in the page's top-right
  corner asks **Save this login?** and shows the site and the username (never the password): **Save**,
  **Not now** or **Never for this site**. If the vault has a login with that username for the site
  but the password you typed is different, it asks **Update saved password?** instead. Typing exactly
  the saved password shows nothing. Untick **Offer to save logins** in the popup to stop all offers.
- **Locked, or no vault yet.** On a password field the menu says **Unlock Personal Vault** (or
  **Set up Personal Vault**) and opens the vault page. Unlock there, then click the field again.
- **Plain `http://` sites.** The menu shows a "Not secure" warning and only an `http://` login is
  offered; a login is never offered for saving on plain `http://` (except on this machine).
- **Vault page** (popup → **Open vault**): the full list with search, add, edit, delete (to the
  Recycle Bin), a password generator, copy (the clipboard is cleared after 30 seconds), profiles,
  settings, export, and the Google Drive panel.

## 4. Google Drive sync

The extension uses the `drive.file` scope only: it sees just the files it created. The vault is
uploaded as `PersonalVault/vault.kdbx`. You need your own Google Cloud project (free).

**Make the OAuth client (once).**

1. In https://console.cloud.google.com pick or create a project. Under **APIs & Services → Library**
   enable the **Google Drive API**.
2. **OAuth consent screen** (or *Google Auth Platform → Audience*): User type **External**; set the
   publishing status to **In production** (in *Testing* Google expires the grant after 7 days).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**, application type
   **Web application**, name `Personal Vault extension`. Leave *JavaScript origins* empty.
4. **Authorized redirect URIs**: add exactly the address the vault page shows under Settings, which
   is `https://pkmjgefocdecdncjcpdlohfnahebkkpi.chromiumapp.org/` (with the final `/`).
5. Create it and copy the **Client ID** (ending `.apps.googleusercontent.com`). You do not need the
   client secret and must not paste it anywhere. Google can take a few minutes to activate a client.

**Connect.** Vault page → Settings → paste the Client ID → **Save settings**. With the vault
unlocked, click **Connect Google Drive** in the Google Drive panel, choose the account, and allow
the permission *"See, edit, create and delete only the specific Google Drive files you use with this
app"*. If Google says the app is not verified, **Advanced → Go to … (unsafe)** is expected for your
own client. The panel then shows the account, **Synced with Google Drive** and the time of the last
upload. In Brave, if the Google window never appears, look in `brave://settings/extensions` for an
"Allow Google login for extensions" switch and turn it on (it is a Brave setting; the name may vary).

**How it behaves.** No refresh token and no client secret are stored. Google gives an access token
of about an hour, kept in memory and renewed without asking while the browser is signed in to that
Google account; when it cannot, the status says **the sign-in needs renewing** and you click
**Reconnect Google Drive**. After any change the vault uploads by itself about 10 seconds later; it
also checks on unlock, every 60 minutes and when the network returns. The panel always says what
happened and why (offline, the sign-in needs renewing, Drive full, both copies changed, file
missing), when the last successful upload was, and whether your latest change is **only on this
computer**. A change is saved in the browser first; a failed upload never touches it and is retried
with backoff. A copy on Drive that this browser has not seen is never overwritten: you are asked.

**Both copies changed.** The panel offers **Keep this computer's copy** (upload it; theirs stays in
Drive's version history) or **Take the Google Drive copy** (adopt theirs; yours becomes the newest
backup). Merging both is not available.

**A vault that is already on Drive** (made by another browser, or by the old desktop app): on the
vault page, while nothing is unlocked, expand **Open a vault that is already on Google Drive**, sign
in, choose the vault and type that vault's master password. It becomes a profile here, keeping its
profile id, so both sides keep using the same file. It is listed only if this OAuth client can see
the file; Google's `drive.file` scope shows a client only the files it created, so a file made by a
different client (the old desktop app's) may not be listed.

## 5. Make it your primary password manager

The menu is drawn inside the page; the browser's own dropdown and other password extensions draw over
it. Turn those off so they never compete:

1. **Pin the extension** (step 1.3), so its icon and the badge are always visible.
2. **Turn off the browser's password manager** — `chrome://password-manager/settings` (Brave:
   `brave://password-manager/settings`): switch off **Offer to save passwords and passkeys** and
   **Sign in automatically**.
3. **Move the passwords the browser already holds** into the vault, then delete them from the
   browser (with "Offer to save" off it stops saving new ones but still offers the old ones). Export
   them from that same page (a plaintext CSV: handle it like a password and delete it after), add
   them to the vault, and delete the CSV.
4. **Turn off address autofill** — `chrome://settings/autofill` (Brave: `brave://settings/autofill`)
   → *Addresses and more* → off. This stops most of the browser's own suggestions on username and
   email fields.
5. **Switch off other password managers' extensions** in `chrome://extensions`. A switched-off
   extension can neither fill nor prompt.
6. **Set the shortcut (optional)** — `chrome://extensions/shortcuts`: the lock shortcut defaults to
   Alt+Shift+L.

**Not done for you:** the extension could turn off the browser's "Offer to save passwords" itself
(`chrome.privacy.services.passwordSavingEnabled`), but that needs the extra `privacy` permission and
the browser then shows the setting as controlled by the extension. Step 2 does the same by hand.

## 6. What it cannot do

- **No extension can block another manager's prompts.** If another manager is enabled it can still
  fill and offer to save; switching it off (step 5.5) is the only reliable answer.
- **The browser's own passkey dialogs still appear.**
- **No fill on page load.** Fill is only after your click, so a page that auto-submits needs the
  menu or the popup.
- **Top frame only.** A login form inside an iframe, even a same-site one, gets no menu and is never
  filled or offered for saving.
- **Pages where extensions do not run:** the browser's own pages (`chrome://…`, the Web Store),
  `file://` pages, and sites an administrator's policy blocks.
- **No Firefox build.**

## 7. If it does not work

| Symptom | What to check |
| --- | --- |
| No menu on a login field | Reload the tab (page scripts reach only pages loaded after the extension). Is the vault unlocked? Is there a login for this exact site (an `https://` login never matches an `http://` page; `localhost` and `127.0.0.1` are different sites)? Is another manager covering it (step 5)? |
| The menu says **Unlock Personal Vault** | The vault is locked (after a browser restart, an extension reload, six hours, or Lock). Unlock it in the tab that opens. |
| No save prompt after signing in | Is **Offer to save logins** ticked in the popup? Is the site on the "never" list? Is it plain `http://`, or is the form inside an iframe? Did you type exactly the saved password? |
| `redirect_uri_mismatch` from Google | The redirect URI in the Google client does not exactly match the one the vault page shows (a missing final `/`, a space). Fix it, wait a few minutes. |
| `Access blocked: … has not completed the Google verification process` | The consent screen is in *Testing* and your account is not a test user: publish it (*In production*) or add the account. |
| The panel says **the sign-in needs renewing** | Click **Reconnect Google Drive**. It happens when the browser is signed out of that Google account or the grant was revoked. |
| The panel says **Google Drive is full** | Free space in Drive; your changes are safe in the browser and upload by themselves. |
| Nothing happens on Fill | The page changed since the menu opened (click the field again), or the fields are hidden: only visible fields are filled. |
| The vault is slow to unlock | Argon2 runs in WebAssembly, single-threaded; a vault made elsewhere keeps its settings and takes about three seconds. |
