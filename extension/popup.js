// The popup ([S]-adjacent): the toolbar button's small window. It lists the
// logins for the tab you are on and starts a fill, unlocks and locks the vault,
// and shows the Google Drive status in one line. It never receives a password:
// fills run in the service worker, and a password typed into the add form goes
// straight to the vault and the field is cleared. Everything else (profiles,
// editing, settings, sync) is on the vault page.
import { store } from "./api.js";

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

// The Google Drive status of the unlocked profile, in one line.
async function renderSync() {
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
  if (status && status.localOnly && status.state !== "off") {
    text += " Latest change: only on this computer.";
  }
  $("sync").textContent = text;
  show("sync", true);
}

// No vault yet, or locked: say so and offer the matching form.
async function renderClosed() {
  const reply = await send("ext_state", { args: {} });
  if (!reply.ok) return setStatus("Could not read the vault list.");
  const { profiles, lastProfileId } = reply.result;
  if (profiles.length === 0) {
    setStatus("No vault in this browser yet.");
    show("setup", true);
    return;
  }
  const select = $("profile");
  select.replaceChildren(
    ...profiles.map((p) =>
      Object.assign(document.createElement("option"), { value: p.id, textContent: p.name }),
    ),
  );
  if (profiles.some((p) => p.id === lastProfileId)) select.value = lastProfileId;
  setStatus("Locked.");
  show("unlock-form", true);
  $("password").focus();
}

async function refresh() {
  setStatus("Checking the vault…");
  for (const id of ["setup", "unlock-form", "sync", "insecure", "add", "lock"]) show(id, false);
  show("open-vault", true);
  matches = [];
  renderMatches();

  const reply = await send("status");
  if (!reply.ok) {
    setStatus("The vault did not answer. Reload the extension.");
    return;
  }
  if (reply.result.state === "locked") {
    await renderClosed();
    return;
  }

  const name = reply.result.profile_name;
  show("lock", true);
  setStatus(`Unlocked: ${name}`);
  await renderSync();
  const logins = await send("get_logins");
  pageUrl = logins.tab_url || "";
  if (!logins.ok) {
    const code = logins.error ? logins.error.code : "unknown";
    if (code === "no_match") show("add", true); // a site with no saved login: add one here
    else if (code === "no_tab") setStatus(`Unlocked: ${name}. Open a web page to see its logins.`);
    else setStatus(`Could not list logins: ${code}`);
    await renderPending();
    return;
  }
  matches = logins.result.logins;
  renderMatches();
  show("add", true);
  if (pageUrl.startsWith("http://")) show("insecure", true);
  await renderPending();
}

$("unlock-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("unlock-button").disabled = true;
  setStatus("Unlocking…");
  const reply = await send("ext_unlock", {
    args: { profileId: $("profile").value, password: $("password").value },
  });
  $("password").value = "";
  $("unlock-button").disabled = false;
  if (reply.ok) await refresh();
  else if (reply.error && reply.error.code === "bad_password") setStatus("Wrong master password.");
  else setStatus(`Could not unlock: ${reply.error ? reply.error.code : "unknown"}`);
});

const openVault = () => chrome.tabs.create({ url: chrome.runtime.getURL("vault.html") });
$("create").addEventListener("click", openVault);
$("open-vault").addEventListener("click", openVault);

$("lock").addEventListener("click", async () => {
  await send("lock");
  await refresh();
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
