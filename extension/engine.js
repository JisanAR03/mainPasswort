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
  KDF_MEMORY_MIB,
  KDF_MIN_ITERATIONS,
  KDF_MIN_MEMORY_MIB,
  KDF_PARALLELISM,
  KDF_TARGET_MS,
} from "./config.js";
import * as idb from "./idb.js";
import { matchUrls } from "./matching.js";

const LOGINS = "Logins";
const RECYCLE_BIN = "Recycle Bin";
const MAX_HISTORY = 10;
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

function summary(entry) {
  const urls = entryUrls(entry);
  return {
    id: entry.uuid.id,
    title: text(entry.fields.get("Title")),
    username: text(entry.fields.get("UserName")),
    hosts: hostsOf(urls),
  };
}

function fullEntry(entry) {
  return {
    ...summary(entry),
    password: text(entry.fields.get("Password")),
    urls: entryUrls(entry),
    notes: text(entry.fields.get("Notes")),
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
async function save() {
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
    if (stored) current = { profileId, hash, db: await load(stored.bytes, hash) };
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
  return { logins: found.map(({ id, title, username }) => ({ id, title, username })) };
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

async function saveLogin({ url, username, password, title }) {
  return addEntry({
    entry: { title: title || url, username, password, urls: [url], notes: "", tags: [], match_subdomains: false },
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
async function adopt({ profileId, bytes: bytesB64, sync }) {
  const { hash } = requireOpen(profileId);
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
  return sums;
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
  close: () => {
    current = null;
    return {};
  },
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
