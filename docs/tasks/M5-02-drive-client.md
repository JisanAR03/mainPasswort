# M5-02 drive_client.py and fake_drive.py behind one interface

Milestone: M5 · Sensitive: no · Depends on: M5-01

## Goal

One small interface for everything sync needs from Drive, with two implementations: the real
v3 REST client and an in-memory fake the tests drive. The interface is about *whole vault
files*, never about bytes of a vault's contents:

- the file for a profile (found by `appProperties.pm_profile_id`, never by name)
- its metadata: id, name, `md5Checksum`, version, size, trashed
- upload (create or update), download, and the revisions since a version
- the `PersonalVault/<profile_id>/` folder

The fake can drop the network, return 429s and 5xx, corrupt a download, and inject a write
from "another device" between any two calls, which is what the engine's race handling is
tested with.

## Files you may change

- app/src/personal_vault/sync/drive_client.py (new)
- app/src/personal_vault/sync/fake_drive.py (new)
- app/tests/sync/test_drive_client.py

## Spec references

- docs/specs/sync.md — Drive layout, closing the race window, how it is tested
- docs/specs/threat-model.md — I6

## Acceptance tests (write these first, show them failing)

- [ ] the client finds the profile's file by `appProperties`, not by name, and treats a
      trashed file as *there but trashed* rather than missing
- [ ] upload sends the exact bytes given, sets the app properties, and returns the new md5
      and version
- [ ] every request goes to the Drive v3 endpoint with the bearer token from the caller
- [ ] a 401, 403, 404, 429, 5xx and a timeout each raise a distinct, retryable-or-not error
- [ ] the fake implements the same behaviour, and its injected failures are what the tests
      asked for
- [ ] a download that does not match the requested md5 is refused by the client
- [ ] no client call logs a token or a body

## Out of scope

The decision table (M5-03), the executor (M5-04)
