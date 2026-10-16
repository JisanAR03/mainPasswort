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

export function fillLogin(username, password) {
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

  const set = (element, value) => {
    element.focus();
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  };

  const textish = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type])';
  const isUsernameHint = (field) =>
    field.autocomplete === "username" || field.autocomplete === "email" || field.type === "email";

  // The field the in-page menu was opened for, when the fill came from there;
  // absent for a fill started from the toolbar popup.
  const hint = globalThis.__personalVaultField;
  const anchor =
    hint instanceof HTMLInputElement && hint.isConnected && visible(hint) ? hint : null;

  let passwordField = null;
  if (anchor && anchor.type === "password") {
    passwordField = anchor;
  } else {
    const scope = (anchor && anchor.form) || document;
    passwordField = [...scope.querySelectorAll('input[type="password"]')].filter(visible)[0] || null;
  }

  // The username field: the chosen field itself, else the nearest visible
  // text-ish field before the password, preferring the autocomplete marker
  // browsers use. A username-only screen (the first step of a two-step login)
  // has no password field; then the first visible username-like field.
  let usernameField = null;
  if (anchor && anchor.type !== "password") {
    usernameField = anchor;
  } else if (passwordField) {
    const scope = passwordField.form || document;
    const before = [...scope.querySelectorAll(textish)]
      .filter(visible)
      .filter(
        (field) => field.compareDocumentPosition(passwordField) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    usernameField = before.find(isUsernameHint) || before[before.length - 1] || null;
  } else {
    usernameField =
      [...document.querySelectorAll(textish)].filter(visible).find(isUsernameHint) || null;
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
