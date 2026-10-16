# Fix: the first unlock creates the vault

Not a milestone card — a blocker found by the owner's first run of the packaged app
(2026-10-16), fixed the same day. Sensitive: **no** (`services.py` and `ui/unlock.py` are not
`[S]` files; no `core/`, `sync/` or `bridge/` change).

## What was found

Creating a profile and opening it answered **"The vault file is damaged and could not be read."**
Nothing was damaged: the file was never made.

```
$ ls -la "$LOCALAPPDATA/PersonalVault/"
client_secret.json      410 bytes
profiles.json           228 bytes      ← the profile, by name
                                        …and no profiles/ folder at all
```

- `ProfileStore.create()` writes the name into `profiles.json` and nothing else
  (`core/profiles.py:97`), and the picker's **New profile** button calls only that
  (`ui/picker.py:90`).
- `VaultSession.create()` (`core/vault.py:206`) makes a vault — and **nothing in the app ever
  called it**: `git log -S "VaultSession.create" -- app/src` is empty for the whole history.
- The unlock window opened `<data>/profiles/<id>/vault.kdbx`, got "no such file", and
  `open_vault` maps every read failure to `VaultCorrupted` — hence "damaged" for a profile
  that had simply never been opened.
- No test walked *New profile → Open → password*: the UI and e2e tests build their own vault
  with `build_weak_vault(...)`, and `test_vault.py` calls `VaultSession.create(...)` directly.
  The suite was green over an app whose first run could not work at all.
- M2-01's acceptance line only ever said "Create shows a name prompt, then the picker lists the
  new profile", so nothing in the plan required the vault to exist.

This is the M6 "Done when" line (a fresh machine installs, unlocks, fills and syncs) failing at
**unlocks**, and manual-tests §12.3 failing at its first step. Nothing in `packaging/` is
involved: the bug is in `app/src`, which the build freezes unchanged.

## The same test, before and after

A temporary test using nothing this fix added — `profiles().create(...)`, `UnlockWindow`, a
password, a click — was run against the code on `main` and against the fix, and then deleted
(it stubs `QMessageBox.warning`, or the failure path blocks on a modal dialog):

```
$ git stash push -- app/src/personal_vault/services.py app/src/personal_vault/ui/unlock.py
$ QT_QPA_PLATFORM=offscreen uv run pytest app/tests/ui/test_zz_tmp_proof.py -q
E   AssertionError: no vault was created; the app said:
    ['The vault file is damaged and could not be read.']
1 failed in 1.60s

$ git stash pop
$ QT_QPA_PLATFORM=offscreen uv run pytest app/tests/ui/test_zz_tmp_proof.py -q
1 passed in 8.97s
```

The failure text is the owner's report word for word.

## What changed

- `services.open_profile_vault` — if the vault file is not there, it creates it with the
  password just typed (`VaultSession.create`) instead of raising. The existing file is still
  opened exactly as before, and a *damaged* file still raises `VaultCorrupted`.
- `services.profile_vault_path` — the vault file's path, so the UI and the service cannot
  disagree about where it is.
- `ui/unlock.py` — with no vault file the window says **Create `<name>`**, explains that the
  password now being chosen becomes the master password, and the button reads **Create vault**.
  With a vault present, nothing about the window changed.

## Acceptance tests

- [x] the new tests, and the file's existing ones, pass:

      $ QT_QPA_PLATFORM=offscreen uv run pytest app/tests/ui/test_unlock.py -q
      ........                                                                 [100%]
      8 passed in 17.40s

- [x] `test_first_unlock_creates_the_vault_and_that_is_its_password` walks the whole path with
      the real widget: named profile → "Create" wording → password typed → vault file exists →
      the same password unlocks it → a different one is refused as "Wrong master password".
- [x] `test_a_profile_without_a_vault_asks_for_a_new_master_password` pins the wording, so the
      window cannot go back to offering "Unlock" for a vault that does not exist.
- [x] the whole gate, on the branch (`scripts/check.py`, with `KEEPASSXC_CLI` and
      `QT_QPA_PLATFORM=offscreen`): ruff, format, mypy strict, both import contracts
      (`core keeps free of Qt…`, `ui talks to core only through services…`) and bandit all
      passed; `387 passed, 21 deselected in 265.07s`, exit 0 — the 385 from M6 plus these two.

## What this does not do

If a vault file *disappears* from a profile that had one (a deletion outside the app), the next
unlock creates an empty vault rather than saying so. Nothing is lost in that case — `backups/`
is untouched and **Backups** can restore from it — but a message for it ("this profile had
backups but no vault") is a UI card of its own, not this fix.

The window still asks for the password once, not twice: a mistyped password at creation leaves an
empty vault nobody can open, which costs nothing to delete (the profile holds no data yet).
