# Spike: extension-only mode (EXT-01), 2026-10-17

Throwaway code in the session scratchpad; only these findings are kept. Browsers: Chrome
155.0.8059.84, Brave 1.97.57 (Chromium 155), Playwright's Chromium 1248, on Windows 11.

## S1 — kdbxweb 2.1.1 + hash-wasm 4.12.0 against desktop vaults: GO, with one fix

A vault made by the desktop app (pykeepass, real calibrated KDF: Argon2id, 128 MiB,
parallelism 2, 14–16 iterations, AES-256) with two URLs on one entry, subdomain matching,
notes, tags, two history items, a login in the Recycle Bin and the hidden `.app` entries
(`browser-pairing`, `drive-sync`) was opened, edited (a history item pushed, a new login
added) and saved by kdbxweb in all three browsers.

| Check | Result |
| --- | --- |
| kdbxweb opens the desktop vault | yes, all fields, history 2, Recycle Bin, `.app` group |
| pykeepass opens kdbxweb's save | yes: both URLs, subdomains flag, notes, tags, history 3, Recycle Bin entry, `.app` values and username intact; KDF still Argon2id 128 MiB |
| **KeePassXC opens kdbxweb's save** | **no, as kdbxweb writes it: `Invalid EnableSearching value`, then `Invalid number value`** |
| …after normalizing unset values (below) | yes: `Logins/ Alpha Gamma`, `Recycle Bin/ Beta`, `.app/ browser-pairing drive-sync` |
| A vault kdbxweb creates (Argon2id 128 MiB, p=2, 12 it.) | pykeepass opens it; `keepassxc-cli db-info`: `Cipher: AES 256-bit`, `KDF: Argon2id (12 rounds, 131072 KB)` |
| Reopen with only SHA-256(password) (the KDBX password hash) | yes — the unlock never has to keep the password |
| The browser's own `DOMParser` in an extension page | present; xmldom never loaded (`window["@xmldom/xmldom"]` undefined) |
| hash-wasm MD5 of `abc` | `900150983cd24fb0d6963f7d28e17f72` (correct) |

**Root cause of the KeePassXC failure.** pykeepass writes `EnableSearching`,
`EnableAutoType`, `IsExpanded` (and an `IconID`) on the root group only. kdbxweb reads the
missing values as `undefined` and writes them back as **empty** elements, which KeePassXC
rejects. The engine now sets every value kdbxweb would write empty to the KeePass default it
already meant (absent flag = inherit = `null`, folder icon 48, usage count 0, the standard
meta numbers) before each save — no change to kdbxweb. The e2e tests open the extension's
uploads in pykeepass and `keepassxc-cli` on every run.

**Cost measured.** Argon2id at 128 MiB in WebAssembly (single-threaded): one run with 12
iterations ≈ 3.1 s in Brave; opening the desktop vault (14 iterations) ≈ 3.0 s; a save ≈
3.8 s (kdbxweb derives the key again on save). The desktop calibrates 14–16 iterations to
1 s with native Argon2. A vault the extension creates is calibrated to ~1 s *in the
browser* (fewer iterations — D9 says "about 1 second on your slowest device", and the
browser is now that device); a desktop-made vault keeps its iterations and unlocks in
~3 s here. Each save also runs the read-back check (another Argon2), so a save of a
desktop-made vault takes ~6–7 s in the background.

## S2 — key and engine lifetimes: from Chrome's documentation, then the e2e suite

A direct probe hung and was stopped; the facts come from Chrome's documentation and are
then proven by the e2e tests:

- `chrome.storage.session`: "Session storage holds data in memory while an extension is
  loaded. The storage is cleared if the extension is disabled, reloaded, updated, and when
  the browser restarts." — so an unlock **cannot** survive an extension reload while the
  key stays off disk (owner's decision Q-F: a reload locks).
- Offscreen documents: "The AUDIO_PLAYBACK reason sets the document to close after 30
  seconds without audio playing. All other reasons don't set lifetime limits." The engine
  uses `DOM_PARSER`.
- e2e: the unlock survives a service-worker stop (`ServiceWorker.stopAllWorkers`) and the
  engine document closing (reopened from the session key); it does not survive a browser
  restart (same profile directory relaunched).

## S3 — real Google sign-in and `drive.file` across clients: NOT RUN

Needs the owner's Google account and a Google Cloud OAuth client of type "Web
application", which this session cannot create. Open questions, now in
docs/manual-tests.md §14:

1. Does `chrome.identity.launchWebAuthFlow` with `response_type=token` and silent renewal
   (`prompt=none`) work in **Brave** as it does in Chrome?
2. Can the extension's Web client see a vault file the **desktop** client created, when
   both clients are in the same Google Cloud project? (ADR-010 assumed `drive.file` is per
   client.) If not, a desktop vault must be opened once through Google Picker, or each vault
   gets one writer.

The automated tests use a fake Google (app/tests/e2e/fake_google.py) for the same calls.

## Found on the way: the desktop app's revision order

`sync/engine.py` `_foreign_revision` treats Drive's `revisions.list` as **newest first**,
and the desktop `FakeDrive` inserts new revisions at the front to match. If the real order
were oldest first, the desktop would see an older revision as "a write from another
device" and raise a false conflict after a few uploads. Evidence against that: the owner's
own profile has synced with real Drive up to remote version 5 with no conflict (2026-10-16),
so either the order is newest first or the check never saw the case. Not verified directly,
not changed (outside this card). The extension sorts revisions by `modifiedTime` itself,
so it does not depend on the order.
