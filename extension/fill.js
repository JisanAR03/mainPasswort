// The fill function the service worker injects into frame 0 after you click
// ([S]).
//
// It is serialized and run inside the page, so it must not reference anything
// outside itself. It fills only visible fields, fires input and change events,
// never submits, and keeps nothing: the password arrives as an argument and
// leaves with the page's DOM.

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

  const passwords = [...document.querySelectorAll('input[type="password"]')].filter(visible);
  if (passwords.length === 0) return { filled: false, reason: "no_password_field" };
  const passwordField = passwords[0];

  // The username field: the nearest visible text-ish field before the
  // password, preferring the autocomplete marker browsers use.
  const scope = passwordField.form || document;
  const fields = [...scope.querySelectorAll('input[type="text"], input[type="email"], input:not([type])')].filter(visible);
  const before = fields.filter(
    (field) => field.compareDocumentPosition(passwordField) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
  const usernameField =
    before.find((field) => field.autocomplete === "username" || field.autocomplete === "email") ||
    before[before.length - 1] ||
    null;

  if (usernameField && username) set(usernameField, username);
  set(passwordField, password);
  return { filled: true, username_filled: Boolean(usernameField && username) };
}
