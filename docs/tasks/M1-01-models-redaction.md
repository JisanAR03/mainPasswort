# M1-01 Domain models and log redaction

Milestone: M1 · Sensitive: yes · Depends on: M0-01

## Goal
The domain types every layer shares (`SecretStr`, `LoginSummary`, `LoginEntry`), plus the
logging filter that keeps secrets out of logs.

## Files you may change

- app/src/personal_vault/core/models.py
- app/src/personal_vault/core/redaction.py
- app/tests/unit/test_models.py
- app/tests/unit/test_redaction.py

## Spec references

- docs/specs/data-model.md — Python domain model
- docs/specs/threat-model.md — invariant I2

## Acceptance tests (write these first, show them failing)

- [x] `str(SecretStr(...))`, `repr(...)` and f-strings print `***`, never the value
- [x] The value is only reachable through `reveal()`
- [x] `LoginSummary`/`LoginEntry` match the spec's field list and types
- [x] A registered secret never appears in a log record's message, arguments or
      exception text; `[REDACTED]` appears instead

## Out of scope

- Any file IO (M1-03), the vault (M1-04)
