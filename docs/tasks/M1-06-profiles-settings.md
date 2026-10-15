# M1-06 Profiles and settings

Milestone: M1 · Sensitive: no · Depends on: M1-03

## Goal
`profiles.json` and `settings.json` with schema versions: atomic writes, defaults for
every setting, and files with a newer `schema_version` opened read-only and never
overwritten.

## Files you may change

- app/src/personal_vault/core/profiles.py
- app/src/personal_vault/core/settings.py
- app/tests/integration/test_profiles_settings.py

## Spec references

- docs/specs/data-model.md — profiles.json, settings.json defaults, "Every JSON file …"

## Acceptance tests (write these first, show them failing)

- [x] Profiles can be created (random `p_` id), renamed, deleted and re-listed
- [x] `last_used_profile_id` is persisted
- [x] Settings return every documented default and persist changes
- [x] A file with a newer `schema_version` loads read-only and every write refuses
- [x] JSON files are written atomically (temp + rename) and re-read before the rename

## Out of scope

- The picker and settings UI (M2)
