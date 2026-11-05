// The vault page for extension-only mode ([S]): profiles, unlock, entries, the
// Recycle Bin, backups, import, password health, generator, settings, export and
// the Google Drive status. Everything goes through the service worker (ext_*
// messages); this page holds an entry only while its form is open and clears
// every field when the vault locks.
import { CLIPBOARD_CLEAR_MS } from "./config.js";

const $ = (id) => document.getElementById(id);

let state = null; // the last ext_state reply
let editing = null; // the entry id being edited, or "" for a new one
let tab = "logins"; // logins | bin | health
let historyPassword = ""; // the password of the earlier version being viewed; cleared with the forms
let totpEntry = null; // the entry whose one-time code is shown
let totpEndsAt = 0;
let totpTicker = null;

async function send(type, args = {}) {
  try {
    const reply = await chrome.runtime.sendMessage({ type, args });
    return reply || { ok: false, error: { code: "internal" } };
  } catch {
    return { ok: false, error: { code: "internal" } };
  }
}

const ERRORS = {
  bad_password: "That master password does not open this vault.",
  password_too_short: "The master password must be at least 12 characters.",
  invalid_name: "Give the profile a name (up to 100 characters).",
  invalid: "Check the fields: a title is needed, web addresses must start with http:// or https://, and a one-time code secret must be Base32 or an otpauth:// link.",
  confirmation_mismatch: "The name you typed does not match the profile's name.",
  locked: "The vault is locked.",
  save_failed: "The change could not be saved; the vault is as it was.",
  no_client_id: "Set the Google OAuth client ID in Settings first.",
  sign_in_cancelled: "Google sign-in was cancelled.",
  reconnect: "Google did not accept the sign-in. Try Connect Google Drive again.",
  wrong_scope: "Google did not grant Drive access. Connect again and allow it.",
  unreadable: "The vault file could not be read.",
  backup_password: "That backup is under an older master password: type it in the box above the list.",
  not_found: "That item is gone: the list was out of date.",
  import_unrecognized: "That file is not a CSV this page can read: it needs a header row with a password column.",
  import_malformed: "That CSV is damaged (a quote is not closed).",
  import_too_large: "That file is empty or too large.",
  import_too_many_rows: "That CSV has too many rows (at most 10,000).",
  merge_failed: "The two copies could not be merged; nothing was changed.",
  no_totp: "This login has no usable one-time code secret.",
};

function notice(text) {
  $("notice").textContent = text || "";
  $("notice").hidden = !text;
}

const failed = (reply) =>
  notice(
    ERRORS[reply.error && reply.error.code] ||
      `Something went wrong (${reply.error ? reply.error.code : "unknown"}).`,
  );

function show(view) {
  for (const id of ["view-create", "view-unlock", "view-vault"]) $(id).hidden = id !== view;
  // opening a vault from Google Drive is offered whenever nothing is unlocked
  $("view-drive").hidden = !(state && !state.unlocked);
  if (!$("view-drive").hidden) {
    $("drive-client").value = state.settings.googleClientId;
    $("drive-client-row").hidden = Boolean(state.settings.googleClientId);
  }
}

function profileName(id) {
  const profile = state.profiles.find((p) => p.id === id);
  return profile ? profile.name : "";
}

const shortDate = (iso) => (iso ? new Date(iso).toLocaleString() : "unknown time");

function toB64(buffer) {
  const bytes = new Uint8Array(buffer);
  let out = "";
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
}

function button(label, onClick, className = "plain") {
  const element = Object.assign(document.createElement("button"), { type: "button", textContent: label, className });
  element.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return element;
}

function row(textParts, ...actions) {
  const item = document.createElement("li");
  const text = document.createElement("div");
  const title = Object.assign(document.createElement("div"), { className: "title", textContent: textParts[0] });
  const detail = Object.assign(document.createElement("div"), { className: "detail", textContent: textParts[1] || "" });
  text.append(title, detail);
  const box = Object.assign(document.createElement("div"), { className: "actions" });
  box.append(...actions);
  item.append(text, box);
  return item;
}

// --- rendering ---------------------------------------------------------------

async function refresh() {
  const reply = await send("ext_state");
  if (!reply.ok) return failed(reply);
  state = reply.result;
  $("lock").hidden = !state.unlocked;
  if (!state.unlocked) {
    clearForms();
    $("who").textContent = "Locked";
    if (state.profiles.length === 0) {
      $("create-heading").textContent = "Create your first vault";
      $("create-cancel").hidden = true;
      return show("view-create");
    }
    const select = $("unlock-profile");
    select.replaceChildren(
      ...state.profiles.map((p) => Object.assign(document.createElement("option"), { value: p.id, textContent: p.name })),
    );
    select.value = state.lastProfileId && state.profiles.some((p) => p.id === state.lastProfileId)
      ? state.lastProfileId
      : state.profiles[0].id;
    return show(location.hash === "#new" ? "view-create" : "view-unlock");
  }
  const until = new Date(state.unlocked.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("who").textContent = `${profileName(state.unlocked.profileId)} — unlocked until ${until}`;
  $("rename-name").value = profileName(state.unlocked.profileId);
  renderSettings();
  renderSync();
  show("view-vault");
  await renderEntries();
  await renderPane();
}

function renderSettings() {
  const { settings } = state;
  $("s-client").value = settings.googleClientId;
  $("s-idle").checked = settings.lockOnScreenLock;
  $("s-idle-minutes").value = String(settings.lockAfterIdleMinutes);
  $("s-unlock-hours").value = String(settings.unlockHours);
  $("s-offer").checked = state.offerToSave;
  $("s-redirect").textContent = state.redirectUrl;
  fillGeneratorOptions();
  renderNever();
}

function renderNever() {
  const list = $("never-list");
  list.replaceChildren();
  for (const origin of state.neverSave) {
    list.append(
      row([origin], button("Allow again", async () => {
        const reply = await send("ext_never_remove", { origin });
        if (!reply.ok) return failed(reply);
        await refresh();
      })),
    );
  }
  if (state.neverSave.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "detail", textContent: "None." }));
  }
  $("never-clear").hidden = state.neverSave.length === 0;
}

function renderSync() {
  const profileId = state.unlocked.profileId;
  const profile = state.profiles.find((p) => p.id === profileId);
  const status = state.statuses[profileId];
  const connected = Boolean(profile && profile.googleEmail);
  $("sync-account").textContent = connected ? profile.googleEmail : "not connected";
  $("sync-state").textContent = status
    ? status.message
    : connected
      ? "Not synced yet."
      : "Not connected to Google Drive: this vault is only on this computer.";
  const at = (iso) => (iso ? new Date(iso).toLocaleString() : null);
  $("sync-last").textContent = (status && at(status.lastSuccessAt)) || "never";
  $("sync-local").textContent =
    status && status.localOnly ? "only on this computer (not uploaded yet)" : connected ? "uploaded" : "only on this computer";
  $("sync-retry").textContent = (status && at(status.nextRetryAt)) || "—";
  $("sync-connect").textContent = connected ? "Reconnect Google Drive" : "Connect Google Drive";
  $("sync-connect").hidden = connected && !(status && status.state === "reconnect");
  $("sync-now").hidden = !connected;
  $("sync-disconnect").hidden = !connected;
  const choosing = status && (status.state === "conflict" || status.state === "first_link");
  $("sync-choice").hidden = !choosing;
  $("choice-merge").hidden = !(status && status.state === "conflict");
  $("sync-rekey").hidden = !(status && status.state === "unreadable");
  $("sync-missing").hidden = !(status && status.state === "missing");
}

async function renderEntries() {
  const reply = await send("ext_list", { query: $("search").value });
  if (!reply.ok) return failed(reply);
  const list = $("entries");
  list.replaceChildren();
  for (const entry of reply.result.entries) {
    const item = document.createElement("li");
    const title = Object.assign(document.createElement("div"), { className: "title", textContent: entry.title });
    const detail = Object.assign(document.createElement("div"), {
      className: "detail",
      textContent: [entry.username, entry.hosts.join(", ")].filter(Boolean).join(" · "),
    });
    item.append(title, detail);
    item.dataset.id = entry.id;
    item.addEventListener("click", () => openEntry(entry.id));
    list.append(item);
  }
  if (reply.result.entries.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "detail", textContent: "No logins yet." }));
  }
}

// --- the sections beside the logins ---------------------------------------------------

function selectTab(name) {
  tab = name;
  for (const element of document.querySelectorAll(".tab")) {
    element.classList.toggle("active", element.dataset.tab === name);
  }
  $("pane-logins").hidden = name !== "logins";
  $("pane-bin").hidden = name !== "bin";
  $("pane-health").hidden = name !== "health";
  if (name === "health") $("health-out").replaceChildren(); // an old report is not shown again
  return renderPane();
}

async function renderPane() {
  if (tab === "bin") await renderBin();
}

async function renderBin() {
  const reply = await send("ext_bin_list");
  if (!reply.ok) return failed(reply);
  const list = $("bin-list");
  list.replaceChildren();
  for (const entry of reply.result.entries) {
    list.append(
      row(
        [entry.title, [entry.username, `deleted ${shortDate(entry.deleted_at)}`].filter(Boolean).join(" · ")],
        button("Restore", async () => {
          const result = await send("ext_bin_restore", { entryId: entry.id });
          if (!result.ok) return failed(result);
          await refresh();
          notice("Restored to your logins.");
        }),
        button("Delete for good", async () => {
          if (!confirm(`Delete "${entry.title}" for good? It cannot be restored.`)) return;
          const result = await send("ext_bin_delete", { entryId: entry.id });
          if (!result.ok) return failed(result);
          await refresh();
          notice("Deleted for good.");
        }, "danger"),
      ),
    );
  }
  if (reply.result.entries.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "detail", textContent: "The Recycle Bin is empty." }));
  }
  $("bin-empty").hidden = reply.result.entries.length === 0;
}

async function renderBackups() {
  const reply = await send("ext_backup_list");
  if (!reply.ok) return failed(reply);
  const list = $("backup-list");
  list.replaceChildren();
  for (const backup of reply.result.backups) {
    list.append(
      row(
        [shortDate(backup.savedAt), `${Math.max(1, Math.round(backup.size / 1024))} KB`],
        button("Restore", async () => {
          if (!confirm("Replace the current vault with this backup? The current vault is kept as the newest backup.")) return;
          const result = await send("ext_restore_backup", {
            backupId: backup.id,
            password: $("backup-password").value,
          });
          if (!result.ok) return failed(result);
          $("backup-password").value = "";
          await refresh();
          await renderBackups();
          notice("Backup restored. The vault you had before is the newest backup.");
        }),
      ),
    );
  }
  if (reply.result.backups.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "detail", textContent: "No backups yet: one is made each time the vault is saved." }));
  }
}

// --- password health ---------------------------------------------------------------------

const REASONS = {
  empty: "no password",
  common: "one of the most common passwords",
  short: "shorter than 8 characters",
  weak: "easy to guess",
};

function healthSection(title, items) {
  const box = Object.assign(document.createElement("div"), { className: "group" });
  box.append(Object.assign(document.createElement("h2"), { textContent: `${title} (${items.length})` }));
  const list = Object.assign(document.createElement("ul"), { className: "entries static" });
  for (const [label, detail, id] of items) {
    list.append(row([label, detail], button("Open", () => openFromHealth(id))));
  }
  if (items.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "detail", textContent: "Nothing to fix." }));
  }
  box.append(list);
  return box;
}

async function openFromHealth(id) {
  await selectTab("logins");
  await openEntry(id);
}

$("health-run").addEventListener("click", async () => {
  const reply = await send("ext_report");
  if (!reply.ok) return failed(reply);
  const { weak, reused, old, total } = reply.result;
  const out = $("health-out");
  out.replaceChildren(
    Object.assign(document.createElement("p"), { textContent: `${total} login${total === 1 ? "" : "s"} checked.` }),
    healthSection("Weak passwords", weak.map((w) => [w.title, `${w.username} — ${REASONS[w.reason] || w.reason}`, w.id])),
    healthSection(
      "Reused passwords",
      reused.flatMap((group) =>
        group.map((g) => [g.title, `${g.username} — the same password as ${group.length - 1} other login${group.length === 2 ? "" : "s"}`, g.id]),
      ),
    ),
    healthSection("Not changed in over a year", old.map((o) => [o.title, `${o.username} — last changed ${shortDate(o.updated_at)}`, o.id])),
  );
});

// --- entry form ----------------------------------------------------------------

function stopTotp() {
  clearInterval(totpTicker);
  totpTicker = null;
  totpEntry = null;
  $("f-totp").hidden = true;
  $("f-totp-code").textContent = "";
  delete $("f-totp-code").dataset.code;
}

function clearForms() {
  // The forms that hold something typed or a login. Not the settings and rename
  // forms: they show saved values, and resetting them would put the browser's blank
  // defaults in front of the next "Save settings".
  for (const form of document.querySelectorAll("form:not(#settings-form):not(#rename-form)")) {
    form.reset();
  }
  $("entry-form").hidden = true;
  $("f-password").type = "password";
  $("f-history").hidden = true;
  $("f-history-view").hidden = true;
  $("f-history-list").replaceChildren();
  historyPassword = "";
  $("hv-password").textContent = "";
  stopTotp();
  editing = null;
}

// the generator options sit in the entry form, which a reset blanks: show the saved ones
function fillGeneratorOptions() {
  if (!state) return;
  const generator = state.settings.generator;
  $("g-length").value = generator.length;
  $("g-upper").checked = generator.upper;
  $("g-lower").checked = generator.lower;
  $("g-digits").checked = generator.digits;
  $("g-symbols").checked = generator.symbols;
  $("g-lookalikes").checked = generator.excludeLookalikes;
}

function fillForm(entry) {
  fillGeneratorOptions();
  $("f-title").value = entry.title || "";
  $("f-username").value = entry.username || "";
  $("f-password").value = entry.password || "";
  $("f-password").type = "password";
  $("f-urls").value = (entry.urls || []).join("\n");
  $("f-subdomains").checked = Boolean(entry.match_subdomains);
  $("f-otp").value = entry.otp || "";
  $("f-notes").value = entry.notes || "";
  $("f-tags").value = (entry.tags || []).join(", ");
}

async function refreshTotp() {
  if (!totpEntry) return;
  const reply = await send("ext_totp", { entryId: totpEntry });
  if (!reply.ok) {
    $("f-totp").hidden = true;
    return;
  }
  const { code, remaining } = reply.result;
  const half = Math.ceil(code.length / 2);
  $("f-totp-code").textContent = `${code.slice(0, half)} ${code.slice(half)}`;
  $("f-totp-code").dataset.code = code;
  totpEndsAt = Date.now() + remaining * 1000;
  $("f-totp-left").textContent = `${remaining} s`;
  $("f-totp").hidden = false;
}

function startTotp(entryId) {
  stopTotp();
  totpEntry = entryId;
  refreshTotp();
  totpTicker = setInterval(() => {
    const left = Math.ceil((totpEndsAt - Date.now()) / 1000);
    if (left <= 0) refreshTotp();
    else $("f-totp-left").textContent = `${left} s`;
  }, 1000);
}

async function renderHistory(entryId) {
  const reply = await send("ext_history_list", { entryId });
  const list = $("f-history-list");
  list.replaceChildren();
  $("f-history-view").hidden = true;
  historyPassword = "";
  if (!reply.ok || reply.result.versions.length === 0) {
    $("f-history").hidden = true;
    return;
  }
  $("f-history").hidden = false;
  for (const version of reply.result.versions) {
    list.append(
      row(
        [shortDate(version.updated_at), [version.title, version.username].filter(Boolean).join(" · ")],
        button("View", () => viewVersion(entryId, version.index)),
        button("Restore this version", async () => {
          if (!confirm("Make this earlier version the current one? The current one is kept in the list.")) return;
          const result = await send("ext_history_restore", { entryId, index: version.index });
          if (!result.ok) return failed(result);
          clearForms();
          await refresh();
          notice("Earlier version restored.");
        }),
      ),
    );
  }
}

async function viewVersion(entryId, index) {
  const reply = await send("ext_history_get", { entryId, index });
  if (!reply.ok) return failed(reply);
  const { entry } = reply.result;
  historyPassword = entry.password;
  $("hv-title").textContent = `Title: ${entry.title}`;
  $("hv-username").textContent = `Username: ${entry.username}`;
  $("hv-password").textContent = entry.password ? "••••••••" : "(no password)";
  $("hv-show").textContent = "Show password";
  $("hv-urls").textContent = `Web addresses: ${(entry.urls || []).join(", ") || "none"}`;
  $("hv-notes").textContent = entry.notes ? `Notes: ${entry.notes}` : "";
  $("f-history-view").hidden = false;
}

$("hv-show").addEventListener("click", () => {
  const hidden = $("hv-show").textContent === "Show password";
  $("hv-password").textContent = hidden ? historyPassword : historyPassword ? "••••••••" : "(no password)";
  $("hv-show").textContent = hidden ? "Hide password" : "Show password";
});

async function openEntry(id) {
  const reply = await send("ext_get", { entryId: id });
  if (!reply.ok) return failed(reply);
  editing = id;
  fillForm(reply.result.entry);
  $("entry-heading").textContent = "Edit login";
  $("f-delete").hidden = false;
  $("entry-form").hidden = false;
  if (reply.result.entry.otp) startTotp(id);
  else stopTotp();
  await renderHistory(id);
}

function newEntry() {
  stopTotp();
  editing = "";
  fillForm({});
  $("entry-heading").textContent = "Add a login";
  $("f-delete").hidden = true;
  $("f-history").hidden = true;
  $("entry-form").hidden = false;
  $("f-title").focus();
}

function formEntry() {
  const entry = {
    title: $("f-title").value.trim(),
    username: $("f-username").value,
    password: $("f-password").value,
    urls: $("f-urls").value.split("\n").map((u) => u.trim()).filter(Boolean),
    match_subdomains: $("f-subdomains").checked,
    otp: $("f-otp").value.trim(),
    notes: $("f-notes").value,
    tags: $("f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
  };
  if (editing) entry.id = editing;
  return entry;
}

// --- events ----------------------------------------------------------------------

$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = $("create-password").value;
  if (password !== $("create-repeat").value) return notice("The two master passwords differ.");
  $("create-submit").disabled = true;
  notice("Creating the vault — this takes a few seconds…");
  const reply = await send("ext_create_profile", { name: $("create-name").value, password });
  $("create-submit").disabled = false;
  $("create-password").value = "";
  $("create-repeat").value = "";
  if (!reply.ok) return failed(reply);
  notice("");
  location.hash = "";
  await refresh();
});

$("create-cancel").addEventListener("click", () => {
  location.hash = "";
  refresh();
});

$("new-profile").addEventListener("click", () => {
  location.hash = "#new";
  $("create-heading").textContent = "Add a profile";
  $("create-cancel").hidden = false;
  show("view-create");
});

$("unlock-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("unlock-submit").disabled = true;
  notice("Unlocking…");
  const reply = await send("ext_unlock", { profileId: $("unlock-profile").value, password: $("unlock-password").value });
  $("unlock-password").value = "";
  $("unlock-submit").disabled = false;
  if (!reply.ok) return failed(reply);
  notice("");
  await refresh();
});

$("lock").addEventListener("click", async () => {
  await send("ext_lock");
  clearForms();
  await refresh();
});

for (const element of document.querySelectorAll(".tab")) {
  element.addEventListener("click", () => selectTab(element.dataset.tab));
}

$("search").addEventListener("input", () => renderEntries());
$("add").addEventListener("click", newEntry);
$("f-cancel").addEventListener("click", clearForms);

$("f-show").addEventListener("click", () => {
  const field = $("f-password");
  field.type = field.type === "password" ? "text" : "password";
  $("f-show").textContent = field.type === "password" ? "Show" : "Hide";
});

function generatorOptions() {
  return {
    length: Number($("g-length").value),
    upper: $("g-upper").checked,
    lower: $("g-lower").checked,
    digits: $("g-digits").checked,
    symbols: $("g-symbols").checked,
    excludeLookalikes: $("g-lookalikes").checked,
  };
}

$("f-generate").addEventListener("click", async () => {
  const reply = await send("ext_generate", generatorOptions());
  if (reply.ok) $("f-password").value = reply.result.password;
});

$("g-save").addEventListener("click", async () => {
  const reply = await send("ext_settings", { generator: generatorOptions() });
  if (!reply.ok) return failed(reply);
  await refresh();
  notice("The generator will use these options from now on.");
});

async function sha256Hex(value) {
  const sha = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
  return [...sha].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Copy here (it needs this click), but the clearing is done by the vault engine,
// which only clears what it was told was copied — and keeps going if this page
// is closed. This page tells it the SHA-256 of the text, never the text.
async function copyToClipboard(value, what) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    notice("The browser did not allow copying.");
    return;
  }
  const armed = await send("ext_clipboard_arm", { digest: await sha256Hex(value) });
  notice(
    armed.ok
      ? `${what} copied; it is taken off the clipboard in ${Math.round(CLIPBOARD_CLEAR_MS / 1000)} seconds.`
      : `${what} copied, but it could not be scheduled to leave the clipboard: clear it yourself.`,
  );
}

$("f-copy").addEventListener("click", () => copyToClipboard($("f-password").value, "Password"));
$("f-totp-copy").addEventListener("click", () => {
  const code = $("f-totp-code").dataset.code;
  if (code) copyToClipboard(code, "Code");
});

$("entry-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("f-save").disabled = true;
  notice("Saving…");
  const reply = await send("ext_save_entry", { entry: formEntry() });
  $("f-save").disabled = false;
  if (!reply.ok) return failed(reply);
  notice("Saved.");
  clearForms();
  await refresh();
});

$("f-delete").addEventListener("click", async () => {
  if (!editing || !confirm("Move this login to the Recycle Bin?")) return;
  const reply = await send("ext_delete_entry", { entryId: editing });
  if (!reply.ok) return failed(reply);
  notice("Moved to the Recycle Bin.");
  clearForms();
  await refresh();
});

$("bin-empty").addEventListener("click", async () => {
  if (!confirm("Delete everything in the Recycle Bin for good? It cannot be restored.")) return;
  const reply = await send("ext_bin_empty");
  if (!reply.ok) return failed(reply);
  await refresh();
  notice(`Removed ${reply.result.removed} login${reply.result.removed === 1 ? "" : "s"} for good.`);
});

$("backups").addEventListener("toggle", () => {
  if ($("backups").open) renderBackups();
});

$("rename-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const reply = await send("ext_rename_profile", { profileId: state.unlocked.profileId, name: $("rename-name").value });
  if (!reply.ok) return failed(reply);
  notice("Renamed.");
  await refresh();
});

$("pw-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const next = $("pw-new").value;
  if (next !== $("pw-repeat").value) return notice("The two new master passwords differ.");
  notice("Changing the master password — this takes a few seconds…");
  const reply = await send("ext_change_password", { password: $("pw-current").value, newPassword: next });
  for (const id of ["pw-current", "pw-new", "pw-repeat"]) $(id).value = "";
  if (!reply.ok) return failed(reply);
  await refresh();
  notice("The master password was changed. Use the new one from now on.");
});

$("delete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const reply = await send("ext_delete_profile", {
    profileId: state.unlocked.profileId,
    confirmName: $("delete-name").value,
  });
  if (!reply.ok) return failed(reply);
  notice("The profile and its vault were deleted from this browser.");
  await refresh();
});

$("export").addEventListener("click", async () => {
  const reply = await send("ext_export");
  if (!reply.ok) return failed(reply);
  const bytes = Uint8Array.from(atob(reply.result.bytes), (c) => c.charCodeAt(0));
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  link.download = `${profileName(state.unlocked.profileId) || "vault"}.kdbx`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10 * 1000);
});

function importDone(reply) {
  if (!reply.ok) return failed(reply);
  const { added, duplicates, skipped } = reply.result;
  return refresh().then(() =>
    notice(
      `Imported ${added} login${added === 1 ? "" : "s"}` +
        `${duplicates ? `, ${duplicates} already here` : ""}${skipped ? `, ${skipped} skipped` : ""}.`,
    ),
  );
}

$("import-csv").addEventListener("click", async () => {
  const file = $("import-csv-file").files[0];
  if (!file) return notice("Choose a CSV file first.");
  notice("Importing…");
  const reply = await send("ext_import_csv", { text: await file.text() });
  $("import-csv-file").value = "";
  await importDone(reply);
});

$("import-kdbx").addEventListener("click", async () => {
  const file = $("import-kdbx-file").files[0];
  if (!file) return notice("Choose a .kdbx file first.");
  notice("Opening and importing — this takes a few seconds…");
  const reply = await send("ext_import_kdbx", {
    bytes: toB64(await file.arrayBuffer()),
    password: $("import-kdbx-password").value,
  });
  $("import-kdbx-password").value = "";
  $("import-kdbx-file").value = "";
  await importDone(reply);
});

$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const idleMinutes = Number($("s-idle-minutes").value);
  if ($("s-idle").checked || idleMinutes > 0) {
    // the optional permission is asked for on this click, never silently
    const granted = await chrome.permissions.request({ permissions: ["idle"] });
    if (!granted) {
      $("s-idle").checked = false;
      $("s-idle-minutes").value = "0";
      notice("Without the permission the vault cannot lock with the screen or when idle.");
    }
  }
  const reply = await send("ext_settings", {
    googleClientId: $("s-client").value,
    lockOnScreenLock: $("s-idle").checked,
    lockAfterIdleMinutes: Number($("s-idle-minutes").value),
    unlockHours: Number($("s-unlock-hours").value),
  });
  if (!reply.ok) return failed(reply);
  const offer = await send("ext_set_offer", { value: $("s-offer").checked });
  if (!offer.ok) return failed(offer);
  await refresh();
  notice("Settings saved.");
});

$("never-clear").addEventListener("click", async () => {
  const reply = await send("ext_never_clear");
  if (!reply.ok) return failed(reply);
  await refresh();
});

async function syncAction(type, args) {
  notice("Working with Google Drive…");
  const reply = await send(type, args);
  if (!reply.ok) return failed(reply);
  notice(
    reply.result && reply.result.state === "unreadable" && args && args.password
      ? "That password does not open the copy on Google Drive."
      : "",
  );
  await refresh();
}

$("sync-connect").addEventListener("click", () => syncAction("ext_connect"));
$("sync-now").addEventListener("click", () => syncAction("ext_sync_now"));
$("sync-disconnect").addEventListener("click", () => {
  if (confirm("Stop syncing this vault with Google Drive? The copy on Drive stays there.")) syncAction("ext_disconnect");
});
$("choice-mine").addEventListener("click", () => syncAction("ext_choose", { choice: "keep_mine" }));
$("choice-theirs").addEventListener("click", () => syncAction("ext_choose", { choice: "take_theirs" }));
$("choice-merge").addEventListener("click", () => syncAction("ext_choose", { choice: "merge" }));
$("choice-upload").addEventListener("click", () => syncAction("ext_choose", { choice: "upload" }));
$("sync-rekey").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = $("rekey-password").value;
  $("rekey-password").value = "";
  if (password) await syncAction("ext_choose", { choice: "take_theirs", password });
});

$("drive-list").addEventListener("click", async () => {
  const clientId = $("drive-client").value.trim();
  if (clientId && clientId !== state.settings.googleClientId) {
    const saved = await send("ext_settings", { googleClientId: clientId });
    if (!saved.ok) return failed(saved);
  }
  notice("Signing in to Google…");
  const reply = await send("ext_drive_list");
  if (!reply.ok) return failed(reply);
  const { vaults, email } = reply.result;
  if (vaults.length === 0) {
    notice(`No vault on ${email || "that account"}'s Google Drive that is not already here.`);
    return;
  }
  notice("");
  $("drive-file").replaceChildren(
    ...vaults.map((v) =>
      Object.assign(document.createElement("option"), {
        value: v.fileId,
        textContent: `${v.profileId} — changed ${v.modifiedTime ? new Date(v.modifiedTime).toLocaleString() : "?"}`,
      }),
    ),
  );
  $("drive-form").hidden = false;
});

$("drive-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("drive-submit").disabled = true;
  notice("Downloading and opening the vault…");
  const reply = await send("ext_drive_open", {
    fileId: $("drive-file").value,
    name: $("drive-name").value,
    password: $("drive-password").value,
  });
  $("drive-password").value = "";
  $("drive-submit").disabled = false;
  if (!reply.ok) return failed(reply);
  notice("");
  $("drive-form").hidden = true;
  await refresh();
});

// Locking anywhere (popup, shortcut, expiry) and sync progress show up here.
chrome.storage.onChanged.addListener((changes, area) => {
  const relevant = Object.keys(changes).some(
    (key) => key === "unlocked" || key === "profiles" || key.startsWith("sync_status:"),
  );
  if (!relevant) return;
  if (area === "session" && changes.unlocked && !changes.unlocked.newValue) clearForms();
  if ($("entry-form").hidden) refresh();
  else if (state && state.unlocked) {
    send("ext_state").then((reply) => {
      if (reply.ok) {
        state = reply.result;
        if (!state.unlocked) refresh();
        else renderSync();
      }
    });
  }
});

refresh();
