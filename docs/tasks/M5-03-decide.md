# M5-03 decide.py, the pure decision table

Milestone: M5 · Sensitive: yes · Depends on: M5-02

## Goal

`decide(local, remote, state) -> Action`: no network, no disk, no clock, so every row of the
spec's decision table is one small test and the table can be read next to the code. This is
where invariant I6 is *decided* — an upload is only ever chosen for a remote version the
state has already seen — and where the first-time-link case (ADR-010) enters as an action of
its own rather than a silent guess.

"Local changed" means `local_dirty` or the local SHA-256 differs from
`last_synced_local_sha256`; "remote changed" means the Drive `md5Checksum` differs from
`last_synced_remote_md5`.

## Files you may change

- app/src/personal_vault/sync/decide.py (new, [S])
- app/src/personal_vault/sync/state.py (new: the state.json shape and its validation)
- app/tests/sync/test_decide.py

## Spec references

- docs/specs/sync.md — the decision rule
- docs/adr/0010-first-time-link.md — the missing-state case
- docs/specs/data-model.md — sync/state.json

## Acceptance tests (write these first, show them failing)

- [ ] every row of the table has its own test: nothing, upload, download, conflict,
      stop-and-ask, update-state-only
- [ ] the same content on both sides (equal sha and md5) is state-only, never a transfer
- [ ] a remote file that is missing or trashed is stop-and-ask, never "create it again"
- [ ] an unreadable state.json is treated as missing, which is the first-time-link flow
- [ ] a state.json from a newer schema refuses to sync and asks for a newer app
- [ ] property test: no combination of inputs yields an upload while the remote md5 differs
      from the last synced remote md5 (I6)
- [ ] property test: the decision never depends on anything but its three arguments

## Out of scope

Doing any of it (M5-04)
