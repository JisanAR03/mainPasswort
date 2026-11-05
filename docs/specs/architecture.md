# Architecture

> Rewritten 2026-11-05 for the extension-only product (ADR-012, ADR-013). The original design
> (a desktop app with the extension as its remote control) is in the git history and in
> `docs/adr/0003-browser-integration.md`.

The product is one Manifest V3 browser extension for Chrome and Brave, plain JavaScript, no
build step. It holds each profile's encrypted vault in the browser and syncs it to the owner's
own Google Drive. Nothing else runs: no server, no desktop program, no native host.

## Pieces

| Piece | File | Runs in | Sees plaintext? | Job |
| --- | --- | --- | --- | --- |
| Vault engine | `engine.js`, `offscreen.html` | Offscreen document | Yes, while unlocked | The only code that reads or writes KDBX: create, open, edit, delete, search, match, save with a read-back check. Answers the service worker only. |
| Service worker | `background.js`, `local.js` | Service worker | One password at a time, for one fill or one save | Profiles, unlock and lock, every request from the popup, the in-page menu and the save prompt; reads tab URLs itself; injects the fill. |
| Storage | `idb.js` | Worker and engine | No: encrypted bytes and bookkeeping | IndexedDB `personal-vault`: vaults, 20 backups each, conflict copies, sync state. |
| Sync | `sync.js`, `decide.js`, `drive.js`, `oauth.js` | Service worker | No: encrypted bytes and an access token | Upload, download, conflict detection, retry, Google sign-in. |
| Vault page | `vault.html`, `vault.js` | Extension tab | Entry being edited | Profiles, entries, generator, settings, export, Drive status and choices. |
| Popup | `popup.html`, `popup.js` | Toolbar popup | Titles and usernames for this site | Unlock, lock, list and fill, add a login, one-line sync status. |
| In-page menu and prompt | `inline.js`, `menu.html/js`, `prompt.html/js` | Content script + extension frames | Frames: titles, usernames; the script: nothing | The suggestion menu under login fields and the save/update prompt, in frames inside a closed shadow root. |
| Detector | `detect.js` | Content script (top frame) | A submitted login, handed straight on | Notices a sign-in: form submit, Enter, sign-in button click, a two-step username. |
| Fill | `fill.js` | Injected into frame 0 | The login it fills | Fills visible fields, never submits. |
| Generator, matching | `generator.js`, `matching.js` | Worker and engine | Generates, never stores | Password generation; the site-matching rules. |
| Vendored libraries | `vendor/` | Offscreen document | Yes (they read the vault) | kdbxweb (KDBX), hash-wasm (Argon2id, MD5), pinned by SHA-256. |
| Google Drive | Google | n/a | Never | Stores the encrypted `vault.kdbx` and its revisions. |

## Trust zones

- **The extension's own pages and workers** (engine, service worker, vault page, popup, the two
  frames) are trusted with plaintext, and only they.
- **Content scripts** run in web pages' processes but in an isolated world: they decide *where*
  to show things and notice sign-ins. They are handed a one-time token and a height, never a
  title, a username or a password. The one thing they see in plaintext is a login the user just
  typed into the page.
- **Web pages** are hostile. They never receive vault data before a user action; the menu and
  prompt live in extension frames inside a closed shadow root they cannot open.
- **Google Drive and the disk** only ever see encrypted bytes.

## Key flows

**Create.** The vault page sends the profile name and master password to the service worker, which
asks the engine to create the vault: calibrate Argon2id iterations to about a second, build the
KDBX file, read it back, store it in IndexedDB. The password hash is kept in `storage.session`.

**Unlock.** The popup or vault page sends the password; the engine derives the key, decrypts the
stored file and keeps the open vault in memory; the service worker keeps
`{profileId, passwordHash, unlockedAt, expiresAt}` in `chrome.storage.session` and sets an alarm
for the expiry. If the engine document is closed meanwhile, it is reopened from that record.

**Save.** The engine normalizes the file (see below), writes it, proves the new bytes decrypt,
then replaces the stored vault and moves the old one to the backups in one IndexedDB transaction.
The profile is marked dirty and the sync engine uploads after a 10-second quiet period.

**Fill.** Focusing a login field asks the service worker for this tab's matches. It returns a
one-time token; the content script frames `menu.html#token`. A click in that frame asks the
service worker to fill that login: it re-checks the tab URL, asks the engine for that one login
(which re-matches the URL, I4), and runs `fillLogin` in that exact document.

**Offer to save.** The detector hands a submitted login to the service worker, which compares it
with the saved login for the same username (new, changed, or already saved) and shows
`prompt.html#token`. Nothing is written until the user clicks Save or Update.

**Lock** (button, shortcut, expiry, screen lock, restart). The service worker removes the unlock
record, every Drive token and every menu session; the engine drops its open vault.

## The KDBX file

Written by kdbxweb, read by kdbxweb, pykeepass and KeePassXC. kdbxweb writes values it never read
as empty XML elements, which KeePassXC refuses (`Invalid EnableSearching value`) on files that
pykeepass made; `engine.js` `normalize()` sets each to the KeePass default it already meant before
every save. Never remove it: the e2e tests open the extension's uploads in KeePassXC.

## The Python reference (`app/`)

Tests only; nothing ships. `core/vault.py` and friends read and write the same vaults with
pykeepass; `sync/decide.py` is the original decision table; `core/matching.py` the original rules.
The e2e suite checks the extension against them: its vaults open in pykeepass and `keepassxc-cli`
with every field intact, its matching and its `decide()` equal the reference on every input.

## Layout

```text
extension/            the product (load this folder unpacked)
  manifest.json  background.js  local.js  engine.js  idb.js  sync.js  decide.js  drive.js
  oauth.js  config.js  matching.js  generator.js  fill.js  detect.js  inline.js
  menu.html/js  prompt.html/js  popup.html/js/css  vault.html/js/css  offscreen.html  frames.css
  vendor/             kdbxweb, hash-wasm: pinned (VENDOR.md)
  test-pages/         hostile and ordinary login pages for the e2e tests
app/                  Python reference implementation + all tests
  src/personal_vault/{core,sync}/
  tests/{unit,integration,security,sync,slow,e2e,fixtures}/
scripts/              check.py, check_vendor.py, check_no_console.py, check_sensitive_review.py, ...
docs/                 this documentation
```
