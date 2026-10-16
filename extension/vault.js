// The vault page for extension-only mode ([S]): profiles, unlock, entries,
// generator, settings, export and the Google Drive status. Everything goes
// through the service worker (ext_* messages); this page holds an entry only
// while its form is open and clears every field when the vault locks.

const $ = (id) => document.getElementById(id);
const CLIPBOARD_CLEAR_MS = 30 * 1000;

let state = null; // the last ext_state reply
let editing = null; // the entry id being edited, or "" for a new one

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
  invalid: "Check the fields: a title is needed, and web addresses must start with http:// or https://.",
  confirmation_mismatch: "The name you typed does not match the profile's name.",
  locked: "The vault is locked.",
  save_failed: "The change could not be saved; the vault is as it was.",
  no_client_id: "Set the Google OAuth client ID in Settings first.",
  sign_in_cancelled: "Google sign-in was cancelled.",
  reconnect: "Google did not accept the sign-in. Try Connect Google Drive again.",
  wrong_scope: "Google did not grant Drive access. Connect again and allow it.",
  unreadable: "The vault file could not be read.",
};

function notice(text) {
  $("notice").textContent = text || "";
  $("notice").hidden = !text;
}

const failed = (reply) => notice(ERRORS[reply.error && reply.error.code] || `Something went wrong (${reply.error ? reply.error.code : "unknown"}).`);

function show(view) {
  for (const id of ["view-mode", "view-create", "view-unlock", "view-vault"]) $(id).hidden = id !== view;
  // opening a vault from Google Drive is offered whenever nothing is unlocked
  $("view-drive").hidden = !(state && state.mode === "extension" && !state.unlocked);
  if (!$("view-drive").hidden) {
    $("drive-client").value = state.settings.googleClientId;
    $("drive-client-row").hidden = Boolean(state.settings.googleClientId);
  }
}

function profileName(id) {
  const profile = state.profiles.find((p) => p.id === id);
  return profile ? profile.name : "";
}

// --- rendering ---------------------------------------------------------------

async function refresh() {
  const reply = await send("ext_state");
  if (!reply.ok) return failed(reply);
  state = reply.result;
  $("lock").hidden = !state.unlocked;
  if (state.mode !== "extension") {
    $("who").textContent = "Desktop app mode";
    return show("view-mode");
  }
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
  $("s-client").value = state.settings.googleClientId;
  $("s-idle").checked = state.settings.lockOnScreenLock;
  $("s-redirect").textContent = state.redirectUrl;
  renderSync();
  show("view-vault");
  await renderEntries();
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

// --- entry form ----------------------------------------------------------------

function clearForms() {
  for (const form of document.querySelectorAll("form")) form.reset();
  $("entry-form").hidden = true;
  $("f-password").type = "password";
  editing = null;
}

function fillForm(entry) {
  $("f-title").value = entry.title || "";
  $("f-username").value = entry.username || "";
  $("f-password").value = entry.password || "";
  $("f-password").type = "password";
  $("f-urls").value = (entry.urls || []).join("\n");
  $("f-subdomains").checked = Boolean(entry.match_subdomains);
  $("f-notes").value = entry.notes || "";
  $("f-tags").value = (entry.tags || []).join(", ");
}

async function openEntry(id) {
  const reply = await send("ext_get", { entryId: id });
  if (!reply.ok) return failed(reply);
  editing = id;
  fillForm(reply.result.entry);
  $("entry-heading").textContent = "Edit login";
  $("f-delete").hidden = false;
  $("entry-form").hidden = false;
}

function newEntry() {
  editing = "";
  fillForm({});
  $("entry-heading").textContent = "Add a login";
  $("f-delete").hidden = true;
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
    notes: $("f-notes").value,
    tags: $("f-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
  };
  if (editing) entry.id = editing;
  return entry;
}

// --- events ----------------------------------------------------------------------

$("use-extension").addEventListener("click", async () => {
  const reply = await send("ext_set_mode", { mode: "extension" });
  if (!reply.ok) return failed(reply);
  notice("");
  await refresh();
});

$("use-desktop").addEventListener("click", async () => {
  if (!confirm("Lock this vault and switch back to the desktop app? Vaults stay in this browser.")) return;
  const reply = await send("ext_set_mode", { mode: "desktop" });
  if (!reply.ok) return failed(reply);
  await refresh();
});

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

$("search").addEventListener("input", () => renderEntries());
$("add").addEventListener("click", newEntry);
$("f-cancel").addEventListener("click", clearForms);

$("f-show").addEventListener("click", () => {
  const field = $("f-password");
  field.type = field.type === "password" ? "text" : "password";
  $("f-show").textContent = field.type === "password" ? "Show" : "Hide";
});

$("f-generate").addEventListener("click", async () => {
  const reply = await send("ext_generate", { length: 20 });
  if (reply.ok) $("f-password").value = reply.result.password;
});

$("f-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("f-password").value);
    notice("Password copied; the clipboard is cleared in 30 seconds.");
    setTimeout(() => navigator.clipboard.writeText("").catch(() => {}), CLIPBOARD_CLEAR_MS);
  } catch {
    notice("The browser did not allow copying.");
  }
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

$("rename-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const reply = await send("ext_rename_profile", { profileId: state.unlocked.profileId, name: $("rename-name").value });
  if (!reply.ok) return failed(reply);
  notice("Renamed.");
  await refresh();
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

$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const wantIdle = $("s-idle").checked;
  if (wantIdle) {
    // the optional permission is asked for on this click, never silently
    const granted = await chrome.permissions.request({ permissions: ["idle"] });
    if (!granted) {
      $("s-idle").checked = false;
      notice("Without the permission the vault cannot lock with the screen.");
    }
  }
  const reply = await send("ext_settings", { googleClientId: $("s-client").value, lockOnScreenLock: $("s-idle").checked });
  if (!reply.ok) return failed(reply);
  notice("Settings saved.");
  await refresh();
});

async function syncAction(type, args) {
  notice("Working with Google Drive…");
  const reply = await send(type, args);
  if (!reply.ok) return failed(reply);
  notice("");
  await refresh();
}

$("sync-connect").addEventListener("click", () => syncAction("ext_connect"));
$("sync-now").addEventListener("click", () => syncAction("ext_sync_now"));
$("sync-disconnect").addEventListener("click", () => {
  if (confirm("Stop syncing this vault with Google Drive? The copy on Drive stays there.")) syncAction("ext_disconnect");
});
$("choice-mine").addEventListener("click", () => syncAction("ext_choose", { choice: "keep_mine" }));
$("choice-theirs").addEventListener("click", () => syncAction("ext_choose", { choice: "take_theirs" }));
$("choice-upload").addEventListener("click", () => syncAction("ext_choose", { choice: "upload" }));

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
    (key) => key === "unlocked" || key === "profiles" || key === "mode" || key.startsWith("sync_status:"),
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
