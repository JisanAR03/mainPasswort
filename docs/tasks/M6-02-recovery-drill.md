# M6-02 Recovery drill

Milestone: M6 · Sensitive: no (a document and a checklist) · Depends on: M1-03, M5-05

## Goal

Write down the three ways back into a vault that has gone wrong, and have the owner walk each
one on a throwaway vault so the words are known to work:

1. **From a local backup.** The app keeps a verified backup per save in
   `<profile>/backups/`. Path A: the Backups window (restore the newest good copy, or any
   older one). Path B, with the app closed or broken: copy `vault-*.kdbx` over `vault.kdbx`
   by hand — it is an ordinary KDBX file and the master password still opens it.
2. **From a Drive revision.** A conflict keeps their bytes under
   `<profile>/sync/conflicts/`, and **Take theirs** adopts them. For a revision older than
   that, Drive's own web UI has the file's version history: download the revision you want
   and either put it back by hand or open it beside the vault. The app deliberately does not
   offer "restore an arbitrary Drive revision" — the write path is the vault file, and the
   console-free way to it is the Backups window.
3. **In KeePassXC.** The vault is KDBX 4 with Argon2id, so KeePassXC (GUI) and
   `keepassxc-cli` open it with the same master password. This is the path that does not
   depend on this project at all, and it is what a rescue from a broken build looks like.

`docs/recovery.md` is the write-up: where the files are, what each path restores, what is lost
by using it, and what to do when the vault itself will not open (`VaultCorrupted`). The drill
itself goes into `docs/manual-tests.md` as section 11, because that file is the owner's
checklist and the one the G2 gate already uses.

## Files you may change

- docs/recovery.md (new)
- docs/manual-tests.md (section 11, the three paths as a checklist)
- docs/tasks/M6-02-recovery-drill.md (this card)

No code changes: every path here is an M1/M5 feature that already exists. If a drill step
turns out not to work, that is a bug to fix in a card of its own, not by widening this one.

## Spec references

- docs/specs/architecture.md — the data folder layout, `vault.kdbx`, `backups/`
- docs/specs/threat-model.md — "Corrupted file, power loss mid-save": atomic write, backups,
  Drive revisions; invariant I3
- docs/tasks/M1-03-atomic-save.md — what a backup is and when one is written
- docs/setup-google-drive.md — the conflict banner and the kept copy

## Acceptance tests

This card is documentation plus an owner-run drill, so there is nothing for CI to run. The
owner's run is the acceptance test, and the milestone's "Done when" line — "the owner has
performed all three recovery paths" — stays unticked until it happens.

- [x] `docs/recovery.md` names the real folder and file names for each path
      (`<data>/profiles/<id>/{vault.kdbx,backups/,sync/conflicts/}`, read out of
      `services.profile_vault_dir`, `core/storage.py` and `sync/engine.py`)
- [x] each path says what it restores and what it does not (each has a "restores what / does
      not restore" line, and the three things the app does not do are listed at the end)
- [x] the KeePassXC path is described for both the GUI and `keepassxc-cli` — and the CLI
      commands were run, not assumed:

      ```
      $ echo "<password>" | keepassxc-cli ls "$D/drill.kdbx"
      Logins/                                          exit=0
      $ echo "<password>" | keepassxc-cli show -s "$D/drill.kdbx" "Logins/example.com"
      exit=0
      $ echo "<password>" | keepassxc-cli show "$D/drill.kdbx" "Logins/example.com"
      UserName: owner@example.com
      Password: PROTECTED
      ```

      on a throwaway vault made by pykeepass in `%TEMP%`, since deleted.
- [x] `docs/manual-tests.md` section 11 has one ticked-line-per-step checklist, on a throwaway
      vault, ending in cleanup (eight steps: backup window, by hand, corrupt file, conflict
      copy, Drive revision, KeePassXC GUI and CLI)
- [ ] the owner has run section 11 and reported the result — **owner-gated**, this is gate G5

## One thing the drill turned up

`VaultSession.restore_backup` replaces `vault.kdbx` without keeping a copy of what it
replaced (`core/vault.py:309` calls `storage.atomic_write` directly, where `save()` calls
`storage.write()` which backs up first). A restore is therefore not itself undoable, and
`docs/recovery.md` says so in the Backups section. Whether that should change is the owner's
call — it is not a bug the tests disagree with (M2-08 asked for "restore after confirmation",
not for a pre-restore backup), so no code was touched.

## Proposed change to docs/specs (rule 7: the owner applies this)

In `docs/specs/milestones.md`, the M6 "Done when" list gains one line above the existing
drill line (which stays unticked — it is gate G5, the owner's own run):

```markdown
- [x] The recovery paths are written down (`docs/recovery.md`) and rehearsed as
      `docs/manual-tests.md` §11
- [ ] The owner has performed all three recovery paths
```

## Out of scope

Restoring an arbitrary Drive revision from inside the app, un-deleting from the Recycle Bin
(the entry is in the file and in the bin; emptying it is not a feature yet), and any
"repair the KDBX" tooling
