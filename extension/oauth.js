// Google sign-in for extension-only mode ([S]: everything here is a token path).
//
// chrome.identity.launchWebAuthFlow with the owner's own Google "Web
// application" OAuth client (its ID is set in the vault page's settings; the
// redirect URI to register is chrome.identity.getRedirectURL()). It asks for
// drive.file alone — the scope the desktop app uses.
//
// No refresh token and no client secret exist here: the flow returns an
// access token (about an hour), kept in chrome.storage.session under
// drive_token:<profileId> and dropped on lock. When it runs out it is renewed
// silently (prompt=none, login_hint = the profile's account) while the
// browser is signed in to that Google account; when that fails, the caller
// shows "the sign-in needs renewing". Nothing here logs, so no token can reach
// a console or an error message.
import { DRIVE_SCOPE, GOOGLE_AUTH_URL } from "./config.js";

const RENEW_MARGIN_MS = 60 * 1000;

export class AuthError extends Error {
  constructor(code) {
    super(code);
    this.code = code; // no_client_id | sign_in_cancelled | reconnect | wrong_scope
  }
}

const tokenKey = (profileId) => `drive_token:${profileId}`;

function randomState() {
  const raw = crypto.getRandomValues(new Uint8Array(16));
  return [...raw].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function clientId() {
  const { settings = {} } = await chrome.storage.local.get("settings");
  const id = typeof settings.googleClientId === "string" ? settings.googleClientId.trim() : "";
  if (!id) throw new AuthError("no_client_id");
  return id;
}

async function authorize(profileId, { interactive, loginHint }) {
  const state = randomState();
  const params = {
    client_id: await clientId(),
    response_type: "token",
    redirect_uri: chrome.identity.getRedirectURL(),
    scope: DRIVE_SCOPE,
    include_granted_scopes: "true",
    prompt: interactive ? "select_account" : "none",
    state,
  };
  if (loginHint) params.login_hint = loginHint;
  const url = `${GOOGLE_AUTH_URL}?${new URLSearchParams(params)}`;
  let responseUrl;
  try {
    responseUrl = await chrome.identity.launchWebAuthFlow({ url, interactive });
  } catch {
    throw new AuthError(interactive ? "sign_in_cancelled" : "reconnect");
  }
  const reply = new URLSearchParams(new URL(responseUrl).hash.slice(1));
  // the state must come back unchanged, or this is not the reply to our request
  if (reply.get("state") !== state || reply.get("error") || !reply.get("access_token")) {
    throw new AuthError(interactive && reply.get("error") === "access_denied" ? "sign_in_cancelled" : "reconnect");
  }
  const granted = (reply.get("scope") || DRIVE_SCOPE).split(" ");
  if (!granted.includes(DRIVE_SCOPE)) throw new AuthError("wrong_scope");
  const lifetime = Number(reply.get("expires_in")) || 3600;
  const token = reply.get("access_token");
  await chrome.storage.session.set({
    [tokenKey(profileId)]: { token, expiresAt: Date.now() + lifetime * 1000 },
  });
  return token;
}

// Interactive sign-in from the vault page (a click there).
export async function signIn(profileId) {
  return authorize(profileId, { interactive: true });
}

// A usable access token for this profile, renewing it silently if needed.
export async function accessToken(profileId, accountEmail) {
  const key = tokenKey(profileId);
  const { [key]: stored } = await chrome.storage.session.get(key);
  if (stored && stored.expiresAt - RENEW_MARGIN_MS > Date.now()) return stored.token;
  return authorize(profileId, { interactive: false, loginHint: accountEmail || undefined });
}

export async function dropToken(profileId) {
  await chrome.storage.session.remove(tokenKey(profileId));
}
