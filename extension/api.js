// The only file that touches the browser's extension API directly, so a
// Firefox build can add browser.* here and change nothing else.
//
// The service worker holds one native port to the desktop app. Requests are
// matched to replies by the envelope id; a dropped port fails every pending
// request with app_not_running, and the popup tells you to start the app.

const HOST_NAME = "com.personalvault.host";

let port = null;
let nextId = 0;
const pending = new Map();

async function pairingKey() {
  const stored = await chrome.storage.local.get("pairing_key");
  return stored.pairing_key || "";
}

function failAllPending(error) {
  const code = error && error.error ? error.error.code : "app_not_running";
  for (const [id, resolve] of pending) {
    pending.delete(id);
    resolve({ v: 1, id, ok: false, error: { code } });
  }
}

function connect() {
  if (port) return port;
  port = chrome.runtime.connectNative(HOST_NAME);
  port.onMessage.addListener((message) => {
    const resolve = pending.get(message.id);
    if (resolve) {
      pending.delete(message.id);
      resolve(message);
      return;
    }
    // The host cannot reach the app, so it answers without an id (it never
    // parses request bodies): that fails every request still open.
    failAllPending(message);
  });
  port.onDisconnect.addListener(() => {
    port = null;
    failAllPending();
  });
  return port;
}

export async function nativeRequest(type, payload = {}) {
  const id = `ext-${++nextId}`;
  const request = { v: 1, id, type, pairing_key: await pairingKey(), payload };
  const failed = () => ({ v: 1, id, ok: false, error: { code: "app_not_running" } });
  return new Promise((resolve) => {
    let openPort;
    try {
      openPort = connect();
    } catch (error) {
      resolve(failed());
      return;
    }
    pending.set(id, resolve);
    try {
      openPort.postMessage(request);
    } catch (error) {
      pending.delete(id);
      resolve(failed());
    }
  });
}

export function newPairingKey() {
  const raw = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...raw));
}

// The same 6-character code the desktop app shows: SHA-256 over the key bytes,
// six digest bytes picking from a 32-character alphabet (see bridge/pairing.py,
// which derives it identically; the e2e suite asserts the two agree).
export async function pairingCode(key) {
  const raw = Uint8Array.from(atob(key), (character) => character.charCodeAt(0));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", raw));
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return [...digest.slice(0, 6)].map((byte) => alphabet[byte % alphabet.length]).join("");
}

export function browserName() {
  return navigator.userAgent.includes("Brave") ? "Brave" : "Chrome";
}

export const store = {
  get: (keys) => chrome.storage.local.get(keys),
  set: (items) => chrome.storage.local.set(items),
  sessionGet: (keys) => chrome.storage.session.get(keys),
  sessionSet: (items) => chrome.storage.session.set(items),
  sessionRemove: (keys) => chrome.storage.session.remove(keys),
};
