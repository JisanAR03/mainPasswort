# Milestones

> Source: design pack draft v0.1, sections 10–13. Status: **G0 not passed; M0 not started.**

Seven milestones, M0 to M6. Each is split into tasks small enough for one AI session, and each
is closed by a gate that the owner signs off. A milestone is done only when every "Done when"
item is ticked by a test that actually ran, never because the AI said so.

Real passwords wait for G2 and real sync waits for G4, so the riskiest code always runs on
fake data first.

## Gates

| Gate | After | What it unlocks |
| --- | --- | --- |
| G0 | Design pack approved | M0 may start |
| G1 | M0 | Format, browser and Drive approaches confirmed |
| G2 | M2 | Real passwords may go into the app, with a KeePassXC-readable backup kept elsewhere |
| G3 | M4 | Extension used on real websites |
| G4 | M5 | Sync turned on for real vaults |
| G5 | M6 | Public release, after an outside security review |

## Roadmap

| When | Milestones |
| --- | --- |
| Now | G0 approval, then M0 spikes and skeleton |
| Next | M1 vault core, M2 desktop app, M3 bridge and native host |
| Later | M4 browser extension, M5 Google Drive sync, M6 merge, hardening and release |

Dates stay open until M0 shows how many task cards get finished in a week.

---

## M0: Spikes and skeleton

**Goal:** prove the three risky integrations work on the target machine before writing the
real app. Spike code is thrown away; only the findings are kept, in `docs/spikes/`.

Tasks:

- **M0-01 Repo skeleton:** `pyproject.toml`, uv, ruff, mypy, pytest, pre-commit, and CI
  running one passing test.
- **M0-02 KDBX spike:** create a vault with pykeepass using Argon2id at the D9 settings, open
  it in KeePassXC, open a KeePassXC-made vault in pykeepass, read and write custom fields, find
  the Recycle Bin and deleted-object records, and time the unlock.
- **M0-03 Browser spike:** a hello-world extension talks to a host, which talks to a Qt local
  socket, in Chrome and Brave on your OS.
- **M0-04 Drive spike** (throwaway Google account): sign in with `drive.file`, upload, read
  the version and `md5Checksum`, list revisions, set `appProperties`, and confirm the token
  survives 8 days with the consent screen in production.

Done when:

- [ ] CI is green on the skeleton
- [ ] KeePassXC opens a pykeepass vault and shows Argon2id in its database settings
- [ ] A message makes the full round trip in both browsers
- [ ] A file round-trips through Drive, and its revision list is readable
- [ ] Each spike has a one-page report; ADR-001, ADR-003 and ADR-004 are confirmed or revised

## M1: Vault core (no UI)

**Goal:** a tested Python library that creates, unlocks, edits, saves and recovers vaults.

Tasks:

- **M1-01** `models.py` with `SecretStr`; `redaction.py` logging filter.
- **M1-02** `kdf.py` calibration; create and open a vault; a distinct error for a wrong
  password.
- **M1-03** `storage.py`: atomic save, read-back check, rotating backups, recovery from the
  newest good backup.
- **M1-04** `vault.py`: add, edit, delete, search, history.
- **M1-05** `matching.py` with the [site matching rules](data-model.md#site-matching-rules).
- **M1-06** `profiles.py` and `settings.py` with schema versions.
- **M1-07** `generator.py`.

Done when:

- [ ] Create, close and reopen returns identical entries
- [ ] A wrong password raises `InvalidPassword` and leaves no partial state
- [ ] Flipping single bytes at 200 random offsets, or truncating the file, gives a clean
      error, never a crash or an overwrite
- [ ] Killing the save process at random moments 200 times always leaves a vault that
      decrypts (I3)
- [ ] `keepassxc-cli` lists entries from our vaults in CI
- [ ] Two profiles cannot open each other's vaults
- [ ] Canary tests pass for logs and temp folders (I1, I2)
- [ ] Generator output uses `secrets`, honours every option, and covers each requested
      character class
- [ ] Matching tests cover subdomains, look-alike domains, ports, punycode, and http versus
      https

## M2: Desktop app

**Goal:** everything usable offline from a plain PySide6 window.

Tasks:

- **M2-01** Profile picker; create, rename, and delete with confirmation.
- **M2-02** Unlock screen; master password rules (at least 12 characters, a passphrase
  recommended).
- **M2-03** Entry list with search; add, edit and delete forms; show and copy password.
- **M2-04** Generator dialog.
- **M2-05** Clipboard copy with a 30-second clear, and exclusion from clipboard history where
  the OS allows.
- **M2-06** Idle lock, manual lock, and lock on sleep where the OS reports it.
- **M2-07** Settings dialog.
- **M2-08** Backups view, restore, encrypted export, KDBX and CSV import.

Done when:

- [ ] pytest-qt tests cover idle lock, form validation and clipboard clearing
- [ ] Plaintext export needs the master password and a typed confirmation (I8)
- [ ] A manual test script in `docs/manual-tests.md` passes, run by the owner
- [ ] The owner has reviewed every `[S]` file from M1 and M2 (gate G2)

## M3: Bridge and native host

**Goal:** the desktop side of browser integration, fully testable in Python before any
JavaScript.

Tasks:

- **M3-01** `protocol.py`: strict message schemas, size limits, dispatch to allowed methods
  only.
- **M3-02** `server.py`: a local socket server that only your user can read.
- **M3-03** `pairing.py`: pairing flow with a confirmation dialog and a matching code.
- **M3-04** `pm_host.py` relay, and `install_native_host.py` for your OS.

Done when:

- [ ] Fuzz tests (Hypothesis) send malformed, oversized and unknown messages; every one gets
      an error reply, and none crash the app
- [ ] A locked vault answers everything with `locked` (I5)
- [ ] A password is never returned for a non-matching URL (I4)
- [ ] Requests without a valid pairing key are refused
- [ ] A subprocess test speaks real native-messaging framing to the host

## M4: Browser extension

**Goal:** click-to-fill in Chrome and Brave (M4a), then save and update prompts (M4b, which
needs separate approval for all-sites access).

Tasks:

- **M4-01** Manifest, service worker, `api.js` shim.
- **M4-02** Popup: matches, fill, lock, unlock, add login for this site.
- **M4-03** `fill.js` with visibility checks.
- **M4-04** `detect.js` and the save or update flow (M4b).
- **M4-05** `docs/setup-browser.md`.

Done when (Playwright, with the extension loaded, against pages in `extension/test-pages/`):

- [ ] A normal login page fills after one click and does not submit
- [ ] A cross-origin iframe login form is never filled
- [ ] Hidden, zero-size and transparent fields are never filled
- [ ] A look-alike domain gets no suggestions
- [ ] An https entry is refused on an http page
- [ ] Navigating between listing and clicking aborts the fill
- [ ] M4b: nothing is saved without a click in the popup

## M5: Google Drive sync

**Goal:** encrypted sync that never silently loses an edit.

Tasks:

- **M5-01** `oauth.py`: connect, disconnect, token stored in the vault.
- **M5-02** `drive_client.py` and `fake_drive.py` behind one interface.
- **M5-03** `decide.py`, the pure decision table.
- **M5-04** `engine.py`: triggers, single-flight, backoff, executor.
- **M5-05** Conflict banner and the three resolution choices.
- **M5-06** Sync status in the UI; `docs/setup-google-drive.md`.

Done when:

- [ ] Every row of the decision table has a test
- [ ] Offline edits upload after the network returns
- [ ] A write injected between check and upload becomes a conflict, never an overwrite (I6)
- [ ] A corrupted download is never adopted (I7)
- [ ] Uploaded bytes never contain the canary and always match a verified local file (I10)
- [ ] A manual two-device test on a throwaway account passes

## M6: Merge, hardening and release

**Goal:** automatic conflict merge, a rehearsed recovery, and a release you would let a friend
install.

Tasks:

- **M6-01** Entry-level merge: the newer `updated_at` wins, the loser goes to history, and
  tombstones are respected.
- **M6-02** Recovery drill: restore from a local backup, from a Drive revision, and by opening
  the vault in KeePassXC; write up `docs/recovery.md`.
- **M6-03** Hardening: dependency and permission review, log and temp-file audit, crash-report
  check.
- **M6-04** Packaging with PyInstaller for your OS; install and update guide.
- **M6-05** README known-limitations page; request an outside security review.

Done when:

- [ ] Property tests show merge loses no entry, gives the same result twice, and does not
      depend on which side is "local"
- [ ] The owner has performed all three recovery paths
- [ ] `pip-audit` and `gitleaks` are clean
- [ ] A fresh machine installs, unlocks, fills and syncs following only the docs

---

## Development workflow

### Tooling

One command runs every check, locally and in CI: `uv run python scripts/check.py`.

| Tool | Job | Where it runs |
| --- | --- | --- |
| uv | Python version, virtual env, hash-pinned `uv.lock` | Everywhere |
| ruff | Lint and format | Pre-commit, CI |
| mypy `--strict` | Type checks on `core/`, `sync/`, `bridge/`, `host/` | CI |
| pytest + pytest-cov | Test runner and coverage | Pre-commit (fast set), CI (all) |
| hypothesis | Property and fuzz tests | CI |
| pytest-qt | UI tests, headless with `QT_QPA_PLATFORM=offscreen` | CI |
| Playwright (Python) | Extension end-to-end tests in Chromium | CI |
| import-linter | Enforces the [layer rules](architecture.md#layer-rules) | CI |
| bandit | Python security lint | CI |
| pip-audit | Known-vulnerable dependencies | CI, weekly schedule |
| gitleaks | Secrets in commits | Pre-commit, CI |
| keepassxc-cli | Proves our vaults open in KeePassXC | CI on Ubuntu |

The extension has no npm dependencies. Its tests live in the Python Playwright suite.

**Pre-commit hooks:** ruff, ruff-format, gitleaks, a large-file check, the fast test set, and
a hook that blocks any `*.kdbx` outside `tests/fixtures/` and any `client_secret*.json`.

### CI pipeline (GitHub Actions)

1. **lint:** ruff, mypy, import-linter, bandit.
2. **test:** pytest on Ubuntu plus your daily OS. Ubuntu installs KeePassXC for the
   compatibility test.
3. **security:** the canary invariant suite, `pip-audit`, and `gitleaks` over the full
   history.
4. **e2e:** Playwright loads the unpacked extension against `extension/test-pages/` (from M4).
5. **sensitive-review:** fails if a commit changes an `[S]` file without a
   `Security-Reviewed-By:` trailer, which only the owner adds after reading the diff.

`main` is protected: green CI required, no direct pushes, squash merges only.

### Test layers

| Layer | Kind of test | Coverage target |
| --- | --- | --- |
| Pure logic: matching, decide, generator, models, protocol validation | Unit + property tests | 95% branch |
| Vault and storage | Temp-folder integration, corruption, crash-during-save, KeePassXC compatibility | 95% branch |
| Security invariants I1–I10 | Canary tests, every commit | At least one test per invariant |
| Desktop UI | pytest-qt smoke tests + `docs/manual-tests.md` | Key flows |
| Bridge and host | Fuzzing + real framing over a subprocess | 95% branch |
| Extension | Playwright against hostile test pages | Every M4 "Done when" item |
| Sync | FakeDrive scenarios + one manual real-Drive smoke test | Every decision-table row |

Test markers: `unit`, `integration`, `security`, `sync`, `e2e`, `slow` (the 200-run crash
test). The quick loop is `uv run pytest -m "not e2e and not slow"`.

Tests create vaults with weak Argon2id settings (8 MiB, 1 iteration) so they run fast.
Production code refuses anything below 64 MiB, and only the test fixture can pass the
override, so a weak vault can never be created by accident.

### Git workflow

- One branch per task card, named like `task/M1-03-atomic-save`.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `test:`).
- Each finished milestone gets a tag, for example `v0.1.0-m1`.

### AI-assisted sessions

Every AI session works from two files: `AGENTS.md` (the standing rules, created once G0 is
approved) and one task card in `docs/tasks/` (this session's job).

1. Pick the next card. The owner writes it, or the AI drafts it and the owner approves it.
2. Start a fresh AI session with `AGENTS.md` and the card. One card per session keeps the
   context small.
3. The AI writes the acceptance tests first, runs them, and shows them failing.
4. The AI implements, runs `scripts/check.py`, and pastes the output.
5. The owner reads the diff. For `[S]` files, use the checklist below, then add
   `Security-Reviewed-By: <name>` to the commit.
6. Merge, tick the card's boxes, and update the docs if behaviour changed.

Review checklist for `[S]` files:

- [ ] Can any new line log, print, or raise an error containing a secret?
- [ ] Does every new file write go through storage and stay encrypted?
- [ ] Is every new outside input validated, with a size limit?
- [ ] Did a dependency, permission or OAuth scope get added?
- [ ] Do the tests cover failure paths, not only the happy path?
- [ ] Does the code match the spec section the card cites?
- [ ] Is there any line you do not understand? Ask the AI to explain it before merging.
