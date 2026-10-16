// The service worker ([S]): owns the native port, reads tab URLs itself (a
// page never supplies one), and runs every fill and every save. It holds a
// password only while it uses it: for the executeScript call that fills it,
// and — for a login you just submitted — in session storage (memory only,
// unreadable by content scripts) until you answer the prompt or two minutes
// pass.
//
// Each message is accepted by where it comes from, as the browser reports it
// (the MessageSender), never by what the message claims:
// - the toolbar popup (popup.html): status, pairing, list, fill, add, lock;
// - content scripts in the top frame of an http(s) tab: menu_open/close,
//   prompt_open, login_submitted, username_submitted — none of them is ever
//   answered with a title, a username or a password;
// - the menu and prompt frames (menu.html, prompt.html) inside a tab: their
//   own requests, each tied to a one-time token handed out for that tab;
// - the vault page (vault.html) and the popup, for extension-only mode's
//   profiles, entries, settings and sync (ext_* messages);
// - the offscreen vault engine (offscreen.html), only to say the network is back.
//
// Two modes (ADR-012): "desktop" sends every vault request to the desktop app
// over native messaging, as before; "extension" answers it from the vault the
// extension holds itself (local.js, engine.js). vaultRequest() is the switch.
import { browserName, nativeRequest, newPairingKey, store } from "./api.js";
import { fillLogin } from "./fill.js";
import * as local from "./local.js";
import * as sync from "./sync.js";

const SAVE_TTL_MS = 2 * 60 * 1000;
const USERNAME_STEP_TTL_MS = 5 * 60 * 1000;
const SEEN_TTL_MS = 10 * 1000;
const PROMPT_CLOSE_DELAY_MS = 1500;
const MAX_USERNAME = 500;
const MAX_PASSWORD = 4096;
const MAX_NEVER_SITES = 500;
const MENU_HEADER_PX = 30;
const MENU_ROW_PX = 46;
const MENU_WARNING_PX = 34;
const MENU_VISIBLE_ROWS = 5;
const LEGACY_DETECT_ID = "detect-submits";

const fail = (code) => ({ ok: false, error: { code } });

async function vaultRequest(type, payload) {
  return (await local.mode()) === "extension"
    ? local.localRequest(type, payload)
    : nativeRequest(type, payload);
}
const pageUrl = (name) => chrome.runtime.getURL(name);

// Before the content scripts were declared in the manifest, the detector was
// registered on demand under this id; drop that registration so a page never
// gets the detector twice.
chrome.scripting.unregisterContentScripts({ ids: [LEGACY_DETECT_ID] }).catch(() => {});

// --- where a message comes from ---------------------------------------------

function fromPage(sender) {
  return (
    sender.id === chrome.runtime.id &&
    Boolean(sender.tab) &&
    sender.frameId === 0 &&
    typeof sender.url === "string" &&
    /^https?:\/\//.test(sender.url)
  );
}

function fromExtensionPage(sender, name) {
  if (sender.id !== chrome.runtime.id || typeof sender.url !== "string") return false;
  return sender.url.split("#")[0].split("?")[0] === pageUrl(name);
}

// --- small helpers -----------------------------------------------------------

function newToken() {
  const raw = crypto.getRandomValues(new Uint8Array(16));
  return [...raw].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isLoopback(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

// Plain http to another machine: logins there are never offered for saving,
// and an http entry fills only with a warning (data-model.md, rule 4).
function plainHttp(url) {
  const parsed = new URL(url);
  return parsed.protocol === "http:" && !isLoopback(parsed.hostname);
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function tellTab(tabId, message) {
  chrome.tabs.sendMessage(tabId, message, { frameId: 0 }).catch(() => {});
}

async function targetTab() {
  const tabs = await chrome.tabs.query({});
  const web = tabs.filter((tab) => tab.url && /^https?:/.test(tab.url));
  return (
    web.find((tab) => tab.active) ||
    web.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0] ||
    null
  );
}

// The vault's answer for one page URL: its matches, or why there are none.
async function loginsFor(url) {
  const reply = await vaultRequest("get_logins", { url });
  if (reply.ok) return { state: "matches", logins: reply.result.logins };
  const code = reply.error ? reply.error.code : "internal";
  if (code === "no_match") return { state: "none", logins: [] };
  if (code === "locked" || code === "not_paired" || code === "app_not_running") {
    return { state: code, logins: [] };
  }
  return { state: "error", logins: [] };
}

// Fill one login into the tab's top frame. With a documentId the script runs
// only in that exact document, so a navigation since the menu opened means no
// fill rather than a fill into whatever page loaded since.
async function fillInto(tabId, documentId, entryId, url) {
  const reply = await vaultRequest("get_secret", { entry_id: entryId, url });
  if (!reply.ok) return reply;
  const { username, password } = reply.result;
  const target = documentId ? { tabId, documentIds: [documentId] } : { tabId, frameIds: [0] };
  try {
    const [outcome] = await chrome.scripting.executeScript({
      target,
      func: fillLogin,
      args: [username, password],
    });
    return { ok: true, result: outcome.result };
  } catch {
    return fail("url_changed");
  }
}

// --- the suggestion menu -------------------------------------------------------

const menuKey = (tabId) => `menu_${tabId}`;

async function menuSession(sender, token) {
  if (!sender.tab || typeof token !== "string" || !token) return null;
  const key = menuKey(sender.tab.id);
  const { [key]: session } = await store.sessionGet(key);
  return session && session.token === token ? session : null;
}

async function closeMenu(tabId) {
  await store.sessionRemove(menuKey(tabId));
  tellTab(tabId, { type: "menu_close" });
}

async function openMenu(message, sender) {
  const url = sender.url;
  const { state, logins } = await loginsFor(url);
  // locked / unpaired / app-not-running are worth saying on a password field
  // (or next to one), never on every username-looking field of the web
  const loginContext = message.field === "password" || message.password_nearby === true;
  const show =
    state === "matches" ||
    (loginContext && (state === "locked" || state === "not_paired" || state === "app_not_running"));
  if (!show) return { show: false };
  const insecure = plainHttp(url);
  const token = newToken();
  await store.sessionSet({
    [menuKey(sender.tab.id)]: { token, url, documentId: sender.documentId, state, logins, insecure },
  });
  let height = MENU_HEADER_PX + (insecure ? MENU_WARNING_PX : 0);
  if (state === "matches") height += Math.min(logins.length, MENU_VISIBLE_ROWS) * MENU_ROW_PX;
  else if (state === "locked") height += MENU_ROW_PX + 48;
  else height += 60;
  return { show: true, token, height };
}

async function handleMenu(message, sender) {
  const session = await menuSession(sender, message.token);
  if (!session) return fail("bad_request");
  const tabId = sender.tab.id;
  switch (message.type) {
    case "menu_data":
      return {
        ok: true,
        result: { state: session.state, logins: session.logins, insecure: session.insecure },
      };
    case "menu_fill": {
      const login = session.logins.find((candidate) => candidate.id === message.entryId);
      if (!login) return fail("bad_request");
      const tab = await chrome.tabs.get(tabId);
      if (tab.url !== session.url) return fail("url_changed");
      const reply = await fillInto(tabId, session.documentId, login.id, session.url);
      if (reply.ok) await closeMenu(tabId);
      return reply;
    }
    case "menu_unlock":
      return vaultRequest("show_unlock", {});
    case "menu_dismiss":
      await closeMenu(tabId);
      return { ok: true };
    default:
      return fail("bad_request");
  }
}

// --- logins to save --------------------------------------------------------------

async function pendingCandidate() {
  const { pending_save: candidate } = await store.sessionGet("pending_save");
  if (!candidate) return null;
  if (Date.now() - candidate.at > SAVE_TTL_MS) {
    await clearCandidate(candidate);
    return null;
  }
  return candidate;
}

async function clearCandidate(candidate, closeDelayMs = 0) {
  await store.sessionRemove("pending_save");
  await chrome.action.setBadgeText({ text: "" });
  if (!candidate) return;
  const close = () => tellTab(candidate.tabId, { type: "prompt_close" });
  if (closeDelayMs) setTimeout(close, closeDelayMs);
  else close();
}

async function offeringSaves(origin) {
  const { offer_to_save: offer, never_save: never } = await store.get(["offer_to_save", "never_save"]);
  return offer !== false && !(never || []).includes(origin);
}

// Is the submitted login new, a changed password for a saved account, or the
// one already saved? The stored password is fetched only to compare, and
// dropped straight after.
async function classify(candidate) {
  const found = await loginsFor(candidate.url);
  if (found.state === "locked") return { kind: "save", locked: true };
  if (found.state === "none") return { kind: "save", locked: false };
  if (found.state !== "matches") return { kind: "none" }; // no app or not paired: nowhere to save
  const wanted = candidate.username.trim().toLowerCase();
  const account = found.logins.find((login) => login.username.trim().toLowerCase() === wanted);
  if (!account) return { kind: "save", locked: false };
  const secret = await vaultRequest("get_secret", { entry_id: account.id, url: candidate.url });
  if (secret.ok && secret.result.password === candidate.password) return { kind: "same" };
  return { kind: "update", locked: false, entryId: account.id, title: account.title };
}

async function rememberedUsername(tabId, origin) {
  const { username_step: step } = await store.sessionGet("username_step");
  if (!step || step.tabId !== tabId || step.origin !== origin) return "";
  return Date.now() - step.at <= USERNAME_STEP_TTL_MS ? step.username : "";
}

async function loginSubmitted(message, sender) {
  const { username, password } = message;
  if (typeof password !== "string" || !password || password.length > MAX_PASSWORD) {
    return fail("bad_request");
  }
  if (typeof username !== "string" || username.length > MAX_USERNAME) return fail("bad_request");
  const origin = new URL(sender.url).origin;
  if (plainHttp(sender.url) || !(await offeringSaves(origin))) return { ok: true };
  const tabId = sender.tab.id;
  const account = username || (await rememberedUsername(tabId, origin));

  // one login usually arrives two or three times (the click, the Enter, the
  // submit it caused): look at it once
  const seenKey = await sha256Hex(`${tabId}\n${origin}\n${account}\n${password}`);
  const { login_seen: seen } = await store.sessionGet("login_seen");
  if (seen && seen.key === seenKey && Date.now() - seen.at < SEEN_TTL_MS) return { ok: true };
  await store.sessionSet({ login_seen: { key: seenKey, at: Date.now() } });

  const candidate = { tabId, origin, url: `${origin}/`, username: account, password, at: Date.now() };
  const verdict = await classify(candidate);
  if (verdict.kind === "same" || verdict.kind === "none") return { ok: true };
  const pending = { ...candidate, ...verdict, token: newToken() };
  await store.sessionSet({ pending_save: pending });
  await store.sessionRemove("username_step");
  await chrome.action.setBadgeText({ text: "1" });
  await chrome.action.setBadgeBackgroundColor({ color: "#2f6f4f" });
  tellTab(tabId, { type: "prompt_show", token: pending.token });
  return { ok: true };
}

// Logins arrive in bursts (see above); handling them one at a time keeps the
// "seen" check honest.
let submitted = Promise.resolve();
function queueLoginSubmitted(message, sender) {
  const result = submitted.then(() => loginSubmitted(message, sender));
  submitted = result.catch(() => {});
  return result;
}

// Save, update, dismiss or "never" for the pending login; shared by the
// in-page prompt and the toolbar popup.
async function resolveCandidate(candidate, action) {
  if (action === "dismiss") {
    await clearCandidate(candidate);
    return { ok: true, result: {} };
  }
  if (action === "never") {
    const { never_save: never = [] } = await store.get("never_save");
    if (!never.includes(candidate.origin)) {
      await store.set({ never_save: [...never, candidate.origin].slice(-MAX_NEVER_SITES) });
    }
    await clearCandidate(candidate);
    return { ok: true, result: {} };
  }
  if (action !== "save" && action !== "update") return fail("bad_request");

  let current = candidate;
  if (candidate.locked) {
    // the vault was locked when you submitted: look again now
    const verdict = await classify(candidate);
    if (verdict.kind === "none") return fail("app_not_running");
    if (verdict.locked) {
      await vaultRequest("show_unlock", {});
      return fail("locked");
    }
    if (verdict.kind === "same") {
      await clearCandidate(candidate, PROMPT_CLOSE_DELAY_MS);
      return { ok: true, result: { already_saved: true } };
    }
    current = { ...candidate, ...verdict };
    await store.sessionSet({ pending_save: current });
  }
  if (action !== current.kind) return fail("reclassified");

  const host = new URL(current.origin).host;
  const reply =
    action === "save"
      ? await vaultRequest("save_login", {
          url: current.url,
          username: current.username,
          password: current.password,
          title: host,
        })
      : await vaultRequest("update_password", {
          entry_id: current.entryId,
          url: current.url,
          new_password: current.password,
        });
  if (!reply.ok) {
    if (reply.error && reply.error.code === "locked") await vaultRequest("show_unlock", {});
    return reply;
  }
  await clearCandidate(current, PROMPT_CLOSE_DELAY_MS);
  return { ok: true, result: {} };
}

async function promptCandidate(sender, token) {
  const candidate = await pendingCandidate();
  if (!candidate || !sender.tab || candidate.tabId !== sender.tab.id) return null;
  return typeof token === "string" && token === candidate.token ? candidate : null;
}

function candidateSummary(candidate) {
  return {
    kind: candidate.kind,
    site: new URL(candidate.origin).host,
    username: candidate.username,
    title: candidate.title || "",
    locked: Boolean(candidate.locked),
  };
}

// --- handlers by sender -----------------------------------------------------------

async function handlePage(message, sender) {
  switch (message.type) {
    case "menu_open":
      return openMenu(message, sender);
    case "menu_close": {
      const session = await menuSession(sender, message.token);
      if (session) await store.sessionRemove(menuKey(sender.tab.id));
      return { ok: true };
    }
    case "prompt_open": {
      const candidate = await pendingCandidate();
      if (!candidate || candidate.tabId !== sender.tab.id) return { show: false };
      return { show: true, token: candidate.token };
    }
    case "login_submitted":
      return queueLoginSubmitted(message, sender);
    case "username_submitted": {
      const { username } = message;
      if (typeof username !== "string" || !username || username.length > MAX_USERNAME) {
        return fail("bad_request");
      }
      const origin = new URL(sender.url).origin;
      await store.sessionSet({
        username_step: { tabId: sender.tab.id, origin, username, at: Date.now() },
      });
      return { ok: true };
    }
    default:
      return fail("bad_request");
  }
}

async function handlePrompt(message, sender) {
  const candidate = await promptCandidate(sender, message.token);
  if (!candidate) return fail("bad_request");
  if (message.type === "prompt_data") return { ok: true, result: candidateSummary(candidate) };
  if (message.type === "prompt_action") return resolveCandidate(candidate, message.action);
  return fail("bad_request");
}

async function handlePopup(message) {
  switch (message.type) {
    case "status":
      return vaultRequest("hello", {
        extension_version: chrome.runtime.getManifest().version,
      });

    case "pair": {
      // the popup makes the key (it shows the code derived from it first); a
      // caller that sends none gets a fresh one here
      const key = message.key || newPairingKey();
      const reply = await nativeRequest("pair_request", {
        key,
        browser_name: browserName(),
      });
      if (reply.ok && reply.result && reply.result.paired) {
        await store.set({ pairing_key: key });
      }
      return reply;
    }

    case "get_logins": {
      const tab = await targetTab();
      if (!tab) return fail("no_tab");
      const reply = await vaultRequest("get_logins", { url: tab.url });
      return { ...reply, tab_url: tab.url };
    }

    case "fill": {
      const tab = await targetTab();
      if (!tab || tab.url !== message.url) {
        // the page changed between listing and clicking: never fill
        return fail("url_changed");
      }
      return fillInto(tab.id, null, message.entryId, message.url);
    }

    case "lock":
      return vaultRequest("lock", {});

    case "unlock":
      return vaultRequest("show_unlock", {});

    case "save_login":
      return vaultRequest("save_login", {
        url: message.url,
        username: message.username,
        password: message.password,
        title: message.title || null,
      });

    case "generate":
      return vaultRequest("generate_password", {});

    case "pending_save": {
      const candidate = await pendingCandidate();
      return { ok: true, result: candidate ? candidateSummary(candidate) : null };
    }

    case "resolve_save": {
      const candidate = await pendingCandidate();
      if (!candidate) return fail("no_candidate");
      return resolveCandidate(candidate, message.action);
    }

    case "set_offer_to_save":
      await store.set({ offer_to_save: message.value === true });
      return { ok: true };

    default:
      return fail("bad_request");
  }
}

const POPUP_TYPES = new Set([
  "status",
  "pair",
  "get_logins",
  "fill",
  "lock",
  "unlock",
  "save_login",
  "generate",
  "pending_save",
  "resolve_save",
  "set_offer_to_save",
]);
const PAGE_TYPES = new Set([
  "menu_open",
  "menu_close",
  "prompt_open",
  "login_submitted",
  "username_submitted",
]);
const MENU_TYPES = new Set(["menu_data", "menu_fill", "menu_unlock", "menu_dismiss"]);
const EXT_TYPES = new Set([
  "ext_state",
  "ext_set_mode",
  "ext_create_profile",
  "ext_rename_profile",
  "ext_delete_profile",
  "ext_unlock",
  "ext_lock",
  "ext_list",
  "ext_get",
  "ext_save_entry",
  "ext_delete_entry",
  "ext_generate",
  "ext_export",
  "ext_settings",
  "ext_connect",
  "ext_disconnect",
  "ext_sync_now",
  "ext_choose",
  "ext_drive_list",
  "ext_drive_open",
]);
const PROMPT_TYPES = new Set(["prompt_data", "prompt_action"]);

// --- extension-only mode: the vault page and the popup ----------------------------

const IDLE_PERMISSION = { permissions: ["idle"] };

async function extState() {
  const profiles = await local.profiles();
  const record = await local.unlockedRecord();
  const { settings = {}, last_profile_id: lastProfileId } = await chrome.storage.local.get([
    "settings",
    "last_profile_id",
  ]);
  const statuses = {};
  for (const profile of profiles) statuses[profile.id] = await sync.status(profile.id);
  return {
    ok: true,
    result: {
      mode: await local.mode(),
      // names and linked accounts only — never anything from inside a vault
      profiles: profiles.map(({ id, name, googleEmail }) => ({ id, name, googleEmail })),
      unlocked: record ? { profileId: record.profileId, expiresAt: record.expiresAt } : null,
      lastProfileId: lastProfileId || null,
      settings: {
        googleClientId: settings.googleClientId || "",
        lockOnScreenLock: settings.lockOnScreenLock === true,
      },
      redirectUrl: chrome.identity.getRedirectURL(),
      statuses,
    },
  };
}

async function unlockedProfileId() {
  const record = await local.unlockedRecord();
  return record ? record.profileId : null;
}

async function handleExt(message) {
  const args = message.args || {};
  switch (message.type) {
    case "ext_state":
      return extState();
    case "ext_set_mode":
      return local.setMode(args.mode);
    case "ext_create_profile":
      return local.createProfile(args.name, args.password);
    case "ext_rename_profile":
      return local.renameProfile(args.profileId, args.name);
    case "ext_delete_profile":
      return local.deleteProfile(args.profileId, args.confirmName);
    case "ext_unlock":
      return local.unlock(args.profileId, args.password);
    case "ext_lock":
      await local.lock();
      return { ok: true, result: {} };
    case "ext_list":
      return local.vaultOp("list", { query: args.query || "" });
    case "ext_get":
      return local.vaultOp("get", { entryId: args.entryId });
    case "ext_save_entry":
      return local.vaultOp(args.entry && args.entry.id ? "edit" : "add", { entry: args.entry });
    case "ext_delete_entry":
      return local.vaultOp("delete", { entryId: args.entryId });
    case "ext_generate":
      return local.localRequest("generate_password", { length: args.length });
    case "ext_export":
      return local.vaultOp("export", {});
    case "ext_settings": {
      const { settings = {} } = await store.get("settings");
      const next = { ...settings };
      if (typeof args.googleClientId === "string") next.googleClientId = args.googleClientId.trim();
      if (typeof args.lockOnScreenLock === "boolean") next.lockOnScreenLock = args.lockOnScreenLock;
      await store.set({ settings: next });
      await watchIdle();
      return { ok: true, result: {} };
    }
    case "ext_connect": {
      const profileId = await unlockedProfileId();
      return profileId ? sync.connect(profileId) : fail("locked");
    }
    case "ext_disconnect": {
      const profileId = await unlockedProfileId();
      return profileId ? sync.disconnect(profileId) : fail("locked");
    }
    case "ext_sync_now": {
      const profileId = await unlockedProfileId();
      return profileId ? { ok: true, result: await sync.runSync(profileId) } : fail("locked");
    }
    case "ext_choose": {
      const profileId = await unlockedProfileId();
      return profileId ? sync.choose(profileId, args.choice) : fail("locked");
    }
    case "ext_drive_list":
      return sync.listDriveVaults();
    case "ext_drive_open":
      return sync.openFromDrive(args.fileId, args.name, args.password);
    default:
      return fail("bad_request");
  }
}

// Lock when the OS locks the screen — only if the owner turned it on and
// granted the optional "idle" permission.
function onIdleState(state) {
  if (state === "locked") vaultRequest("lock", {});
}

async function watchIdle() {
  if (!chrome.idle) return;
  const { settings = {} } = await store.get("settings");
  const wanted = settings.lockOnScreenLock === true;
  const granted = await chrome.permissions.contains(IDLE_PERMISSION);
  chrome.idle.onStateChanged.removeListener(onIdleState);
  if (wanted && granted) chrome.idle.onStateChanged.addListener(onIdleState);
}
watchIdle();
chrome.permissions.onAdded.addListener(watchIdle);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "unlock-expiry") local.lock();
  else sync.handleAlarm(alarm.name);
});

// The lock shortcut works in both modes.
chrome.commands.onCommand.addListener((command) => {
  if (command === "lock-vault") vaultRequest("lock", {});
});

async function route(message, sender) {
  if (!message || typeof message.type !== "string") return fail("bad_request");
  const { type } = message;
  if (EXT_TYPES.has(type) && (fromExtensionPage(sender, "vault.html") || fromExtensionPage(sender, "popup.html"))) {
    return handleExt(message);
  }
  if (type === "engine_online" && fromExtensionPage(sender, "offscreen.html")) {
    await sync.syncUnlocked();
    return { ok: true };
  }
  if (POPUP_TYPES.has(type) && fromExtensionPage(sender, "popup.html")) return handlePopup(message);
  if (PAGE_TYPES.has(type) && fromPage(sender)) return handlePage(message, sender);
  if (MENU_TYPES.has(type) && sender.tab && fromExtensionPage(sender, "menu.html")) {
    return handleMenu(message, sender);
  }
  if (PROMPT_TYPES.has(type) && sender.tab && fromExtensionPage(sender, "prompt.html")) {
    return handlePrompt(message, sender);
  }
  return fail("bad_request");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.target === "engine") return false; // for the offscreen engine, not us
  route(message, sender).then(sendResponse, () => sendResponse(fail("internal")));
  return true; // keep the channel open for the async reply
});
