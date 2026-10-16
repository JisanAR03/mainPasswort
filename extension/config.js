// Constants for extension-only mode, in one place so the e2e test copy can point
// them at a fake Google and shorten timers — the way weak KDF settings exist
// only in test fixtures. test_ext_basics asserts the shipped values.

// An unlock lasts this long at most, or until the browser closes (ADR-012).
export const UNLOCK_HOURS = 6;

// Vault strength (docs/specs/data-model.md, D9): Argon2id, 128 MiB, 2 lanes,
// iterations calibrated so one unlock takes about a second here. A vault with
// less memory than the minimum is never created.
export const KDF_MEMORY_MIB = 128;
export const KDF_MIN_MEMORY_MIB = 64;
export const KDF_PARALLELISM = 2;
export const KDF_TARGET_MS = 1000;
export const KDF_MIN_ITERATIONS = 2;

// Google endpoints — the same Drive API and scope the desktop app uses.
export const DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files";
export const DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files";
export const DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about";
export const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
export const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";

// Sync timing (docs/specs/sync.md): a quiet period after a save, an interval
// while unlocked, and a backoff schedule ending at a 30-minute cap.
export const UPLOAD_QUIET_MS = 10 * 1000;
export const SYNC_INTERVAL_MINUTES = 60;
export const BACKOFF_SECONDS = [30, 60, 120, 240, 480, 960, 1800];
