# Browser extension setup (M4)

The extension is a thin remote control for the desktop app. When you click into a login
field on a site you have a saved login for, a small Personal Vault menu opens under the field
with that site's logins; click one to fill it. When you sign in with a login the vault does
not have — or with a new password for one it has — a "Save this login?" or "Update saved
password?" prompt appears in the page's top-right corner. The extension stores no vault data,
and it handles a password only when you choose to fill one or submit one.

The extension is loaded unpacked from the repository folder — there is no published
extension, packaged or otherwise (M6-04 packaged the desktop app only). Chrome and Brave both
do this, and both take the same native host.

> The desktop app must be running. If it is not, the menu on a password field and the popup
> both say so and do nothing else — that is by design, not a fault.

## 1. Install the native host

The browser cannot talk to the app directly; it starts a small host process that relays one
request at a time over a local socket only your OS user can reach.

```
uv run python scripts/install_native_host.py
```

It writes the host files under `extension/native-host/` (git-ignored) and registers them:

| Browser | Windows (registry) | Linux |
| --- | --- | --- |
| Chrome | `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.personalvault.host` | `~/.config/google-chrome/NativeMessagingHosts/com.personalvault.host.json` |
| Brave | Chrome's key above — see the note below | `~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.personalvault.host.json` |

**Brave on Windows reads Chrome's registry key**, not one of its own. The script also writes
`HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.personalvault.host`, but
a host registered only there is "not found" by Brave (checked with Brave 1.97 on Windows,
2026-10-16): it is the Chrome key that makes Brave work, so do not delete it while you use
Brave. The Linux paths are the documented ones and have not been checked on a Linux machine.

The host launcher runs the app's package straight out of this repository, so the install
must be repeated if you move the folder. **Restart the browser afterwards**: Chrome and
Brave read the native-host registration once, at startup.

On a machine running the packaged build (M6-04) rather than a checkout there is no `uv run`
to start, so register the packaged host instead — same script, one option, on a machine that
still has `uv`:

```
uv run python scripts/install_native_host.py --host-exe "%LOCALAPPDATA%\Programs\PersonalVault\personal-vault-host.exe"
```

On the fresh machine that has only the copied folder, [install.md](install.md) gives the same
three files by hand (launcher, manifest, registry value), which needs no Python at all.

## 2. Load the extension (Chrome)

1. Go to `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. **Load unpacked** → pick the `extension` folder in this repository.
4. The extension appears with the ID `pkmjgefocdecdncjcpdlohfnahebkkpi`. That ID is fixed
   by the key in `manifest.json`; the host registration names it, so a different ID means
   the extension was loaded from a different folder.

## 3. Load the extension (Brave)

Same steps at `brave://extensions`. Brave is Chromium, so the manifest and the host are the
same; only the registry key / folder in step 1 differs.

## 4. Pair the browser with the app

1. Start the desktop app and unlock the vault.
2. Click the extension's toolbar icon, then **Pair this browser**. The popup shows a
   6-character code, for example `K7M2QP`.
3. The desktop app shows the same code. Click **Pair** there only if the two match — that
   comparison is what stops some other program from pairing itself with your vault. You
   have 60 seconds.

Pairing writes one 32-byte key into your vault (in the stored group `browser-pairing`), not
into the browser. If you later restore an older vault backup, the browser must pair again.

## 5. What you see on a login page

- **Click into the username or password field** of a site you have a login saved for. A
  Personal Vault menu opens under the field with the matching logins (title and username,
  never a password). Click one, or press ↓ then Enter: the extension fills the username and
  the password and does not submit — you press the site's own button. On a two-step login
  (username on one screen, password on the next) the menu fills whichever field is there.
- **Vault locked:** the menu on a password field says **Unlock Personal Vault**; clicking it
  brings the desktop app's unlock window forward. Unlock there, then click the field again.
- **App not running / browser not paired:** the menu on a password field says so.
- **No saved login for this site:** no menu at all.
- **Plain `http://` site:** the menu carries a "Not secure" warning, and only a login saved
  for `http://` is offered (an `https://` login is never filled into an `http://` page).
- **After you sign in** with a login the vault does not have, a prompt in the top-right corner
  asks **Save this login?** and shows the site and the username — never the password. Choose
  **Save**, **Not now**, or **Never for this site**. If the vault already has a login with that
  username for the site but the password you typed is different, it asks **Update saved
  password?** instead. If you typed exactly the saved password, nothing is shown.

The menu and the prompt are pages of the extension, shown in a frame inside the page that the
site's own scripts cannot open or read. Nothing reaches the vault until you click Save or
Update.

After installing or reloading the extension, **reload the tabs that were already open** —
the browser adds the extension's page scripts only to pages loaded afterwards.

## 6. Make it your primary password manager

Our menu is drawn inside the page; the browser's own password dropdown and other password
extensions draw over it. Turn those off so the two never compete:

1. **Pin the extension** — click the puzzle-piece icon in the toolbar and pin Personal
   Vault, so its icon (and its badge when a login is waiting to be saved) is always visible.
2. **Turn off the browser's password manager** — `chrome://password-manager/settings`
   (Brave: `brave://password-manager/settings`): switch off **Offer to save passwords and
   passkeys** and **Sign in automatically**.
3. **Delete the passwords the browser already holds** once they are in the vault (after gate
   G2 — real passwords only then). With "Offer to save" off the browser stops saving new
   ones, but it still offers the ones it has. To move them: export them from the same page
   (Export passwords, a plaintext CSV), import the CSV in the desktop app, then delete the
   CSV and the browser's copies.
4. **Turn off address autofill** — `chrome://settings/autofill` → *Addresses and more* (Brave:
   `brave://settings/autofill`) → off. This stops most of the browser's own suggestions on
   username and email fields.
5. **Turn off other password managers' extensions** — `chrome://extensions` (Brave:
   `brave://extensions`): switch off 1Password, Bitwarden, LastPass and similar, and form
   fillers. A switched-off extension can neither fill nor prompt. (Leaving one on and only
   disabling its in-page menu in its own settings also works, but its save prompts stay.)
6. **Set a shortcut (optional)** — `chrome://extensions/shortcuts`: give "Activate the
   extension" a key combination (for example `Ctrl+Shift+L`). It opens the toolbar popup for
   the current tab, which can also fill, add a login by hand, lock and pair.

**Chrome's privacy API (not enabled).** An extension can switch off the browser's "Offer to
save passwords" itself (`chrome.privacy.services.passwordSavingEnabled`), but that needs the
extra `privacy` permission ("Change your privacy-related settings"), the browser then shows
the setting as controlled by the extension, it does not stop the browser filling passwords it
already has, and the setting snaps back when the extension is removed. It is not part of this
version; step 2 does the same by hand.

## 7. Offering to save logins

On by default. To stop all offers, untick **Offer to save logins** at the bottom of the
toolbar popup; tick it again to resume. **Never for this site** in the prompt stops offers for
that one site (scheme, host and port). That list lives in the extension's local storage —
site names only, no usernames or passwords; to clear it, remove and re-add the extension.

What counts as signing in: submitting a login form, pressing Enter in a login field, or
clicking a button labelled like *Log in*, *Sign in*, *Continue* or *Next* — the last two for
sites that sign in with a script and never submit a form. A login is never offered for:

- a plain `http://` site (only `https://`, and `http://` on this machine — `localhost` or
  `127.0.0.1` — for local development);
- a login form inside an iframe (the extension works in the page's top frame only);
- a failed login the site rejects — the extension cannot tell, so a wrong password may be
  offered; choose **Not now**.

The submitted username and password are held in the extension's memory (not on disk) for two
minutes, or until you answer the prompt.

The extension can read the pages you visit, in order to find login fields and notice
sign-ins: it asks for access to all `http` and `https` sites when it is installed. It reads
only login fields, and only when you focus one or submit one.

## 8. What this cannot do

- **No extension can block another manager's prompts.** If another password manager is
  installed and enabled, it can still offer to save and fill; switching it off (step 6.5) is
  the only reliable answer. We do not and cannot "outbid" it.
- **The browser's own passkey dialogs still appear.** The steps above turn off the browser's
  password saving and autofill, not its passkey support.
- **No fill on page load.** We fill only after your click, so pages that auto-submit need the
  menu or the popup rather than nothing.
- **Top frame only.** A login form inside an iframe — including one from the same site — gets
  no menu and is never filled or offered for saving.
- **Pages that block extensions.** The browser does not run any extension on its own pages
  (`chrome://…`, the Chrome Web Store), on `file://` pages, or where an administrator's
  policy forbids it.
- **No Firefox build yet** (open question Q5). `api.js` is the only file that touches the
  browser API, so a Firefox build is a small change, but it does not exist today.

## 9. If it does not work

| Symptom | What to check |
| --- | --- |
| No menu on a login field | Reload the tab (page scripts reach only pages loaded after the extension). Check the site has a saved login (`no_match` in the popup means none). Check another manager is not covering it (step 6). |
| Menu says the app is not running | Start the app; if it is running, the host registration is missing — re-run step 1 and restart the browser. |
| Menu or popup says not paired | Pair again (step 4). An older vault backup may have replaced the stored key. |
| "Could not list logins: no_match" in the popup | No entry's URL matches this host under the [site matching rules](specs/data-model.md#site-matching-rules) — an `https://` entry never matches an `http://` page, and look-alike hosts (for example `localhost` vs `127.0.0.1`) are different sites. |
| No save prompt after signing in | Is **Offer to save logins** ticked in the popup? Was the site marked **Never**? Is it plain `http://`, or is the form inside an iframe? Did you type exactly the password already saved? |
| Nothing happens on Fill | The page may have changed since the menu or the list opened (click the field again or reopen the popup), or the form's fields are hidden — the fill only touches visible fields. |
