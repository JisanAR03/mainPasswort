// The extension's own storage for extension-only mode: one IndexedDB database
// shared by the service worker and the offscreen vault engine ([S]-adjacent).
//
// It holds encrypted bytes and bookkeeping only — never a plaintext entry
// field, a password or a key (invariants I1 and I12):
//   vaults    profileId -> { profileId, bytes, sha256, md5, savedAt }  the KDBX file
//   backups   auto id   -> { profileId, bytes, savedAt }  the previous KEEP_BACKUPS files
//   sync      profileId -> the desktop app's state.json fields
//   conflicts auto id   -> { profileId, bytes, keptAt, remote_md5, remote_version }
//
// Every write that replaces a vault is one transaction: the old copy moves to
// backups and the new one goes in together, or neither does.

const DB_NAME = "personal-vault";
const DB_VERSION = 1;
export const KEEP_BACKUPS = 20;

let opening = null;

export function openDb() {
  if (opening) return opening;
  opening = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore("vaults", { keyPath: "profileId" });
      db.createObjectStore("sync", { keyPath: "profileId" });
      db.createObjectStore("backups", { keyPath: "id", autoIncrement: true }).createIndex(
        "profileId",
        "profileId",
      );
      db.createObjectStore("conflicts", { keyPath: "id", autoIncrement: true }).createIndex(
        "profileId",
        "profileId",
      );
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => {
        db.close();
        opening = null;
      };
      resolve(db);
    };
    request.onerror = () => {
      opening = null;
      reject(request.error);
    };
  });
  return opening;
}

const done = (tx) =>
  new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error || new Error("transaction aborted"));
    tx.onerror = () => reject(tx.error);
  });

const result = (request) =>
  new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

export async function get(store, key) {
  const db = await openDb();
  return result(db.transaction(store).objectStore(store).get(key));
}

export async function put(store, value) {
  const db = await openDb();
  const tx = db.transaction(store, "readwrite");
  tx.objectStore(store).put(value);
  await done(tx);
}

export async function remove(store, key) {
  const db = await openDb();
  const tx = db.transaction(store, "readwrite");
  tx.objectStore(store).delete(key);
  await done(tx);
}

// Read-modify-write of one record, atomically: change(current) returns the new
// record (or null to delete, undefined to leave it).
export async function update(store, key, change) {
  const db = await openDb();
  const tx = db.transaction(store, "readwrite");
  const objects = tx.objectStore(store);
  let next;
  const current = await result(objects.get(key));
  next = change(current === undefined ? null : current);
  if (next === null) objects.delete(key);
  else if (next !== undefined) objects.put(next);
  await done(tx);
  return next;
}

async function pruneBackups(backups, profileId) {
  const keys = await result(backups.index("profileId").getAllKeys(profileId));
  keys.sort((a, b) => a - b);
  for (const key of keys.slice(0, Math.max(0, keys.length - KEEP_BACKUPS))) backups.delete(key);
}

// Replace a profile's vault with bytes that were already verified to decrypt.
// The previous file becomes the newest backup; `syncChange` (optional) updates
// the sync record in the same transaction.
export async function replaceVault(profileId, record, syncChange) {
  const db = await openDb();
  const tx = db.transaction(["vaults", "backups", "sync"], "readwrite");
  const vaults = tx.objectStore("vaults");
  const backups = tx.objectStore("backups");
  const current = await result(vaults.get(profileId));
  if (current) {
    backups.add({ profileId, bytes: current.bytes, savedAt: current.savedAt });
    await pruneBackups(backups, profileId);
  }
  vaults.put({ profileId, ...record });
  if (syncChange) {
    const sync = tx.objectStore("sync");
    const state = await result(sync.get(profileId));
    const next = syncChange(state === undefined ? null : state);
    if (next) sync.put(next);
  }
  await done(tx);
}

export async function listBackups(profileId) {
  const db = await openDb();
  const rows = await result(db.transaction("backups").objectStore("backups").index("profileId").getAll(profileId));
  return rows.sort((a, b) => b.id - a.id);
}

export async function addConflict(profileId, copy) {
  const db = await openDb();
  const tx = db.transaction("conflicts", "readwrite");
  const id = await result(tx.objectStore("conflicts").add({ profileId, ...copy }));
  await done(tx);
  return id;
}

export async function deleteProfileData(profileId) {
  const db = await openDb();
  const tx = db.transaction(["vaults", "backups", "sync", "conflicts"], "readwrite");
  tx.objectStore("vaults").delete(profileId);
  tx.objectStore("sync").delete(profileId);
  for (const name of ["backups", "conflicts"]) {
    const store = tx.objectStore(name);
    for (const key of await result(store.index("profileId").getAllKeys(profileId))) store.delete(key);
  }
  await done(tx);
}
