// The popup ([S]-adjacent): lists matches for the tab, starts a fill, and
// offers lock, unlock, pairing and the add form. It never receives a password:
// fills run in the service worker, and a password typed into the add form is
// sent straight to the app and the field is cleared.
import { newPairingKey, pairingCode, store } from "./api.js";

const $ = (id) => document.getElementById(id);

const send = (type, extra = {}) =>
  chrome.runtime.sendMessage({ type, ...extra }).then((reply) => reply || { ok: false });

let pageUrl = "";
let matches = [];

function show(id, visible) {
  $(id).hidden = !visible;
}

function setStatus(text) {
  $("status").textContent = text;
}

function renderMatches() {
  const list = $("matches");
  list.replaceChildren();
  for (const match of matches) {
    const item = document.createElement("li");
    item.className = "match";
    const who = document.createElement("span");
    who.className = "who";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = match.title;
    const username = document.createElement("span");
    username.className = "username";
    username.textContent = match.username;
    who.append(title, username);
    const fill = document.createElement("button");
    fill.textContent = "Fill";
    fill.addEventListener("click", () => startFill(match, fill));
    item.append(who, fill);
    list.append(item);
  }
}

async function startFill(match, button) {
  button.disabled = true;
  const reply = await send("fill", { entryId: match.id, url: pageUrl });
  button.disabled = false;
  if (reply.ok) {
    setStatus("Filled.");
  } else if (reply.error && reply.error.code === "url_changed") {
    setStatus("The page changed since this list loaded. Reopen the popup.");
  } else {
    setStatus(`Could not fill: ${reply.error ? reply.error.code : "unknown error"}`);
  }
}

async function renderPending() {
  const { result: candidate } = await send("pending_save");
  show("save-prompt", Boolean(candidate));
  if (!candidate) return;
  // the service worker has already decided: a new login, or a changed
  // password for the saved login with that same username
  const isUpdate = candidate.kind === "update";
  $("save-question").textContent = isUpdate
    ? `Update the saved password for ${candidate.site}?`
    : `Save the login for ${candidate.site}?`;
  show("save-new", !isUpdate);
  const update = $("save-update");
  update.hidden = !isUpdate;
  if (isUpdate) update.textContent = `Update ${candidate.title}`;
}

async function refresh() {
  setStatus("Checking the desktop app…");
  show("not-running", false);
  show("locked", false);
  show("unpaired", false);
  show("pair-code", false);
  show("pair-hint", false);
  show("insecure", false);
  show("ext-setup", false);
  show("ext-unlock", false);
  show("ext-sync", false);
  show("open-vault", false);
  matches = [];
  renderMatches();

  const reply = await send("status");
  if (reply.ok && reply.result.mode === "extension") {
    show("open-vault", true);
    if (reply.result.state === "locked") {
      show("lock", false);
      await renderExtensionLocked();
      return;
    }
    await renderExtensionSync();
  }
  if (!reply.ok) {
    const code = reply.error ? reply.error.code : "unknown";
    if (code === "app_not_running") {
      setStatus("The desktop app is not running.");
      show("not-running", true);
    } else {
      setStatus(`The desktop app answered: ${code}`);
    }
    show("lock", false);
    return;
  }

  $("lock").hidden = false;
  if (reply.result.state === "locked") {
    setStatus(`${reply.result.profile_name} is locked.`);
    show("locked", true);
    return;
  }

  setStatus(`Unlocked: ${reply.result.profile_name}`);
  const logins = await send("get_logins");
  if (!logins.ok) {
    if (logins.error && logins.error.code === "not_paired") {
      setStatus("Not paired yet.");
      show("unpaired", true);
    } else {
      setStatus(`Could not list logins: ${logins.error.code}`);
    }
    return;
  }
  pageUrl = logins.tab_url || "";
  matches = logins.result.logins;
  renderMatches();
  if (pageUrl.startsWith("http://")) show("insecure", true);
  await renderPending();
}

$("unlock").addEventListener("click", async () => {
  await send("unlock");
  setStatus("Bringing the desktop window forward…");
});

// --- extension-only mode: unlock here, see the sync status -----------------------

async function renderExtensionLocked() {
  const reply = await send("ext_state", { args: {} });
  if (!reply.ok) return setStatus("Could not read the vault list.");
  const { profiles, lastProfileId } = reply.result;
  if (profiles.length === 0) {
    setStatus("No vault in this browser yet.");
    show("ext-setup", true);
    return;
  }
  const select = $("ext-profile");
  select.replaceChildren(
    ...profiles.map((p) => Object.assign(document.createElement("option"), { value: p.id, textContent: p.name })),
  );
  if (profiles.some((p) => p.id === lastProfileId)) select.value = lastProfileId;
  setStatus("Locked.");
  show("ext-unlock", true);
  $("ext-password").focus();
}

async function renderExtensionSync() {
  const reply = await send("ext_state", { args: {} });
  if (!reply.ok || !reply.result.unlocked) return;
  const id = reply.result.unlocked.profileId;
  const status = reply.result.statuses[id];
  const profile = reply.result.profiles.find((p) => p.id === id);
  let text = status
    ? status.message
    : profile && profile.googleEmail
      ? "Not synced yet."
      : "Only on this computer (Google Drive not connected).";
  if (status && status.localOnly && status.state !== "off") text += " Latest change: only on this computer.";
  $("ext-sync").textContent = text;
  show("ext-sync", true);
}

$("ext-unlock").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("ext-unlock-button").disabled = true;
  setStatus("Unlocking…");
  const reply = await send("ext_unlock", {
    args: { profileId: $("ext-profile").value, password: $("ext-password").value },
  });
  $("ext-password").value = "";
  $("ext-unlock-button").disabled = false;
  if (reply.ok) await refresh();
  else if (reply.error && reply.error.code === "bad_password") setStatus("Wrong master password.");
  else setStatus(`Could not unlock: ${reply.error ? reply.error.code : "unknown"}`);
});

const openVault = (hash = "") => chrome.tabs.create({ url: chrome.runtime.getURL(`vault.html${hash}`) });
$("ext-create").addEventListener("click", () => openVault());
$("open-vault").addEventListener("click", () => openVault());
$("use-extension").addEventListener("click", () => openVault());

$("lock").addEventListener("click", async () => {
  await send("lock");
  await refresh();
});

$("pair").addEventListener("click", async () => {
  // the key is made here so its code can be shown now: the app asks the user to
  // compare the two while its own "Pair" button waits for the click
  const key = newPairingKey();
  $("pair-code").textContent = await pairingCode(key);
  show("pair-code", true);
  show("pair-hint", true);
  setStatus("Confirm the code in the desktop app…");
  const reply = await send("pair", { key });
  if (reply.ok && reply.result.paired) await refresh();
  else setStatus("Pairing was not confirmed.");
});

$("add").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("add-username").value;
  const password = $("add-password").value;
  if (!password) {
    setStatus("Type or generate a password first.");
    return;
  }
  const reply = await send("save_login", {
    url: pageUrl,
    username,
    password,
    title: $("add-title").value,
  });
  $("add-password").value = "";
  setStatus(reply.ok ? "Saved." : `Could not save: ${reply.error.code}`);
});

$("add-suggest").addEventListener("click", async () => {
  const reply = await send("generate");
  if (reply.ok) $("add-password").value = reply.result.password;
});

$("save-new").addEventListener("click", async () => {
  const reply = await send("resolve_save", { action: "save" });
  setStatus(reply.ok ? "Saved." : `Could not save: ${reply.error.code}`);
  await renderPending();
});

$("save-update").addEventListener("click", async () => {
  const reply = await send("resolve_save", { action: "update" });
  setStatus(reply.ok ? "Updated." : `Could not update: ${reply.error.code}`);
  await renderPending();
});

$("save-dismiss").addEventListener("click", async () => {
  await send("resolve_save", { action: "dismiss" });
  await renderPending();
});

$("watch").addEventListener("change", async () => {
  const offer = $("watch").checked;
  await send("set_offer_to_save", { value: offer });
  setStatus(offer ? "Will offer to save logins you submit." : "Will not offer to save logins.");
});

async function initWatchToggle() {
  // on unless you turned it off
  const { offer_to_save: offer } = await store.get("offer_to_save");
  $("watch").checked = offer !== false;
}

initWatchToggle();
refresh();
