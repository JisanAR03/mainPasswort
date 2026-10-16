# M4-04 detect.js and the save or update flow (M4b, all-sites approval)

Milestone: M4 · Sensitive: yes · Depends on: M4-03

## Goal

After a login form is submitted, `detect.js` hands the candidate to the service worker,
which keeps it in `chrome.storage.session` for 2 minutes and shows a badge. The popup then
offers Save, Update existing or Dismiss — and nothing is sent to the app without that click.
All-sites access is an **optional permission** the owner turns on from the popup; it is
never part of the base install and can be turned off the same way.

## Files you may change

- extension/detect.js, extension/background.js, extension/popup.html, extension/popup.js
- extension/manifest.json (optional_host_permissions only)
- extension/test-pages/ (a submit fixture)
- app/tests/e2e/test_save_flow.py

## Spec references

- docs/specs/browser-protocol.md — save and update (M4b)
- docs/specs/milestones.md — "M4b: nothing is saved without a click in the popup"

## Acceptance tests (write these first, show them failing)

- [x] the base manifest carries no all-sites access; the popup's "watch for logins" toggle
      is what asks for it, and turning it off unregisters the detector
- [x] after a submit, the candidate sits in chrome.storage.session only, with a badge
- [x] nothing is saved without a click in the popup
- [x] Save sends `save_login` once and clears the candidate
- [x] Update sends `update_password` for the matching entry
- [x] Dismiss sends nothing and clears the candidate
- [x] a candidate older than 2 minutes is ignored

## Out of scope

Auto-merge (M6), saving without a click (never)
