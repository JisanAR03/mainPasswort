# Fix: login fields inside shadow DOM (Reddit's login modal)

Not a milestone card — a bug the owner reported on 2026-11-05: on Reddit's login modal, clicking the
email or password box showed no suggestion menu, and the popup's Fill did not work either. Sensitive:
**yes** — `extension/fill.js`, `detect.js` and `inline.js` are `[S]` files, and a new script,
`extension/deep.js`, is added to the list.

## What was found

Reproduced in real Chrome on reddit.com with a **fake** login in a throwaway vault (nothing was
submitted to Reddit):

- Reddit's username and password `<input>`s are **inside open shadow roots** of `faceplate-text-input`
  web components. There is no `<dialog>` and no login iframe (the only iframes are reCAPTCHA).
- After a real click in the username box: **no menu appeared**.
- The popup's Fill answered `{"ok": true, "result": {"filled": false, "reason": "no_login_field"}}`
  — and the popup then said **"Filled."**, because it only checked that the request succeeded.

## Root cause

The extension found login fields with `document.querySelector`-style queries, which stop at a shadow
boundary:

- `fill.js` looked for password and username fields with `document.querySelectorAll`: it found none.
- `inline.js` listens to `focusin` on the document, where an event from inside a shadow root arrives
  **retargeted to the outermost host** (`faceplate-text-input`), not an `<input>`, so it never
  considered the field; and `document.activeElement` is also the host, which its "still focused?" check
  compared against.
- `detect.js` searched a form with `querySelector`, so it never found the password after a sign-in:
  no save prompt either.

Three smaller defects were found in the same code: `autocomplete="username webauthn"` (Reddit's) was not
recognised as a username by `fill.js` (it compared for equality); "the username before the password"
used `compareDocumentPosition`, which cannot order fields in different shadow roots; and the popup
reported "Filled." when nothing was filled.

## What changed

- **`extension/deep.js` (new content script, loaded first):** `deepQueryAll` (every match in page order,
  descending into open shadow roots), `deepActiveElement`, `eventTarget` (the real target from
  `composedPath()`), `composedClosest`, `composedParent`. Shared with `detect.js` and `inline.js`
  through the extension's isolated world.
- **`fill.js`:** a serialized function cannot import, so it carries its own copy of the walk; it finds
  fields in open shadow roots, orders username-before-password by the walk's order and picks the
  *nearest* username, recognises `autocomplete` tokens (`"username webauthn"`), and dispatches `input`
  with `composed: true` (as a typed one is) so a listener outside the shadow root hears the fill.
- **`inline.js`:** real target from the composed path, deep active element for the focus checks, and a
  deep "is there a password on the page" search.
- **`detect.js`:** deep password and username search, deep enclosing-container search (climbs through
  shadow hosts), and the real click and Enter targets. Every `isTrusted` check is kept.
- **Honest fill results:** a fill that finds no field returns `no_login_field`; the popup says "No login
  fields found on this page." and the in-page menu says the same and stays open, instead of reporting a
  fill.
- **`manifest.json`:** `deep.js` added to the content scripts (the exact-manifest test is updated for it).

**Not supported, by design:** closed shadow roots. The browser hides them from page script and from any
content script; the extension does not try to get around that. There the menu does not open and the
popup says no fields were found.

## Tests

- `extension/test-pages/shadow-login.html`: a Reddit-style login built from web components — separate
  shadow roots for the username, the password and the Log In button, hidden/zero-size/transparent
  password fields inside shadow DOM placed *before* the real ones, a fetch-based sign-in, `?mode=nested`
  (components inside another component's shadow root) and `?mode=closed`.
- `app/tests/e2e/test_shadow_dom.py` (7): the menu on the username (flat and nested) fills both fields
  without submitting, the page hears the composed `input` events, hidden shadow fields stay empty; the
  menu on the password field; the popup's Fill; a new login signed in through shadow DOM is offered and
  saved; a changed password offers the update; a closed shadow root gets no menu and the popup says so.
- **They fail on the old code**: with the previous extension restored, all 7 fail; with the fix, all 7
  pass.

## Results

See the report for this change (the commands and their real output).

## Not verified, and why

- **Re-checking on the real Reddit after the fix.** Reddit stopped offering a Log In control to the
  test browser after several loads (very likely a bot check), so the fixed build could not be shown
  working on the live site. The structure that was reproduced there is what `shadow-login.html` copies,
  and the old code failed on both; the owner should try Reddit in a browser.
- **Submitting a fake login to Reddit** (to see the save prompt there) was blocked by the harness and
  not attempted. The save prompt through shadow DOM is tested on the local page.
- Edge was not re-run for this change: Edge support in the test harness is still an uncommitted change
  in another worktree.

## `[S]` files for the owner's review

`extension/fill.js`, `extension/detect.js`, `extension/inline.js`, `extension/deep.js` (new). Also
changed: `background.js` (`[S]`: a fill that finds no field is no longer reported as a success),
`popup.js`, `menu.js`, `manifest.json` (`[S]`: `deep.js` is added to the content scripts; no new
permission).
