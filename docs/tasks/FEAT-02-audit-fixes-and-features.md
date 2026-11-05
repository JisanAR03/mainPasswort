# FEAT-02: audit fixes, then the missing vault features

Not a milestone card: the owner asked on 2026-11-05 (after an audit of `main` at 166dd7b) to fix every
bug the audit found and to add the features the extension was missing, proving each in a real browser.
Work is split in two pull requests so each can be reviewed on its own:

1. **Bug fixes** (this part, branch `fix/audit-bugs`).
2. **Features** (branch `feat/vault-management`, stacked on the first).

## Owner's decisions (2026-11-05, asked once at the start)

| Question | Answer |
|---|---|
| Git | Branches, commits, push and pull requests allowed; **nothing is merged** by the assistant. |
| `clipboardRead` | **Yes.** Needed to clear the clipboard only when it still holds the copied password. |
| Breach check (haveibeenpwned) | **No.** Stays fully offline; weak and reused-password reports are offline. |
| Plaintext export | **No.** The spec's "no plaintext export" stands; encrypted export stays. |

Firefox was not asked about and is **out of scope**: it is a port (the engine depends on
`chrome.offscreen`, which Firefox lacks) and cannot be proven in Brave.

## Part 1: bugs

| # | Bug (found in the audit) | Fix | Proof |
|---|---|---|---|
| 1 | A login inside a native modal `<dialog>` (`showModal()`): the menu is outside it, so it is covered and inert. | The menu now mounts **inside** the open modal dialog or popover the field is in (its own layer; the save prompt stays on the page) and is placed relative to wherever `position: fixed` is anchored, so a dialog centred with a transform still gets the menu under its field. `inline.js` | `test_the_menu_works_inside_a_native_modal_dialog` (plain and transformed dialog): both failed before the fix. |
| 2 | The popup answered for whichever tab the browser listed first, not the window it was in. | The toolbar popup (no tab of its own) acts on the active tab of the last focused window; popup.html opened as a tab acts on the last page used in its own window. Never a tab of another window. `background.js` | `test_the_popup_lists_the_logins_of_the_window_it_is_in` failed before. |
| 3 | The popup's "Add a login" stored the whole address-bar URL, query included, as title and web address. | `saveLogin` stores the site's origin and the host as title. Matching ignores the path, so nothing is lost. `engine.js` | `test_the_popup_add_form_stores_the_site_and_never_the_query` failed before. |
| 4 | Disconnect then Connect (same Google account) asked the first-link question again. | Disconnect keeps what was synced, tagged with the account; the same account resumes from it (`decide()` still compares everything, so any change is an upload, download or conflict, never a blind overwrite); another account starts over with the first-link question (ADR-010 unchanged). `sync.js` | `test_reconnecting_the_same_account_resumes...` failed before; `test_connecting_another_account_still_asks...` is the guard. |
| 5 | The 30 s clipboard clear (a) wiped whatever you had copied meanwhile and (b) never ran if the vault tab was closed. | The clear runs in the offscreen engine, which keeps only the SHA-256 of what was copied and clears only if the clipboard still holds it; locking clears at once. `engine.js`, `local.js`, `vault.js`, `config.js` | Four tests; the three that exercise the fix failed before. |

### Permissions (read this)

- **`clipboardRead`** was approved by the owner.
- **`clipboardWrite` is a second permission the same fix needs.** Measured in Chromium: in the offscreen
  document `execCommand("paste")` works with `clipboardRead`, but `execCommand("copy")` returns `false`
  without `clipboardWrite`, so the clear cannot write. It was added on that evidence and is called out
  here for the owner to accept or reject (rejecting it means the clear can only run while the vault page
  is open and focused).
- The offscreen document is now created with reasons `DOM_PARSER` and `CLIPBOARD`.
- An empty `execCommand("copy")` leaves the clipboard unchanged (measured), so the clear writes one space.

### `[S]` files for the owner's review

`extension/inline.js`, `background.js`, `engine.js`, `local.js`, `sync.js`, `vault.js`, `config.js`,
`manifest.json`.

### Not verifiable here

- The toolbar popup itself (no tab) cannot be opened by the automated browser; the popup-in-a-window test
  uses popup.html as a tab, which takes the tab path. The no-tab path is two lines
  (`active: true, lastFocusedWindow: true`) and is in the manual checklist.

---

## Part 2: the missing features (branch `feat/vault-management`, stacked on part 1)

Sensitive: **yes**. Every feature touches the vault engine or the page-facing scripts.

### Files you may change (rule 6)

`extension/engine.js`, `local.js`, `background.js`, `sync.js`, `vault.js`, `vault.html`, `vault.css`,
`popup.js`, `inline.js`, `menu.js`, `fill.js`, `config.js`, `manifest.json`; new `extension/csv.js`,
`extension/totp.js`, `extension/test-pages/signup.html`; `scripts/check_sensitive_review.py` (the two new
modules join the `[S]` list); tests under `app/tests/e2e/`; `README.md` and the user docs
(`docs/setup-browser.md`, `recovery.md`, `known-limitations.md`, `manual-tests.md`). Nothing in
`docs/specs/`, `docs/adr/` or `AGENTS.md` was edited: the changes they need are proposed below.

### What was added

| Feature | Where | Why / how |
|---|---|---|
| Change the master password | `engine.js` `changePassword`, `local.js`, vault page | Re-keys the open vault (current password re-typed; kdbxweb draws fresh seeds on save). A failed save puts the stored file and old key back. |
| Download re-keyed elsewhere | `engine.js` `adopt`, `sync.js` | A Drive copy under a changed password gives `unreadable`; the panel asks for the new password and `take_theirs` uses it. A wrong one adopts nothing. |
| Recycle Bin: view, restore, delete for good, empty | `engine.js`, vault page tab | "For good" uses kdbxweb's deleted-object record, so a merge does not bring it back. |
| Backups: list and restore | `engine.js` `restoreBackup`, vault page | A copy from before a password change asks for the old password and is **re-keyed to the current key**; the vault it replaces becomes the newest backup (undoable). |
| Import CSV and `.kdbx` | `csv.js`, `engine.js` | Own RFC 4180 reader (no dependency). Headers of Chrome/Firefox/Bitwarden/1Password/LastPass/KeePassXC. Counts only, never a value; duplicates skipped; one save. `.kdbx` import leaves out its bin and the desktop app's hidden `.app` group. |
| Earlier versions of a login | `engine.js`, entry form | List, view (password hidden until asked), restore (current goes to history). |
| One-time codes (TOTP) | `totp.js`, `engine.js`, popup | RFC 6238 with WebCrypto HMAC; stored as KeePassXC's `otp` field. A value it cannot compute (Steam, HOTP) is kept untouched, never blocks an edit, and is dropped (login kept) on import. |
| Password health | `engine.js` `report` | Weak, reused, old — offline; titles and usernames only, never a password or hash. |
| Merge both copies | `engine.js` `mergeRemote`, `sync.js` `mergeKept` | kdbxweb's own merge. Their copy counts as seen only if Drive still holds the copy that was kept (I6); otherwise the conflict returns. |
| Settings | `background.js`, `local.js`, vault page | Lock after idle (needs the optional `idle` permission), a shorter unlock (never longer than 6 h), generator options, the Never list and "offer to save". |
| New-password suggestion | `inline.js`, `background.js` `menu_suggest`, `menu.js`, `fill.js` `fillNewPassword` | On an `autocomplete="new-password"` field of an unlocked vault; fills that field and its confirmation only after a click in the menu frame; never submits. |
| Alt+Shift+P | `manifest.json` | `_execute_action`: opens the popup. (Not a one-key fill: that was not built.) |

### Found by looking at Brave screenshots (all tests were green before these)

| Problem | Fix | Test (fails on the old code) |
|---|---|---|
| The menu inside a transformed modal dialog was cut off at the dialog's edge | The in-dialog host is also a popover, shown in the top layer (not clipped, not offset by the dialog's transform) | the transformed-dialog test now checks the menu's last pixels |
| Choice buttons ("Keep this computer's copy", "Upload this vault again") and an empty code row were visible when they should be hidden: `.row` overrode `hidden` (the sync buttons were already like this) | `[hidden] { display: none !important }` on the vault page | `test_parts_of_the_page_that_should_be_hidden_are_hidden` |
| Closing the login form reset the settings form (blank client ID, unlock "1 hour", offer off) and blanked the generator options, so the next "Save settings" would save them (the reset-everything was already there) | `clearForms` skips the settings and rename forms; generator options are re-filled from the saved ones | `test_closing_a_login_form_leaves_the_settings_and_generator_options_alone` |
| Menu rows were 46 px in the size maths but about 52 px on screen, so the last row of a menu was cut off (already so for several saved logins) | `MENU_ROW_PX = 52` | the menu-height assertion in `test_a_new_password_field_on_a_site_with_a_login_offers_both` |
| An open health report vanished whenever the page refreshed itself (every sync status write) | the report is cleared only when you switch to the tab | `test_the_health_report_stays_while_the_page_refreshes_itself` |

### `[S]` files for the owner's review

`extension/engine.js`, `local.js`, `background.js`, `sync.js`, `vault.js`, `inline.js`, `menu.js`,
`fill.js`, `config.js`, `manifest.json`, and the new `totp.js` and `csv.js`.

### Out of scope, and why

- **Breach check** — the owner chose not to (it sends hash prefixes to an outside service).
- **Plaintext export** — the owner chose not to; the data model says there is none.
- **Firefox** — a port, not a feature: the engine depends on `chrome.offscreen`, which Firefox lacks.
- **A one-key "fill the only match" shortcut** — cannot be verified by automation; Alt+Shift+P opens the
  popup instead.

### What automation cannot verify (manual checklist: `docs/manual-tests.md` §4b)

The real toolbar popup (it has no tab), the idle lock (the OS idle state), the keyboard shortcuts,
real sites that use a modal dialog, real Google, and the browser's Reload button (see the next section).

### Found while proving the upgrade

An automated upgrade in Brave (the extension at 166dd7b creates a vault, then the new code opens the same
profile folder) passed 25 of 25 checks **once the browser's cached background script was cleared**. Without
that, a plain browser restart kept running the previous background script for 40+ seconds; clicking
**Reload** on the extension card is the supported update path (documented in `setup-browser.md`). The
vault, storage and Preferences were never touched by the harness.

### Proposed text for files the rules say I may not edit (rule 7)

- **`docs/specs/data-model.md`** (§ export, "no import from a file"): "The vault page imports logins from a
  CSV (Chrome/Firefox/Bitwarden/1Password/LastPass/KeePassXC headers) or a `.kdbx`. A one-time-password
  secret is stored in the entry's `otp` field as an `otpauth://` URI, as KeePassXC does. There is still no
  plaintext export."
- **`docs/specs/browser-protocol.md`**: add the vault-page/popup requests `ext_change_password`,
  `ext_bin_list|restore|delete|empty`, `ext_backup_list`, `ext_restore_backup`,
  `ext_history_list|get|restore`, `ext_totp`, `ext_import_csv`, `ext_import_kdbx`, `ext_report`,
  `ext_never_remove|clear`, `ext_set_offer`, `ext_clipboard_arm`; the popup request `get_totp`; the menu
  request `menu_suggest`; and `ext_choose` choice `merge` and its optional `password`.
- **`docs/specs/threat-model.md`**: the extension now holds `clipboardRead` and `clipboardWrite`: it reads
  the clipboard once, 30 s after a Copy, keeps only a SHA-256 of what it copied, and clears only a match.
  A TOTP secret stored next to the password means one opened vault gives both factors.
- **`docs/specs/sync.md` / ADR-006**: a conflict has a third resolution, **merge**, using the library's merge,
  allowed only against the copy that was kept (I6).
- **ADR-010**: "Disconnect keeps the sync record, tagged with the account; connecting the same account resumes
  from it (decide() still runs); another account starts at the first-link question."
- **AGENTS.md**: still the old text (see EXT-01).

### Decisions asked of the owner at the end

1. **`clipboardWrite`**: it was added **before** asking, because `clipboardRead` alone cannot make the clear
   work (measured: `execCommand("copy")` returned `false` without it). Keep it, or revert it (then the clear
   only runs while the vault page is open and focused).
2. Whether to merge PR 12 before PR 13, and how (a merge commit or a rebase, not a squash, keeps PR 13's
   diff small; after a squash PR 13 needs `git rebase --onto origin/main fix/audit-bugs`).
