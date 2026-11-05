// Shadow-DOM-aware element search for the page scripts ([S]).
//
// Many sites (Reddit's login, for one) build their inputs inside web components
// whose contents live in a shadow root. document.querySelector cannot see into
// one, so without this the menu never opens on those fields and nothing is
// filled or captured. This script is loaded before detect.js and inline.js and
// shares its helpers with them through the extension's isolated world, which the
// page's own scripts cannot reach.
//
// It descends into OPEN shadow roots only. A closed root is deliberately out of
// reach: the browser hides it from page script and from this one, and the
// extension does not try to get around that.
//
// fill.js is serialized into the page by executeScript and cannot use this file;
// it carries its own copy of the same walk (keep the two in step).

(() => {
  // Every element under `root` (a document, a shadow root or an element) that
  // matches `selector`, in page order, with an open shadow root's contents listed
  // right after its host.
  function deepQueryAll(root, selector) {
    const found = [];
    const walk = (scope) => {
      for (const element of scope.querySelectorAll("*")) {
        if (element.matches(selector)) found.push(element);
        if (element.shadowRoot) walk(element.shadowRoot);
      }
    };
    if (root instanceof Element) {
      if (root.matches(selector)) found.push(root);
      if (root.shadowRoot) walk(root.shadowRoot);
    }
    walk(root);
    return found;
  }

  // The element that really has focus, even when it sits inside shadow roots
  // (document.activeElement stops at the outermost host).
  function deepActiveElement() {
    let element = document.activeElement;
    while (element && element.shadowRoot && element.shadowRoot.activeElement) {
      element = element.shadowRoot.activeElement;
    }
    return element;
  }

  // The element an event started on. A listener on the document sees an event
  // from inside a shadow root retargeted to the outermost host; composedPath()
  // still starts at the real target when the root is open.
  function eventTarget(event) {
    const path = event.composedPath ? event.composedPath() : [];
    return path.length ? path[0] : event.target;
  }

  // The nearest ancestor of `element` matching `selector`, climbing out of shadow
  // roots through their hosts (Element.closest stops at a shadow boundary).
  function composedClosest(element, selector) {
    let node = element;
    while (node) {
      if (node instanceof Element && node.matches(selector)) return node;
      node = node.parentNode instanceof ShadowRoot ? node.parentNode.host : node.parentNode;
    }
    return null;
  }

  // The parent of `element` in the composed tree: its parent element, or the host
  // when it is the top of a shadow root.
  function composedParent(element) {
    if (element.parentElement) return element.parentElement;
    const root = element.getRootNode();
    return root instanceof ShadowRoot ? root.host : null;
  }

  globalThis.__personalVaultDeep = {
    deepQueryAll,
    deepActiveElement,
    eventTarget,
    composedClosest,
    composedParent,
  };
})();
