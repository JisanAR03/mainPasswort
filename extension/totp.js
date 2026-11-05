// One-time codes (TOTP, RFC 6238) for the vault engine ([S]).
//
// The secret is stored in the entry's "otp" field the way KeePassXC stores it: an
// otpauth://totp/... URI (a bare Base32 secret is accepted and written as one).
// The HMAC is WebCrypto's; nothing here is cryptography of our own, only the
// counter, the truncation and the Base32 reading the RFCs describe. Tested
// against the RFC 6238 appendix B vectors (SHA-1, SHA-256, SHA-512).

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const ALGORITHMS = { SHA1: "SHA-1", SHA256: "SHA-256", SHA512: "SHA-512" };
const DEFAULT_PERIOD = 30;
const DEFAULT_DIGITS = 6;
const MAX_OTP_LENGTH = 2048;

// Base32 (RFC 4648), upper or lower case, spaces and dashes ignored, padding optional.
export function base32Decode(text) {
  const clean = text.replace(/[\s-]/g, "").replace(/=+$/, "").toUpperCase();
  if (!clean || /[^A-Z2-7]/.test(clean)) return null;
  const bytes = [];
  let buffer = 0;
  let bits = 0;
  for (const char of clean) {
    buffer = (buffer << 5) | BASE32.indexOf(char);
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((buffer >> bits) & 0xff);
      buffer &= (1 << bits) - 1;
    }
  }
  return bytes.length ? new Uint8Array(bytes) : null;
}

// What a stored value means: { secret, digits, period, algorithm, label, issuer },
// or null when it is not a usable time-based secret (HOTP and Steam are not
// supported, and a value that is not Base32 is not guessed at).
export function parseOtp(value) {
  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!raw || raw.length > MAX_OTP_LENGTH) return null;
  let secretText = raw;
  let digits = DEFAULT_DIGITS;
  let period = DEFAULT_PERIOD;
  let algorithm = "SHA1";
  let label = "";
  let issuer = "";
  if (/^otpauth:/i.test(raw)) {
    let url;
    try {
      url = new URL(raw);
    } catch {
      return null;
    }
    if (url.hostname.toLowerCase() !== "totp") return null;
    if (url.searchParams.get("encoder")) return null; // Steam and other custom encoders
    secretText = url.searchParams.get("secret") || "";
    digits = Number(url.searchParams.get("digits") || DEFAULT_DIGITS);
    period = Number(url.searchParams.get("period") || DEFAULT_PERIOD);
    algorithm = (url.searchParams.get("algorithm") || "SHA1").toUpperCase();
    issuer = url.searchParams.get("issuer") || "";
    label = decodeURIComponent(url.pathname.replace(/^\//, ""));
  }
  if (!ALGORITHMS[algorithm]) return null;
  if (!Number.isInteger(digits) || digits < 6 || digits > 8) return null;
  if (!Number.isInteger(period) || period < 1 || period > 300) return null;
  const secret = base32Decode(secretText);
  if (!secret) return null;
  return { secret, digits, period, algorithm, label, issuer };
}

// The stored form of a value the user typed: an otpauth URI. A bare secret gets
// the entry's title as its label.
export function normalizeOtp(value, label = "") {
  const parsed = parseOtp(value);
  if (!parsed) return null;
  if (/^otpauth:/i.test(value.trim())) return value.trim();
  const name = encodeURIComponent(label || "login");
  return `otpauth://totp/${name}?secret=${value.replace(/[\s-]/g, "").replace(/=+$/, "").toUpperCase()}`;
}

async function hotp(secret, counter, digits, algorithm) {
  const key = await crypto.subtle.importKey(
    "raw",
    secret,
    { name: "HMAC", hash: ALGORITHMS[algorithm] },
    false,
    ["sign"],
  );
  const message = new ArrayBuffer(8);
  new DataView(message).setBigUint64(0, BigInt(counter));
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, message));
  const offset = mac[mac.length - 1] & 0x0f;
  const binary =
    ((mac[offset] & 0x7f) << 24) | (mac[offset + 1] << 16) | (mac[offset + 2] << 8) | mac[offset + 3];
  return String(binary % 10 ** digits).padStart(digits, "0");
}

// The code for a stored value at `nowMs`, and how long it still holds.
export async function totpCode(value, nowMs = Date.now()) {
  const parsed = parseOtp(value);
  if (!parsed) return null;
  const seconds = Math.floor(nowMs / 1000);
  const counter = Math.floor(seconds / parsed.period);
  return {
    code: await hotp(parsed.secret, counter, parsed.digits, parsed.algorithm),
    period: parsed.period,
    digits: parsed.digits,
    remaining: parsed.period - (seconds % parsed.period),
  };
}
