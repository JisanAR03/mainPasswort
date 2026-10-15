# Architecture decision records

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-vault-format.md) | Vault format: KDBX 4 via pykeepass | Accepted |
| [0002](0002-stack.md) | Stack: Python, PySide6, plain JavaScript | Accepted |
| [0003](0003-browser-integration.md) | Browser integration: native messaging to a local socket | Accepted |
| [0004](0004-sync.md) | Sync: whole encrypted file on Drive with version checks | Accepted |
| [0005](0005-extension-before-sync.md) | Build the extension before sync | Accepted |
| [0006](0006-conflicts.md) | Conflicts: keep both in v1, merge in M6 | Accepted |
| [0007](0007-license.md) | License (open: see Q6) | Proposed |
| [0008](0008-m4-host-paths.md) | The "M4.0" task: host paths are owned by M3-04 | Accepted |
| [0009](0009-security-review-trailer.md) | Where the Security-Reviewed-By trailer lives | Accepted |
| [0010](0010-first-time-link.md) | First-time link and a lost state.json | Accepted |

An accepted ADR is never edited; it is superseded by a newer one that says so.

## Decision log (owner sign-off, 2026-10-15)

Gate G0 passed. The owner approved the design pack's recommendations D1 and D3–D10 as
proposed, with the answers below.

| Decision | Content | Owner's call |
| --- | --- | --- |
| D1 | Vault format: KDBX 4 via pykeepass | Approved as proposed |
| D2 | License: GPL-3.0 | **Open.** Superseded by the answer to Q6: the license is not decided yet. No LICENSE file for now; remind the owner before any public release. ADR-007 stays Proposed. |
| D3 | Stack: Python 3.12+, PySide6, plain-JS MV3 | Approved as proposed |
| D4 | Milestone order: extension before sync | Approved as proposed |
| D5 | Unlock in the desktop app only | Approved as proposed |
| D6 | `drive.file`, one Google account per profile, token in the vault | Approved as proposed; the Q4 answer (one Google account for everything) settles the account question |
| D7 | Conflicts: detect, keep both, ask | Approved as proposed |
| D8 | Autofill: click-to-fill, top frame, exact hostname | Approved as proposed |
| D9 | Argon2id, 128 MiB, parallelism 2, ~1 s unlock | Approved as proposed; desktop-only calibration (Q3) |
| D10 | Target OS: daily OS first | Approved as proposed; mainly Windows, also Linux (Q1) |

## Owner's answers to the open questions

| # | Question | Answer (2026-10-15) |
| --- | --- | --- |
| Q1 | Daily operating system? | Mainly Windows, and also Linux. Support both. |
| Q2 | Are the profiles other people? | No. Profiles are labels for the owner's own accounts (Work, Social Media, School). One user, everything local. |
| Q3 | Phone access? | No. Key derivation is tuned for desktop only. |
| Q4 | One Google account or one per profile? | One Google account for everything. Google Drive is mainly an encrypted backup location for the vault. Settles D6. |
| Q5 | TOTP codes in v1? | No. Left out of v1. |
| Q6 | License? | **Open.** Not decided yet. No LICENSE file. Remind the owner before any public release (ADR-007). |
| Q7 | Where do the current passwords live? | **Open.** The owner did not understand the question; it is re-asked in plain terms in the M0 report and must not block the build. The first importer (M2-08) stays open until it is answered. |

## Other recorded decisions

- **KeePassXC two-week trial (spec, riskiest assumptions):** the owner chose to build the
  project instead of running the trial. Recorded 2026-10-15.
- **Spec PDF:** stays out of the repository (git-ignored, local only).
- **Repository name:** the spec calls the repo `personal-vault`; this repository is named
  `mainPasswort` on GitHub. Renaming it is the owner's GitHub-admin action, unrelated to the
  code layout. The Python package is `personal_vault` as the spec requires.

## Spike confirmations (M0)

- **ADR-001 confirmed** by the M0-02 spike (2026-10-15): KeePassXC 2.7.12 accepts a
  pykeepass vault with Argon2id at the D9 settings ("KDF: Argon2id (12 rounds, 131072 KB)"),
  and pykeepass opens KeePassXC-made vaults. See
  [docs/spikes/2026-10-15-kdbx-spike.md](../spikes/2026-10-15-kdbx-spike.md).
- **ADR-003 confirmed** by the M0-03 spike (2026-10-15): a message makes the full
  extension → host → local socket loop with real native-messaging framing; host startup is
  ~290 ms with an `--onedir` build. See
  [docs/spikes/2026-10-15-browser-spike.md](../spikes/2026-10-15-browser-spike.md).
- **ADR-004 confirmed in design, spike pending the owner** (M0-04): the round trip needs the
  throwaway Google account, so the spike is a ready-to-run script
  (see [docs/setup-google-drive.md](../setup-google-drive.md)); the day-1 run and the 8-day
  token test close it.

## Spec issues found during setup

Resolved by ADRs:

1. **"M4.0" task does not exist** → ADR-008: M3-04 owns host paths; M4-05 documents them.
2. **Squash merges hide the review trailer from CI** → ADR-009: trailer in the PR body or a
   PR commit, pasted into the squash commit at merge time.
3. **First-time link / second device not covered** → ADR-010: ask once, adopt or upload,
   never silently.

Still open (do not block M0–M3):

4. `drive.file` is per OAuth client → every device uses the same `client_secret.json`
   (recorded in `docs/specs/sync.md` and the setup guide; re-checked at M0-04 and M5).
5. Overlapping decisions and questions (D2/Q6, D6/Q4, D10/Q1) → answered once each above.
6. Lock on screen lock: the threat model promises it but `settings.json` has only
   `lock_on_sleep` → resolved at M2-06 with a Windows power-event hook plus the elapsed-time
   fallback; re-check against the spec then.
7. Cipher not chosen ("ChaCha20 or AES-256") → **resolved by the M0-02 spike: AES-256**
   (pykeepass's KDBX 4 default), confirmed by `keepassxc-cli db-info`.
8. Phone access and the KDF → moot: no phone access (Q3).
9. Extension distribution (unpacked vs Chrome Web Store) → decide at M6.
10. Files referenced but missing from the tree (`docs/spikes/`, `docs/manual-tests.md`,
    `scripts/check.py`) → added by M0 and M2.
11. Docs layout → switched to the spec's layout (`docs/specs/`, `docs/adr/`, `docs/tasks/`,
    root `AGENTS.md`, package `personal_vault`) on 2026-10-15.
