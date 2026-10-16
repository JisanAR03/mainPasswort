// The "Save this login?" / "Update saved password?" prompt ([S]).
//
// An extension page that inline.js shows in an iframe inside a closed shadow
// root, so the web page around it can read none of it. It shows the site and
// the username of the login you just submitted — never the password, which
// stays in the service worker's memory — and nothing reaches the vault until
// you click Save or Update here.

const token = location.hash.slice(1);
const $ = (id) => document.getElementById(id);

const send = (type, extra = {}) =>
  chrome.runtime
    .sendMessage({ type, token, ...extra })
    .then((reply) => reply || { ok: false, error: { code: "internal" } })
    .catch(() => ({ ok: false, error: { code: "internal" } }));

function say(text) {
  $("message").textContent = text;
  $("message").hidden = false;
}

function busy(on) {
  for (const button of document.querySelectorAll("button")) button.disabled = on;
}

async function render() {
  const reply = await send("prompt_data");
  if (!reply.ok) {
    document.body.hidden = true;
    return;
  }
  const { kind, site, username, title, locked } = reply.result;
  $("question").textContent = kind === "update" ? "Update saved password?" : "Save this login?";
  $("site").textContent = site;
  $("username").textContent = username || "(no username)";
  $("save").textContent = kind === "update" ? `Update ${title}` : "Save";
  $("save").dataset.action = kind === "update" ? "update" : "save";
  $("message").hidden = true;
  if (locked) say("The vault is locked: unlock it in the desktop app first.");
}

async function act(action) {
  busy(true);
  const reply = await send("prompt_action", { action });
  busy(false);
  if (reply.ok) {
    if (reply.result && reply.result.already_saved) say("This login is already saved.");
    else if (action === "save") say("Saved to Personal Vault.");
    else if (action === "update") say("Password updated.");
    busy(true); // the service worker closes the prompt in a moment
    return;
  }
  const code = reply.error ? reply.error.code : "internal";
  if (code === "locked") say("Unlock the vault in the desktop app, then click again.");
  else if (code === "reclassified") await render();
  else if (code === "app_not_running") say("Start the Personal Vault desktop app, then click again.");
  else say(`Could not save (${code}).`);
}

$("save").addEventListener("click", (event) => {
  if (event.isTrusted) act($("save").dataset.action);
});
$("later").addEventListener("click", (event) => {
  if (event.isTrusted) act("dismiss");
});
$("close").addEventListener("click", (event) => {
  if (event.isTrusted) act("dismiss");
});
$("never").addEventListener("click", (event) => {
  if (event.isTrusted) act("never");
});

render();
