# M4-01 Manifest, service worker and the api.js shim

Milestone: M4 · Sensitive: no · Depends on: M3-04

## Goal

The extension's skeleton: a Manifest V3 `manifest.json` whose fixed `key` pins the ID to
`pkmjgefocdecdncjcpdlohfnahebkkpi`, exactly four permissions (`nativeMessaging`,
`activeTab`, `scripting`, `storage`) and no all-sites access, `api.js` wrapping `chrome.*`
so a Firefox shim can be added later, and `background.js` owning the native port. The
Playwright end-to-end harness carries the extension through Chromium with the real host and
a real bridge in front of a weak test vault.

## Files you may change

- extension/manifest.json, extension/api.js, extension/background.js
- app/tests/e2e/conftest.py, app/tests/e2e/bridge_app.py
- pyproject.toml (playwright dev dependency), .github/workflows/ci.yml (browser install)

## Spec references

- docs/specs/browser-protocol.md — manifest table, native host, message envelope
- docs/specs/architecture.md — extension service worker: one password, one fill

## Acceptance tests (write these first, show them failing)

- [x] Chromium loads the unpacked extension and its ID equals the pinned ID
- [x] the manifest asks for exactly nativeMessaging, activeTab, scripting, storage — no
      host permissions in the base install
- [x] with the bridge running, `hello` over the real host returns the app version and
      profile name
- [x] with no bridge running, the popup reports app_not_running

## Out of scope

The popup UI (M4-02), fill.js (M4-03), detect.js (M4-04)
