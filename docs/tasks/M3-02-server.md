# M3-02 Local socket server

Milestone: M3 · Sensitive: yes · Depends on: M3-01

## Goal

`server.py`: the Qt local socket server the native host relays to. It listens on a
named pipe / Unix socket that only the current OS user can read, frames messages with
the same 4-byte native-order length prefix the host uses, dispatches through the M3-01
`Dispatcher`, and rate-limits `get_secret` to 10 per minute per pairing key.

## Files you may change

- app/src/personal_vault/bridge/server.py
- app/tests/unit/test_server.py (pytest-qt; in-process QLocalSocket client)

## Spec references

- docs/specs/browser-protocol.md — Native host, framing, `get_secret` 10 per minute
- docs/specs/threat-model.md — B4: only your user can read the socket

## Acceptance tests (write these first, show them failing)

- [x] a framed request sent over a real QLocalSocket gets one framed reply
- [x] back-to-back requests on one connection each get their own reply
- [x] a declared length over 16 KB → `too_large` and the connection is closed
- [x] the server asks the OS for user-only access (UserAccessOption set)
- [x] `get_secret` is limited to 10 per minute per pairing key; another key is unaffected
- [x] a non-JSON body → `bad_request` reply, and the connection stays usable
- [x] replies use the same framing the host will relay (native-order length prefix)

## Out of scope

The pairing flow and its storage (M3-03), the stdio host relay (M3-04), wiring the
server into the desktop app (done when M3-03 provides real pairing)
