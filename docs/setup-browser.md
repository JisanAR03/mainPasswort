# Browser extension setup (M4)

The extension is a thin remote control for the desktop app: it lists the logins that match
the tab you are on and fills one when you click. It stores no vault data, and it never sees
a password except the one you just clicked to fill.

Until packaging (M6), you load the extension from the repository folder. Chrome and Brave
both do this, and both take the same native host.

> The desktop app must be running. If it is not, the popup says "The desktop app is not
> running." and does nothing else — that is by design, not a fault.

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
| Brave | `HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.personalvault.host` | `~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.personalvault.host.json` |

The host launcher runs the app's package straight out of this repository, so the install
must be repeated if you move the folder. **Restart the browser afterwards**: Chrome and
Brave read the native-host registration once, at startup.

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

## 5. Make it your primary password manager

1. **Turn off the browser's own manager** — `chrome://password-manager/settings` (or
   `brave://password-manager/settings`): switch **Offer to save passwords** off, and turn
   off **Auto Sign-in** and autofill for passwords where offered.
2. **Disable other password managers** — `chrome://extensions`: turn off (not remove)
   any other password or autofill extension. Extensions that are off cannot fill or
   prompt.
3. **Pin it** — click the puzzle-piece icon in the toolbar and pin Personal Vault, so the
   icon is always visible.
4. **Set the shortcut** — `chrome://extensions/shortcuts`: give "Activate the extension" a
   key combination you can reach (for example `Ctrl+Shift+L`). Pressing it opens the popup
   for the current tab.
5. **Only bitwarden-style prompt-free use**: nothing else is required. The extension asks
   the app for matches when the popup opens, and for one password when you click Fill.

## 6. Optional: watch for logins to save (M4b)

Out of the box the extension can only see a site **after you click its icon or press the
shortcut** (the `activeTab` permission). To offer to save a login you just submitted, the
extension has to read the pages you visit, which is a broader permission:

- Turn on **Watch for logins to save** at the bottom of the popup. The browser asks to
  read and change data on all websites; the permission is requested only by that click.
- With it on, a submitted password form offers "Save the login for …?" the next time you
  open the popup, for two minutes. Nothing is saved unless you click Save.
- Turn the switch off at any time; the browser also lets you revoke it in the extension's
  details page (**Site access**). The extension then goes back to seeing only the tab you
  click on.

Plain words: with this off, the extension sees a page only when you ask it to. With it on,
it can see pages as you use them, in order to notice logins — it reads only a submitted
username and password field, and keeps that candidate in memory (not on disk) for two
minutes.

## 7. What this cannot do

- **No extension can block another manager's prompts.** If another password manager is
  installed and enabled, it can still offer to save and fill; disabling it (step 5.2) is the
  only reliable answer. We do not and cannot "outbid" it.
- **The browser's own passkey and password dialogs still appear.** The built-in manager
  keeps its UI for passkeys and for settings; the steps above turn off its saving and
  autofill, not the browser's passkey support.
- **No autofill on page load.** We fill only after your click, so passwordless or
  auto-submitting pages may need the popup rather than a keystroke.
- **No Firefox build yet** (open question Q5). `api.js` is the only file that touches the
  browser API, so a Firefox build is a small change, but it does not exist today.

## 8. If it does not work

| Symptom | What to check |
| --- | --- |
| "The desktop app is not running." | Start the app; if it is running, the host registration is missing — re-run step 1 and restart the browser. |
| "Not paired yet." | Pair again (step 4). An older vault backup may have replaced the stored key. |
| "Could not list logins: no_match" | No entry's URL matches this host under the [site matching rules](specs/data-model.md#site-matching-rules) — an `https://` entry never matches an `http://` page, and look-alike hosts (for example `localhost` vs `127.0.0.1`) are different sites. |
| Nothing happens on Fill | The page may have changed since the list loaded (reopen the popup), or the form's fields are hidden — the fill only touches visible fields. |
