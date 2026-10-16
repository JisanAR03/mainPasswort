// Extension-only mode, service-worker side ([S]): profiles, unlock and lock,
// and the vault requests the desktop app would otherwise answer over native
// messaging — answered here by the offscreen vault engine (engine.js).
//
// Where the key lives (ADR-012, invariant I11): an unlock keeps exactly one
// record in chrome.storage.session —
//   unlocked = { profileId, passwordHash, unlockedAt, expiresAt }
// where passwordHash is SHA-256(master password), the KDBX password hash
// (password-equivalent for that vault; the password itself is never kept).
// storage.session is memory only, unreadable by content scripts, and cleared
// by the browser when it closes or the extension is reloaded, updated or
// disabled. expiresAt is unlockedAt + UNLOCK_HOURS, checked on every request
// and enforced by an alarm. Lock removes it, the Drive token and every menu
// session (they hold titles and usernames), and closes the engine's copy.
import { UNLOCK_HOURS } from "./config.js";
import { generatePassword } from "./generator.js";
import * as idb from "./idb.js";

const OFFSCREEN_URL = "offscreen.html";
const MIN_PASSWORD_LENGTH = 12;
const MAX_NAME_LENGTH = 100;
const UNLOCK_MS = UNLOCK_HOURS * 60 * 60 * 1000;

// Set by sync.js, so this module does not import it.
export const hooks = { saved: () => {}, unlocked: () => {}, locked: () => {} };

const fail = (code) => ({ ok: false, error: { code } });

// --- the offscreen engine ---------------------------------------------------------

let creating = null;

async function engineExists() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)],
  });
  return contexts.length > 0;
}

async function ensureEngine() {
  if (await engineExists()) return;
  if (!creating) {
    creating = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_URL,
        reasons: ["DOM_PARSER"],
        justification: "Reads and writes the encrypted KDBX vault with the browser's XML parser.",
      })
      .catch(async (error) => {
        if (!(await engineExists())) throw error; // another call made it first
      })
      .finally(() => {
        creating = null;
      });
  }
  await creating;
}

export async function engine(op, args = {}) {
  try {
    await ensureEngine();
    const reply = await chrome.runtime.sendMessage({ target: "engine", op, args });
    return reply || fail("internal");
  } catch {
    return fail("internal");
  }
}

// --- mode and profiles ------------------------------------------------------------

export async function mode() {
  const { mode: value } = await chrome.storage.local.get("mode");
  return value === "extension" ? "extension" : "desktop";
}

export async function setMode(value) {
  if (value !== "extension" && value !== "desktop") return fail("bad_request");
  if (value === "desktop") await lock();
  await chrome.storage.local.set({ mode: value });
  return { ok: true, result: { mode: value } };
}

export async function profiles() {
  const { profiles: list } = await chrome.storage.local.get("profiles");
  return Array.isArray(list) ? list : [];
}

async function saveProfiles(list) {
  await chrome.storage.local.set({ profiles: list });
}

export async function updateProfile(profileId, change) {
  const list = await profiles();
  const index = list.findIndex((p) => p.id === profileId);
  if (index < 0) return null;
  list[index] = { ...list[index], ...change };
  await saveProfiles(list);
  return list[index];
}

// The desktop format, "p_" + 6 random bytes in URL-safe base64, so a profile
// linked to a desktop vault can keep that vault's pm_profile_id.
function newProfileId() {
  const raw = crypto.getRandomValues(new Uint8Array(6));
  const b64 = btoa(String.fromCharCode(...raw)).replace(/\+/g, "-").replace(/\//g, "_");
  return `p_${b64.replace(/=+$/, "")}`;
}

const validName = (name) =>
  typeof name === "string" && name.trim().length >= 1 && name.trim().length <= MAX_NAME_LENGTH;

export async function createProfile(name, password) {
  if (!validName(name)) return fail("invalid_name");
  if (typeof password !== "string" || password.length < MIN_PASSWORD_LENGTH) {
    return fail("password_too_short");
  }
  await lock(); // one profile unlocked at a time
  const id = newProfileId();
  const reply = await engine("create", { profileId: id, password });
  if (!reply.ok) return reply;
  const list = await profiles();
  list.push({ id, name: name.trim(), createdAt: new Date().toISOString(), googleEmail: null });
  await saveProfiles(list);
  await remember(id, reply.result.passwordHash);
  return { ok: true, result: { profileId: id } };
}

// A vault that already exists elsewhere (Google Drive) becomes a profile here,
// keeping its own profile id so both sides keep finding the same Drive file.
const PROFILE_ID = /^p_[A-Za-z0-9_-]{1,32}$/;

export async function importProfile({ profileId, name, password, bytes, sync, googleEmail }) {
  if (typeof profileId !== "string" || !PROFILE_ID.test(profileId)) return fail("bad_profile_id");
  if (!validName(name)) return fail("invalid_name");
  if ((await profiles()).some((p) => p.id === profileId)) return fail("exists");
  await lock();
  const reply = await engine("import", { profileId, bytes, password, sync });
  if (!reply.ok) return reply;
  const list = await profiles();
  list.push({ id: profileId, name: name.trim(), createdAt: new Date().toISOString(), googleEmail });
  await saveProfiles(list);
  await remember(profileId, reply.result.passwordHash);
  return { ok: true, result: { profileId } };
}

export async function renameProfile(profileId, name) {
  if (!validName(name)) return fail("invalid_name");
  const updated = await updateProfile(profileId, { name: name.trim() });
  return updated ? { ok: true, result: {} } : fail("not_found");
}

// Deleting a profile deletes its vault, backups and sync state from this
// browser — the caller must send the profile's name back as confirmation.
export async function deleteProfile(profileId, confirmName) {
  const list = await profiles();
  const profile = list.find((p) => p.id === profileId);
  if (!profile) return fail("not_found");
  if (confirmName !== profile.name) return fail("confirmation_mismatch");
  const record = await unlockedRecord();
  if (record && record.profileId === profileId) await lock();
  await idb.deleteProfileData(profileId);
  await chrome.storage.session.remove(`drive_token:${profileId}`);
  await chrome.storage.local.remove(`sync_status:${profileId}`);
  await saveProfiles(list.filter((p) => p.id !== profileId));
  return { ok: true, result: {} };
}

// --- unlock and lock --------------------------------------------------------------

async function remember(profileId, passwordHash) {
  const now = Date.now();
  await chrome.storage.session.set({
    unlocked: { profileId, passwordHash, unlockedAt: now, expiresAt: now + UNLOCK_MS },
  });
  await chrome.storage.local.set({ last_profile_id: profileId });
  await chrome.alarms.create("unlock-expiry", { when: now + UNLOCK_MS });
  hooks.unlocked(profileId);
}

// The current unlock, or null; an expired one is locked on the spot.
export async function unlockedRecord() {
  const { unlocked } = await chrome.storage.session.get("unlocked");
  if (!unlocked) return null;
  if (typeof unlocked.expiresAt !== "number" || Date.now() >= unlocked.expiresAt) {
    await lock();
    return null;
  }
  return unlocked;
}

// The unlocked profile, with its vault open in the engine (reopened from the
// session key if the engine document was closed meanwhile), or null.
export async function ensureOpen() {
  const record = await unlockedRecord();
  if (!record) return null;
  const status = await engine("status");
  if (status.ok && status.result.profileId === record.profileId) return record;
  const reopened = await engine("open", {
    profileId: record.profileId,
    passwordHash: record.passwordHash,
  });
  if (!reopened.ok) {
    await lock();
    return null;
  }
  return record;
}

export async function unlock(profileId, password) {
  if (!(await profiles()).some((p) => p.id === profileId)) return fail("not_found");
  if (typeof password !== "string" || !password) return fail("bad_password");
  await lock();
  const reply = await engine("open", { profileId, password });
  if (!reply.ok) return reply;
  await remember(profileId, reply.result.passwordHash);
  return { ok: true, result: { profileId } };
}

export async function lock() {
  const stored = await chrome.storage.session.get(null);
  const keys = Object.keys(stored).filter(
    (key) => key === "unlocked" || key.startsWith("drive_token:") || key.startsWith("menu_"),
  );
  if (keys.length) await chrome.storage.session.remove(keys);
  await chrome.alarms.clear("unlock-expiry");
  if (await engineExists()) await engine("close");
  hooks.locked();
}

// --- what the desktop app answers over native messaging -----------------------------

async function profileName(profileId) {
  const profile = (await profiles()).find((p) => p.id === profileId);
  return profile ? profile.name : "";
}

async function showUnlock() {
  try {
    await chrome.action.openPopup();
  } catch {
    await chrome.tabs.create({ url: chrome.runtime.getURL("vault.html#unlock") });
  }
  return { ok: true, result: { shown: true } };
}

export async function localRequest(type, payload = {}) {
  switch (type) {
    case "hello": {
      const record = await unlockedRecord();
      const { last_profile_id: last } = await chrome.storage.local.get("last_profile_id");
      return {
        ok: true,
        result: {
          app_version: chrome.runtime.getManifest().version,
          state: record ? "unlocked" : "locked",
          profile_name: await profileName(record ? record.profileId : last),
          mode: "extension",
        },
      };
    }
    case "get_logins": {
      if (!(await ensureOpen())) return fail("locked");
      const reply = await engine("matches", { url: payload.url });
      if (!reply.ok) return reply;
      if (reply.result.logins.length === 0) return fail("no_match");
      return { ok: true, result: { logins: reply.result.logins.slice(0, 20) } };
    }
    case "get_secret": {
      if (!(await ensureOpen())) return fail("locked");
      return engine("secret", { entryId: payload.entry_id, url: payload.url });
    }
    case "save_login": {
      const record = await ensureOpen();
      if (!record) return fail("locked");
      const reply = await engine("save_login", {
        url: payload.url,
        username: payload.username,
        password: payload.password,
        title: payload.title,
      });
      if (reply.ok) hooks.saved(record.profileId);
      return reply.ok ? { ok: true, result: { entry_id: reply.result.id } } : reply;
    }
    case "update_password": {
      const record = await ensureOpen();
      if (!record) return fail("locked");
      const reply = await engine("update_password", {
        entryId: payload.entry_id,
        url: payload.url,
        newPassword: payload.new_password,
      });
      if (reply.ok) hooks.saved(record.profileId);
      return reply.ok ? { ok: true, result: { entry_id: payload.entry_id } } : reply;
    }
    case "generate_password":
      return { ok: true, result: { password: generatePassword({ length: payload.length || 20 }) } };
    case "lock":
      await lock();
      return { ok: true, result: {} };
    case "show_unlock":
      return showUnlock();
    default:
      return fail("bad_request"); // pairing has no meaning without the desktop app
  }
}

// --- the vault page's own requests (vault.html) --------------------------------------

export async function vaultOp(op, args) {
  const record = await ensureOpen();
  if (!record) return fail("locked");
  const reply = await engine(op, args);
  if (reply.ok && ["add", "edit", "delete"].includes(op)) hooks.saved(record.profileId);
  return reply;
}
