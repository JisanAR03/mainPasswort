# M1-05 Site matching

Milestone: M1 · Sensitive: yes · Depends on: M1-01

## Goal
The five site-matching rules as pure functions, shared later by the UI and the bridge.

## Files you may change

- app/src/personal_vault/core/matching.py
- app/tests/unit/test_matching.py

## Spec references

- docs/specs/data-model.md — Site matching rules

## Acceptance tests (write these first, show them failing)

- [x] Exact hostname match; case and trailing dot are normalized
- [x] `match_subdomains` matches `*.entry-host` but never a parent or a suffix look-alike
- [x] Look-alike domains (homoglyphs, digit substitutions) do not match
- [x] International names match after punycode conversion
- [x] Ports must match when the entry URL names one
- [x] An https entry never matches an http page; an http entry matches only http

## Out of scope

- Enforcing the rules in the bridge (I4, M3)
