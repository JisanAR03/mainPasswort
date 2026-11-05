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
