// The service worker: owns the native port, reads the active tab's URL itself,
// and injects the fill. It keeps a password in memory only for the
// executeScript call that uses it, then drops it.
import { browserName, nativeRequest, newPairingKey, store } from "./api.js";
import { fillLogin } from "./fill.js";

const SAVE_TTL_MS = 2 * 60 * 1000;
const DETECT_ID = "detect-submits";
const ALL_SITES = "<all_urls>";

async function targetTab() {
  const tabs = await chrome.tabs.query({});
  const web = tabs.filter((tab) => tab.url && /^https?:/.test(tab.url));
  return (
    web.find((tab) => tab.active) ||
    web.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0] ||
    null
  );
}

async function pendingCandidate() {
  const { pending_save: candidate } = await store.sessionGet("pending_save");
  if (!candidate) return null;
  if (Date.now() - candidate.at > SAVE_TTL_MS) {
    await clearCandidate();
    return null;
  }
  return candidate;
}

async function clearCandidate() {
  await store.sessionRemove("pending_save");
  await chrome.action.setBadgeText({ text: "" });
}

async function syncWatch() {
  const { watch_logins: wanted } = await store.get("watch_logins");
  const granted = await chrome.permissions.contains({ origins: [ALL_SITES] });
  const registered = await chrome.scripting
    .getRegisteredContentScripts({ ids: [DETECT_ID] })
    .catch(() => []);
  if (wanted && granted && registered.length === 0) {
    await chrome.scripting.registerContentScripts([
      {
        id: DETECT_ID,
        matches: ["http://*/*", "https://*/*"],
        js: ["detect.js"],
        runAt: "document_idle",
        allFrames: false,
      },
    ]);
  } else if ((!wanted || !granted) && registered.length > 0) {
    await chrome.scripting.unregisterContentScripts({ ids: [DETECT_ID] });
  }
}
syncWatch();

async function handle(message) {
  switch (message.type) {
    case "status":
      return nativeRequest("hello", {
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
      if (!tab) return { ok: false, error: { code: "no_tab" } };
      const reply = await nativeRequest("get_logins", { url: tab.url });
      return { ...reply, tab_url: tab.url };
    }

    case "fill": {
      const tab = await targetTab();
      if (!tab || tab.url !== message.url) {
        // the page changed between listing and clicking: never fill
        return { ok: false, error: { code: "url_changed" } };
      }
      const reply = await nativeRequest("get_secret", {
        entry_id: message.entryId,
        url: message.url,
      });
      if (!reply.ok) return reply;
      const { username, password } = reply.result;
      const [outcome] = await chrome.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [0] },
        func: fillLogin,
        args: [username, password],
      });
      return { ok: true, result: outcome.result };
    }

    case "lock":
      return nativeRequest("lock", {});

    case "unlock":
      return nativeRequest("show_unlock", {});

    case "save_login":
      return nativeRequest("save_login", {
        url: message.url,
        username: message.username,
        password: message.password,
        title: message.title || null,
      });

    case "generate":
      return nativeRequest("generate_password", {});

    case "pending_save":
      return { ok: true, result: await pendingCandidate() };

    case "login_submitted": {
      // from detect.js, only while "watch for logins" is on
      await store.sessionSet({
        pending_save: {
          url: message.url,
          username: message.username,
          password: message.password,
          at: Date.now(),
        },
      });
      await chrome.action.setBadgeText({ text: "1" });
      await chrome.action.setBadgeBackgroundColor({ color: "#2f6f4f" });
      return { ok: true };
    }

    case "resolve_save": {
      const candidate = await pendingCandidate();
      if (!candidate) return { ok: false, error: { code: "no_candidate" } };
      if (message.action === "dismiss") {
        await clearCandidate();
        return { ok: true };
      }
      if (message.action === "save") {
        const reply = await nativeRequest("save_login", {
          url: candidate.url,
          username: candidate.username,
          password: candidate.password,
          title: message.title || null,
        });
        if (reply.ok) await clearCandidate();
        return reply;
      }
      if (message.action === "update") {
        const reply = await nativeRequest("update_password", {
          entry_id: message.entryId,
          url: candidate.url,
          new_password: candidate.password,
        });
        if (reply.ok) await clearCandidate();
        return reply;
      }
      return { ok: false, error: { code: "bad_request" } };
    }

    case "watch_on":
      await store.set({ watch_logins: true });
      await syncWatch();
      return { ok: true };

    case "watch_off":
      await store.set({ watch_logins: false });
      await syncWatch();
      return { ok: true };

    default:
      return { ok: false, error: { code: "bad_request" } };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handle(message).then(sendResponse);
  return true; // keep the channel open for the async reply
});
