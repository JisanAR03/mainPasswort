# ADR-006 Conflicts: keep both in v1, merge in M6

Status: Accepted
Date: 2026-10-15

## Context
Automatic merge is the most bug-prone code in any sync system.

## Decision
v1 detects conflicts and asks. M6 adds entry-level merge keyed on the entry UUID: the newer
`updated_at` wins, the loser goes to history, and deletions recorded as tombstones are
respected.

## Consequences
A rare manual step in v1, in exchange for zero silent merges until the merge code has
property tests.
