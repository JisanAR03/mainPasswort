// Site matching rules from docs/specs/data-model.md, for extension-only mode
// ([S]). A port of app/src/personal_vault/core/matching.py: the e2e parity test
// runs both on the same table of URLs, so there is one rulebook in two
// languages. Input is hostile, so every parse failure resolves to "no match".

// What urlsplit() reads out of an absolute URL: scheme, host, explicit port.
const AUTHORITY = /^([a-z][a-z0-9+.-]*):\/\/(?:[^@/?#]*@)?(\[[^\]]*\]|[^:/?#]*)(?::([^/?#]*))?/i;

// Returns { scheme, host, port } for http(s) URLs, or null.
export function parseSite(url) {
  if (typeof url !== "string") return null;
  const raw = AUTHORITY.exec(url.trim());
  if (!raw) return null;
  const scheme = raw[1].toLowerCase();
  if (scheme !== "http" && scheme !== "https") return null;
  let port = null;
  if (raw[3] !== undefined && raw[3] !== "") {
    if (!/^\d+$/.test(raw[3])) return null;
    port = Number(raw[3]);
    if (port > 65535) return null;
  }
  let host;
  try {
    // the browser's URL parser lower-cases and converts to punycode (rule 1)
    host = new URL(`${scheme}://${raw[2]}/`).hostname;
  } catch {
    return null;
  }
  host = host.replace(/^\[|\]$/g, "").replace(/\.+$/, "");
  if (!host) return null;
  return { scheme, host, port };
}

// Rules 2-5: exact host, subdomains only when the entry opts in, never a
// downgrade to http, and the port when the entry names one.
export function entryMatches(page, entry, matchSubdomains) {
  if (page.host !== entry.host && !(matchSubdomains && page.host.endsWith(`.${entry.host}`))) {
    return false;
  }
  if (entry.port !== null && page.port !== entry.port) return false;
  if (entry.scheme === "https" && page.scheme !== "https") return false;
  if (entry.scheme === "http" && page.scheme !== "http") return false;
  return true;
}

export function matchUrls(entryUrls, pageUrl, matchSubdomains) {
  const page = parseSite(pageUrl);
  if (!page) return false;
  for (const url of entryUrls) {
    const entry = parseSite(url);
    if (entry && entryMatches(page, entry, matchSubdomains)) return true;
  }
  return false;
}
