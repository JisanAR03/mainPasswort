# Fix: the extension does its job on login pages

Not a milestone card — a blocker the owner reported on 2026-10-16: on real sites the extension
showed nothing when a login field was clicked, and nothing offered to save a login after
signing in. Sensitive: **yes** — `extension/background.js`, `fill.js`, `detect.js` and the new
`inline.js`, `menu.js`, `prompt.js` are `[S]` files and need the owner's line-by-line review
(list at the end).

## What was found

Every link was checked in the real browsers (Chrome 155 and Brave 1.97 on Windows), with a
throwaway vault behind the real bridge code and the native host registered under a different
name, so nothing could reach the owner's app or vault.

| Link | Result | Evidence |
| --- | --- | --- |
| Extension loaded, service worker running | works | The SW `background.js` starts in both browsers; no errors in the SW or page consoles (only favicon 404s and Chrome's own `[DOM]` hints). |
| Installed in Brave | works | Brave `Secure Preferences`: unpacked from `D:\PasswordManager\extension`, all-sites access granted at runtime, `watch_logins: true`, paired. |
| Installed in Chrome | **missing** | Chrome's only profile (`Default`) has no record of the extension. Nothing could ever happen in Chrome. |
| Toolbar icon pinned (Brave) | **no** | Brave `pinned_extensions` does not list it. The only save signal the old design had — a badge on the icon — was hidden in the puzzle menu. |
| Other managers | **competing** | 1Password is installed, enabled and pinned in Brave; it puts its own icon, menu and save prompt on every login field. |
| Content script on login pages | **never as shipped** | The shipped manifest had no host access (`optional_host_permissions` only); `getRegisteredContentScripts()` → `[]` until "Watch for logins" was ticked, and then only `detect.js`, `allFrames: false`, `document_idle`. |
| Field focus → suggestion | **not built** | No code listened for focus at all. The spec excluded it: D8 "fill only after a click in the popup", ADR-003 "No inline field icons in v1", the MVP list "in-page autofill dropdowns" excluded. Focusing fields changed nothing in the DOM in either browser. |
| Form detection on submit | **partly broken** | With watching on, `detect.js` caught only a `submit` event on a `<form>`: standard form ✓, form built by JS ✓, **two-step login ✗** (no candidate), **SPA with no `<form>` / fetch login ✗** (no candidate). Cross-origin iframe ✗ (by design). |
| Save prompt | **not built in the page** | A caught login only set a badge "1"; the "Save?" question appeared only if you opened the popup within two minutes. |
| Update prompt | **broken** | The popup offered "Update <first match>" for any login on a site with any saved login — regardless of the username, and even when the password was unchanged — so it could overwrite another account's password. |
| Extension ↔ app (native messaging) | works | The registration names the right extension ID (`pkmjgefocdecdncjcpdlohfnahebkkpi`, derived from the manifest key); a `hello` frame through the owner's registered host exe reached the running app (`ok: true, state: locked`). |
| Brave's registry key | **misdocumented** | Brave on Windows reads **Chrome's** key, not `Software\BraveSoftware\Brave-Browser\NativeMessagingHosts`: a host registered only under Brave's key was "not found" (2 of 2 runs), under Chrome's or Chromium's key it was found (2 of 2). It works for the owner only because the installer also writes Chrome's key. |
| Vault state in the extension | works (popup only) | The popup said "… is locked." with Unlock; nothing in the page did. |

**Why the tests did not catch it.** Every e2e test ran Playwright's bundled Chromium (never
Chrome or Brave), loaded a copy whose manifest had all-sites access granted up front (so the
real install path, where the detector is off, never ran), opened `popup.html` as a tab, used
one plain `<form>` submit, and asserted the designed behaviour — a badge and a popup prompt.
The suite tested the spec faithfully; the spec did not include what a user expects a password
manager to do on a login page, and no test exercised a page the way a person does.

## What changed

Missing, now built (to the owner's acceptance criteria, which go beyond the spec — see
"Proposed spec changes"):

- **Suggestion menu** (`inline.js`, `menu.html`, `menu.js`, `frames.css`): focusing a username
  or password field on a site with saved logins opens a menu under it listing title and
  username; a click fills (and never submits). Locked vault → "Unlock Personal Vault" (sends
  `show_unlock`); app not running / not paired → a message, on password fields only. Closes on
  Escape, blur, typing, and after a fill; ↓ moves into it.
- **Save / update prompt** (`prompt.html`, `prompt.js`): after a sign-in the page shows "Save
  this login?" or "Update saved password?" in the top-right corner with the site and the
  username (never the password), and Save / Update, Not now, Never for this site. Nothing is
  saved without that click. A login identical to the saved one shows nothing. A login
  submitted while the vault is locked asks you to unlock, then saves on the next click.

Broken, now fixed:

- **Detection** (`detect.js`): a login counts as submitted on a form submit, Enter in a login
  field, or a click on a sign-in-labelled button (fetch/SPA logins); forms without `<form>`
  are scoped by the nearest ancestor holding the password field; a username submitted on its
  own (step 1 of a two-step login) is paired with the next password on the same site. Only
  `isTrusted` events count.
- **Update offer**: the service worker decides new / update / already saved by comparing with
  the saved login **with the same username** (the stored password is fetched with
  `get_secret` only to compare and dropped). The popup uses that decision.
- **Always on**: the content scripts are declared in the manifest (top frame only,
  `document_end`), with host access to `http://*/*` and `https://*/*` declared instead of an
  optional `<all_urls>`. "Watch for logins to save" became "Offer to save logins", on by
  default, with no permission prompt. The old on-demand registration (`detect-submits`) is
  unregistered at start-up so no page gets the detector twice. **This is a permission change
  for the owner to approve (AGENTS.md rule 5):** narrower in scheme than the old optional
  `<all_urls>` (no `file://`, no other schemes), but granted at install instead of on a
  click — the menu and the prompt cannot work on a site the extension cannot read.
- **Saved entries** are stored as the site's origin (`https://host[:port]/`) and titled with
  the host, rather than the full page URL (whose query string can carry tokens).
- **Docs**: setup-browser.md (what you see, exact Chrome/Brave settings, the Brave registry
  fact), install.md, known-limitations.md, README, manual-tests §13, CHANGELOG.

## Security

- **Matching** is unchanged and still the app's (`core/matching.py`, I4): exact host, port when
  the entry names one, `https` entries never on `http` pages, subdomains only when the entry
  opts in, punycode-normalized — never a substring. The e2e suite checks the look-alike host
  (`localhost` vs `127.0.0.1`) and the https-on-http case through the new menu.
- **No vault data in the page.** Titles and usernames live only in `menu.html` / `prompt.html`,
  extension pages framed inside a **closed** shadow root. Checked in both browsers: the page
  sees `shadowRoot === null`, no iframe in its DOM, no title/username/password in its text or
  HTML; a page script watching `PerformanceObserver`, `MutationObserver` and `message` events
  saw only that a `<personal-vault>` element was added, never the frame URL or its token. The
  content scripts never receive a title, username or password; the service worker hands them a
  one-time token and a height. A page that frames `menu.html` itself (it is web-accessible)
  gets an empty menu: no valid token, no data.
- **A user action before every fill**: a trusted click (or Enter) inside the extension's own
  frame, which the page cannot script; the service worker re-checks that the tab URL is the
  one the menu opened for, fills only into that exact document (`documentIds`, so a
  navigation in between means no fill), top frame only, visible fields only, no submit.
- **Senders are checked** by what the browser reports (`MessageSender`), not by what a message
  claims: popup-only messages from `popup.html`, page messages only from frame 0 of an
  `http(s)` tab, frame messages only from `menu.html` / `prompt.html` with a matching token.
  URLs come from `sender.url` / `chrome.tabs`, never from a message.
- **Never logged**: there is no `console.*` call anywhere in the extension; errors become
  `{ok: false, error: {code}}` with a code only.
- **Plain http**: no save prompt on a non-loopback `http://` page; a fill there carries a
  "Not secure" warning, and only an `http://` entry matches it (spec rule 4). `http://` on
  `localhost` / `127.0.0.1` is treated as secure (it never leaves the machine).
- **In memory only**: a submitted password sits in `chrome.storage.session` (memory, not
  readable by content scripts) until answered or two minutes pass. "Never" sites are stored in
  `chrome.storage.local` as origins only.
- **Residual risks** (accepted, as in every manager with an in-page menu): a page can learn
  the extension is installed (it sees the host element appear); a page can cover or overlay
  the menu to trick a click — which fills only that same site's own login into that same
  page; a site's own scripts read a password once it is filled; a failed sign-in may be
  offered for saving.

## Priority over the browser's own manager

The menu is built to appear as early as the page allows (on focus, on a click into an
already-focused field, and for a field that had focus before the script arrived). It cannot
outrank browser UI, so setup-browser.md §6 gives the exact settings: pin the icon, turn off
"Offer to save passwords and passkeys" and "Sign in automatically", delete the passwords the
browser already holds once they are in the vault, turn off address autofill, and switch off
other managers' extensions (1Password in the owner's Brave).

**Proposed, not enabled:** `chrome.privacy.services.passwordSavingEnabled = false` would turn
off the browser's "Offer to save passwords" while the extension is installed. Trade-offs: it
needs the `privacy` permission (the browser warns "Change your privacy-related settings"),
the setting then shows as controlled by the extension, it does not stop the browser filling
the passwords it already has, and it reverts when the extension is removed. If wanted, it
belongs behind an explicit opt-in in the popup (`optional_permissions: ["privacy"]`,
requested on that click) — AGENTS.md rule 5 requires the owner to approve the permission.

## Proposed spec changes (owner to accept; AGENTS.md rule 7 — not edited here)

- **ADR-011 "In-page suggestion menu and save prompt"**, superseding ADR-003's "No inline
  field icons in v1" and D8's "fill only after a click in the popup": the extension shows a
  menu on login fields and a save/update prompt in the page, both as extension-origin frames
  inside a closed shadow root, top frame only, fill only after a click in the menu; host
  access to http/https is declared at install. Consequences: the permission prompt at install
  says the extension can read and change data on all sites; the page can detect the
  extension; iframes and shadow-DOM fields are not covered.
- `docs/specs/browser-protocol.md`: add `inline.js`, `menu.html`/`menu.js`,
  `prompt.html`/`prompt.js`, `frames.css` to the pieces table; replace "M4b … badge, open the
  popup" with the in-page prompt; note `content_scripts` and `host_permissions` in the
  manifest row; state that Brave on Windows reads Chrome's registry key.
- `docs/specs/architecture.md`: list the three new `[S]` files in the project tree.
- `docs/specs/milestones.md`: an M4 "Done when" line per new behaviour (menu on focus, prompt
  after sign-in, update only for the same username), run in Chrome and Brave, not only Chromium.

## Tests

New pages in `extension/test-pages/`: `js-form.html` (form built by script, fetch-and-redirect
submit), `multi-step.html` (username, then password, no reload), `spa.html` (no `<form>`, a
`div` button, fetch login), `iframe-login.html` (cross-origin, or same-origin with `?same=1`),
`welcome.html`.

- `test_inline_fill.py` (17): menu on username and password fields, fill on click without
  submit, the page cannot read the menu, a forged menu frame gets nothing, no menu on a site
  with no login, look-alike host, hidden fields, cross- and same-origin iframes, JS-built
  form, form-less page, two-step login, page changed since the menu opened, plain-http
  warning, locked vault → unlock reaches the app, app not running, not paired.
- `test_save_flow.py` (rewritten, 14): in-page prompt and save only on click, Not now, Never,
  update for a changed password, nothing for the saved password, JS form, SPA, two-step login,
  iframe not captured, plain http not offered, offers turned off, locked vault, the popup's
  offer, an expired candidate.
- `test_extension_basics.py`: the manifest test now asserts the declared http/https access,
  the top-frame-only content scripts and the two web-accessible pages (the old assertion —
  no host access — described the design this fix changes; it is replaced, not loosened).
- The e2e harness (`conftest.py`) runs in Playwright's Chromium by default and in the
  installed Chrome or Brave with `PV_E2E_BROWSER=chrome|brave`; the test copy of the extension
  talks to `com.personalvault.e2e`, so a run in the browsers you use cannot reach your real
  app. Chrome is loaded over DevTools (`Extensions.loadUnpacked`) because branded Chrome
  ignores `--load-extension`.

Results are in the owner's report for this change.

## `[S]` files for the owner's review

- `extension/background.js` — sender checks, tokens, classification, save/update/never
- `extension/inline.js` — new; frames, focus handling, no vault data
- `extension/menu.js` — new; renders titles/usernames, fill on trusted click
- `extension/prompt.js` — new; renders site/username, never the password
- `extension/detect.js` — submit/Enter/button detection, two-step username
- `extension/fill.js` — anchor field, username-only step, focus flag

`scripts/check_sensitive_review.py` lists the three new files, so CI's `sensitive-review` job
asks for the trailer on them too.
