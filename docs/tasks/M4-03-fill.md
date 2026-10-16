# M4-03 fill.js with visibility checks

Milestone: M4 · Sensitive: yes · Depends on: M4-02

## Goal

The function the service worker injects into frame 0 after a fill click: it fills only
visible fields (non-zero size, not hidden, not transparent), fires `input` and `change`
events, never submits, and returns what it filled. It receives the username and password as
arguments and stores nothing.

## Files you may change

- extension/fill.js
- extension/background.js (injection call)
- extension/test-pages/ (hostile HTML fixtures)
- app/tests/e2e/test_fill.py

## Spec references

- docs/specs/browser-protocol.md — fill procedure steps 4–6
- docs/specs/threat-model.md — the page is hostile; one fill, top frame only

## Acceptance tests (write these first, show them failing)

- [x] a normal login page fills after one click and does not submit
- [x] hidden, zero-size and transparent fields are never filled
- [x] a cross-origin iframe login form is never filled
- [x] only the top frame is filled
- [x] navigating between listing and clicking aborts the fill (nothing fills on the new page)
- [x] the page's own scripts cannot see the fill (no globals left behind) and the extension
      keeps no copy

## Out of scope

Save detection (M4-04), Firefox (Q5)
