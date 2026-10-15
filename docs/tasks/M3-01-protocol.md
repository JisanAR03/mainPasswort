# M3-01 Protocol: strict messages, size limits, dispatch

Milestone: M3 · Sensitive: yes · Depends on: M2-08

## Goal

The bridge message layer: every request is parsed against a strict schema, oversized
requests are refused, unknown fields and types are rejected (never ignored), and dispatch
allows exactly the nine message types of the browser protocol.

## Files you may change

- app/src/personal_vault/bridge/protocol.py
- app/src/personal_vault/bridge/backend.py (VaultBackend: the bridge's door to the vault)
- app/src/personal_vault/core/vault.py (matching_logins used by the bridge)
- app/tests/unit/test_protocol.py
- app/tests/integration/test_bridge_backend.py
- app/tests/security/test_invariants.py (I4, I5 canaries)

## Spec references

- docs/specs/browser-protocol.md — envelope, error codes, message table
- docs/specs/threat-model.md — invariants I4, I5

## Acceptance tests (write these first, show them failing)

- [x] parse accepts a well-formed envelope for each of the nine message types
- [x] unknown type, unknown field, wrong type, missing id → `bad_request` reply, never a crash
- [x] requests over 16 KB → `too_large`
- [x] dispatch exposes exactly the nine types (no list-all, search, settings, export)
- [x] Hypothesis fuzz: malformed, oversized and unknown messages always get an error reply
- [x] `get_secret` and `update_password` re-match the URL; a mismatch → `url_mismatch` (I4)
- [x] a locked vault answers every request with `locked` (I5)
- [x] unpaired requests are refused with `not_paired` except `hello`, `pair_request`,
      `show_unlock` and `generate_password`
- [x] replies serialize under the 64 KB cap

## Out of scope

Socket transport (M3-02), the pairing flow (M3-03), the host relay (M3-04)
