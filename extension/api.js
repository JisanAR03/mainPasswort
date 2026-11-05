// The extension's storage helpers: chrome.storage.local (persists) and
// chrome.storage.session (memory only, cleared when the browser closes or the
// extension is reloaded, updated or disabled). Everything else the extension
// does is local to its own pages, so nothing here talks to another program.

export const store = {
  get: (keys) => chrome.storage.local.get(keys),
  set: (items) => chrome.storage.local.set(items),
  sessionGet: (keys) => chrome.storage.session.get(keys),
  sessionSet: (items) => chrome.storage.session.set(items),
  sessionRemove: (keys) => chrome.storage.session.remove(keys),
};
