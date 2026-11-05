// The fill function the service worker injects into frame 0 after you choose a
// login ([S]).
//
// It is serialized and run inside the page, in the extension's isolated world
// (the same one inline.js runs in, which the page's own scripts cannot see),
// so it must not reference anything outside itself except the two markers it
// shares with inline.js: the field the suggestion menu was opened for, and a
// flag that is set while this fill runs. It fills only visible fields, fires
// input and change events, never submits, and keeps nothing: the password
// arrives as an argument and leaves with the page's DOM.
//
// It finds fields inside OPEN shadow roots too (web components such as Reddit's
// login boxes), using its own copy of the walk in deep.js, which a serialized
// function cannot import: keep the two in step. A closed shadow root is out of
// reach by design.

export function fillLogin(username, password) {
  // Every element under `root` that matches `selector`, in page order, with an
  // open shadow root's contents listed right after its host. (Same walk as
  // deep.js.)
  const deepAll = (selector) => {
    const found = [];
    const walk = (scope) => {
      for (const element of scope.querySelectorAll("*")) {
        if (element.matches(selector)) found.push(element);
        if (element.shadowRoot) walk(element.shadowRoot);
      }
    };
    walk(document);
    return found;
  };

  const visible = (element) => {
    if (element.disabled || element.readOnly) return false;
    const style = getComputedStyle(element);
    if (style.display === "none") return false;
    if (style.visibility === "hidden" || style.visibility === "collapse") return false;
    if (Number.parseFloat(style.opacity) === 0) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    return true;
  };

  // `input` is composed, as a real keystroke's is, so a listener outside a shadow
  // root hears a fill into a field inside one; `change` is not, as the real one.
  const set = (element, value) => {
    element.focus();
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  };

  const textish = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type])';
  // "username", "email" and combinations such as "username webauthn"
  const isUsernameHint = (field) => {
    const tokens = (field.autocomplete || "").toLowerCase().split(/\s+/);
    return field.type === "email" || tokens.includes("username") || tokens.includes("email");
  };

  // The field the in-page menu was opened for, when the fill came from there;
  // absent for a fill started from the toolbar popup.
  const hint = globalThis.__personalVaultField;
  const anchor =
    hint instanceof HTMLInputElement && hint.isConnected && visible(hint) ? hint : null;

  let passwordField = null;
  if (anchor && anchor.type === "password") {
    passwordField = anchor;
  } else {
    const passwords = deepAll('input[type="password"]').filter(visible);
    const inForm = anchor && anchor.form ? passwords.filter((f) => f.form === anchor.form) : passwords;
    passwordField = inForm[0] || null;
  }

  // The username field: the chosen field itself, else the nearest visible
  // text-ish field before the password (nearest, so an unrelated field earlier on
  // the page does not win), preferring the autocomplete marker browsers use. The
  // order is the walk's, because compareDocumentPosition cannot order fields that
  // sit in different shadow roots. A username-only screen (the first step of a
  // two-step login) has no password field; then the first visible username-like
  // field.
  let usernameField = null;
  if (anchor && anchor.type !== "password") {
    usernameField = anchor;
  } else if (passwordField) {
    const ordered = deepAll(`${textish}, input[type="password"]`);
    const cut = ordered.indexOf(passwordField);
    let before = ordered.slice(0, cut < 0 ? ordered.length : cut);
    before = before.filter((field) => field.type !== "password" && visible(field));
    if (passwordField.form) before = before.filter((field) => field.form === passwordField.form);
    usernameField = [...before].reverse().find(isUsernameHint) || before[before.length - 1] || null;
  } else {
    usernameField = deepAll(textish).filter(visible).find(isUsernameHint) || null;
  }

  if (!passwordField && !usernameField) return { filled: false, reason: "no_login_field" };

  // inline.js ignores the focus changes this fill causes (they fire while the
  // flag is up), so the menu does not reopen on the field just filled
  globalThis.__personalVaultFilling = true;
  try {
    if (usernameField && username) set(usernameField, username);
    if (passwordField) set(passwordField, password);
  } finally {
    globalThis.__personalVaultFilling = false;
  }
  return {
    filled: true,
    username_filled: Boolean(usernameField && username),
    password_filled: Boolean(passwordField),
  };
}
