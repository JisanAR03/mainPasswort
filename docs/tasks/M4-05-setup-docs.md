# M4-05 setup-browser.md and milestone close-out

Milestone: M4 · Sensitive: no · Depends on: M4-01..04

## Goal

The owner-facing guide: load the extension in Chrome and Brave, run the native host
installer, make this the primary password manager (turn off the built-in one, disable other
managers, pin, set the shortcut), and the honest limits. Plus the M4 "Done when" ticks in
the milestone list.

## Files you may change

- docs/setup-browser.md
- docs/specs/milestones.md (M4 Done-when ticks)

## Spec references

- docs/specs/browser-protocol.md — "Making it your primary manager"
- docs/specs/milestones.md — M4 Done when

## Acceptance tests (write these first, show them failing)

- [x] setup-browser.md covers: load unpacked in Chrome and Brave; the host installer; the
      browser's own password manager and autofill turned off; disable other managers; pin;
      set the shortcut
- [x] it states the limits: no extension can block another manager's prompts, and the
      browser's own passkey dialogs still appear
- [x] it explains the M4b all-sites permission in plain words and how to turn it off, and
      says the extension never sees a password except the one you click to fill
- [x] the M4 "Done when" items in milestones.md are ticked against tests that ran

## Out of scope

Packaging (M6), Firefox (Q5)
