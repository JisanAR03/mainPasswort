// The sync decision table for extension-only mode ([S]): a line-by-line port of
// app/src/personal_vault/sync/decide.py, so the extension follows the desktop
// app's rules rather than a second rulebook. The e2e parity test feeds both
// the same generated table of inputs and fails on any difference (I13).
//
// decide(local, remote, state) has no network, no storage and no clock. An
// upload is only ever chosen for a remote version the state has already seen
// (I6).
//
// local  = { exists, sha256, md5, dirty }
// remote = { exists, trashed, md5, version }
// state  = { last_synced_remote_md5, last_synced_local_sha256 } or null

export const Action = Object.freeze({
  NOTHING: "nothing",
  UPDATE_STATE: "update_state",
  UPLOAD: "upload",
  DOWNLOAD: "download",
  CONFLICT: "conflict",
  ASK: "ask", // the remote copy is missing or trashed: never recreate silently
  ASK_FIRST_LINK: "ask_first_link", // ADR-010: a file is on Drive, this device has no state
});

const localChanged = (local, state) =>
  local.dirty || local.sha256 !== state.last_synced_local_sha256;

const remoteChanged = (remote, state) => remote.md5 !== state.last_synced_remote_md5;

export function decide(local, remote, state) {
  if (!local.exists) return Action.ASK; // the vault cannot be read: never upload, never adopt

  if (state === null) {
    // a file is already there and we have no history — the owner chooses; a
    // trashed one is still "there", so it asks rather than recreating it
    if (remote.exists || remote.trashed) return Action.ASK_FIRST_LINK;
    return Action.UPLOAD;
  }

  if (!remote.exists || remote.trashed) return Action.ASK;

  if (local.md5 !== null && local.md5 === remote.md5) {
    // same bytes on both sides, whatever changed to get there
    if (localChanged(local, state) || remoteChanged(remote, state)) return Action.UPDATE_STATE;
    return Action.NOTHING;
  }

  const local_ = localChanged(local, state);
  const remote_ = remoteChanged(remote, state);
  if (local_ && remote_) return Action.CONFLICT;
  if (local_) return Action.UPLOAD;
  if (remote_) return Action.DOWNLOAD;
  return Action.NOTHING;
}
