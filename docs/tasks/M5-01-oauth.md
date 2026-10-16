# M5-01 oauth.py: connect Google, token in the vault

Milestone: M5 · Sensitive: yes · Depends on: M2-08

## Goal

Sign in with Google for `drive.file` alone, through a Desktop-app OAuth client with a
loopback redirect and PKCE. The refresh token lives in the profile's vault — the hidden
`.app/drive-sync` entry, refresh token in the protected Password field, account email beside
it — so sync runs only while that profile is unlocked and no token ever reaches a plaintext
file, a log or an error message. Disconnect removes the entry.

A refresh that comes back `invalid_grant` raises `ReconnectRequired` and the UI says
"Reconnect Google"; local use of the vault continues. Any other refresh failure is
retryable.

## Files you may change

- app/src/personal_vault/sync/oauth.py (new, [S])
- app/src/personal_vault/core/vault.py (app-entry fields only)
- app/src/personal_vault/services.py (the functions the UI calls)
- app/tests/sync/test_oauth.py, app/tests/sync/__init__.py

## Spec references

- docs/specs/sync.md — permissions and sign-in; errors and retries
- docs/specs/data-model.md — the hidden `.app` group and the `drive-sync` entry
- docs/setup-google-drive.md — the owner's own Cloud project steps

## Acceptance tests (write these first, show them failing)

- [ ] the flow asks for `drive.file` only, with a loopback redirect and PKCE
- [ ] the token round-trips through the vault: save, lock, unlock, load
- [ ] the refresh token, the client secret and the access token never appear in a log
      record or an error message
- [ ] `invalid_grant` raises `ReconnectRequired`; other failures raise a retryable error
- [ ] disconnect deletes the entry and nothing else in the vault changes
- [ ] a missing or unreadable client_secret.json is reported, not crashed on
- [ ] a token minted for another scope is refused

## Out of scope

Drive calls (M5-02), scheduling (M5-04)
