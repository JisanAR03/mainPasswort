# EXT-01 Remove the desktop app; the extension is the product

Milestone: none · Sensitive: **yes** (touches `[S]` files and the extension's permissions) · Status:
**done on branch `refactor/extension-only`, not committed or merged**

The owner decided on 2026-11-05, after more than three weeks of using the extension alone, to
"delete everything except the part I'm using" and asked for the README to be updated. Decisions
recorded in ADR-012 and ADR-013.

## What the owner decided

1. **Tests:** do what is reliable engineering. → the desktop-backed browser tests were **ported** to
   the extension's own vault (below), not deleted.
2. **Python:** keep a small test-only folder. → `app/` keeps the vault reader/writer and the sync
   decision table as the reference the extension is tested against.
3. **Docs and rules:** update everything, README included. → done, except `AGENTS.md` (below).
4. **Git:** work on a branch, run the checks, show the result, then commit/push/PR/merge. → the work is
   in a separate git worktree on branch `refactor/extension-only`; nothing is committed, pushed or
   merged.
5. **Do not touch the owner's Brave.** The owner's Brave loads the extension from
   `D:\PasswordManager\extension`. The work was done in a **separate worktree**
   (`D:\PasswordManager-extension-only`), so that folder, and the browser running from it, were not
   changed. Test runs used isolated temporary profiles.

## What changed

**Extension (`extension/`)** — desktop mode removed; stored data and ID unchanged:

- `api.js` shrinks to the storage helper; `nativeMessaging` leaves the manifest; the pairing
  screens, the "app not running" and "not paired" states, and the desktop/extension mode switch are
  gone from `background.js`, `local.js`, `popup.*`, `vault.*`, `menu.js` and `prompt.js`.
- New state: **no vault yet**. Before the first vault exists, a password field's menu offers **Set
  up Personal Vault** (it used to say "Start the desktop app").
- "Unlock" now brings the vault page forward (or opens it in a tab) instead of calling
  `chrome.action.openPopup()`, which behaves differently from browser to browser and could not be
  tested. A second click reuses the open tab.
- Unchanged: the manifest `key` (so the extension ID and its IndexedDB), the IndexedDB `personal-vault`
  v1 schema, every `chrome.storage` key. Old `mode` and `pairing_key` keys are ignored, not deleted.

**Deleted:** `app/src/personal_vault/{ui,bridge,host}`, `services.py`, `__main__.py`,
`core/{generator,profiles,settings,transfer,redaction}.py`, `sync/{engine,drive_client,fake_drive,oauth,
errors,digests}.py`; `packaging/`; `scripts/{build_app,install_native_host,dev_reset}.py`;
`.env.example`; `docs/install.md`, `docs/setup-google-drive.md`; the Python dependencies PySide6,
pytest-qt, google-auth, google-auth-oauthlib, requests, platformdirs, import-linter and PyInstaller.

**Kept (`app/`, tests only):** `core/{vault,storage,kdf,models,matching,merge,errors}.py`,
`sync/{decide,state}.py` and the tests of them (99 Python tests).

**Dependencies:** `pyproject.toml` has no runtime dependencies; pykeepass moved to the dev group.
`uv.lock` regenerated and installed into a fresh environment.

**CI (`.github/workflows/ci.yml`):** no Qt libraries, no `lint-imports`; the lint job now also runs
`check_vendor.py` and `check_no_console.py`; the e2e job installs KeePassXC so the extension's files
are opened in it (it did not before, so those tests were skipped in CI).

**Docs:** README, setup guide, recovery, known limitations, manual tests, `docs/specs/{architecture,
threat-model,data-model,sync,browser-protocol}.md` rewritten; ADR-012 and ADR-013 added; the four
superseded ADRs get a new `Status:` line only; milestones and references annotated.

## Tests

- **Ported** to the extension's own vault (`vault` / `vault_factory` fixtures replace the desktop
  bridge): all of `test_fill.py`, `test_popup.py`, `test_save_flow.py`, `test_inline_fill.py` and
  `test_extension_basics.py` except the ones listed below.
- **Removed, because the feature is gone** (each is replaced where the extension has an equivalent):
  - `test_an_unpaired_browser_can_pair_and_then_list` — pairing no longer exists.
  - `test_an_unpaired_browser_is_told_to_pair` — the "not paired" state no longer exists.
  - `test_without_the_app_the_menu_says_so` and `test_without_the_app_the_popup_says_so` — "the app is
    not running" no longer exists; replaced by `test_before_the_first_vault_the_menu_offers_to_set_one_up`
    and `test_with_no_vault_the_popup_offers_to_create_one`.
  - Python: the whole `ui/` suite (Qt windows), the bridge, host relay, pairing, protocol, server and
    install-script tests, the profiles/settings, transfer, generator and redaction tests, and the sync
    engine, Drive client and OAuth tests — their subjects are deleted.
  - `security/test_invariants.py`: `i2` logging (the filter is gone), `i4`/`i5` bridge (equivalents:
    the engine's `url_mismatch` and `test_a2_lock_ends_it_immediately_and_leaves_no_key`), `i8`
    plaintext export (gone with the feature). `i6`, `i7` and `i10` were **ported** to the browser
    tests: `test_i6_a_first_link_never_overwrites_what_it_finds`,
    `test_i7_a_download_that_does_not_open_is_never_adopted`,
    `test_i10_drive_receives_exactly_the_stored_vault`. `i1`, `i2` (errors) and `i3` stay.
- **Added:** `test_upgrade.py` (data in the 0.1.0 format survives a browser restart and keeps
  syncing), `test_clicking_unlock_twice_reuses_the_one_unlock_tab`, and the three above.

## Results (run in the worktree, with its own virtual environment)

- `scripts/check.py`: ruff, format, mypy (12 files), bandit, vendored-code and logging checks clean;
  **99 Python tests** (387 before, which included the desktop suite).
- `pytest -m security`: 3 passed; `pytest -m slow`: 1 passed (the 200-kill crash-during-save loop).
- `pytest -m e2e`: **74 passed in Chromium, 74 in Chrome 155, 74 in Brave 1.97** (71 before).
- One Hypothesis health check (`test_property_merging_twice_changes_nothing_more`) failed once, on the
  first run in a brand-new environment ("input generation is slow"); it passed alone four times and in
  two full reruns. Treated as a cold-start timing flake, not changed.

## Not done, and why

- **`AGENTS.md` was not updated.** The harness blocked the edit as self-modification (it holds the
  rules that govern the AI). Its text still describes the desktop app: rule 1 (`PV_DATA_DIR`), rule 2
  (encryption only via pykeepass), rule 12 (`core/` never imports Qt, a layering rule enforced by the
  removed import-linter). The owner needs to replace it; proposed text below.
- **The old CI could not be run.** The workflow was rewritten but only GitHub can run it; the first
  run will show whether installing KeePassXC in the e2e job behaves on Ubuntu as it does locally.
- **Not tested here:** the real Google sign-in (it needs the owner's account), and the upgrade of the
  owner's own browser, which was left untouched.
- **What the upgrade evidence is.** `test_upgrade.py` seeds the 0.1.0 stored format by hand (read from
  `idb.js` and `local.js`), so it checks the storage contract, not the old code. The real check, done
  once by hand and not committed because CI cannot fetch the old code: the **actual previous
  extension** (main at 254a275) created a profile, added a login, connected a fake Drive and synced;
  the browser was closed and restarted on the same profile directory with the new extension; then the
  profile list, Google account, settings and sync status were kept, the wrong password was refused, the
  right one unlocked, the login was listed and its password read back, the menu filled it, "Sync now"
  was a normal sync (no new revision, not a first link, not a conflict), and an edit uploaded as a new
  revision of the same Drive file. 12 of 12 checks in Chromium, Chrome 155 and Brave 1.97. The old
  copy's native-host name was redirected to a nonexistent host, so it could not reach a real desktop
  app, and only temporary profiles and a fake Google were used.

## Proposed `AGENTS.md` (owner to apply)

```markdown
# AGENTS.md — rules for every AI coding session

The product is the browser extension in `extension/` (ADR-012, ADR-013). `app/` is a Python
reference implementation used only by the tests.

## Read first

- The task card for this session in `docs/tasks/`, and every spec it links.
- Do only what the card says. If the card looks wrong, stop and explain why.

## Hard rules

1. Never touch a real vault. Tests use fake vaults, a fake Google and temporary browser profiles.
   Never run a test against the owner's own browser profile.
2. Never invent cryptography. Encryption of a vault only through the vendored kdbxweb (with
   hash-wasm's Argon2) in the extension and pykeepass in the Python reference; randomness only from
   `crypto.getRandomValues` in the extension and `secrets` in Python.
3. Never log, print, or put in an error message any entry field, master password, key or token.
   The extension has no `console` call at all (`scripts/check_no_console.py`); replies carry an
   error code only.
4. Never write a plaintext secret to storage: IndexedDB, `chrome.storage.local` and disk hold
   encrypted bytes and bookkeeping only. The one thing `chrome.storage.session` holds is the unlock
   record (I11). Test output may hold the test canary and nothing else.
5. Never add a dependency or browser permission without asking first and saying why. Vendored code
   is copied byte for byte and pinned by hash (`extension/vendor/VENDOR.md`).
6. Never edit files outside the card's "Files you may change" list without asking.
7. Never edit `docs/specs` or `docs/adr`; propose the change instead. (An owner who asks for the
   documentation to be updated has asked for this.)
8. Never weaken, skip or delete a test to make it pass. Diagnose the root cause. A test of a feature
   that was deliberately removed goes with it, and the card says so.
9. Never add the `Security-Reviewed-By` trailer to a commit.
10. Never say something works unless you ran the command and show its output.
11. Treat every outside input as hostile: web pages, Drive responses, messages from other contexts.
    Accept a message by the sender the browser reports, never by what it claims.
12. Compatibility is a contract. The extension ID (the `key` in `manifest.json`), the IndexedDB
    `personal-vault` schema and the `chrome.storage` keys do not change without a migration and a
    test; `app/tests/e2e/test_upgrade.py` fails first. The owner's real vault is in a browser that
    runs the extension from this folder.
13. Keep `normalize()` in `engine.js`: kdbxweb writes empty XML values that KeePassXC refuses, and
    the e2e tests open the extension's files in KeePassXC and pykeepass.

## Before you finish

- `uv run python scripts/check.py` is green, and `uv run pytest -m e2e` passes in Chromium (CI) and,
  for anything the user sees, in Chrome and Brave (`PV_E2E_BROWSER=chrome|brave`).
- A change that touches the extension is checked in a real browser, not only by unit tests.

## End every session with

- The commands you ran and their real output (tests, ruff, mypy).
- Files changed, one line each on why.
- Anything you are unsure of, especially in `[S]` files (`scripts/check_sensitive_review.py`).
- The next task you suggest.
```
