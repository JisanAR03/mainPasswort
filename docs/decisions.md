# Decisions

> Source: design pack draft v0.1, sections 1–3, 14 and 15. Status: **no decision is approved
> yet.** Gate G0 passes once all ten decisions below are approved, and only then can
> milestone M0 start.

## Decisions awaiting approval

| # | Decision | Recommendation | Main alternative | Status |
| --- | --- | --- | --- | --- |
| D1 | Vault format | KDBX 4 via pykeepass, one file per profile (ADR-001) | Custom encrypted JSON with `cryptography` + `argon2-cffi` | Pending |
| D2 | Project license | GPL-3.0, required because pykeepass is GPL-3 (ADR-007) | MIT, only possible with the custom format | Pending |
| D3 | Stack | Python 3.12+, PySide6, plain-JavaScript Manifest V3 extension (ADR-002) | Rust + Tauri | Pending |
| D4 | Milestone order | Browser extension (M4) before Drive sync (M5) (ADR-005) | The original brief's order: sync first | Pending |
| D5 | Where unlock happens | Desktop app only; the popup can only ask the app to show its unlock window (ADR-003) | Master password typed into the popup | Pending |
| D6 | Drive access | `drive.file` scope, one Google account per profile, OAuth token stored inside that profile's vault, sync runs only while unlocked (ADR-004) | Token in the OS keychain, so sync runs while locked | Pending |
| D7 | Conflict policy for v1 | Detect, keep both copies, ask; automatic entry-level merge arrives in M6 (ADR-006) | Automatic merge from the start | Pending |
| D8 | Autofill policy | Fill only after a click in the popup, top frame only, exact hostname match by default | Inline field icons and subdomain matching from the start | Pending |
| D9 | Key derivation | Argon2id, 128 MiB memory, parallelism 2, iterations calibrated so unlock takes about 1 second on your slowest device | KeePassXC defaults | Pending |
| D10 | Target operating systems | Your daily OS first; the others only after M6 (see Q1) | All three from day one | Pending |

## Where the spec departs from the original brief

- **Browser extension before Drive sync.** Local-only use is safe and gives daily value.
  Sync is where data gets lost, so it comes last and is built carefully.
- **Unlock happens in the desktop app, not the browser popup.** Typing the master password
  into the extension moves it through a process that websites can attack.
- **Profiles are not a wall between people.** Real separation between people requires
  separate OS accounts.
- **Python cannot reliably erase secrets from memory.** The design minimises secret lifetimes
  and documents the limit honestly.

## Foundation options considered

| Option | What it gives you | Main problem | Verdict |
| --- | --- | --- | --- |
| KeePassXC + its browser extension + Google Drive for Desktop (zero code) | Profiles as separate `.kdbx` files, browser fill, auto-lock and a generator, all today | Sync is a blind file copy; two devices editing can create conflict copies | The baseline this project must beat; use it during the build |
| Fork or extend KeePassXC | Mature, audited features | Large C++/Qt codebase, GPL; every upstream release must be re-merged | Not realistic for one person |
| Bitwarden or Vaultwarden | Polished clients and sync | Requires running a server, which the brief rules out | No |
| Own app on KDBX 4 via pykeepass | Your UI, sync rules and extension; a standard format; KeePassXC as the fallback | pykeepass is GPL-3 and not audited; KDF settings need a spike to confirm | **Recommended** |
| Own app with a custom encrypted JSON file | Smallest code, easy to read | No outside tool can open the vault if the app breaks | Fallback only, if the KDBX spike fails |

## Architecture decision records

All seven ADRs are **Proposed** until the decisions above are approved. Once accepted, an ADR
is never edited, only superseded by a newer one that says so.

### ADR-001 Vault format: KDBX 4 via pykeepass

- **Context:** the brief forbids custom cryptography and demands recovery from damaged files.
- **Decision:** one KDBX 4 file per profile, read and written with pykeepass, using Argon2id
  key derivation.
- **Consequences:** KeePassXC and mobile KeePass apps can open every vault, which is the
  recovery plan. pykeepass is GPL-3 and unaudited, so M0-02 must confirm its KDF and cipher
  output. If the spike fails, fall back to a custom JSON envelope using `cryptography`
  (AES-256-GCM) and `argon2-cffi`.

### ADR-002 Stack: Python, PySide6, plain JavaScript

- **Context:** one developer, AI-assisted, who wants readable code and few dependencies.
- **Decision:** Python 3.12+ and PySide6 for the app; Manifest V3 for the extension, with no
  framework and no npm packages.
- **Consequences:** fast to build and easy to read. Python cannot wipe secrets from memory,
  and this is documented rather than worked around. Rust, Tauri and SQLite are rejected for v1
  because they add complexity without defeating the main threat, malware running as you.

### ADR-003 Browser integration: native messaging to a local socket

- **Context:** the extension must not hold a copy of the vault.
- **Decision:** extension → native host (stdio) → desktop app (local socket), with a pairing
  key per profile. Click-to-fill only, top frame only, and unlock only in the desktop app.
- **Consequences:** the app must be running for the extension to work. No inline field icons
  in v1.

### ADR-004 Sync: whole encrypted file on Drive with version checks

- **Context:** Drive must never see plaintext, and edits must never be silently overwritten.
- **Decision:** `drive.file` scope; one Google account per profile; the refresh token stored
  inside the vault; sync runs only while unlocked; the pure `decide()` function governs every
  action.
- **Consequences:** locked profiles do not sync. Drive v3 has no atomic conditional upload,
  so a revision check after each upload closes the race.

### ADR-005 Build the extension before sync

- **Context:** the brief orders sync before the extension.
- **Decision:** M4 extension, then M5 sync.
- **Consequences:** daily browser use arrives sooner, on a local-only vault where data loss is
  unlikely. Multi-device use waits until M5, and KeePassXC with manual copies covers the gap.

### ADR-006 Conflicts: keep both in v1, merge in M6

- **Context:** automatic merge is the most bug-prone code in any sync system.
- **Decision:** v1 detects conflicts and asks. M6 adds entry-level merge keyed on the entry
  UUID: the newer `updated_at` wins, the loser goes to history, and deletions recorded as
  tombstones are respected.
- **Consequences:** a rare manual step in v1, in exchange for zero silent merges until the
  merge code has property tests.

### ADR-007 License: GPL-3.0

- **Context:** pykeepass is GPL-3, and the project may be open-sourced.
- **Decision:** release under GPL-3.0.
- **Consequences:** anyone who distributes a modified version must share its source. MIT would
  require dropping pykeepass.

### ADR template

```markdown
# ADR-00N <decision in a few words>
Status: Proposed | Accepted | Superseded by ADR-00M
Date: YYYY-MM-DD

## Context
What forces this decision, in two or three sentences.

## Decision
What we will do.

## Consequences
What gets easier, what gets harder, what we will watch.
```

## Open questions for the owner

| # | Question | Why it matters |
| --- | --- | --- |
| Q1 | Which operating system do you use daily? | Decides host install paths, packaging and lock-on-sleep (D10) |
| Q2 | Are the other planned profile users other people sharing this computer, or separate identities of yours? | Other people need their own OS accounts |
| Q3 | Do you want phone access? | A KeePass app on a phone can read the Drive file; letting it write too means more conflicts for sync to handle |
| Q4 | One Google account for all profiles, or one per profile? | Settles D6 |
| Q5 | Do you need two-factor (TOTP) codes in v1? | Currently excluded |
| Q6 | Is GPL-3.0 acceptable for the open-source release? | Settles D2 |
| Q7 | Where do your current passwords live (Chrome, Bitwarden, KeePassXC, a spreadsheet)? | Decides the first importer |

## Riskiest assumptions

| Assumption | If it is wrong | Cheapest test |
| --- | --- | --- |
| pykeepass writes Argon2id vaults with our settings, and KeePassXC accepts them | Switch to the custom-format fallback in ADR-001 | M0-02, one session |
| A Python native host starts fast enough that the popup feels instant | Use a slimmer host without Qt, or keep the port open | M0-03: time 20 popup opens |
| Drive's revision list is readable with `drive.file` and shows every write | Race detection weakens; switch to one file per device | M0-04, on a throwaway account |
| You will prefer this app to KeePassXC plus its extension | Most of the effort buys little | Use KeePassXC and its extension for two weeks now and list what annoys you; that list is your real requirement set |

The last row is the one to take seriously. If the annoyance list is short, the smallest useful
project may be just the sync engine (M5) wrapped around KeePassXC vaults.

## Gaps and inconsistencies found in the spec

These came up while reviewing the spec during project setup (2026-10-15). They should be
resolved before, or during, the milestone named.

1. **Non-existent task "M4.0".** The native host section says host paths are "confirmed per
   OS in M4.0", but M4's tasks start at M4-01. The host installer is task M3-04, and the
   browser spike is M0-03. Clarify which task owns this.
2. **Squash merges and the `Security-Reviewed-By` trailer.** CI runs on the pull request's
   commits, before the squash commit message exists, so the `sensitive-review` job cannot see
   a trailer that is added at merge time. Decide where the review sign-off lives (M0-01).
3. **First-time link and second device.** The sync decision table does not cover linking a
   device that has no `state.json` to a profile that already exists on Drive, or recovering
   after `state.json` is lost (for example, which side wins). Specify this before M5.
4. **`drive.file` is per OAuth client.** The app can only see files created through the same
   Google Cloud OAuth client, so every device must use the same `client_secret.json`. The
   setup doc should say so (M0-04, M5).
5. **Overlapping decisions and questions.** D2 and Q6, D6 and Q4, and D10 and Q1 ask the same
   thing. Answer each pair once.
6. **Lock on screen lock.** The threat model promises "lock on sleep and screen lock", but
   `settings.json` has only `lock_on_sleep`, and task M2-06 mentions only idle, manual and
   sleep lock.
7. **Cipher not chosen.** "ChaCha20 or AES-256" is left to the M0-02 spike.
8. **Phone access and the KDF.** If Q3 is yes, the "slowest device" in D9 is likely the
   phone. Mobile KeePass apps, especially iOS autofill extensions, run under tight memory
   limits, so 128 MiB Argon2id should be tested on the phone in M0-02.
9. **Extension distribution.** M6 aims for "a release you would let a friend install", but
   the spec does not say whether the extension ships unpacked (with a fixed key) or through
   the Chrome Web Store.
10. **Files referenced but missing from the project tree.** `docs/spikes/`,
    `docs/manual-tests.md` and `scripts/check.py` are used by milestones but not listed in the
    planned structure. They have been added to the tree in [architecture.md](architecture.md).
11. **Docs layout.** The spec plans `docs/specs/`, `docs/adr/`, `docs/tasks/` and a root
    `AGENTS.md`, and calls the repo `personal-vault`. This repo uses a flat `docs/` folder and
    is named `mainPasswort`. Confirm the layout and name at M0-01.
