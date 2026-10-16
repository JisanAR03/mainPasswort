# M6-05 Release docs and the outside review

Milestone: M6 · Sensitive: no (documents and a README) · Depends on: M6-01, M6-02, M6-03

## Goal

Two things the milestone asks for: a page that says what this app does not do, and an actual
request for someone outside this project to look at it.

The page is `docs/known-limitations.md`, linked from the README and from the security section
at the top of it. It is written to be read *before* a password goes in, so it leads with the
gates that are still open and the limits that will never close, and only then lists the v1
feature gaps.

The README was the other half of this card: it still said "There is no application code yet"
and "planned for v1" about features that have been merged since M0. It now states where the
project actually is, names the two gates that block real use, links the known limitations, the
recovery page, the manual test script and the task cards, and drops the "planned" framing from
the stack and the run instructions.

## Files you may change

- docs/known-limitations.md (new)
- README.md (status, features heading, stack heading, how to run, documentation table)
- docs/tasks/M6-05-release-docs.md (this card)

## What the page says

| Section | Why it is there |
| --- | --- |
| Not reviewed by anyone outside this project | the honest headline; G2's `[S]` read-through is the owner reviewing their own work |
| G2 / G4 / G5 table | what each open gate blocks, in the order a new user hits them |
| What it cannot protect you from | the threat model's accepted limits, kept short and concrete: malware, a compromised OS, a weak master password, a shared OS login, a lost master password, a password you paste |
| Not in this version | the v1 exclusions, unchanged from the spec |
| Deliberate but surprising | the behaviour found while building: a restore does not keep what it replaced, nothing is repaired or auto-restored, the bin is never emptied, sync is whole-file, the Drive token lives in the vault, `<all_urls>` while save detection is on, no installer, no license |

## Acceptance tests

- [x] `docs/known-limitations.md` exists, covers the gates, the accepted limits, the v1 gaps
      and the behaviour found while building, and is linked from the README
- [x] every claim in it traces to code or spec that was read this session
      (`restore_backup` at `core/vault.py:309`, `storage.recover` with no caller,
      `APP_GROUP`/`DRIVE_SYNC_ENTRY`, the Recycle Bin never emptied, the extension's
      optional `<all_urls>`, ADR-007 open)
- [x] the README no longer says there is no code and no longer calls merged work "planned"
- [ ] **the owner requests the outside review** — the milestone's other half, and gate G5

## The outside review (owner action)

Nothing in this repository can do this part. What to send, when you send it:

1. `docs/specs/threat-model.md` — what it promises, and I1–I10
2. `docs/known-limitations.md` — what it does not promise
3. the `[S]` file list in `scripts/check_sensitive_review.py` — the code that handles the
   master password, the entries and the Drive token
4. `docs/recovery.md` — what a stranded user can actually do
5. the CI result on `main`, and the two audits from M6-03 (pip-audit, gitleaks) with their
   dates

A reviewer with an hour will get furthest in `core/merge.py` (new in M6, and it moves
passwords between files), `core/vault.py` and `core/storage.py`. A reviewer with a day should
also have the browser extension and `bridge/`, since that is the part a web page can reach.

Until that review happens, G5 stays closed and the project should not be described as
reviewed. The README says so.

## Out of scope

Answering the review, a `SECURITY.md` with a disclosure address (worth having, but it needs
the owner's contact decision first), and any change to the spec files (rule 7)
