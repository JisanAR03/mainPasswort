# M3-04 Native messaging host relay and installer

Milestone: M3 · Sensitive: yes · Depends on: M3-03

## Goal

`host/pm_host.py`: the stdio process Chrome/Brave start. It reads one framed request
from stdin, forwards it to the app's local socket, writes the framed reply to stdout,
and holds nothing. `scripts/install_native_host.py` writes the host manifest for
Chrome and Brave with `allowed_origins` fixed to our extension ID (derived from the
keypair generated once into `extension/key.pem`, which is git-ignored; M4-01 embeds
the public half in the manifest).

## Files you may change

- app/src/personal_vault/host/__init__.py, app/src/personal_vault/host/pm_host.py
- scripts/install_native_host.py
- scripts/generate_extension_key.py
- .gitignore (*.pem, extension/native-host/)
- app/tests/integration/test_host_relay.py (subprocess, real framing)
- app/tests/unit/test_install_native_host.py

## Spec references

- docs/specs/browser-protocol.md — Native host: stdio, framing, 16 KB cap,
  `allowed_origins` lists only our extension ID; the host holds no state
- docs/specs/milestones.md — M3 done when: "A subprocess test speaks real
  native-messaging framing to the host"

## Acceptance tests (write these first, show them failing)

- [x] a subprocess host relays a framed request to a running server and returns the
      framed reply
- [x] the same host process answers a second request after the first
- [x] with no server running, the host answers `app_not_running`
- [x] a request whose declared length exceeds 16 KB gets `too_large` and the host
      stays usable for the next request
- [x] when stdin closes, the host exits cleanly (code 0)
- [x] the install script writes the manifest with `allowed_origins` restricted to the
      fixed extension ID and registers it for Chrome and Brave

## Out of scope

The extension itself (M4), uninstalling (not asked), Firefox (Q5: Chrome and Brave
only in v1)
