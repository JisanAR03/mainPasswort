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
  const host = new URL(candidate.url).hostname;
  $("save-question").textContent = `Save the login for ${host}?`;
  const update = $("save-update");
  if (matches.length > 0) {
    update.hidden = false;
    update.textContent = `Update ${matches[0].title}`;
    update.dataset.entryId = matches[0].id;
  } else {
    update.hidden = true;
  }
}

async function refresh() {
  setStatus("Checking the desktop app…");
  show("not-running", false);
  show("locked", false);
  show("unpaired", false);
  show("pair-code", false);
  show("pair-hint", false);
  show("insecure", false);
  matches = [];
  renderMatches();

  const reply = await send("status");
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
  const reply = await send("resolve_save", {
    action: "update",
    entryId: $("save-update").dataset.entryId,
  });
  setStatus(reply.ok ? "Updated." : `Could not update: ${reply.error.code}`);
  await renderPending();
});

$("save-dismiss").addEventListener("click", async () => {
  await send("resolve_save", { action: "dismiss" });
  await renderPending();
});

$("watch").addEventListener("change", async () => {
  if ($("watch").checked) {
    // the permission request must come from this click, so it happens here
    const granted = await chrome.permissions.request({ origins: ["<all_urls>"] });
    await send(granted ? "watch_on" : "watch_off");
    $("watch").checked = granted;
    setStatus(granted ? "Watching for logins to save." : "All-sites access was not granted.");
  } else {
    await send("watch_off");
    setStatus("Stopped watching for logins.");
  }
});

async function initWatchToggle() {
  const { watch_logins: wanted } = await store.get("watch_logins");
  const granted = await chrome.permissions.contains({ origins: ["<all_urls>"] });
  $("watch").checked = Boolean(wanted) && granted;
}

initWatchToggle();
refresh();
