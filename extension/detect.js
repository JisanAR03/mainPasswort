// The save detector ([S]).
//
// Registered as a content script only while you have turned on "watch for
// logins" and granted all-sites access; never part of the base install. It
// notices a submitted form with a password field and hands the candidate to
// the service worker, which holds it in memory for two minutes and shows a
// badge. Nothing is saved until you choose in the popup.

document.addEventListener(
  "submit",
  (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const password = form.querySelector('input[type="password"]');
    if (!password || !password.value) return;
    const user = form.querySelector(
      'input[autocomplete="username"], input[type="email"], input[type="text"]',
    );
    chrome.runtime.sendMessage({
      type: "login_submitted",
      url: location.href,
      username: user ? user.value : "",
      password: password.value,
    });
  },
  true,
);
