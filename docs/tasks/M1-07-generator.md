# M1-07 Password generator

Milestone: M1 · Sensitive: yes · Depends on: M1-01

## Goal
A password generator built only on the `secrets` module, honouring every option and
covering every requested character class, with look-alike exclusion.

## Files you may change

- app/src/personal_vault/core/generator.py
- app/tests/unit/test_generator.py

## Spec references

- docs/specs/data-model.md — settings.json defaults (generator row)
- AGENTS.md — rule 2 (randomness only from `secrets`)

## Acceptance tests (write these first, show them failing)

- [x] Output length is exact; every requested class appears at least once
- [x] Disabled classes never appear
- [x] `exclude_lookalikes` removes the look-alike set from all pools
- [x] Randomness comes from `secrets` (monkeypatched `secrets` functions are hit)
- [x] Fewer classes than length is refused; no class at all is refused
- [x] Returns a `SecretStr`

## Out of scope

- The generator dialog (M2-04)
