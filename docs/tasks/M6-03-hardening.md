# M6-03 Hardening

Milestone: M6 · Sensitive: **yes** — `core/vault.py` is an `[S]` file (the export fix below)
· Depends on: M5

## Goal

The four audits the milestone names — dependencies, browser permissions, logs and temp files,
crash reports — each answered with a command that was run rather than an opinion. Anything the
audit turns up as a real leak is fixed here; anything that is the owner's call is written down.

## Files you may change

- app/src/personal_vault/ui/app.py (`configure_logging()`, called from `run()`)
- app/src/personal_vault/ui/vault_view.py (two `log.debug` lines)
- app/tests/security/test_invariants.py (one new test, under I2)
- app/src/personal_vault/core/vault.py (`export_kdbx`, owner-decided fix below — `[S]`)
- app/tests/integration/test_transfer.py (the test for it)
- docs/tasks/M6-03-hardening.md (this card)

The `[S]` change came after the audits, on the owner's decision, and is the one part of this
card that needs a reviewer's eye; no `Security-Reviewed-By:` trailer is recorded for it (rule
9 — the owner adds that, nobody else).

## 1. Dependencies

Six direct runtime dependencies, all of them doing work that would otherwise be ours to write:

| Package | Why |
| --- | --- |
| pykeepass | the KDBX format. Rule 2: encryption only through it |
| platformdirs | the platform data folder, so no hand-rolled `%LOCALAPPDATA%` |
| PySide6 | the desktop UI (Qt) |
| google-auth | the OAuth token and its refresh |
| google-auth-oauthlib | the loopback-installed-app flow in `sync/oauth.py` |
| requests | the Drive HTTP calls in `sync/drive_client.py` |

`uv.lock` resolves 84 packages including build and dev groups; the dev group is the test and
lint toolchain (pytest, hypothesis, ruff, mypy, bandit, import-linter, pip-audit, playwright,
pre-commit), none of which ships.

    $ uv run pip-audit
    No known vulnerabilities found
    Name           Skip Reason
    personal-vault Dependency not found on PyPI and could not be audited: personal-vault (0.1.0)

The one skip is this project itself, which is not published and so cannot be audited against
an advisory database. Nothing was added for M6-03; adding anything needs the owner first
(rule 5), which is where M6-04 stands.

## 2. Browser permissions

`extension/manifest.json` asks for four permissions and one optional host permission. Every
one is used, and the code that uses it is:

| Permission | Used by |
| --- | --- |
| `nativeMessaging` | `api.js:29` `chrome.runtime.connectNative(HOST_NAME)` — the only way to the desktop app |
| `activeTab` | the click-to-fill path: `background.js:98` `scripting.executeScript` into the tab the owner clicked, which activeTab grants without a host permission |
| `scripting` | `background.js:43/53` register and unregister the detect content script, and the `executeScript` above |
| `storage` | `api.js:15` the pairing key in `storage.local`; `background.js` keeps the save candidate in `storage.session` |
| `<all_urls>` (optional) | `popup.js:193` `permissions.request`, asked for at the moment the owner turns on watch-for-saves, and dropped again by `background.js:53` when it goes off |

Two things worth stating plainly, both by design and neither new:

- The extension does keep one secret: the **pairing key** in `storage.local` (M3-03). It is a
  token the desktop app issued, not a password, and it is what stops any other extension or
  page from driving the bridge.
- `<all_urls>` is never granted silently — it is an optional permission and the code path
  that uses it only runs after the request above returns true.

The manifest's `key` is a **public** key that pins the extension id the native-host
registration names. The matching private key `extension/key.pem` is on disk and is *not* in
the repository: `.gitignore` has `*.pem`, and `git ls-files extension/` lists only the twelve
source files, no key.

## 3. Logs

Nothing configures a logging handler, so at runtime Python's last-resort handler is what
exists and only `WARNING` and above reach stderr. Two paths could still put an entry field
into a record, and both are now closed:

1. **Our own logging.** `vault_view.py` logged the whole entry after a save —
   `log.debug("saved entry %s", entry)` — and a `LoginEntry` renders as every field it has.
   `SecretStr.__str__` redacts the password, so the password was never in that line, but the
   title, the username and the notes were. Both lines (`_add_flow`, `_edit_selected`) now log
   `entry.id`.
2. **pykeepass.** Its own DEBUG logging prints the XPath behind every search, and pykeepass
   searches *by value*: the record reads
   `.../Value[text()="CANARY-title-4b7c"]/../../String/Key[text()="UserName"]/../Value[text()="CANARY-user-4b7c"]`.
   `run()` now calls `configure_logging()`, which puts `pykeepass` at `WARNING`, so enabling
   logging in a future build cannot surface those.

Both were found by the new test, `test_i2_the_app_never_logs_an_entry_field` in
`app/tests/security/test_invariants.py`: it runs a real add and a real edit with a canary in
every field, keeps every record at DEBUG, and asserts none of the four values appears. It
fails on the pre-fix code (`assert ['CANARY-note...RY-user-4b7c'] == []`).

The existing I2 test only ever exercised `RedactionFilter` with a hand-registered secret. That
filter is still installed by nobody — the app registers no secrets with it, because
`SecretStr` already keeps them out of the way this file is meant to catch. It stays as the
second line of defence it was written to be; this card records that it is not load-bearing
today rather than pretending otherwise.

## 4. Temp files

Two places write outside the vault's own folder, and both were read:

- `core/kdf.py` `calibrate_iterations` creates `mkdtemp(prefix="pv-calibrate-")`, writes
  throwaway KDBX files with a `secrets.token_hex` password that is never reused, and removes
  the whole folder in a `finally`.
- `core/storage.py` `atomic_write` writes `<name>.tmp-<pid>-<random>` **beside the target**
  (same filesystem, so the rename is atomic) and unlinks it in a `finally`. A vault temp file
  therefore sits in the profile folder for the length of one save, encrypted, like the vault.

The one remaining temp-file-adjacent path is the bridge socket: `host/pm_host.py` connects to
`<TMPDIR>/personal-vault-bridge` on POSIX because that is where `QLocalServer` puts a socket
file. The server sets `QLocalServer.SocketOption.UserAccessOption` (`bridge/server.py:115`), so
the socket is the owner's alone on Unix, and on Windows it is a named pipe with the default
per-user ACL. No secret is written to it; it carries protocol messages.

## 5. Crash reports

No crash-reporting or telemetry library, endpoint or identifier exists anywhere in the tree:

    $ grep -rniE "sentry|telemetry|analytics|crash.?report|bugsplat" app/src extension
    (no matches)

The only hosts the app talks to are `googleapis.com` (the Drive v3 files, upload and about
endpoints) and `oauth2.googleapis.com/token`, both in `sync/drive_client.py` and
`sync/oauth.py`. The browser extension talks only to the native host
(`connectNative`) — `grep -rn "console\." extension/*.js` finds no logging in it at all.

## Found while auditing: an export carries the Drive token

Not a leak found by a grep but by following the token to its file. `save_google_account`
stores the Drive refresh token in the vault's hidden `.app` group
(`services.py:300` → `set_app_value`), and `export_kdbx` (`core/vault.py:285`) writes its copy
by opening the vault and re-saving it under the new password — so the exported file contains
`.app` and therefore the token, and the pairing key with it.

- CSV export is not affected: `export_csv` writes the Logins group only.
- Merge is not affected: `merge_side()` leaves `.app` out, so no merge moves a token.
- The spec is not contradicted: data-model.md says "the default export is an encrypted KDBX
  copy", and a copy is what it is. The spec simply never considered app values.

**Decided by the owner (2026-10-16): strip `.app` from the export.** `export_kdbx` now deletes
the `.app` group from the copy before it saves it. The cost the card named is real and stands:
someone who exports a vault and then uses the export as their main vault has to link Drive and
pair the extension again. The owner took the trade.

The change is in `core/vault.py` — an `[S]` file — so it carries its own test,
`test_export_kdbx_leaves_the_apps_own_secrets_behind` in `app/tests/integration/test_transfer.py`
(a Drive-token canary is set on the session, the export is opened, and the test asserts the
`.app` group is absent from the copy while the source vault keeps its token). The export dialog
was left as it is: its KDBX option is a copy of your entries either way, and the honest place
for the token is this page and
[docs/known-limitations.md](../known-limitations.md), which no longer calls it an open
question.

## Acceptance tests

- [x] each of the four audits answered with a command and its output (above)
- [x] `pip-audit` clean (`No known vulnerabilities found`)
- [x] every extension permission traced to the code that uses it
- [x] the log leak found and fixed, with a test that fails on the old code
- [x] `gitleaks` clean on the branch (`27 commits scanned … no leaks found`, run after M6-01
      and M6-02 were committed)
- [ ] the owner re-runs `uv run pip-audit` and `gitleaks detect --source . --config .gitleaks.toml`
      on `main` at release time — M6's "Done when" line is theirs
- [x] the owner decided the KDBX export's `.app` group — strip it — and the fix is in with its
      test (above)

## Out of scope

Adding any dependency (M6-04 asks first, rule 5), an install-time permission review of the
packaged app (there is no package yet), and turning the extension's `<all_urls>` grant into
per-site grants — a product decision, not a hardening one
