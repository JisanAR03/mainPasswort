// Reading a CSV export from another password manager ([S]: it parses hostile
// input that ends up in the vault). No dependency: a small RFC 4180 reader
// (quoted fields, doubled quotes, commas and line breaks inside quotes, CRLF, LF
// or CR, a leading byte-order mark), and a column mapper that knows the headers
// the common exporters use (Chrome/Brave/Edge, Firefox, Bitwarden, 1Password,
// LastPass, KeePassXC and similar). Nothing here logs or echoes a value.

export const MAX_CSV_CHARS = 8 * 1024 * 1024;
export const MAX_CSV_ROWS = 10000;

// Header names that mean each field, best first.
const COLUMNS = {
  title: ["name", "title", "site name", "entry", "account name"],
  url: ["url", "login_uri", "website", "web site", "web address", "site", "origin", "address"],
  username: ["username", "login_username", "login username", "user name", "user", "login", "email"],
  password: ["password", "login_password", "pass"],
  notes: ["notes", "note", "extra", "comments", "comment"],
  otp: ["totp", "login_totp", "otpauth", "otp", "one-time password", "2fa"],
};

// All the rows of a CSV text as arrays of strings, or null when it is malformed
// (an unterminated quote).
export function parseCsv(input) {
  const text = input.charCodeAt(0) === 0xfeff ? input.slice(1) : input;
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  let i = 0;
  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    if (row.length > 1 || row[0] !== "") rows.push(row); // a blank line is not a row
    row = [];
  };
  while (i < text.length) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"' && field === "") {
      quoted = true;
    } else if (char === ",") {
      endField();
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      endRow();
    } else {
      field += char;
    }
    i += 1;
  }
  if (quoted) return null;
  if (field !== "" || row.length) endRow();
  return rows;
}

function columnIndexes(header) {
  const names = header.map((cell) => cell.trim().toLowerCase());
  const found = {};
  for (const [field, synonyms] of Object.entries(COLUMNS)) {
    for (const synonym of synonyms) {
      const index = names.indexOf(synonym);
      if (index >= 0) {
        found[field] = index;
        break;
      }
    }
  }
  return found;
}

// "example.com" is a site too; anything that is not http(s) cannot be matched
// to a page and is dropped (the login itself is kept).
function webAddress(value) {
  const raw = value.trim();
  if (!raw) return null;
  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`;
  try {
    const url = new URL(candidate);
    return ["http:", "https:"].includes(url.protocol) && url.hostname ? `${url.origin}/` : null;
  } catch {
    return null;
  }
}

// The logins in a CSV text: { logins: [{ title, username, password, urls, notes,
// otp }], skipped } — or { error } with a code ("too_large", "malformed",
// "unrecognized", "too_many_rows"). Rows with no password and no username are
// blank and counted as skipped.
export function loginsFromCsv(text) {
  if (typeof text !== "string" || text.length === 0 || text.length > MAX_CSV_CHARS) {
    return { error: "too_large" };
  }
  const rows = parseCsv(text);
  if (rows === null) return { error: "malformed" };
  if (rows.length < 2) return { error: "unrecognized" };
  if (rows.length - 1 > MAX_CSV_ROWS) return { error: "too_many_rows" };
  const at = columnIndexes(rows[0]);
  if (at.password === undefined) return { error: "unrecognized" };
  const cell = (row, field) => (at[field] === undefined ? "" : (row[at[field]] || "").trim());
  const logins = [];
  let skipped = 0;
  for (const row of rows.slice(1)) {
    const password = at.password === undefined ? "" : row[at.password] || "";
    const username = cell(row, "username");
    if (!password && !username) {
      skipped += 1;
      continue;
    }
    const address = webAddress(cell(row, "url"));
    const title = cell(row, "title") || (address ? new URL(address).host : "") || username || "Imported login";
    logins.push({
      title: title.slice(0, 200),
      username,
      password,
      urls: address ? [address] : [],
      notes: cell(row, "notes"),
      otp: cell(row, "otp"),
    });
  }
  return { logins, skipped };
}
