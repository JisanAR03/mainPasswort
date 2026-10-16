// The save detector ([S]).
//
// A content script in the top frame of every http(s) page (never in iframes).
// It notices a submitted login and hands the username and password to the
// service worker, which decides whether to offer Save or Update and shows the
// prompt. It shows nothing and keeps nothing itself; the service worker drops
// the candidate when "Offer to save logins" is off, the site is on the
// "never" list, or the page is plain http.
//
// A login counts as submitted on any of: a form submit, Enter in a login
// field, or a click on a sign-in button — the last one for pages that log in
// with fetch and never submit a form. A username sent on its own (the first
// screen of a two-step login) is handed over too, so the next screen's
// password can be paired with it. Only events the user caused count
// (isTrusted), so page script cannot raise a prompt by faking a submit.

(() => {
  if (window.top !== window) return;

  const SUBMIT_WORDS =
    /\b(log\s*-?\s*in|sign\s*-?\s*in|log\s*-?\s*on|sign\s*-?\s*on|submit|continue|next|anmelden|einloggen|weiter|connexion|entrar|iniciar)\b/i;
  const NOT_SUBMIT =
    /\b(show|hide|reveal|toggle|view|forgot|reset|cancel|back|sign\s*-?\s*up|register|create)\b/i;
  const USERNAME_HINT = /user|email|e-mail|login|account|identifier|phone|mobile/i;
  const TEXTISH = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type])';
  const BUTTONISH =
    'button, input[type="submit"], input[type="button"], input[type="image"], [role="button"]';

  function passwordIn(scope) {
    const fields = [...scope.querySelectorAll('input[type="password"]')].filter((f) => f.value);
    // a change-password form: the new password is the one to keep
    return fields.find((f) => f.autocomplete === "new-password") || fields[0] || null;
  }

  function looksLikeUsername(field) {
    const autocomplete = (field.autocomplete || "").toLowerCase();
    if (autocomplete.includes("username") || autocomplete === "email") return true;
    if (field.type === "email") return true;
    const hints = [field.name, field.id, field.getAttribute("aria-label"), field.placeholder];
    return USERNAME_HINT.test(hints.join(" "));
  }

  function usernameIn(scope, passwordField) {
    let fields = [...scope.querySelectorAll(TEXTISH)].filter((f) => f.value);
    if (passwordField) {
      fields = fields.filter(
        (f) => f.compareDocumentPosition(passwordField) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
      return fields.find(looksLikeUsername) || fields[fields.length - 1] || null;
    }
    return fields.find(looksLikeUsername) || null;
  }

  // The part of the page that holds the login: the form, or — for pages with
  // no <form> — the nearest ancestor that also holds a password field.
  function scopeOf(element) {
    if (element.form) return element.form;
    let node = element;
    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
      if (node.querySelector('input[type="password"]')) return node;
    }
    return element.closest("form") || document.body;
  }

  function send(message) {
    try {
      chrome.runtime.sendMessage(message).catch(() => {});
    } catch {
      // the extension was reloaded under this page; nothing to report to
    }
  }

  function capture(scope) {
    if (!scope) return;
    const password = passwordIn(scope);
    if (password) {
      const user = usernameIn(scope, password);
      send({ type: "login_submitted", username: user ? user.value : "", password: password.value });
      return;
    }
    const user = usernameIn(scope, null);
    if (user) send({ type: "username_submitted", username: user.value });
  }

  document.addEventListener(
    "submit",
    (event) => {
      if (event.isTrusted && event.target instanceof HTMLFormElement) capture(event.target);
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (!event.isTrusted || event.key !== "Enter") return;
      const field = event.target;
      if (field instanceof HTMLInputElement && (field.type === "password" || looksLikeUsername(field))) {
        capture(scopeOf(field));
      }
    },
    true,
  );

  document.addEventListener(
    "click",
    (event) => {
      if (!event.isTrusted || !(event.target instanceof Element)) return;
      const button = event.target.closest(BUTTONISH);
      if (!button) return;
      const label = [
        button.innerText,
        button.value,
        button.getAttribute("aria-label"),
        button.title,
        button.id,
        button.name,
      ].join(" ");
      if (NOT_SUBMIT.test(label)) return;
      if (button.type === "submit" || SUBMIT_WORDS.test(label)) capture(scopeOf(button));
    },
    true,
  );
})();
