# M3-03 Pairing: confirmation dialog and matching code

Milestone: M3 · Sensitive: yes · Depends on: M3-02

## Goal

`pairing.py`: the pair flow. A `pair_request` carries a fresh 32-byte key; the app
shows a confirmation dialog with a 6-character code the browser also shows; only a
clicked Pair within 60 seconds stores the key — in the vault itself, in the hidden
`.app` group (`browser-pairing`, data-model.md) — and only then do requests with that
key pass `key_valid`.

## Files you may change

- app/src/personal_vault/bridge/pairing.py
- app/src/personal_vault/core/vault.py (the `.app` group get/set the key lives in)
- app/src/personal_vault/ui/pairing_dialog.py
- app/src/personal_vault/bridge/backend.py, bridge/protocol.py (session swap, socket name)
- app/src/personal_vault/ui/app.py (start the bridge server, swap sessions on lock)
- app/tests/unit/test_pairing.py
- app/tests/integration/test_bridge_pairing.py
- app/tests/ui/test_pairing_dialog.py

## Spec references

- docs/specs/browser-protocol.md — `pair_request`: both sides show the same 6-character
  code, 60-second timeout
- docs/specs/data-model.md — the hidden `.app` group holds `browser-pairing`
- docs/specs/threat-model.md — every request must carry a pairing key stored in the vault

## Acceptance tests (write these first, show them failing)

- [x] the code is 6 characters from an unambiguous alphabet, deterministic per key
- [x] a malformed key (wrong length, not 32 bytes of base64) is refused without a dialog
- [x] clicking Pair stores the key in the vault and `key_valid` accepts it
- [x] Cancel stores nothing
- [x] re-pairing with the same key succeeds without a second dialog
- [x] pairing a second key requires the dialog; accepted replaces, rejected keeps the old
- [x] a confirm after the 60-second window is refused
- [x] with no unlocked vault, a new key cannot be paired
- [x] the dialog shows the browser name and the code; Pair and Cancel decide the result

## Out of scope

The extension side of the flow (M4-01), the host relay (M3-04), multiple simultaneous
browsers (v1 pairs one key, replacing on a new pairing)
