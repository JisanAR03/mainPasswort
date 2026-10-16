// Google Drive sync for extension-only mode ([S]). A port of
// app/src/personal_vault/sync/engine.py driven by decide.js (the desktop's
// decision table, kept identical by the parity test), so the extension
// follows the same rules: an unseen remote is never overwritten (I6), a
// download is adopted only once it decrypts (I7), only bytes the engine
// verified are uploaded (I10), and a conflict keeps both copies (ADR-006).
//
// A local change is committed to IndexedDB before any upload is tried, so an
// upload that fails never touches it. Every outcome is written to
// sync_status:<profileId> in storage.local — what failed, why, when the last
// successful upload was, and whether the latest change is only on this
// computer — and nothing fails without a status saying so.
//
// Triggers (docs/specs/sync.md): unlock, a quiet period after a save, an
// interval while unlocked, the network coming back, and "Sync now". Retries
// back off 30 s … 30 min with jitter. The service worker sleeps after ~30 s,
// so every timer is also an alarm.
import { BACKOFF_SECONDS, SYNC_INTERVAL_MINUTES, UPLOAD_QUIET_MS } from "./config.js";
import { Action, decide } from "./decide.js";
import * as drive from "./drive.js";
import * as idb from "./idb.js";
import { engine, ensureOpen, hooks, importProfile, profiles, updateProfile } from "./local.js";
import * as oauth from "./oauth.js";

const VAULT_NAME = "vault.kdbx";
const VAULT_FOLDER = "PersonalVault";
const ALARM_MIN_MS = 30 * 1000;
const JITTER_FRACTION = 0.2;

const MESSAGES = {
  off: "Not connected to Google Drive: this vault is only on this computer.",
  synced: "Synced with Google Drive.",
  waiting: "Saved on this computer; uploading in a moment.",
  syncing: "Syncing with Google Drive…",
  locked: "Locked: changes upload after you unlock.",
  offline: "Google Drive cannot be reached right now. Your change is saved on this computer.",
  server: "Google Drive had a server error. Your change is saved on this computer.",
  rate_limited: "Google Drive asked us to slow down. Your change is saved on this computer.",
  quota: "Google Drive is full, so the upload was refused. Your change is saved on this computer.",
  reconnect: "The Google sign-in needs renewing: click Connect Google Drive. Your changes are saved on this computer.",
  no_client_id: "No Google OAuth client ID is set (Settings). Your changes are saved on this computer.",
  wrong_scope: "Google did not grant Drive access. Connect again and allow it.",
  access_denied: "Google Drive refused access to the vault file.",
  conflict: "Both copies changed since the last sync: choose which one to keep.",
  missing: "The vault file is missing or in the bin on Google Drive.",
  first_link: "A vault for this profile is already on Google Drive: keep this one, or take that one.",
  unreadable: "The copy on Google Drive could not be opened with this vault's password; nothing was adopted.",
  changed: "The vault changed while syncing; trying again.",
  error: "Sync failed. Your change is saved on this computer.",
};

const statusKey = (profileId) => `sync_status:${profileId}`;
const now = () => new Date().toISOString();
const timers = new Map();
const running = new Set();

const b64 = (buffer) => {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(text);
};

async function sha256(buffer) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
  return [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// --- status ------------------------------------------------------------------

async function localOnly(profileId) {
  const [vault, state] = await Promise.all([idb.get("vaults", profileId), idb.get("sync", profileId)]);
  if (!vault) return false;
  if (!state) return true;
  return state.local_dirty === true || vault.sha256 !== state.last_synced_local_sha256;
}

export async function status(profileId) {
  const key = statusKey(profileId);
  const { [key]: stored } = await chrome.storage.local.get(key);
  return stored || null;
}

async function setStatus(profileId, state, extra = {}) {
  const key = statusKey(profileId);
  const previous = (await status(profileId)) || {};
  const next = {
    ...previous,
    state,
    message: MESSAGES[state] || MESSAGES.error,
    localOnly: await localOnly(profileId),
    lastAttemptAt: previous.lastAttemptAt || null,
    lastSuccessAt: previous.lastSuccessAt || null,
    ...extra,
  };
  await chrome.storage.local.set({ [key]: next });
  return next;
}

// --- scheduling --------------------------------------------------------------

function later(profileId, name, delayMs) {
  const id = `${name}:${profileId}`;
  clearTimeout(timers.get(id));
  timers.set(
    id,
    setTimeout(() => {
      timers.delete(id);
      runSync(profileId);
    }, delayMs),
  );
  // the worker may be gone by then: an alarm (≥ 30 s) is the fallback
  chrome.alarms.create(id, { when: Date.now() + Math.max(delayMs, ALARM_MIN_MS) });
}

function cancel(profileId, name) {
  const id = `${name}:${profileId}`;
  clearTimeout(timers.get(id));
  timers.delete(id);
  chrome.alarms.clear(id);
}

export function handleAlarm(name) {
  const match = /^(sync-due|sync-retry):(.+)$/.exec(name);
  if (match) return runSync(match[2]);
  if (name === "sync-interval") return syncUnlocked();
  return null;
}

export async function syncUnlocked() {
  const record = await ensureOpen();
  if (record) await runSync(record.profileId);
}

hooks.saved = async (profileId) => {
  const profile = await profileOf(profileId);
  if (!profile || !profile.googleEmail) {
    await setStatus(profileId, "off");
    return;
  }
  await setStatus(profileId, "waiting");
  later(profileId, "sync-due", UPLOAD_QUIET_MS);
};
hooks.unlocked = (profileId) => {
  chrome.alarms.create("sync-interval", { periodInMinutes: SYNC_INTERVAL_MINUTES });
  runSync(profileId);
};
hooks.locked = () => {
  chrome.alarms.clear("sync-interval");
};

// --- one run --------------------------------------------------------------------

class Outcome {
  constructor(state, extra = {}) {
    this.state = state;
    this.extra = extra;
  }
}

async function profileOf(profileId) {
  return (await profiles()).find((p) => p.id === profileId) || null;
}

// Runs one sync for an unlocked, connected profile and records its status.
export async function runSync(profileId, choice = null) {
  if (running.has(profileId)) return status(profileId);
  const profile = await profileOf(profileId);
  if (!profile) return null;
  if (!profile.googleEmail) return setStatus(profileId, "off");
  const record = await ensureOpen();
  if (!record || record.profileId !== profileId) return setStatus(profileId, "locked");
  running.add(profileId);
  try {
    await setStatus(profileId, "syncing", { lastAttemptAt: now() });
    const outcome = await guarded(profile, choice);
    return await finish(profileId, outcome);
  } finally {
    running.delete(profileId);
  }
}

async function finish(profileId, outcome) {
  const previous = (await status(profileId)) || {};
  if (outcome.retryable) {
    const attempt = previous.attempts || 0;
    const base = BACKOFF_SECONDS[Math.min(attempt, BACKOFF_SECONDS.length - 1)] * 1000;
    const delay = Math.round(base * (1 + Math.random() * JITTER_FRACTION));
    later(profileId, "sync-retry", delay);
    return setStatus(profileId, outcome.state, {
      ...outcome.extra,
      attempts: attempt + 1,
      nextRetryAt: new Date(Date.now() + delay).toISOString(),
    });
  }
  cancel(profileId, "sync-retry");
  const success = outcome.state === "synced";
  return setStatus(profileId, outcome.state, {
    ...outcome.extra,
    attempts: 0,
    nextRetryAt: null,
    failed: success ? null : outcome.extra.failed || null,
    ...(success ? { lastSuccessAt: now() } : {}),
  });
}

async function guarded(profile, choice) {
  const retryable = (state, failed) => Object.assign(new Outcome(state, { failed }), { retryable: true });
  let token;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      token = await oauth.accessToken(profile.id, profile.googleEmail);
      return await syncOnce(profile.id, token, choice);
    } catch (error) {
      if (error instanceof oauth.AuthError) return new Outcome(error.code, { failed: "sign-in" });
      if (error instanceof drive.DriveError) {
        if (error.code === "auth_expired" && attempt === 0) {
          await oauth.dropToken(profile.id); // refresh once, then retry (sync.md)
          continue;
        }
        if (error.code === "auth_expired") return new Outcome("reconnect", { failed: "sign-in" });
        if (error.code === "network") return retryable("offline", "network");
        if (error.retryable) return retryable(error.code, error.code);
        if (error.code === "access_denied") return new Outcome("access_denied", { failed: "access" });
        return new Outcome("error", { failed: error.code });
      }
      return new Outcome("error", { failed: "internal" });
    }
  }
  return new Outcome("reconnect", { failed: "sign-in" });
}

async function localState(profileId, state) {
  const vault = await idb.get("vaults", profileId);
  if (!vault) return { exists: false, sha256: null, md5: null, dirty: false };
  return { exists: true, sha256: vault.sha256, md5: vault.md5, dirty: Boolean(state && state.local_dirty) };
}

function remoteStateOf(remote) {
  if (!remote) return { exists: false, trashed: false, md5: null, version: null };
  return { exists: !remote.trashed, trashed: remote.trashed, md5: remote.md5, version: remote.version };
}

const decideState = (state) =>
  state
    ? {
        last_synced_remote_md5: state.last_synced_remote_md5 || null,
        last_synced_local_sha256: state.last_synced_local_sha256 || null,
      }
    : null;

async function remoteFile(token, profileId, state) {
  if (state && state.drive_file_id) {
    try {
      return await drive.metadata(token, state.drive_file_id);
    } catch (error) {
      if (error instanceof drive.DriveError && error.code === "missing") return null; // decide() asks
      throw error;
    }
  }
  return drive.findVaultFile(token, profileId);
}

async function syncOnce(profileId, token, choice) {
  const state = (await idb.get("sync", profileId)) || null;
  if (choice) return resolve(profileId, token, state, choice);
  const local = await localState(profileId, state);
  if (!local.exists) return new Outcome("error", { failed: "read" });
  const remote = await remoteFile(token, profileId, state);
  const action = decide(local, remoteStateOf(remote), decideState(state));
  switch (action) {
    case Action.NOTHING:
      if (state && state.last_error) await idb.put("sync", { ...state, last_error: null });
      return new Outcome("synced");
    case Action.UPLOAD:
      return upload(profileId, token, local, remote, state);
    case Action.UPDATE_STATE:
      await record(profileId, remote, { sha256: local.sha256 });
      return new Outcome("synced");
    case Action.DOWNLOAD:
      return download(profileId, token, remote, state);
    case Action.CONFLICT:
      return conflict(profileId, token, remote, state);
    case Action.ASK_FIRST_LINK:
      return new Outcome("first_link", { failed: "link" });
    default:
      return new Outcome("missing", { failed: "check" });
  }
}

// --- the owner's choices: conflict, first link, missing file -------------------------

async function resolve(profileId, token, state, choice) {
  const local = await localState(profileId, state);
  if (!local.exists) return new Outcome("error", { failed: "read" });
  if (choice === "keep_mine" || choice === "upload") {
    // over whatever is there: their copy stays in Drive's revision history
    // and, after a conflict, in this browser's conflict store
    const remote = await remoteFile(token, profileId, state);
    return upload(profileId, token, local, remote && !remote.trashed ? remote : null, state, {
      overwrite: true,
      linkedFrom: choice === "upload" && !state ? "upload" : undefined,
    });
  }
  if (choice === "take_theirs") {
    const kept = state && state.conflict && state.conflict.conflict_id;
    const copy = kept ? await idb.get("conflicts", kept) : null;
    if (copy) return adoptKept(profileId, token, copy, state);
    const remote = await remoteFile(token, profileId, state);
    if (!remote || remote.trashed) return new Outcome("missing", { failed: "check" });
    return download(profileId, token, remote, state, { linkedFrom: state ? undefined : "adopt" });
  }
  return new Outcome("error", { failed: "bad_choice" });
}

// Their copy, already kept here after a conflict: adopt it (it must decrypt),
// then publish it, which is how their version wins on Drive too.
async function adoptKept(profileId, token, copy, state) {
  let head = null;
  try {
    head = await remoteFile(token, profileId, state);
  } catch {
    head = null;
  }
  const reply = await engine("adopt", {
    profileId,
    bytes: b64(copy.bytes),
    sync: {
      last_synced_remote_md5: head ? head.md5 : state.last_synced_remote_md5,
      last_synced_remote_version: head ? head.version : state.last_synced_remote_version,
      local_dirty: true, // their copy still has to go up to Drive
      last_error: null,
      conflict: null,
    },
  });
  if (!reply.ok) return new Outcome("unreadable", { failed: "adopt" });
  return syncOnce(profileId, token, null);
}

// --- upload (I6, I10) -----------------------------------------------------------

async function upload(profileId, token, local, seen, state, { overwrite = false, linkedFrom } = {}) {
  const vault = await idb.get("vaults", profileId);
  if (!vault) return new Outcome("error", { failed: "read" });
  const digest = await sha256(vault.bytes);
  // I10: the bytes must be exactly the file the engine verified and recorded
  if (digest !== vault.sha256) return new Outcome("error", { failed: "verify" });
  if (digest !== local.sha256) return Object.assign(new Outcome("changed"), { retryable: true });

  let current = seen;
  if (seen && !overwrite) {
    current = await drive.metadata(token, seen.id); // immediately before uploading
    if (state && state.last_synced_remote_md5 && current.md5 !== state.last_synced_remote_md5) {
      return conflict(profileId, token, current, state);
    }
  }
  const folderId = (state && state.drive_folder_id) || (await drive.ensureFolder(token, VAULT_FOLDER));
  const uploaded = await drive.upload(token, {
    fileId: current ? current.id : null,
    name: VAULT_NAME,
    parentId: folderId,
    bytes: vault.bytes,
    profileId,
  });
  const foreign = await foreignRevision(token, uploaded, current);
  if (foreign) {
    // somebody wrote while we were uploading: their copy is kept and the owner
    // decides; their revision is still in Drive's history either way
    return conflict(profileId, token, uploaded, state, { revisionId: foreign, folderId });
  }
  await record(profileId, uploaded, { sha256: digest, folderId, linkedFrom });
  return new Outcome("synced");
}

async function foreignRevision(token, uploaded, seen) {
  if (!seen || !seen.headRevisionId) return null;
  const ids = (await drive.listRevisions(token, uploaded.id)).map((r) => r.id); // newest first
  const seenAt = ids.indexOf(seen.headRevisionId);
  if (seenAt < 0) return null; // history pruned: nothing to compare, and nothing to claim
  const newer = ids.slice(0, seenAt).filter((id) => id !== uploaded.headRevisionId);
  return newer.length ? newer[0] : null;
}

// Both files agree again: write down the versions we saw.
async function record(profileId, remote, { sha256: localSha, folderId, linkedFrom }) {
  await idb.update("sync", profileId, (state) => ({
    ...(state || { profileId }),
    profileId,
    drive_file_id: remote.id,
    drive_folder_id: folderId || (state && state.drive_folder_id) || remote.parentId,
    last_synced_remote_md5: remote.md5,
    last_synced_remote_version: remote.version,
    last_synced_local_sha256: localSha,
    local_dirty: false,
    last_success_at: now(),
    last_error: null,
    conflict: null,
    ...(linkedFrom ? { linked_from: linkedFrom } : {}),
  }));
}

// --- download and adoption (I7) ---------------------------------------------------

async function download(profileId, token, remote, state, { linkedFrom } = {}) {
  const bytes = await drive.download(token, remote.id);
  const sums = await engine("digest", { bytes: b64(bytes) });
  if (!sums.ok || (remote.md5 && sums.result.md5 !== remote.md5)) {
    return new Outcome("unreadable", { failed: "download" });
  }
  const reply = await engine("adopt", {
    profileId,
    bytes: b64(bytes),
    sync: {
      drive_file_id: remote.id,
      drive_folder_id: (state && state.drive_folder_id) || remote.parentId,
      last_synced_remote_md5: remote.md5,
      last_synced_remote_version: remote.version,
      local_dirty: false,
      last_success_at: now(),
      last_error: null,
      conflict: null,
      ...(linkedFrom ? { linked_from: linkedFrom } : {}),
    },
  });
  // I7: a file that does not open with this vault's key replaces nothing
  if (!reply.ok) return new Outcome("unreadable", { failed: "adopt" });
  return new Outcome("synced", { adopted: true });
}

// --- conflict -------------------------------------------------------------------

async function conflict(profileId, token, remote, state, { revisionId, folderId } = {}) {
  const theirs = revisionId
    ? await drive.downloadRevision(token, remote.id, revisionId)
    : await drive.download(token, remote.id);
  const keptId = await idb.addConflict(profileId, {
    bytes: theirs,
    keptAt: now(),
    remote_md5: remote.md5,
    remote_version: remote.version,
  });
  await idb.update("sync", profileId, (current) => ({
    ...(current || state || { profileId }),
    profileId,
    drive_file_id: remote.id,
    drive_folder_id: folderId || (current && current.drive_folder_id) || remote.parentId,
    last_error: "conflict",
    conflict: {
      detected_at: now(),
      remote_version: remote.version,
      remote_md5: remote.md5,
      conflict_id: keptId,
    },
  }));
  return new Outcome("conflict", { failed: "upload" });
}

// --- connect / disconnect -------------------------------------------------------

export async function connect(profileId) {
  const profile = await profileOf(profileId);
  if (!profile) return { ok: false, error: { code: "not_found" } };
  const record = await ensureOpen();
  if (!record || record.profileId !== profileId) return { ok: false, error: { code: "locked" } };
  try {
    const token = await oauth.signIn(profileId);
    const email = await drive.accountEmail(token);
    if (!email) return { ok: false, error: { code: "bad_response" } };
    await updateProfile(profileId, { googleEmail: email });
  } catch (error) {
    const code = error && error.code ? error.code : "internal";
    await setStatus(profileId, MESSAGES[code] ? code : "error", { failed: "sign-in" });
    return { ok: false, error: { code } };
  }
  return { ok: true, result: await runSync(profileId) };
}

export async function disconnect(profileId) {
  await oauth.dropToken(profileId);
  await updateProfile(profileId, { googleEmail: null });
  await idb.remove("sync", profileId); // a later connect links again (ADR-010)
  cancel(profileId, "sync-retry");
  cancel(profileId, "sync-due");
  return { ok: true, result: await setStatus(profileId, "off", { lastSuccessAt: null }) };
}

// --- open a vault that is already on Google Drive -------------------------------

const LINK_ID = "_link"; // the token used before a profile exists

// Sign in (a click on the vault page) and list the vault files this app's
// Google client can see that are not profiles here yet.
export async function listDriveVaults() {
  try {
    const token = await oauth.signIn(LINK_ID);
    const email = await drive.accountEmail(token);
    const local = new Set((await profiles()).map((p) => p.id));
    const vaults = (await drive.listVaults(token)).filter((v) => v.profileId && !local.has(v.profileId));
    return {
      ok: true,
      result: {
        email,
        vaults: vaults.map(({ id, profileId, modifiedTime }) => ({ fileId: id, profileId, modifiedTime })),
      },
    };
  } catch (error) {
    return { ok: false, error: { code: error && error.code ? error.code : "internal" } };
  }
}

// Download one of them, open it with the password given, and make it a
// profile linked to that file (ADR-010's "adopt", chosen by the owner here).
export async function openFromDrive(fileId, name, password) {
  try {
    const token = await oauth.accessToken(LINK_ID, null);
    const email = await drive.accountEmail(token);
    const remote = await drive.metadata(token, fileId);
    const listed = (await drive.listVaults(token)).find((v) => v.id === fileId);
    if (!listed || !listed.profileId || remote.trashed) return { ok: false, error: { code: "missing" } };
    const bytes = await drive.download(token, fileId);
    const sums = await engine("digest", { bytes: b64(bytes) });
    if (!sums.ok || (remote.md5 && sums.result.md5 !== remote.md5)) {
      return { ok: false, error: { code: "unreadable" } };
    }
    // read before importing: the import locks, and a lock drops every token
    const linkKey = `drive_token:${LINK_ID}`;
    const { [linkKey]: linked } = await chrome.storage.session.get(linkKey);
    const reply = await importProfile({
      profileId: listed.profileId,
      name,
      password,
      bytes: b64(bytes),
      googleEmail: email,
      sync: {
        drive_file_id: remote.id,
        drive_folder_id: remote.parentId,
        last_synced_remote_md5: remote.md5,
        last_synced_remote_version: remote.version,
        last_success_at: now(),
        last_error: null,
        conflict: null,
        linked_from: "adopt",
      },
    });
    if (!reply.ok) return reply;
    // the sign-in now belongs to the profile
    if (linked) await chrome.storage.session.set({ [`drive_token:${listed.profileId}`]: linked });
    await oauth.dropToken(LINK_ID);
    await setStatus(listed.profileId, "synced", { lastSuccessAt: now(), attempts: 0 });
    return reply;
  } catch (error) {
    return { ok: false, error: { code: error && error.code ? error.code : "internal" } };
  }
}

export async function choose(profileId, choice) {
  if (!["keep_mine", "take_theirs", "upload"].includes(choice)) {
    return { ok: false, error: { code: "bad_request" } };
  }
  return { ok: true, result: await runSync(profileId, choice) };
}
