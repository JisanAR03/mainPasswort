# EXT-00 Extension-only mode — proposal, acceptance tests and plan

Milestone: none (new mode) · Sensitive: **yes** · Status: **built 2026-10-17, uncommitted;
ADR-012 and the threat-model text (sections 5–6) still proposals for the owner to apply**

The owner approved every recommendation in section 8 on 2026-10-17 ("go with whatever you
suggest"): kdbxweb 2.1.1 + hash-wasm 4.12.0, format-compatible with KeePassXC; no refresh
token; a mode of the same extension; both apps may write one Drive vault; link a desktop vault
through the adopt flow; a reload or update locks; one profile unlocked at a time; 6 hours
absolute plus optional lock with the screen; the AGENTS.md rule-2 wording (not applied —
AGENTS.md is the owner's to edit). The work is gated the way every card is: `uv run python
scripts/check.py` green, plus the e2e suite in Chromium, Chrome and Brave
(`PV_E2E_BROWSER=chromium|chrome|brave`).

## 0. What was built, and where it departs from the plan

Spikes: [docs/spikes/2026-10-17-extension-only-spike.md](../spikes/2026-10-17-extension-only-spike.md).
S1 passed with one fix; S2 came from Chrome's documentation and is proven by the tests; **S3
(real Google sign-in, and whether the extension's Web client sees the desktop client's files)
was not run** — it needs the owner's Google account; it is manual test §14.6 and §14.11.

- **New in `extension/`:** `vendor/` (kdbxweb, hash-wasm Argon2 and MD5, licences,
  `VENDOR.md` with SHA-256 pins), `config.js`, `offscreen.html` + `engine.js` (the vault
  engine), `idb.js`, `local.js` (profiles, unlock, the local backend), `oauth.js`,
  `drive.js`, `decide.js`, `sync.js`, `matching.js`, `generator.js`, `vault.html` /
  `vault.js` / `vault.css` (the vault page). **Changed:** `background.js` (one switch,
  `vaultRequest()`, between native messaging and the local engine; `ext_*` messages;
  alarms; the lock shortcut; optional lock with the screen), `manifest.json`, `popup.*`.
- **Checks:** `scripts/check_vendor.py` (vendored bytes match their pins) and
  `scripts/check_no_console.py` (no `console.*` in extension code), both run by `check.py`;
  13 more files on the `[S]` list in `scripts/check_sensitive_review.py`.
- **Tests:** `app/tests/e2e/test_ext_only.py` (24 tests, A1–A8), `fake_google.py` (a fake
  Drive v3 and OAuth redirect), fixtures in `conftest.py`, two new manifest/config tests in
  `test_extension_basics.py`.
- **Departure 1 — values normalized before every save.** kdbxweb writes unset values as empty
  XML elements that KeePassXC refuses on files pykeepass made (spike S1). `engine.js`
  `normalize()` sets each to the KeePass default it already meant. Not a change to kdbxweb.
- **Departure 2 — "Open a vault that is already on Google Drive".** Section 7 assumed a
  profile could keep a desktop vault's `pm_profile_id` but no step created one; the vault
  page now lists the vault files the app can see, downloads the chosen one, and imports it
  only if it opens with the password typed (Q-E).
- **Departure 3 — revisions sorted by time.** The extension does not trust the order of
  Drive's revision list; the desktop app does (see the spike report: a possible desktop
  bug, unverified, not changed here).
- **Departure 4 — the lock shortcut is Alt+Shift+L**, not the Ctrl+Shift+K section 4 named:
  a choice made while building, nothing more; anyone can change it at
  `chrome://extensions/shortcuts`.
- **Not built:** a conflict merge in the browser (out of scope, as planned); changing the
  master password; importing a `.kdbx` or CSV file from disk (only from Drive).

## 1. Goal

The browser extension is the whole product; the desktop app is never needed:

1. Create, open, edit and delete vaults, switch between them, unlock, fill, generate passwords
   and change settings — all in the extension.
2. Several profiles, each with its own vault, master password and Google account. One
   profile's data never shows up in another's.
3. Only the unlocked profile's logins are shown or filled. A locked profile's titles,
   usernames and notes appear nowhere: not in the popup, the in-page menu, or any message.
4. An unlock lasts 6 hours or until the browser closes, whichever comes first. Lock is one
   click and a keyboard shortcut.
5. Google Drive sync from the extension with the same `drive.file` scope, file layout and
   `appProperties` as the desktop app, so both can share one vault. It uploads by itself
   after a change (debounced), and checks on unlock, on an interval and when the network
   returns. It uses the desktop app's decision rules, not a second rulebook.
6. Every sync failure is visible and explained (what, why, last successful upload, whether
   the latest change is only local). Nothing fails silently; a local change is never lost
   because an upload failed. Retries back off.

## 2. What this reverses — plainly

| Today | In extension-only mode |
| --- | --- |
| ADR-003: "The extension must not hold a copy of the vault"; "the app must be running". | The extension holds the encrypted vault and, while unlocked, the decrypted one. No app runs. |
| I9: "The master password never leaves the desktop process: not to the extension, not to Drive, not to disk." | The master password is typed into the extension and the vault is decrypted in the browser. I9 cannot hold; section 6 replaces it. |
| D5 / ADR-003: unlock only in the desktop app, because typing the master password into the extension "moves it through a process that websites can attack". | The master password is typed into an extension page (popup or vault page), never into a web page — but it is now in the browser. |
| Threat model, unattended computer: idle lock after 5 minutes. | An unlock lasts up to 6 hours. An unattended unlocked browser gives that window to whoever sits down. |
| ADR-002 / threat model: "no npm packages in the extension", plain JavaScript, no build step. | Two third-party libraries (section 3) are vendored into the extension. Still no build step and no `npm install`. |
| AGENTS.md rule 2: "Encryption only via pykeepass." | In the extension, encryption is done by kdbxweb with an Argon2 WASM module. Rule 2 needs an amendment (section 8, Q-I). |
| ADR-004: the refresh token is stored inside the vault. | Depends on Q-B: either no refresh token at all, or one stored inside the vault. Never loose in extension storage. |
| ADR-010 assumes "`drive.file` is per OAuth client, so all devices use the same `client_secret.json`". | An extension cannot use the desktop OAuth client (it has no loopback redirect). Sharing one Drive file between the two needs the extension's client to see files the desktop client made — unproven, spike S3. |

**What is lost:** the guarantee that a compromised or malicious web-facing process (the
browser) never holds the master password or the decrypted vault; the short idle window; the
"no third-party code in the extension" property; and, if the extension is removed, every
local vault it held (the encrypted copy lives in the extension's own browser storage — only a
Drive copy or an exported `.kdbx` survives an uninstall).

## 3. Libraries (facts checked 2026-10-17 against the npm registry and GitHub)

| Package | Version | Licence | Maintainer | Last release | Shipped as | What breaks if it is wrong |
| --- | --- | --- | --- | --- | --- | --- |
| **kdbxweb** (KDBX 3/4 read and write; the engine of KeeWeb) | 2.1.1 | MIT | one maintainer (`antelle`, KeeWeb) | 2021-09-06; repo last pushed 2024-12-24 (docs only); 455 stars, 15 open issues | `dist/kdbxweb.min.js` (135 KB), vendored | A bug here can corrupt a vault, drop fields (custom fields, history, recycle bin, the hidden `.app` group) or weaken encryption. It is the make-or-break dependency: it is the only established JS KDBX library, and it is no longer actively released. |
| **hash-wasm** — Argon2 only | 4.12.0 | MIT (embedded C from the Argon2 reference code, CC0-1.0 / Apache-2.0) | two maintainers (`daninet`, `sdombi94`) | 2024-11-19; 1,161 stars, 13 open issues | `dist/argon2.umd.min.js` (29 KB, WASM embedded), vendored | Wrong Argon2 output means the vault does not open (the KDBX HMAC catches it: it fails closed, not silently). Slow Argon2 means a slow unlock. |

npm integrity of the exact tarballs, to be recorded beside the vendored files:

- kdbxweb-2.1.1: `sha512-z+a2+BEzyK2kUh0xDekY7gwc9CkbzSetUyvc78NKVawxV06UG1KYbg9W9hZCJdQPYizIVePTvQsYUXIO1qtAhQ==`
- hash-wasm-4.12.0: `sha512-+/2B2rYLb48I/evdOIhP+K/DD2ca2fgBjp6O+GBEnCDk2e4rpeXIK8GvIyRPjTezgmWn9gmKwkQjjx6BtqDHVQ==`

No advisories are filed against kdbxweb or hash-wasm. Two dependency findings matter:

- **kdbxweb's XML dependency is vulnerable and must not ship.** kdbxweb 2.1.1 requires
  `@xmldom/xmldom ^0.7.4`; every 0.7.x release has unpatched HIGH advisories (fixed only in
  0.8.15+ / 0.9.12), and `^0.7.4` can never reach a fixed version. The bundle uses the
  browser's own `DOMParser` / `XMLSerializer` when they exist and only falls back to xmldom
  otherwise (`dist/kdbxweb.js` lines 5340–5368). A service worker has no `DOMParser`; an
  extension page or **offscreen document** does. So the vault runs in an offscreen document
  and xmldom is **not vendored at all** — if the fallback were ever reached it would throw,
  failing closed.
- kdbxweb inlines **fflate** 0.7.x. Its one advisory family (an infinite loop in
  `unzipSync` on malformed ZIP64) is in ZIP parsing; kdbxweb uses only gzip. Recorded, not
  blocking.

Considered and not proposed: **argon2-browser 1.18.0** (MIT, `antelle`, 2021-06, the one
KeeWeb uses — older and unmaintained since 2023); **@noble/hashes 2.4.0** (MIT, `paulmillr`,
2026-08, pure JavaScript — its Argon2 at 128 MiB is expected to be far too slow; spike S1
measures it, as the fallback if hash-wasm is refused).

How they are shipped: copied from the npm tarballs into `extension/vendor/` with their
licence files, the tarball integrity and the file SHA-256 in `extension/vendor/VENDOR.md`,
and a new `scripts/check_vendor.py` (run by `check.py`) that fails if a vendored file's hash
changes. No `npm install`, no lock file, no build step.

Licence note (Q6): both are MIT, so the extension-only build contains no GPL code — unlike
the packaged desktop app (pykeepass). The project itself is still unlicensed; Q6 stays open.

## 4. Browser permissions and manifest changes

| Change | Why | Install warning |
| --- | --- | --- |
| `offscreen` | The vault engine runs in an offscreen document: it has a native `DOMParser` (so no xmldom) and survives service-worker restarts. Reason `DOM_PARSER`, which has no lifetime limit. | none |
| `alarms` | The 6-hour expiry, the 60-minute sync interval and backoff retries must fire although the service worker is killed after ~30 s idle. | none |
| `identity` | `chrome.identity.launchWebAuthFlow` for Google sign-in (`getAuthToken` is Chrome-only; Brave needs `launchWebAuthFlow` — spike S3). | none |
| CSP `extension_pages: "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"` | WebAssembly (Argon2) is blocked in extension pages without it. Allows compiling WASM, not `eval` of JavaScript. | none |
| `commands` (manifest key, not a permission) | The lock shortcut (suggested `Ctrl+Shift+K`). | none |
| `idle` — **optional, recommended** | Lock when the OS screen locks (`chrome.idle.onStateChanged` → `locked`), closing most of the 6-hour unattended window. | none |

Google endpoints (`www.googleapis.com`, `oauth2.googleapis.com`, `accounts.google.com`) are
already covered by the declared `https://*/*`. `nativeMessaging` stays for desktop mode.

## 5. Proposed ADR-012 (text for `docs/adr/0012-extension-only-mode.md`, owner to accept)

```markdown
# ADR-012 Extension-only mode

Status: Proposed
Date: 2026-10-17
Supersedes, for extension-only installs: ADR-003 (premise and consequences), D5, invariant I9.
Amends: ADR-002 (third-party code in the extension), ADR-004 (where the Drive token lives),
AGENTS.md rule 2.

## Context
The owner wants the browser extension to be the whole product, with no desktop app installed
or running. ADR-003's premise — the extension never holds the vault, the app must be running —
and I9 — the master password never leaves the desktop process — cannot hold for that.

## Decision
- An extension install chooses one mode: **desktop** (today: the extension is a remote control
  for the app over native messaging) or **extension-only** (this ADR). Desktop mode is
  unchanged and stays supported.
- In extension-only mode each profile's vault is a KDBX 4 file (Argon2id 128 MiB,
  parallelism 2, iterations calibrated at creation; ChaCha20 or AES-256 with HMAC), read and
  written by kdbxweb 2.1.1 with Argon2 from hash-wasm 4.12.0, both vendored and hash-pinned.
  No other cryptography: randomness from `crypto.getRandomValues`, SHA-256/HMAC from
  WebCrypto, as kdbxweb uses them.
- The vault engine runs in one offscreen document. The encrypted vault, its backups and its
  sync state live in the extension's IndexedDB. The master password is typed only into
  extension pages, used once to derive the KDBX composite key, and never stored.
- An unlock keeps that profile's composite key in `chrome.storage.session` (memory only,
  unreadable by content scripts) for at most 6 hours. Lock, expiry, browser close, and an
  extension reload, update or disable end it. One profile is unlocked at a time.
- Sync uses the desktop app's rules: `decide()` is ported to JavaScript and must agree with
  the Python function on every input in a shared, generated table (one rulebook, two
  languages); the Drive layout and `appProperties` are the desktop app's.
- Nothing about a locked profile — no title, username, note or URL — exists outside its
  encrypted file.

## Consequences
- The browser now holds the master password while it is typed and the decrypted vault while
  unlocked. A compromised browser, or a malicious build of this extension, exposes the vault.
- An unlocked profile stays usable for up to 6 hours unattended (shortened by the optional
  lock-on-screen-lock).
- Two vendored libraries become part of the trusted base; kdbxweb has had no release since
  2021 and one maintainer. A KeePassXC/pykeepass compatibility test runs on every commit.
- Removing the extension deletes its local vaults; Drive copies and exported `.kdbx` files
  survive.
- Sharing one Drive vault with the desktop app depends on the extension's OAuth client seeing
  files the desktop client created (spike S3). Conflicts follow ADR-006: kept, never merged
  silently; the extension offers keep-mine / take-theirs, and merge stays in the desktop app.
```

## 6. Proposed threat-model changes (`docs/specs/threat-model.md`, owner to accept)

**Trust boundaries.** Add **B6 Browser profile**: the extension's IndexedDB and
`chrome.storage.local` are files in the browser profile on disk (treated like B1: encrypted
data only); `chrome.storage.session` and the offscreen document are browser memory. Change
**B3** to say web pages never receive vault data even though the vault is now in the browser.

**Threats — new or changed rows.**

| Threat | In scope | Mitigation | What remains |
| --- | --- | --- | --- |
| Malicious website reads vault data from the extension | Yes | Vault engine in an offscreen document; titles and usernames only in extension frames inside a closed shadow root (as today); content scripts get tokens and counts, never data; senders checked by `MessageSender` | A page can read a password after it is filled |
| Another extension reads our storage or messages | Partly | Extension storage is per-extension; no `externally_connectable`; `storage.session` access level stays trusted-contexts only | An extension with `debugger` or a compromised browser can read anything |
| Compromised or malicious build of this extension (supply chain) | Yes | Vendored libraries hash-pinned and checked in CI; unpacked install from the reviewed repository only; `[S]` review of engine code | Whoever controls the code that is loaded controls the vault |
| Browser compromise / malicious browser | No | — | Full compromise; documented (was: out of reach of the browser) |
| Unattended unlocked browser | Yes | 6-hour expiry, Lock button and shortcut, optional lock on OS screen lock | Up to 6 hours (was 5 minutes) |
| Uninstall or "clear extension data" deletes local vaults | Yes | Drive sync, encrypted `.kdbx` export, warning before removal where the browser allows | An unsynced, unexported vault is gone |
| Stale third-party KDBX code corrupts a vault | Yes | Read-back check before every replace, 20 rotating backups in IndexedDB, KeePassXC and pykeepass compatibility tests on every commit | Bugs the tests do not cover |

**Invariants.**

- **I9 (replaced, extension-only mode):** the master password is typed only into extension
  pages and lives only in that page and the offscreen document while the key is derived; it
  is never stored anywhere, never sent to a content script, a web page, Drive or disk.
- **I11 (new):** the composite key lives only in `chrome.storage.session` and the offscreen
  document's memory, for at most 6 hours, and is gone after Lock, expiry, browser restart and
  extension reload.
- **I12 (new):** a locked profile's titles, usernames, notes and URLs exist only inside its
  encrypted file — no index, cache, badge or message carries them.
- **I13 (new):** the JavaScript `decide()` returns the same action as the Python `decide()`
  for every input in the shared table.
- **I1, I2, I5, I6, I7, I10** apply unchanged to the extension (no plaintext to disk — here
  IndexedDB and `storage.local`; no secrets in console output or errors; locked answers
  nothing; never upload over an unseen remote; never adopt a download that does not
  decrypt; upload only bytes that were verified).

## 7. Design: where everything lives

| Thing | Where | How long |
| --- | --- | --- |
| Master password | The popup / vault page field → one runtime message → the offscreen document, which derives the composite key and drops it | Seconds; never stored |
| Composite key (SHA-256 of the password's SHA-256, the KDBX credentials hash — password-equivalent for that vault) | `chrome.storage.session` `unlock:<profileId>` = key, `unlockedAt`, `expiresAt = unlockedAt + 6 h`; and in the offscreen document while it is open | Until Lock, `expiresAt` (checked on every request and by an alarm), browser close, extension reload/update/disable |
| Decrypted vault | Offscreen document memory (kdbxweb `Kdbx` object) | While unlocked; dropped on lock/expiry; if the browser closes the offscreen document, reopened from IndexedDB with the session key (one Argon2, ~1–3 s) |
| Encrypted vault, backups (20), conflict copies | Extension IndexedDB, one store per profile, written in one transaction after a read-back check | Until deleted by the owner or the extension is removed |
| Sync state (the `state.json` fields) and status | IndexedDB / `storage.local`, no secrets | Persistent |
| Profile list (id, display name, Google email, mode) | `storage.local` — visible to anyone who can read the browser profile, like `profiles.json` | Persistent |
| Google access token | `storage.session`, ≤ 1 hour (Q-B) | Until expiry or Lock |

Profile ids use the desktop format (`p_` + 8 random characters) so a profile linked to a
desktop vault keeps that vault's `pm_profile_id`. Only one profile is unlocked at a time;
unlocking another locks the first (Q-G).

Sync: a save commits to IndexedDB first, then marks the profile dirty; the upload runs after
a 10-second quiet period (timer while the worker lives, alarm fallback — alarms fire at most
every 30 s), on unlock, every 60 minutes, and on the offscreen document's `online` event.
Backoff: 30 s, 1, 2, 4, 8, 16, 30 min (cap) with jitter, as `docs/specs/sync.md`. The status
shown per profile: Synced · Waiting to upload · Offline (retrying at …) · Sign-in needs
renewing · Drive full · Conflict, action needed · File missing on Drive · Error (…), always
with "last successful upload" and "your latest change is only on this computer" when true. A
failed upload never touches the local copy.

## 8. Questions for the owner (recommendation first)

- **Q-A Library and compatibility.** kdbxweb 2.1.1 + hash-wasm 4.12.0 (section 3)?
  Compatibility target: **format-compatible, not bit-identical** — KeePassXC and pykeepass
  open every file the extension writes with every field, history item, recycle-bin entry,
  tombstone and the `.app` group intact. Bit-identical output is impossible: every save
  draws new random seeds.
- **Q-B Drive token.** Recommended: **no refresh token at all** — `launchWebAuthFlow` returns
  a 1-hour access token kept in `storage.session`, renewed silently (`prompt=none`,
  `login_hint=<the profile's account>`) while the browser is signed in to that Google
  account; when silent renewal fails, the status says the sign-in needs renewing. No client
  secret ships in the extension. Alternative: authorization code with an offline refresh
  token from a Google "Web application" client (its client secret must ship inside the
  extension), the refresh token stored **inside the vault** (`.app` group, entry
  `drive-sync-extension`, beside the desktop's `drive-sync`), never loose in extension
  storage.
- **Q-C Separate mode or replacement.** Recommended: a **mode of the same extension**, chosen
  at first run and switchable in settings; the desktop app stays and is unchanged. The cost:
  desktop-mode installs carry the new permissions too. (A separate extension build would keep
  them apart but duplicates the extension.)
- **Q-D One writer or two.** Recommended: **both may write** the same Drive vault, always
  through the same `decide()` rules — an unseen remote is never overwritten, a conflict keeps
  both copies. The extension resolves conflicts with keep-mine / take-theirs only; merging
  stays in the desktop app. If you would rather avoid conflicts entirely: one writer at a
  time, with the other read-only for that vault.
- **Q-E Existing Drive files and the pairing key.** Recommended: an extension profile can
  **link an existing desktop vault** through ADR-010's adopt flow, keeping its
  `pm_profile_id`; kdbxweb saves must keep the desktop's `.app/drive-sync` and
  `.app/browser-pairing` entries untouched (tested), and extension-only mode never uses
  them. This only works if spike S3 shows the extension's OAuth client can see the desktop
  client's files in the same Google Cloud project. If it cannot: one-writer-per-vault, or
  opening the file once through Google Picker (another dependency, to ask about then).
- **Q-F Extension reload vs `storage.session` — they contradict.** Chrome's documentation:
  session storage "is cleared if the extension is disabled, reloaded, updated, and when the
  browser restarts." So "unlock survives an extension reload" and "the key lives only in
  `storage.session`, never on disk" cannot both hold. Recommended: **keep the key off disk
  and accept that a reload or an update locks the vault**; the acceptance test becomes "an
  extension reload locks it, and nothing is lost". The alternative would write a key to
  disk.
- **Q-G One unlocked profile at a time?** Recommended: yes — it makes requirement 3 simple to
  prove.
- **Q-H The 6 hours.** Recommended: **absolute** (6 hours from unlock, not sliding), plus the
  optional lock on OS screen lock (`idle` permission).
- **Q-I AGENTS.md rule 2.** Proposed wording: "Never invent cryptography. Encryption only
  via pykeepass in the app and via the vendored kdbxweb and hash-wasm in the extension;
  randomness only from `secrets` / `crypto.getRandomValues`."

## 9. Plan (one card per session, each gated by `check.py` and the 3-browser e2e run)

- **EXT-01 Spikes** (throwaway code; findings in `docs/spikes/`), before any product code:
  - S1 — kdbxweb + hash-wasm: open a desktop-made vault, save, reopen in pykeepass and
    `keepassxc-cli`; custom fields, history, recycle bin, tombstones and `.app` group intact;
    Argon2id at D9 settings timed in Chrome and Brave (and @noble/hashes as the fallback);
    can kdbxweb take the composite key directly (so the password itself is never kept)?
  - S2 — lifetimes measured in Chrome and Brave: `storage.session` across a service-worker
    stop, an extension reload and a browser restart; offscreen document across
    service-worker stops.
  - S3 — Google sign-in in Chrome and Brave via `launchWebAuthFlow` (silent renewal with
    `prompt=none`), and whether a file made by the desktop client is visible to the
    extension's client in the same Cloud project under `drive.file`.
- **EXT-02** Vendor the two libraries, `check_vendor.py`, CSP; the offscreen vault engine:
  create, open, save with read-back check, rotating backups in IndexedDB; compatibility
  tests with pykeepass and `keepassxc-cli`.
- **EXT-03** Profiles, unlock, lock, 6-hour expiry, shortcut; the existing menu, prompt and
  popup served by the local engine instead of the native host.
- **EXT-04** Vault management UI (full-page `vault.html`): entries, generator, settings,
  profile create/rename/delete/switch, `.kdbx` export.
- **EXT-05** `decide.js` and the shared decision table generated from the Python
  `decide()`; the Drive client; Google sign-in.
- **EXT-06** Sync engine: triggers, quiet period, backoff, status UI, conflict choices.
- **EXT-07** Docs (setup, known limitations, manual tests), and ADR-012 / threat model
  applied by the owner.

## Files you may change (EXT-02 … EXT-07, once approved)

- `extension/` — new: `offscreen.html`, `vault-engine.js` [S], `vault.html`, `vault.js` [S],
  `sync.js` [S], `decide.js` [S], `drive.js` [S], `oauth.js` [S], `vendor/` (vendored
  files, licences, `VENDOR.md`); changed: `manifest.json`, `background.js` [S], `popup.*`,
  `api.js`
- `app/tests/e2e/` — new tests and a fake Drive server; `app/tests/sync/` — the decision
  table generator and parity test
- `scripts/check_vendor.py` (new), `scripts/check.py`, `scripts/check_sensitive_review.py`
- `docs/setup-browser.md`, `docs/known-limitations.md`, `docs/manual-tests.md`, `README.md`,
  `CHANGELOG.md`, `docs/spikes/`

Not without asking: `docs/specs/`, `docs/adr/`, `AGENTS.md`, anything under `app/src/`.

## Spec references

- `docs/adr/0003-browser-integration.md`, `0004-sync.md`, `0006-conflicts.md`,
  `0010-first-time-link.md`
- `docs/specs/threat-model.md` (I1–I10), `docs/specs/sync.md` (decision table, backoff),
  `docs/specs/data-model.md` (KDBX settings, `.app` group, `state.json`)

## Acceptance tests (write these first, show them failing)

Automated tests run in Chromium, Chrome and Brave with **no native host registered and no
desktop app** (the e2e harness's host registration is turned off for this suite).
Drive is a fake Drive server reached through Playwright routing, except where noted.

**A1 — no desktop app anywhere**
- [ ] In a brand-new browser profile: create a profile, set a master password, add a login,
      fill it on a test page from the in-page menu, lock, unlock again.
- [ ] Manual (owner): the same on a real site with a fake login, on a machine where the
      desktop app is not installed.

**A2 — how long an unlock lasts**
- [ ] Survives a service-worker stop (CDP `ServiceWorker.stopAllWorkers`).
- [ ] Survives the offscreen document being closed (reopened from IndexedDB with the session
      key).
- [ ] Ends at `expiresAt`: a test-only copy of the extension sets the lifetime to 5 seconds
      (the way weak KDF settings exist only in test fixtures); another test asserts the
      shipped value is exactly 6 hours.
- [ ] Does not survive a browser restart (relaunch with the same profile directory).
- [ ] Extension reload: per Q-F — recommended "a reload locks it and nothing is lost".
- [ ] Lock (button and the `commands` shortcut) ends it immediately: the next request is
      refused and `storage.session` holds no key.

**A3 — one profile's data never reaches another**
- [ ] With A unlocked and B locked (B's entries carry a canary title, username and note):
      the popup, the in-page menu on B's site, `chrome.runtime.sendMessage` from an
      extension page and from a content script, and dumps of `storage.local`,
      `storage.session` and IndexedDB contain none of B's canaries.
- [ ] Unlocking B locks A; then A's canaries are unreachable the same way.

**A4 — Drive**
- [ ] Editing an entry produces a new revision on the fake Drive within 60 seconds, with
      `appProperties` `{pm_profile_id, pm_schema: "1"}` in the desktop layout.
- [ ] That uploaded file opens in pykeepass (and `keepassxc-cli`) with the edit visible.
- [ ] Manual (owner): the same against a throwaway real Google account, then the desktop app
      opens the file from Drive.

**A5 — offline**
- [ ] With the network off (`context.set_offline(True)`): an edit saves locally and the
      status says offline, the change is only on this computer, and when the next retry is.
- [ ] Network back: it uploads by itself without a click.

**A6 — sign-in revoked**
- [ ] When the token is refused (401 / `invalid_grant`): the status says the sign-in needs
      renewing, "last successful upload" is unchanged, and no status ever says Synced.

**A7 — sync rules**
- [ ] I13: the JavaScript `decide()` agrees with the Python `decide()` on every row of the
      generated table (CI fails on any difference).
- [ ] An upload is never made over a remote md5 the state has not seen (I6); a conflict keeps
      both copies; a missing or trashed remote file asks instead of recreating.
- [ ] Every failure kind — signed out, offline, Drive full (403 `storageQuotaExceeded`),
      conflict, file missing, expired token, 5xx — has a test that shows its status text and
      keeps the local change.

**A8 — security**
- [ ] I1 / I12: after a session of edits with a canary password, no plaintext canary is in
      `storage.local`, IndexedDB or any Drive upload; only the composite key is in
      `storage.session`.
- [ ] I2: no `console.*` call in the extension (a check in `check.py`), and the canary is in
      no page, service-worker or offscreen console output.
- [ ] The vendored files match `VENDOR.md` (`check_vendor.py`).
- [ ] Compatibility: a vault made by the desktop app opens, edits and saves in the extension,
      and opens again in pykeepass and `keepassxc-cli` with every field intact.

## Out of scope

Merging conflicts in the extension (desktop app only), Firefox, passkeys, TOTP, a Web Store
listing, and changing desktop mode.
