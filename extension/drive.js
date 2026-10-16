// Google Drive v3 for extension-only mode ([S]: the token path). A port of
// app/src/personal_vault/sync/drive_client.py: the same calls, the same
// "PersonalVault" folder, the same file name and the same appProperties
// ({pm_profile_id, pm_schema: "1"}), so the desktop app and the extension find
// and share the same files. It speaks about whole encrypted vault files only,
// and never logs, so neither a token nor a vault body can leak.
import { DRIVE_ABOUT_URL, DRIVE_FILES_URL, DRIVE_UPLOAD_URL } from "./config.js";

export const FOLDER_MIME = "application/vnd.google-apps.folder";
export const VAULT_SCHEMA = "1";
const FILE_FIELDS =
  "id,name,md5Checksum,version,size,trashed,modifiedTime,headRevisionId,parents,appProperties";

// code: auth_expired | quota | access_denied | missing | rate_limited | server |
// network | unreadable | bad_response; retryable ones are retried with backoff.
export class DriveError extends Error {
  constructor(code, retryable = false) {
    super(code);
    this.code = code;
    this.retryable = retryable;
  }
}

const escape = (value) => value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");

function remoteFile(item) {
  if (!item || typeof item.id !== "string") throw new DriveError("bad_response");
  const version = Number(item.version);
  return {
    id: item.id,
    name: typeof item.name === "string" ? item.name : "",
    md5: typeof item.md5Checksum === "string" ? item.md5Checksum : null,
    version: Number.isFinite(version) ? version : null,
    headRevisionId: typeof item.headRevisionId === "string" ? item.headRevisionId : null,
    trashed: item.trashed === true,
    parentId: Array.isArray(item.parents) && item.parents.length ? item.parents[0] : null,
  };
}

async function reasonOf(reply) {
  try {
    const body = await reply.json();
    const errors = (body && body.error && body.error.errors) || [];
    return errors.map((e) => e.reason || "").join(" ");
  } catch {
    return "";
  }
}

async function request(token, method, url, { params, body, headers } = {}) {
  const full = new URL(url);
  for (const [key, value] of Object.entries(params || {})) full.searchParams.set(key, value);
  let reply;
  try {
    reply = await fetch(full, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(headers || {}) },
      body,
      cache: "no-store",
    });
  } catch {
    throw new DriveError("network", true);
  }
  const { status } = reply;
  if (status === 401) throw new DriveError("auth_expired");
  if (status === 403) {
    const reason = await reasonOf(reply);
    if (/storageQuotaExceeded|quotaExceeded/.test(reason)) throw new DriveError("quota", true);
    if (/rateLimitExceeded|userRateLimitExceeded/.test(reason)) {
      throw new DriveError("rate_limited", true);
    }
    throw new DriveError("access_denied");
  }
  if (status === 404) throw new DriveError("missing");
  if (status === 429) throw new DriveError("rate_limited", true);
  if (status >= 500) throw new DriveError("server", true);
  if (status >= 400) throw new DriveError("bad_response");
  return reply;
}

async function json(reply) {
  try {
    return await reply.json();
  } catch {
    throw new DriveError("bad_response");
  }
}

async function list(token, query) {
  const reply = await request(token, "GET", DRIVE_FILES_URL, {
    params: { q: query, fields: `files(${FILE_FIELDS})`, spaces: "drive", pageSize: "10" },
  });
  const body = await json(reply);
  return Array.isArray(body.files) ? body.files : [];
}

// By appProperties, never by name; trashed files count as found.
export async function findVaultFile(token, profileId) {
  const match = `appProperties has { key='pm_profile_id' and value='${escape(profileId)}' }`;
  for (const trashed of ["false", "true"]) {
    const found = await list(token, `${match} and trashed = ${trashed}`);
    if (found.length) return remoteFile(found[0]);
  }
  return null;
}

// Every vault file this app's Google client can see (drive.file shows only
// those it created or was given), for "open a vault from Google Drive".
export async function listVaults(token) {
  const found = await list(token, `appProperties has { key='pm_schema' and value='${VAULT_SCHEMA}' } and trashed = false`);
  return found.map((item) => {
    const file = remoteFile(item);
    const props = item.appProperties || {};
    return {
      ...file,
      profileId: typeof props.pm_profile_id === "string" ? props.pm_profile_id : null,
      modifiedTime: typeof item.modifiedTime === "string" ? item.modifiedTime : null,
    };
  });
}

export async function ensureFolder(token, name) {
  const query = `name = '${escape(name)}' and mimeType = '${FOLDER_MIME}' and trashed = false`;
  const found = await list(token, query);
  if (found.length) return found[0].id;
  const reply = await request(token, "POST", DRIVE_FILES_URL, {
    params: { fields: "id" },
    headers: { "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify({ name, mimeType: FOLDER_MIME }),
  });
  const body = await json(reply);
  if (typeof body.id !== "string") throw new DriveError("bad_response");
  return body.id;
}

// Send exactly these bytes, as a new file or a new version of one.
export async function upload(token, { fileId, name, parentId, bytes, profileId }) {
  const metadata = { name, appProperties: { pm_profile_id: profileId, pm_schema: VAULT_SCHEMA } };
  if (!fileId) metadata.parents = [parentId];
  const boundary = `pv${crypto.getRandomValues(new Uint32Array(2)).join("")}`;
  const body = new Blob([
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n`,
    JSON.stringify(metadata),
    `\r\n--${boundary}\r\nContent-Type: application/octet-stream\r\n\r\n`,
    bytes,
    `\r\n--${boundary}--`,
  ]);
  const reply = await request(token, fileId ? "PATCH" : "POST", fileId ? `${DRIVE_UPLOAD_URL}/${fileId}` : DRIVE_UPLOAD_URL, {
    params: { uploadType: "multipart", fields: FILE_FIELDS },
    headers: { "Content-Type": `multipart/related; boundary=${boundary}` },
    body,
  });
  return remoteFile(await json(reply));
}

// A 404 is "missing": the file we synced against is gone.
export async function metadata(token, fileId) {
  const reply = await request(token, "GET", `${DRIVE_FILES_URL}/${fileId}`, { params: { fields: FILE_FIELDS } });
  return remoteFile(await json(reply));
}

async function media(token, url) {
  const reply = await request(token, "GET", url, { params: { alt: "media" } });
  try {
    return await reply.arrayBuffer();
  } catch {
    throw new DriveError("network", true);
  }
}

export const download = (token, fileId) => media(token, `${DRIVE_FILES_URL}/${fileId}`);

export const downloadRevision = (token, fileId, revisionId) =>
  media(token, `${DRIVE_FILES_URL}/${fileId}/revisions/${revisionId}`);

export async function listRevisions(token, fileId) {
  const reply = await request(token, "GET", `${DRIVE_FILES_URL}/${fileId}/revisions`, {
    params: { fields: "revisions(id,modifiedTime)", pageSize: "100" },
  });
  const body = await json(reply);
  const revisions = Array.isArray(body.revisions)
    ? body.revisions
        .filter((r) => r && typeof r.id === "string")
        .map((r, index) => ({ id: r.id, modifiedTime: r.modifiedTime || "", index }))
    : [];
  // Newest first, by time rather than by the API's order, which this code does
  // not rely on; ties keep the later-listed revision first.
  revisions.sort((a, b) => b.modifiedTime.localeCompare(a.modifiedTime) || b.index - a.index);
  return revisions.map(({ id }) => ({ id }));
}

export async function accountEmail(token) {
  const reply = await request(token, "GET", DRIVE_ABOUT_URL, { params: { fields: "user(emailAddress)" } });
  const body = await json(reply);
  return body && body.user && typeof body.user.emailAddress === "string" ? body.user.emailAddress : null;
}
