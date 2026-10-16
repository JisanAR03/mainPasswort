// The in-page part of the extension ([S]): the suggestion menu under a login
// field, and the "Save this login?" prompt in the page's corner.
//
// A content script in the top frame of every http(s) page (never in iframes).
// It decides only *where* to show things. What they show — titles, usernames,
// the site of a login to save — lives in two extension pages (menu.html,
// prompt.html) that this script places in iframes inside a closed shadow
// root: the page's own scripts can neither reach the shadow root nor read a
// frame of another origin, so no vault data ever enters the page. This
// script itself never sees a title, a username or a password; the service
// worker hands it only a one-time token for each frame and the frame's
// height. A fill is started by your click inside the menu frame, which the
// page cannot fake.

(() => {
  if (window.top !== window) return;

  const MENU_URL = chrome.runtime.getURL("menu.html");
  const PROMPT_URL = chrome.runtime.getURL("prompt.html");
  const MENU_WIDTH = 300;
  const PROMPT_WIDTH = 340;
  const PROMPT_HEIGHT = 168;
  const PROMPT_TTL_MS = 2 * 60 * 1000;
  const USERNAME_HINT = /user|email|e-mail|login|account|identifier|phone|mobile/i;

  const host = document.createElement("personal-vault");
  const shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  // !important on :host wins over any page rule aimed at the host element
  style.textContent = `
    :host { all: initial !important; position: fixed !important; top: 0 !important;
      left: 0 !important; width: 0 !important; height: 0 !important; display: block !important;
      opacity: 1 !important; visibility: visible !important; z-index: 2147483647 !important; }
    iframe { position: fixed; border: 0; border-radius: 8px; background: transparent;
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.22); color-scheme: normal; }
  `;
  shadow.append(style);

  let menu = null; // { frame, field, token }
  let opening = null; // the field a menu is being asked for
  let prompt = null; // { frame, token, timer }
  let openSeq = 0;
  let placing = false;

  function request(message) {
    try {
      return chrome.runtime.sendMessage(message).catch(() => null);
    } catch {
      return Promise.resolve(null); // the extension was reloaded under this page
    }
  }

  function attach(frame) {
    shadow.append(frame);
    if (!host.isConnected) document.documentElement.append(host);
  }

  function visible(element) {
    if (!element.isConnected || element.disabled || element.readOnly) return false;
    const css = getComputedStyle(element);
    if (css.display === "none" || css.visibility === "hidden" || Number(css.opacity) === 0) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isPassword(field) {
    return field instanceof HTMLInputElement && field.type === "password";
  }

  function isUsername(field) {
    if (!(field instanceof HTMLInputElement)) return false;
    if (!["text", "email", "tel"].includes(field.type)) return false;
    const autocomplete = (field.autocomplete || "").toLowerCase();
    if (autocomplete.includes("username") || autocomplete === "email" || field.type === "email") {
      return true;
    }
    const hints = [field.name, field.id, field.getAttribute("aria-label"), field.placeholder];
    return USERNAME_HINT.test(hints.join(" "));
  }

  function passwordNear(field) {
    return Boolean((field.form || document).querySelector('input[type="password"]'));
  }

  // set by fill.js, in this same isolated world, while it moves focus
  function filling() {
    return globalThis.__personalVaultFilling === true;
  }

  // --- the suggestion menu -------------------------------------------------

  function place() {
    if (!menu) return;
    if (!visible(menu.field)) {
      closeMenu();
      return;
    }
    const rect = menu.field.getBoundingClientRect();
    const height = Number.parseFloat(menu.frame.style.height);
    const width = Math.min(Math.max(rect.width, MENU_WIDTH), 380);
    const left = Math.min(Math.max(rect.left, 8), Math.max(window.innerWidth - width - 8, 8));
    let top = rect.bottom + 4;
    if (top + height > window.innerHeight && rect.top - height - 4 > 0) top = rect.top - height - 4;
    Object.assign(menu.frame.style, { left: `${left}px`, top: `${top}px`, width: `${width}px` });
  }

  function schedulePlace() {
    if (placing || !menu) return;
    placing = true;
    requestAnimationFrame(() => {
      placing = false;
      place();
    });
  }

  async function openMenu(field) {
    if ((menu && menu.field === field) || opening === field) return;
    closeMenu();
    const seq = ++openSeq;
    const password = isPassword(field);
    opening = field;
    const reply = await request({
      type: "menu_open",
      field: password ? "password" : "username",
      password_nearby: password || passwordNear(field),
    });
    if (opening === field) opening = null;
    // a later focus, or the field losing focus meanwhile, wins
    if (seq !== openSeq || !reply || !reply.show || document.activeElement !== field) {
      if (reply && reply.token) request({ type: "menu_close", token: reply.token });
      return;
    }
    const frame = document.createElement("iframe");
    frame.src = `${MENU_URL}#${reply.token}`;
    frame.title = "Personal Vault";
    frame.style.height = `${reply.height}px`;
    attach(frame);
    menu = { frame, field, token: reply.token };
    globalThis.__personalVaultField = field; // read by fill.js, in this same isolated world
    place();
  }

  function closeMenu() {
    openSeq += 1;
    if (!menu) return;
    const { frame, token } = menu;
    menu = null;
    globalThis.__personalVaultField = null;
    frame.remove();
    request({ type: "menu_close", token });
  }

  function considerField(field) {
    if (filling() || !(field instanceof HTMLInputElement) || !visible(field)) return;
    if (isPassword(field) || isUsername(field)) openMenu(field);
  }

  document.addEventListener(
    "focusin",
    (event) => {
      if (event.isTrusted) considerField(event.target);
    },
    true,
  );

  // a click on a field that already has focus (after Escape, say) reopens it
  document.addEventListener(
    "click",
    (event) => {
      if (event.isTrusted && !menu && event.target === document.activeElement) {
        considerField(event.target);
      }
    },
    true,
  );

  document.addEventListener(
    "focusout",
    () => {
      // focus moving into the menu frame shows up as focus on our host element
      setTimeout(() => {
        if (menu && document.activeElement !== menu.field && document.activeElement !== host) {
          closeMenu();
        }
      }, 150);
    },
    true,
  );

  // typing means you are not using the menu: close it (and drop a menu still
  // being asked for, which closeMenu does too), so it never covers the site's
  // own button while you type
  document.addEventListener(
    "input",
    (event) => {
      if (!event.isTrusted || filling()) return;
      if (opening === event.target || (menu && menu.field === event.target)) closeMenu();
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (!menu || event.target !== menu.field) return;
      if (event.key === "Escape") closeMenu();
      if (event.key === "ArrowDown") {
        event.preventDefault();
        menu.frame.focus();
      }
    },
    true,
  );

  window.addEventListener("scroll", schedulePlace, { capture: true, passive: true });
  window.addEventListener("resize", schedulePlace, { passive: true });

  // --- the save / update prompt --------------------------------------------

  function showPrompt(token) {
    if (prompt && prompt.token === token) return;
    closePrompt();
    const frame = document.createElement("iframe");
    frame.src = `${PROMPT_URL}#${token}`;
    frame.title = "Personal Vault";
    Object.assign(frame.style, {
      top: "12px",
      right: "12px",
      width: `${PROMPT_WIDTH}px`,
      height: `${PROMPT_HEIGHT}px`,
    });
    attach(frame);
    // the offer lapses with the candidate it is for
    prompt = { frame, token, timer: setTimeout(closePrompt, PROMPT_TTL_MS) };
  }

  function closePrompt() {
    if (!prompt) return;
    clearTimeout(prompt.timer);
    prompt.frame.remove();
    prompt = null;
  }

  // --- messages from the service worker ------------------------------------

  chrome.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== chrome.runtime.id || !message) return;
    if (message.type === "menu_close") closeMenu();
    if (message.type === "prompt_show" && typeof message.token === "string") {
      showPrompt(message.token);
    }
    if (message.type === "prompt_close") closePrompt();
  });

  // --- on load: a pending offer from the page before (a login that navigated),
  // and a login field that already had focus when this script arrived
  request({ type: "prompt_open" }).then((reply) => {
    if (reply && reply.show) showPrompt(reply.token);
  });
  considerField(document.activeElement);
})();
