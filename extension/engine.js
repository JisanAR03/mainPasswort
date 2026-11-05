// The vault engine for extension-only mode ([S]). It runs in the offscreen
// document (offscreen.html), where the browser's own XML parser exists — so
// kdbxweb never needs the vulnerable xmldom fallback, which is not shipped.
//
// It is the only code that reads or writes KDBX: kdbxweb (vendored, pinned)
// for the format and the cipher, hash-wasm for Argon2id and MD5, WebCrypto
// for SHA-256 and randomness. No cryptography of our own.
//
// It answers the service worker only (sender checked), one request at a time.
// It holds at most one open vault — the unlocked profile's — and keeps no
// password: an unlock hands back SHA-256(password), the KDBX password hash,
// which the service worker keeps in storage.session for the unlock's lifetime
// and hands back when the engine has to reopen the vault. Nothing here writes
// a plaintext field anywhere: IndexedDB gets the encrypted file only.
/* global kdbxweb, hashwasm */
import {
  CLIPBOARD_CLEAR_MS,
  KDF_MEMORY_MIB,
  KDF_MIN_ITERATIONS,
  KDF_MIN_MEMORY_MIB,
  KDF_PARALLELISM,
  KDF_TARGET_MS,
} from "./config.js";
import { loginsFromCsv } from "./csv.js";
import * as idb from "./idb.js";
import { matchUrls } from "./matching.js";
import { normalizeOtp, parseOtp, totpCode } from "./totp.js";

const LOGINS = "Logins";
const RECYCLE_BIN = "Recycle Bin";
const MAX_HISTORY = 10;
const MIN_PASSWORD_LENGTH = 12;
const OTP_FIELD = "otp"; // KeePassXC's name for a one-time-password secret
const OLD_AFTER_DAYS = 365;
const SUBDOMAINS_KEY = "PM_MATCH_SUBDOMAINS";
const EXTRA_URL = /^KP2A_URL_\d+$/;
const STANDARD_FIELDS = new Set(["Title", "UserName", "Password", "URL", "Notes"]);
const BACKGROUND_URL = chrome.runtime.getURL("background.js");

class EngineError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

// --- crypto plumbing ---------------------------------------------------------

kdbxweb.CryptoEngine.setArgon2Impl(
  (password, salt, memory, iterations, length, parallelism, type, version) => {
    if (version !== 0x13) return Promise.reject(new EngineError("unsupported_kdf"));
    const argon2 =
      type === kdbxweb.CryptoEngine.Argon2TypeArgon2id ? hashwasm.argon2id : hashwasm.argon2d;
    return argon2({
      password: new Uint8Array(password),
      salt: new Uint8Array(salt),
      parallelism,
      iterations,
      memorySize: memory,
      hashLength: length,
      outputType: "binary",
    }).then((out) => out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength));
  },
);

const toB64 = (buffer) => {
  const bytes = new Uint8Array(buffer);
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(text);
};
const fromB64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0)).buffer;

async function digests(buffer) {
  const sha = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
  return {
    sha256: [...sha].map((b) => b.toString(16).padStart(2, "0")).join(""),
    md5: await hashwasm.md5(new Uint8Array(buffer)),
  };
}

async function credentialsFromHash(hashB64) {
  const credentials = new kdbxweb.Credentials(null);
  await credentials.ready;
  credentials.passwordHash = kdbxweb.ProtectedValue.fromBinary(fromB64(hashB64));
  return credentials;
}

async function passwordHash(password) {
  return toB64(await kdbxweb.ProtectedValue.fromString(password).getHash());
}

async function load(bytes, hashB64) {
  try {
    return await kdbxweb.Kdbx.load(bytes.slice(0), await credentialsFromHash(hashB64));
  } catch (error) {
    if (error && error.code === kdbxweb.Consts.ErrorCodes.InvalidKey) {
      throw new EngineError("bad_password");
    }
    throw new EngineError("unreadable");
  }
}

// Iterations so one Argon2 run at the vault's memory takes about KDF_TARGET_MS
// in this browser (D9: about a second on the slowest device you use).
async function calibrateIterations() {
  const started = performance.now();
  await hashwasm.argon2id({
    password: "calibrate",
    salt: crypto.getRandomValues(new Uint8Array(32)),
    parallelism: KDF_PARALLELISM,
    iterations: 1,
    memorySize: KDF_MEMORY_MIB * 1024,
    hashLength: 32,
    outputType: "binary",
  });
  const perIteration = Math.max(performance.now() - started, 1);
  return Math.max(KDF_MIN_ITERATIONS, Math.round(KDF_TARGET_MS / perIteration));
}

// --- the clipboard -----------------------------------------------------------------
//
// A password copied from the vault page is taken off the clipboard after
// CLIPBOARD_CLEAR_MS — but only if the clipboard still holds it, so something you
// copied afterwards is never wiped. It happens here, not in the vault page, so
// closing that page does not leave the password on the clipboard. Only the
// SHA-256 of the copied text is kept here, never the text. This document has no
// focus, so it uses the old copy/paste commands: clipboardRead lets "paste" read
// the clipboard here and clipboardWrite lets "copy" write it without a click
// (measured: without it the write returns false). An empty copy leaves the
// clipboard as it was, so the clear writes a single space.

let armed = null; // { digest, timer }

function clipboardField() {
  const field = document.createElement("textarea");
  document.body.append(field);
  return field;
}

function readClipboard() {
  const field = clipboardField();
  try {
    field.focus();
    return document.execCommand("paste") ? field.value : null;
  } catch {
    return null;
  } finally {
    field.remove();
  }
}

function writeClipboard(text) {
  const field = clipboardField();
  try {
    field.value = text;
    field.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
  }
}

async function hexSha256(textValue) {
  const sha = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(textValue)));
  return [...sha].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Clear the clipboard if it still holds the copied text; if it cannot be read
// (the permission was refused), clear it anyway — better a lost copy than a
// password left behind.
async function clearIfHeld() {
  if (!armed) return;
  const { digest, timer } = armed;
  clearTimeout(timer);
  armed = null;
  const held = readClipboard();
  if (held === null || (await hexSha256(held)) === digest) writeClipboard(" ");
}

function armClipboard({ digest }) {
  if (typeof digest !== "string" || !/^[0-9a-f]{64}$/.test(digest)) throw new EngineError("bad_request");
  if (armed) clearTimeout(armed.timer);
  armed = { digest, timer: setTimeout(() => clearIfHeld(), CLIPBOARD_CLEAR_MS) };
  return {};
}

// --- the file as KeePassXC and pykeepass expect it ------------------------------

// kdbxweb writes a value it never read as an empty XML element, and KeePassXC
// refuses a file with one ("Invalid EnableSearching value"). pykeepass leaves
// these out of the groups it makes, so before each save every such value is
// set to the KeePass default it already meant (an absent flag is "inherit").
function normalize(db) {
  const now = new Date();
  const times = (t) => {
    for (const key of ["creationTime", "lastModTime", "lastAccessTime", "expiryTime", "locationChanged"]) {
      if (!t[key]) t[key] = now;
    }
    if (t.expires === undefined) t.expires = false;
    if (typeof t.usageCount !== "number") t.usageCount = 0;
  };
  const entry = (e) => {
    if (e.autoType && e.autoType.enabled === undefined) e.autoType.enabled = true;
    times(e.times);
    e.history.forEach(entry);
  };
  const group = (g) => {
    if (typeof g.icon !== "number") g.icon = kdbxweb.Consts.Icons.Folder;
    if (g.expanded === undefined) g.expanded = true;
    if (g.enableAutoType === undefined) g.enableAutoType = null;
    if (g.enableSearching === undefined) g.enableSearching = null;
    times(g.times);
    g.entries.forEach(entry);
    g.groups.forEach(group);
  };
  db.groups.forEach(group);
  const meta = db.meta;
  const protection = meta.memoryProtection;
  for (const key of ["title", "userName", "url", "notes"]) {
    if (protection[key] === undefined) protection[key] = false;
  }
  if (protection.password === undefined) protection.password = true;
  if (meta.recycleBinEnabled === undefined) meta.recycleBinEnabled = true;
  const numbers = {
    mntncHistoryDays: 365,
    keyChangeRec: -1,
    keyChangeForce: -1,
    historyMaxItems: MAX_HISTORY,
    historyMaxSize: 6291456,
  };
  for (const [key, value] of Object.entries(numbers)) {
    if (typeof meta[key] !== "number") meta[key] = value;
  }
}

function findGroup(group, name) {
  if (group.name === name) return group;
  for (const child of group.groups) {
    const found = findGroup(child, name);
    if (found) return found;
  }
  return null;
}

function loginsGroup(db, create = false) {
  const root = db.getDefaultGroup();
  const found = findGroup(root, LOGINS);
  if (found || !create) return found;
  return db.createGroup(root, LOGINS);
}

function recycleBin(db) {
  let bin = db.meta.recycleBinUuid ? db.getGroup(db.meta.recycleBinUuid) : null;
  if (!bin) {
    bin = db.getDefaultGroup().groups.find((g) => g.name === RECYCLE_BIN) || null;
    if (bin) db.meta.recycleBinUuid = bin.uuid;
  }
  if (!bin) {
    db.createRecycleBin();
    bin = db.getGroup(db.meta.recycleBinUuid);
  }
  return bin;
}

// --- entries <-> the LoginEntry shape (docs/specs/data-model.md) ----------------

const text = (value) =>
  value instanceof kdbxweb.ProtectedValue ? value.getText() : typeof value === "string" ? value : "";

function entryUrls(entry) {
  const urls = [];
  const main = text(entry.fields.get("URL"));
  if (main) urls.push(main);
  const extra = [...entry.fields.keys()].filter((key) => EXTRA_URL.test(key)).sort();
  for (const key of extra) {
    const value = text(entry.fields.get(key));
    if (value) urls.push(value);
  }
  return urls;
}

const subdomains = (entry) => text(entry.fields.get(SUBDOMAINS_KEY)) === "true";

function hostsOf(urls) {
  const hosts = [];
  for (const url of urls) {
    try {
      hosts.push(new URL(url).host);
    } catch {
      // not a URL we can show; matching ignores it too
    }
  }
  return hosts;
}

const hasOtp = (entry) => text(entry.fields.get(OTP_FIELD)).trim() !== "";

function summary(entry) {
  const urls = entryUrls(entry);
  return {
    id: entry.uuid.id,
    title: text(entry.fields.get("Title")),
    username: text(entry.fields.get("UserName")),
    hosts: hostsOf(urls),
    has_totp: hasOtp(entry),
  };
}

function fullEntry(entry) {
  return {
    ...summary(entry),
    password: text(entry.fields.get("Password")),
    urls: entryUrls(entry),
    notes: text(entry.fields.get("Notes")),
    otp: text(entry.fields.get(OTP_FIELD)),
    tags: [...(entry.tags || [])],
    match_subdomains: subdomains(entry),
    created_at: entry.times.creationTime ? entry.times.creationTime.toISOString() : null,
    updated_at: entry.times.lastModTime ? entry.times.lastModTime.toISOString() : null,
  };
}

// The data-model rules; errors never echo a value.
function validate(input) {
  const fail = () => {
    throw new EngineError("invalid");
  };
  if (!input || typeof input !== "object") fail();
  const { title, username, password, notes = "", tags = [], urls = [] } = input;
  if (typeof title !== "string" || title.length < 1 || title.length > 200) fail();
  if (typeof username !== "string" || username.length > 500) fail();
  if (typeof password !== "string" || password.length > 4096) fail();
  if (typeof notes !== "string" || new TextEncoder().encode(notes).length > 64 * 1024) fail();
  if (!Array.isArray(tags) || tags.length > 20 || tags.some((t) => typeof t !== "string")) fail();
  if (!Array.isArray(urls) || urls.length > 20) fail();
  for (const url of urls) {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      fail();
    }
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) fail();
  }
  if (typeof input.match_subdomains !== "boolean" && input.match_subdomains !== undefined) fail();
  if (input.otp !== undefined && (typeof input.otp !== "string" || (input.otp.trim() && !parseOtp(input.otp)))) {
    fail(); // a one-time-password secret that is not a usable time-based secret
  }
}

function apply(entry, input) {
  entry.fields.set("Title", input.title);
  entry.fields.set("UserName", input.username);
  entry.fields.set("Password", kdbxweb.ProtectedValue.fromString(input.password));
  const urls = input.urls || [];
  entry.fields.set("URL", urls[0] || "");
  entry.fields.set("Notes", input.notes || "");
  entry.tags = [...(input.tags || [])];
  entry.fields.set(SUBDOMAINS_KEY, input.match_subdomains ? "true" : "false");
  if (typeof input.otp === "string") {
    const stored = input.otp.trim() ? normalizeOtp(input.otp, input.title) : null;
    if (stored) entry.fields.set(OTP_FIELD, kdbxweb.ProtectedValue.fromString(stored));
    else entry.fields.delete(OTP_FIELD);
  }
  for (const key of [...entry.fields.keys()]) {
    if (EXTRA_URL.test(key)) entry.fields.delete(key);
  }
  urls.slice(1).forEach((url, index) => entry.fields.set(`KP2A_URL_${index + 1}`, url));
}

function findLogin(db, id) {
  const logins = loginsGroup(db);
  if (!logins || typeof id !== "string") return null;
  return logins.entries.find((entry) => entry.uuid.id === id) || null;
}

// --- the open vault --------------------------------------------------------------

let current = null; // { profileId, db, hash }

function requireOpen(profileId) {
  if (!current || (profileId && current.profileId !== profileId)) throw new EngineError("locked");
  return current;
}

// Save: normalize, write, prove the new bytes decrypt, then replace the stored
// file and its newest backup in one transaction (the IndexedDB version of the
// desktop's atomic save with read-back check). A failure leaves the stored
// vault as it was and reloads it, so memory never holds unsaved edits.
async function save(reloadHash) {
  const { db, hash, profileId } = requireOpen();
  try {
    normalize(db);
    const bytes = await db.save();
    await load(bytes, hash); // the read-back check
    const sums = await digests(bytes);
    await idb.replaceVault(
      profileId,
      { bytes, ...sums, savedAt: new Date().toISOString() },
      (state) => (state ? { ...state, local_dirty: true } : null),
    );
    return sums;
  } catch (error) {
    const stored = await idb.get("vaults", profileId);
    const back = reloadHash || hash; // after a key change the stored file is still under the old key
    if (stored) current = { profileId, hash: back, db: await load(stored.bytes, back) };
    throw error instanceof EngineError ? new EngineError("save_failed") : error;
  }
}

async function createVault({ profileId, password }) {
  if (typeof password !== "string" || password.length < 1) throw new EngineError("invalid");
  if (KDF_MEMORY_MIB < KDF_MIN_MEMORY_MIB) throw new EngineError("kdf_too_weak");
  if (await idb.get("vaults", profileId)) throw new EngineError("exists");
  const iterations = await calibrateIterations();
  const credentials = new kdbxweb.Credentials(kdbxweb.ProtectedValue.fromString(password));
  const db = kdbxweb.Kdbx.create(credentials, "Personal Vault");
  db.header.setKdf(kdbxweb.Consts.KdfId.Argon2id);
  const params = db.header.kdfParameters;
  const { ValueType } = kdbxweb.VarDictionary;
  params.set("M", ValueType.UInt64, kdbxweb.Int64.from(KDF_MEMORY_MIB * 1024 * 1024));
  params.set("P", ValueType.UInt32, KDF_PARALLELISM);
  params.set("I", ValueType.UInt64, kdbxweb.Int64.from(iterations));
  db.meta.historyMaxItems = MAX_HISTORY;
  loginsGroup(db, true);
  const hash = await passwordHash(password);
  current = { profileId, db, hash };
  try {
    await save();
  } catch (error) {
    current = null; // nothing was stored, so nothing is open
    throw error;
  }
  return { passwordHash: hash, iterations };
}

async function openVault({ profileId, password, passwordHash: given }) {
  const stored = await idb.get("vaults", profileId);
  if (!stored) throw new EngineError("no_vault");
  const hash = typeof password === "string" ? await passwordHash(password) : given;
  if (typeof hash !== "string") throw new EngineError("bad_request");
  const db = await load(stored.bytes, hash);
  current = { profileId, db, hash };
  return { passwordHash: hash };
}

function matches({ url }) {
  const { db } = requireOpen();
  const logins = loginsGroup(db);
  if (!logins) return { logins: [] };
  const found = logins.entries
    .filter((entry) => matchUrls(entryUrls(entry), url, subdomains(entry)))
    .map(summary)
    .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));
  return {
    logins: found.map(({ id, title, username, has_totp: totp }) => ({ id, title, username, has_totp: totp })),
  };
}

function secret({ entryId, url }) {
  const { db } = requireOpen();
  const entry = findLogin(db, entryId);
  if (!entry || !matchUrls(entryUrls(entry), url, subdomains(entry))) {
    throw new EngineError("url_mismatch"); // I4: never the password for another site
  }
  return { username: text(entry.fields.get("UserName")), password: text(entry.fields.get("Password")) };
}

function list({ query }) {
  const { db } = requireOpen();
  const logins = loginsGroup(db);
  const needle = typeof query === "string" ? query.toLowerCase() : "";
  const rows = (logins ? logins.entries : []).filter((entry) => {
    if (!needle) return true;
    const haystack = [
      text(entry.fields.get("Title")),
      text(entry.fields.get("UserName")),
      text(entry.fields.get("Notes")),
      ...entryUrls(entry),
      ...(entry.tags || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
  return {
    entries: rows.map(summary).sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase())),
  };
}

function getEntry({ entryId }) {
  const entry = findLogin(requireOpen().db, entryId);
  if (!entry) throw new EngineError("not_found");
  return { entry: fullEntry(entry) };
}

async function addEntry({ entry: input }) {
  validate(input);
  const { db } = requireOpen();
  const entry = db.createEntry(loginsGroup(db, true));
  apply(entry, input);
  await save();
  return { id: entry.uuid.id };
}

async function editEntry({ entry: input }) {
  validate(input);
  const { db } = requireOpen();
  const entry = findLogin(db, input.id);
  if (!entry) throw new EngineError("not_found");
  entry.pushHistory();
  apply(entry, input);
  entry.times.update();
  if (entry.history.length > MAX_HISTORY) entry.removeHistory(0, entry.history.length - MAX_HISTORY);
  await save();
  return { id: entry.uuid.id };
}

async function deleteEntry({ entryId }) {
  const { db } = requireOpen();
  const entry = findLogin(db, entryId);
  if (!entry) throw new EngineError("not_found");
  db.move(entry, recycleBin(db));
  entry.times.lastModTime = new Date(); // a deletion needs a time for the desktop merge
  await save();
  return {};
}

// A login saved from a page is saved for the site: its origin, never the path
// or query of the address bar (which can hold a token), and the host as the
// default title. Matching ignores the path, so nothing is lost.
async function saveLogin({ url, username, password, title }) {
  let site;
  try {
    site = new URL(url);
  } catch {
    throw new EngineError("invalid");
  }
  if (!["http:", "https:"].includes(site.protocol) || !site.hostname) throw new EngineError("invalid");
  return addEntry({
    entry: {
      title: title || site.host,
      username,
      password,
      urls: [`${site.origin}/`],
      notes: "",
      tags: [],
      match_subdomains: false,
    },
  });
}

async function updatePassword({ entryId, url, newPassword }) {
  const { db } = requireOpen();
  const entry = findLogin(db, entryId);
  if (!entry || !matchUrls(entryUrls(entry), url, subdomains(entry))) throw new EngineError("url_mismatch");
  return editEntry({ entry: { ...fullEntry(entry), password: newPassword } });
}

// Sync: take a file from Drive. It must open with this vault's key before it
// replaces anything (I7); the replaced file becomes the newest backup.
// The file may have been re-keyed on another device (its master password
// changed): then `password` is the new one, the file must open with it, and the
// new key replaces this unlock's.
async function adopt({ profileId, bytes: bytesB64, sync, password }) {
  const open = requireOpen(profileId);
  const hash = typeof password === "string" && password ? await passwordHash(password) : open.hash;
  const bytes = fromB64(bytesB64);
  const db = await load(bytes, hash);
  const sums = await digests(bytes);
  await idb.replaceVault(profileId, { bytes, ...sums, savedAt: new Date().toISOString() }, (state) => ({
    ...(state || {}),
    ...sync,
    profileId,
    last_synced_local_sha256: sums.sha256,
  }));
  current = { profileId, db, hash };
  return hash === open.hash ? sums : { ...sums, passwordHash: hash };
}

// A vault that already exists (on Google Drive, made by the desktop app or
// another browser) becomes a profile here: it must open with the password
// given before anything is stored, and it keeps its own profile id.
async function importVault({ profileId, bytes: bytesB64, password, sync }) {
  if (typeof password !== "string" || !password) throw new EngineError("bad_password");
  if (await idb.get("vaults", profileId)) throw new EngineError("exists");
  const bytes = fromB64(bytesB64);
  const hash = await passwordHash(password);
  const db = await load(bytes, hash);
  const sums = await digests(bytes);
  await idb.replaceVault(profileId, { bytes, ...sums, savedAt: new Date().toISOString() }, () => ({
    ...sync,
    profileId,
    last_synced_local_sha256: sums.sha256,
    local_dirty: false,
  }));
  current = { profileId, db, hash };
  return { passwordHash: hash, ...sums };
}

// --- master password -----------------------------------------------------------------

// Re-key the open vault. The current password must be typed again; the new key
// is used from the next save (kdbxweb draws a fresh master seed and KDF salt on
// every save). The stored copies in backups and on other devices are still
// under the old key, which is why restoring a backup re-keys it to the current
// key and why a download from Drive can ask for the new password (adopt).
async function changePassword({ password, newPassword }) {
  const open = requireOpen();
  if (typeof password !== "string" || typeof newPassword !== "string") throw new EngineError("invalid");
  if (newPassword.length < MIN_PASSWORD_LENGTH) throw new EngineError("password_too_short");
  const oldHash = open.hash;
  if ((await passwordHash(password)) !== oldHash) throw new EngineError("bad_password");
  const newHash = await passwordHash(newPassword);
  open.db.credentials.passwordHash = kdbxweb.ProtectedValue.fromBinary(fromB64(newHash));
  open.db.meta.masterKeyChanged = new Date();
  open.hash = newHash;
  await save(oldHash); // on failure the stored file and the old key are put back
  return { passwordHash: newHash };
}

// --- Recycle Bin ---------------------------------------------------------------------

function existingBin(db) {
  const bin = db.meta.recycleBinUuid ? db.getGroup(db.meta.recycleBinUuid) : null;
  return bin || db.getDefaultGroup().groups.find((g) => g.name === RECYCLE_BIN) || null;
}

function findInBin(db, id) {
  const bin = existingBin(db);
  if (!bin || typeof id !== "string") return null;
  return bin.entries.find((entry) => entry.uuid.id === id) || null;
}

const isoOf = (date) => (date ? date.toISOString() : null);

function binList() {
  const bin = existingBin(requireOpen().db);
  const rows = (bin ? bin.entries : []).map((entry) => ({
    ...summary(entry),
    deleted_at: isoOf(entry.times.lastModTime),
  }));
  rows.sort((a, b) => String(b.deleted_at).localeCompare(String(a.deleted_at)));
  return { entries: rows };
}

async function binRestore({ entryId }) {
  const { db } = requireOpen();
  const entry = findInBin(db, entryId);
  if (!entry) throw new EngineError("not_found");
  db.move(entry, loginsGroup(db, true));
  entry.times.lastModTime = new Date(); // the move needs a time newer than the deletion for a merge
  await save();
  return {};
}

// Gone for good: kdbxweb records a deleted object, so a merge with another copy
// does not bring it back.
async function binDelete({ entryId }) {
  const { db } = requireOpen();
  const entry = findInBin(db, entryId);
  if (!entry) throw new EngineError("not_found");
  db.move(entry, undefined);
  await save();
  return {};
}

async function binEmpty() {
  const { db } = requireOpen();
  const bin = existingBin(db);
  const doomed = bin ? [...bin.entries] : [];
  for (const entry of doomed) db.move(entry, undefined);
  if (doomed.length) await save();
  return { removed: doomed.length };
}

// --- backups -------------------------------------------------------------------------

async function backupList() {
  const rows = await idb.listBackups(requireOpen().profileId);
  return { backups: rows.map((row) => ({ id: row.id, savedAt: row.savedAt, size: row.bytes.byteLength })) };
}

// Put an earlier copy back. The copy may be under an older master password (the
// password was changed since): `password` opens it, and either way it is re-keyed
// to the CURRENT key before it is saved, so this browser, its backups and Drive
// keep one key. The vault being replaced becomes the newest backup, so a restore
// can be undone.
async function restoreBackup({ backupId, password }) {
  const open = requireOpen();
  const rows = await idb.listBackups(open.profileId);
  const row = rows.find((candidate) => candidate.id === backupId);
  if (!row) throw new EngineError("not_found");
  let db;
  try {
    db = await load(row.bytes, open.hash);
  } catch (error) {
    if (!(error instanceof EngineError) || error.code !== "bad_password") throw error;
    if (typeof password !== "string" || !password) throw new EngineError("backup_password");
    db = await load(row.bytes, await passwordHash(password));
  }
  db.credentials.passwordHash = kdbxweb.ProtectedValue.fromBinary(fromB64(open.hash));
  open.db = db;
  await save(); // on failure the stored vault is reloaded
  return {};
}

// --- an entry's earlier versions ----------------------------------------------------------

function findHistory(db, entryId, index) {
  const entry = findLogin(db, entryId);
  if (!entry) throw new EngineError("not_found");
  const old = Number.isInteger(index) ? entry.history[index] : null;
  if (!old) throw new EngineError("not_found");
  return { entry, old };
}

function historyList({ entryId }) {
  const entry = findLogin(requireOpen().db, entryId);
  if (!entry) throw new EngineError("not_found");
  const versions = entry.history.map((old, index) => ({
    index,
    updated_at: isoOf(old.times.lastModTime),
    title: text(old.fields.get("Title")),
    username: text(old.fields.get("UserName")),
  }));
  return { versions: versions.reverse() }; // newest first
}

function historyGet({ entryId, index }) {
  const { old } = findHistory(requireOpen().db, entryId, index);
  return { entry: fullEntry(old) };
}

// The old version becomes the current one; what is current now goes to history.
async function historyRestore({ entryId, index }) {
  const { db } = requireOpen();
  const { old } = findHistory(db, entryId, index);
  const { id: _id, created_at: _c, updated_at: _u, hosts: _h, has_totp: _t, ...fields } = fullEntry(old);
  return editEntry({ entry: { ...fields, id: entryId } });
}

// --- one-time codes -------------------------------------------------------------------------

// The code for an entry now. With `url` (the popup asks for the page's own login)
// the entry must match that page, like a password does.
async function totp({ entryId, url }) {
  const { db } = requireOpen();
  const entry = findLogin(db, entryId);
  if (!entry) throw new EngineError("not_found");
  if (url !== undefined && !matchUrls(entryUrls(entry), url, subdomains(entry))) {
    throw new EngineError("url_mismatch");
  }
  const code = await totpCode(text(entry.fields.get(OTP_FIELD)));
  if (!code) throw new EngineError("no_totp");
  return code;
}

// --- import ----------------------------------------------------------------------------------

const sameLogin = (input) =>
  `${input.title.toLowerCase()}\n${input.username}\n${input.urls[0] ? new URL(input.urls[0]).origin : ""}`;

// Add many logins with ONE save. An entry that is invalid is skipped; one that is
// already there (same title, username and site) is a duplicate. Counts only: a
// failure never says which value was wrong.
async function addMany(inputs) {
  const { db } = requireOpen();
  const logins = loginsGroup(db, true);
  const known = new Set(
    logins.entries.map((entry) =>
      sameLogin({
        title: text(entry.fields.get("Title")),
        username: text(entry.fields.get("UserName")),
        urls: entryUrls(entry),
      }),
    ),
  );
  let added = 0;
  let duplicates = 0;
  let skipped = 0;
  for (const input of inputs) {
    try {
      validate(input);
    } catch {
      skipped += 1;
      continue;
    }
    const key = sameLogin(input);
    if (known.has(key)) {
      duplicates += 1;
      continue;
    }
    known.add(key);
    apply(db.createEntry(logins), input);
    added += 1;
  }
  if (added) await save();
  return { added, duplicates, skipped };
}

async function importCsv({ text: csv }) {
  requireOpen();
  const parsed = loginsFromCsv(csv);
  if (parsed.error) throw new EngineError(`import_${parsed.error}`);
  const counted = await addMany(
    parsed.logins.map((login) => ({ ...login, tags: ["imported"], match_subdomains: false })),
  );
  return { ...counted, skipped: counted.skipped + parsed.skipped };
}

// Logins from another KDBX file (any KeePass-compatible export): it must open
// with the password given. Its Recycle Bin and the desktop app's hidden ".app"
// group (pairing and sync secrets) are never imported.
async function importKdbx({ bytes: bytesB64, password }) {
  requireOpen();
  if (typeof password !== "string" || !password) throw new EngineError("bad_password");
  const source = await load(fromB64(bytesB64), await passwordHash(password));
  const binId = source.meta.recycleBinUuid ? source.meta.recycleBinUuid.id : null;
  const skipGroup = (group) => group.name === ".app" || group.name === RECYCLE_BIN || group.uuid.id === binId;
  const inputs = [];
  const walk = (group) => {
    if (skipGroup(group)) return;
    for (const entry of group.entries) {
      const urls = entryUrls(entry).flatMap((url) => {
        try {
          const parsed = new URL(url);
          return ["http:", "https:"].includes(parsed.protocol) && parsed.hostname ? [`${parsed.origin}/`] : [];
        } catch {
          return [];
        }
      });
      inputs.push({
        title: text(entry.fields.get("Title")) || "Imported login",
        username: text(entry.fields.get("UserName")),
        password: text(entry.fields.get("Password")),
        urls,
        notes: text(entry.fields.get("Notes")),
        otp: text(entry.fields.get(OTP_FIELD)),
        tags: [...(entry.tags || []), "imported"],
        match_subdomains: false,
      });
    }
    group.groups.forEach(walk);
  };
  source.groups.forEach(walk);
  return addMany(inputs);
}

// --- password health (offline) -----------------------------------------------------------------

const COMMON = new Set([
  "password", "passw0rd", "123456", "1234567", "12345678", "123456789", "qwerty", "abc123", "letmein",
  "welcome", "admin", "iloveyou", "monkey", "dragon", "111111", "changeme", "football", "login",
]);

// A rough guess at the strength in bits: the size of the character classes used,
// with repeated characters counting for little. It is an estimate, not a proof.
function strengthBits(password) {
  let pool = 0;
  if (/[a-z]/.test(password)) pool += 26;
  if (/[A-Z]/.test(password)) pool += 26;
  if (/[0-9]/.test(password)) pool += 10;
  if (/[^A-Za-z0-9]/.test(password)) pool += 33;
  if (!pool) return 0;
  const distinct = new Set(password).size;
  return Math.min(password.length, distinct * 2) * Math.log2(pool);
}

function weakness(password) {
  if (!password) return "empty";
  if (COMMON.has(password.toLowerCase())) return "common";
  if (password.length < 8) return "short";
  if (strengthBits(password) < 50) return "weak";
  return null;
}

// Which logins have a weak password, share one with another, or have not changed
// in a year. Titles and usernames only — never a password or a hash.
async function report() {
  const { db } = requireOpen();
  const logins = loginsGroup(db);
  const entries = logins ? logins.entries : [];
  const brief = (entry) => ({
    id: entry.uuid.id,
    title: text(entry.fields.get("Title")),
    username: text(entry.fields.get("UserName")),
  });
  const weak = [];
  const old = [];
  const byPassword = new Map();
  const cutoff = Date.now() - OLD_AFTER_DAYS * 24 * 60 * 60 * 1000;
  for (const entry of entries) {
    const password = text(entry.fields.get("Password"));
    const reason = weakness(password);
    if (reason) weak.push({ ...brief(entry), reason });
    if (password) {
      const key = (await digests(new TextEncoder().encode(password).buffer)).sha256;
      byPassword.set(key, [...(byPassword.get(key) || []), brief(entry)]);
    }
    const changed = entry.times.lastModTime;
    if (changed && changed.getTime() < cutoff) old.push({ ...brief(entry), updated_at: isoOf(changed) });
  }
  const reused = [...byPassword.values()].filter((group) => group.length > 1);
  return { total: entries.length, weak, reused, old };
}

// --- merge both copies -----------------------------------------------------------------------

// A conflict: the copy kept from Drive is merged INTO this vault with kdbxweb's
// own merge (entries from both sides survive, the newer edit wins and the older
// goes to history, deletions are respected). The merged file is saved here; the
// service worker then uploads it over Drive's.
async function mergeRemote({ bytes: bytesB64 }) {
  const open = requireOpen();
  const theirs = await load(fromB64(bytesB64), open.hash);
  try {
    open.db.merge(theirs);
  } catch {
    const stored = await idb.get("vaults", open.profileId);
    if (stored) current = { ...open, db: await load(stored.bytes, open.hash) };
    throw new EngineError("merge_failed");
  }
  await save();
  return {};
}


async function decrypts({ bytes }) {
  const { hash } = requireOpen();
  try {
    await load(fromB64(bytes), hash);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

async function exportVault() {
  const stored = await idb.get("vaults", requireOpen().profileId);
  return { bytes: toB64(stored.bytes) };
}

async function digestOf({ bytes }) {
  return digests(fromB64(bytes));
}

const OPS = {
  status: () => ({ profileId: current ? current.profileId : null }),
  create: createVault,
  open: openVault,
  close: async () => {
    current = null;
    await clearIfHeld(); // locking takes a copied password off the clipboard
    return {};
  },
  clipboard_arm: armClipboard,
  matches,
  secret,
  list,
  get: getEntry,
  add: addEntry,
  edit: editEntry,
  delete: deleteEntry,
  save_login: saveLogin,
  update_password: updatePassword,
  adopt,
  import: importVault,
  decrypts,
  export: exportVault,
  digest: digestOf,
  change_password: changePassword,
  bin_list: binList,
  bin_restore: binRestore,
  bin_delete: binDelete,
  bin_empty: binEmpty,
  backup_list: backupList,
  restore_backup: restoreBackup,
  history_list: historyList,
  history_get: historyGet,
  history_restore: historyRestore,
  totp,
  import_csv: importCsv,
  import_kdbx: importKdbx,
  report,
  merge: mergeRemote,
};

let queue = Promise.resolve();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.target !== "engine") return false;
  if (sender.id !== chrome.runtime.id || sender.url !== BACKGROUND_URL) {
    sendResponse({ ok: false, error: { code: "bad_request" } });
    return false;
  }
  const op = OPS[message.op];
  if (!op) {
    sendResponse({ ok: false, error: { code: "bad_request" } });
    return false;
  }
  const run = queue.then(() => op(message.args || {}));
  queue = run.catch(() => {});
  run.then(
    (result) => sendResponse({ ok: true, result }),
    (error) => sendResponse({ ok: false, error: { code: error instanceof EngineError ? error.code : "internal" } }),
  );
  return true;
});

// The network coming back is a sync trigger (docs/specs/sync.md). The service
// worker sleeps; this document stays, so it is the one that hears it.
window.addEventListener("online", () => {
  chrome.runtime.sendMessage({ type: "engine_online" }).catch(() => {});
});
