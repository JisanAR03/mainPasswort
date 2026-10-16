// The suggestion menu under a login field ([S]).
//
// An extension page that inline.js shows in an iframe inside a closed shadow
// root, so the web page around it can read none of it. It asks the service
// worker for this tab's matches with the one-time token in its URL, lists
// titles and usernames (never a password), and on your click asks the service
// worker to fill that login into the page's top frame. Without a valid token
// — a page that embedded this file itself, say — it shows nothing.

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

function button(label, detail, onClick) {
  const item = document.createElement("button");
  item.type = "button";
  item.setAttribute("role", "option");
  const title = document.createElement("span");
  title.className = "title";
  title.textContent = label;
  item.append(title);
  if (detail) {
    const sub = document.createElement("span");
    sub.className = "detail";
    sub.textContent = detail;
    item.append(sub);
  }
  item.addEventListener("click", (event) => {
    if (event.isTrusted) onClick(item);
  });
  $("menu").append(item);
  return item;
}

async function fill(login, item) {
  item.disabled = true;
  const reply = await send("menu_fill", { entryId: login.id });
  if (reply.ok) return; // the service worker closes this menu
  item.disabled = false;
  const code = reply.error ? reply.error.code : "internal";
  if (code === "url_changed") say("The page changed. Click the field again.");
  else if (code === "locked") say("The vault locked. Unlock it in the desktop app.");
  else say(`Could not fill (${code}).`);
}

async function render() {
  const reply = await send("menu_data");
  if (!reply.ok) return;
  const { state, logins, insecure } = reply.result;
  $("insecure").hidden = !insecure;
  if (state === "matches") {
    for (const login of logins) {
      button(login.title, login.username, (item) => fill(login, item));
    }
  } else if (state === "locked") {
    button("Unlock Personal Vault", "Opens the desktop app", async () => {
      await send("menu_unlock");
      say("Unlock in the desktop app, then click the field again.");
    });
  } else if (state === "not_paired") {
    say("This browser is not paired. Click the Personal Vault toolbar icon to pair it.");
  } else if (state === "app_not_running") {
    say("Start the Personal Vault desktop app to fill logins here.");
  }
}

// keyboard: arrows move between items, Escape closes the menu
document.addEventListener("keydown", (event) => {
  const items = [...document.querySelectorAll("#menu button:not(:disabled)")];
  const index = items.indexOf(document.activeElement);
  if (event.key === "ArrowDown" && items.length) {
    event.preventDefault();
    items[(index + 1) % items.length].focus();
  } else if (event.key === "ArrowUp" && items.length) {
    event.preventDefault();
    items[(index - 1 + items.length) % items.length].focus();
  } else if (event.key === "Escape") {
    send("menu_dismiss");
  }
});

window.addEventListener("focus", () => {
  const first = document.querySelector("#menu button:not(:disabled)");
  if (first && !document.activeElement.matches("#menu button")) first.focus();
});

render();
