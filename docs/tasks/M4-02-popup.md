# M4-02 Popup: matches, fill, lock, unlock, add login

Milestone: M4 · Sensitive: no · Depends on: M4-01

## Goal

The only extension UI: it shows the logins that match the active tab (titles and usernames
only), a fill button per match, lock and unlock buttons, and an "add login for this site"
form. The popup never sees a password: fill goes through the service worker, and the add
form sends the typed password straight to the app.

## Files you may change

- extension/popup.html, extension/popup.js, extension/popup.css
- extension/background.js (message routing)
- app/tests/e2e/test_popup.py

## Spec references

- docs/specs/browser-protocol.md — messages, fill procedure, locked or not running
- docs/specs/data-model.md — site matching rules (points 2–5)

## Acceptance tests (write these first, show them failing)

- [x] the popup lists the matches for the tab's URL with title and username, and no
      password ever appears in the popup page
- [x] a look-alike domain gets no suggestions
- [x] an https entry is refused on an http page, and an http entry shows its warning
- [x] the fill button starts exactly one fill
- [x] lock sends `lock`; unlock sends `show_unlock`
- [x] "add login for this site" sends `save_login` and the password is not stored in the
      extension
- [x] with the vault locked, the popup shows "Unlock in app" instead of matches

## Out of scope

The fill mechanics (M4-03), save detection (M4-04)
