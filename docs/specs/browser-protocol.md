# Extension messaging and the fill procedure

> Rewritten 2026-11-05 (ADR-012). The native-messaging protocol, its framing, the pairing key and
> the local socket are gone with the desktop app (ADR-013); this document is the extension's
> internal messaging.

The extension is a Manifest V3 extension in plain JavaScript. Its parts talk through
`chrome.runtime` messages. The service worker (`background.js`) accepts each message by **where it
comes from, as the browser reports it** (the `MessageSender`), never by what the message claims.
Anything else is answered `bad_request`.

## Who may send what

| Sender (as the browser reports it) | Messages | Answered with |
| --- | --- | --- |
| The toolbar popup (`popup.html`) | `status`, `get_logins`, `fill`, `lock`, `unlock`, `save_login`, `generate`, `pending_save`, `resolve_save`, `set_offer_to_save`, and the `ext_*` messages | A result, or `{ok: false, error: {code}}` |
| The vault page (`vault.html`) | The `ext_*` messages: `ext_state`, `ext_create_profile`, `ext_rename_profile`, `ext_delete_profile`, `ext_unlock`, `ext_lock`, `ext_list`, `ext_get`, `ext_save_entry`, `ext_delete_entry`, `ext_generate`, `ext_export`, `ext_settings`, `ext_connect`, `ext_disconnect`, `ext_sync_now`, `ext_choose`, `ext_drive_list`, `ext_drive_open` | A result, or an error code |
| A content script in the top frame of an `http(s)` tab | `menu_open`, `menu_close`, `prompt_open`, `login_submitted`, `username_submitted` | Only a token, a height and booleans: **never a title, a username or a password** |
| `menu.html` framed in a tab | `menu_data`, `menu_fill`, `menu_unlock`, `menu_dismiss` | Only with the one-time token handed out for that tab |
| `prompt.html` framed in a tab | `prompt_data`, `prompt_action` | Only with the token of the pending save for that tab |
| The offscreen document (`offscreen.html`) | `engine_online` (the network is back) | Nothing |

The engine (`engine.js`) answers messages with `target: "engine"` from the service worker
(`sender.url` must be `background.js`); a message from an extension page or a web page is refused.
There is no `externally_connectable` and no `onMessageExternal`: no other extension and no web
page can message this one.

Error codes in replies: `locked`, `no_vault`, `no_match`, `url_mismatch`, `url_changed`,
`bad_request`, `bad_password`, `invalid`, `not_found`, `save_failed`, `internal`, plus the sync
codes `no_client_id`, `sign_in_cancelled`, `reconnect`, `wrong_scope`, `missing`, `unreadable`.
Unknown message types are rejected, never ignored. A reply carries a code only: no message,
stack or value ever echoes an entry field, the master password, a key or a token.

## Manifest

| Item | Value | Why |
| --- | --- | --- |
| `permissions` | `activeTab`, `scripting`, `storage`, `offscreen`, `alarms`, `identity` | fill and menu injection; storage; the engine's document; timers that outlive the worker; Google sign-in |
| `optional_permissions` | `idle` | lock when the screen locks; asked for on a click |
| `host_permissions` | `http://*/*`, `https://*/*` | the menu and the save prompt work on every site; no `file://` or other schemes |
| `content_scripts` | `deep.js`, `detect.js`, `inline.js`, top frame only, `document_end` | the shadow-DOM search, the detector and the menu |
| `web_accessible_resources` | `menu.html`, `prompt.html`, for `http(s)` pages | so the content script can frame them |
| `content_security_policy` | `script-src 'self' 'wasm-unsafe-eval'; object-src 'self'` | WebAssembly for Argon2 and nothing else new |
| `commands` | `lock-vault` (suggested Alt+Shift+L) | lock from the keyboard |
| `key` | fixed | pins the extension ID, which is the origin of the stored data |

There is no `nativeMessaging` permission: nothing talks to another program.

## Fill procedure

1. The user focuses a username or password field. `inline.js` asks the service worker
   (`menu_open`) whether to show a menu.
2. The service worker asks the engine for the logins that match `sender.url` (the page never
   supplies a URL) and, if there are any, stores `{token, url, documentId, logins}` in
   `storage.session` and returns the token and a height. If the vault is locked, or there is no
   vault yet, it returns a one-row menu that opens the unlock or set-up page, but only on a
   password field or next to one.
3. `inline.js` frames `menu.html#token` in a closed shadow root. The frame lists titles and
   usernames. A trusted click in it sends `menu_fill`.
4. The service worker re-reads the tab URL and refuses if it changed since step 2, asks the
   engine for that one login (the engine re-matches the URL against the entry, I4) and runs
   `fillLogin` in **that exact document** (`documentIds`), so a navigation in between means no
   fill rather than a fill into whatever loaded since.
5. `fillLogin` fills only visible fields (non-zero size, not hidden, not transparent) in the top
   frame, including fields inside open shadow roots; fires `input` (composed, as a typed one is) and
   `change`; and does not submit. If it finds no login field it says so (`no_login_field`) and the menu
   or popup tells the user, rather than reporting a fill. It also fills the username alone on the first
   screen of a two-step login.
6. The service worker drops its references and closes the menu.

The toolbar popup does the same with a button per login (`fill`).

## Save and update

1. `detect.js` notices a sign-in: a form submit, Enter in a login field, or a click on a sign-in
   labelled button (for logins that use a script and never submit a form); only events the user
   caused count (`isTrusted`). A username sent on its own is remembered for five minutes so the
   next screen's password can be paired with it. Forms in iframes are never captured.
2. `login_submitted` reaches the service worker, which drops it if offers are off, the site is on
   the "never" list, or the page is plain `http` (other than this machine).
3. It compares the login with the saved login for the same username: **new** (offer to save),
   **changed password** (offer to update), or **identical** (offer nothing). The candidate is held
   in `storage.session` for two minutes.
4. `prompt.html#token` is framed in the page's top-right corner with the site and username, never
   the password, and **Save/Update**, **Not now** and **Never for this site**. Nothing is written
   until a trusted click there. A submit while the vault is locked asks for an unlock first.

## Making it your primary manager

See [setup-browser.md](../setup-browser.md): turn off the browser's own password saving and
autofill, switch off other managers' extensions, pin this one. No extension can block another
manager's prompts, and the browser's own passkey dialogs still appear.
