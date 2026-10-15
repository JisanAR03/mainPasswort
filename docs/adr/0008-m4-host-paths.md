# ADR-008 The "M4.0" task and host path ownership

Status: Accepted
Date: 2026-10-15

## Context
Section 8 of the design pack says host paths are "confirmed per OS in M4.0", but M4's tasks
start at M4-01 — there is no M4.0. The owner asked for the simplest reasonable resolution,
recorded here.

## Decision
"M4.0" is a typo in the spec. Host install paths are produced and verified by M3-04
(`scripts/install_native_host.py`), which writes the native-messaging host manifest for
Chrome and Brave on Windows and Linux. The resulting paths are recorded in
`docs/setup-browser.md` in M4-05.

## Consequences
No new milestone or task is created. The path confirmation step is tested in M3 (the host
manifest is written and a framing round trip runs against the installed host), and the
documentation step stays in M4.
