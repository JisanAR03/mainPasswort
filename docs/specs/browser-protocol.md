# Browser extension and native messaging protocol

> Source: design pack v0.1, section 8. Status: accepted at gate G0 (2026-10-15).

The extension is a thin remote control. It asks the desktop app for logins that match the
current tab, and fills one password after you click. It stores no vault data, and the
protocol has no message that returns more than one password.

## Extension (Manifest V3, plain JavaScript)

| Piece | File | Job |
| --- | --- | --- |
| Manifest | `manifest.json` | Permissions: `nativeMessaging`, `activeTab`, `scripting`, `storage`. A fixed key keeps the extension ID stable during development. |
| Service worker | `background.js` | Owns the native port, reads the active tab's URL, injects the fill |
| Popup | `popup.html`, `popup.js` | Lists matches, with fill buttons, lock and unlock buttons, and an "add login for this site" form |
| Fill function | `fill.js` | Injected on click into the top frame only; fills visible fields, never submits |
| Save detector (M4b) | `detect.js` | Content script that notices a submitted login; needs access to all sites |
| Browser shim | `api.js` | Wraps `chrome.*` so Firefox's `browser.*` can be added later |

M4a needs no access to any website until you click, because `activeTab` grants access to that
one tab. M4b's save detection needs permission to read all sites, so it is a separate step
with its own approval.

## Native host

- Name `com.personalvault.host`, type `stdio`. `allowed_origins` lists only our extension ID.
- `scripts/install_native_host.py` writes the host manifest for Chrome and Brave on your OS.
  The exact paths are recorded in `docs/setup-browser.md`.
- The host holds no state. It reads one framed message, forwards it to the app's local
  socket, and writes back the reply.
- Framing: a 4-byte length in native byte order, then UTF-8 JSON. Chrome caps host-to-browser
  messages at 1 MB. Our host rejects requests over 16 KB, and our replies stay under 64 KB.
- Local socket: a Qt local socket (a named pipe on Windows, a Unix socket elsewhere) that
  only your OS user can read.

## Message envelope

```json
{ "v": 1, "id": "8f14e45f-...", "type": "get_logins", "pairing_key": "base64...",
  "payload": { "url": "https://github.com/login" } }

{ "v": 1, "id": "8f14e45f-...", "ok": false, "error": { "code": "locked" } }
```

Error codes: `locked`, `not_paired`, `no_match`, `url_mismatch`, `bad_request`, `too_large`,
`rate_limited`, `app_not_running`, `internal`. Unknown fields or types are rejected, never
ignored.

## Messages

| Type | Needs pairing | Payload | Returns | Rules |
| --- | --- | --- | --- | --- |
| `hello` | No | Extension version | App version, `locked` or `unlocked`, profile name | No vault data |
| `pair_request` | No | New 32-byte key, browser name | `paired: true` | You confirm in the desktop app; both sides show the same 6-character code; 60-second timeout |
| `show_unlock` | No | None | `shown: true` | Brings the desktop unlock window forward |
| `get_logins` | Yes | Tab URL | Up to 20 of `{id, title, username}` | Matching rules from the [data model](data-model.md#site-matching-rules) |
| `get_secret` | Yes | Entry ID, tab URL | `{username, password}` | The app re-matches the URL against that entry; 10 per minute |
| `save_login` | Yes | URL, username, password, optional title | New entry ID | Always creates; never overwrites |
| `update_password` | Yes | Entry ID, URL, new password | Entry ID | URL must match; the old password goes to history |
| `generate_password` | No | Optional length | Password | Generator only, no vault access |
| `lock` | Yes | None | None | Locks the vault |

There is deliberately no message to list all entries, search by free text, export, or change
settings.

## Fill procedure

1. You click the toolbar icon or press the shortcut. The service worker reads the active
   tab's URL itself; the page never supplies it.
2. `get_logins` returns the matches, and the popup shows titles and usernames.
3. You click one. The service worker re-reads the tab URL and aborts if it changed since
   step 1.
4. `get_secret` returns that login. The service worker injects `fill.js` into frame 0, with
   the username and password as arguments.
5. `fill.js` fills only visible fields (non-zero size, not hidden, not transparent), fires
   `input` and `change` events, and does not submit.
6. The service worker drops its references, and the popup closes.

## Save and update (M4b)

1. `detect.js` notices a submitted form with a password field and sends the candidate to the
   service worker.
2. The service worker keeps it in `chrome.storage.session` (memory only) for 2 minutes and
   shows a badge.
3. You open the popup and choose Save, Update existing or Dismiss. Nothing is saved without
   that click.

## Locked or not running

If the vault is locked, the popup shows "Unlock in app", which sends `show_unlock`. If the
app is not running, the popup says so and asks you to start it.

## Making it your primary manager

`docs/setup-browser.md` (M4) will cover: turning off "Offer to save passwords" and autofill
in Chrome and Brave, disabling other managers' extensions, pinning ours, and setting its
keyboard shortcut. It must also state the limits: no extension can block another manager's
prompts, and the browser's own passkey dialogs still appear.
