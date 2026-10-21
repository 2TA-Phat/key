/* TIST LAB: each physical browser tab has its own selector (not a password). */
(function () {
  'use strict';
  const key = 'TIST_TAB_SESSION_ID_V1';
  let id = '';
  // window.name survives F5 and same-tab navigation; newly opened tabs get new name.
  if (window.name && /^TIST_TAB_[a-f0-9]{32}$/.test(window.name)) {
    id = window.name.substring('TIST_TAB_'.length);
  } else {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    id = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    window.name = 'TIST_TAB_' + id;
  }
  sessionStorage.setItem(key, id);
  const internalURL = url => {
    const u = new URL(url, location.href);
    if (u.origin !== location.origin) return null;
    if (!/^https?:$/.test(u.protocol)) return null;
    u.searchParams.set('_tab', id);
    return u;
  };
  const current = new URL(location.href);
  if (current.searchParams.get('_tab') !== id) {
    current.searchParams.set('_tab', id);
    location.replace(current.href);
    return;
  }
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    // A <select name="action"> can shadow form.action.
    // Read the HTML attribute, and use the current URL for forms without action.
    const targetURL = form.getAttribute('action') || location.href;
    const u = internalURL(targetURL);
    if (u) form.setAttribute('action', u.href);
    let inp = form.querySelector('input[name="_tab"]');
    if (!inp) {
      inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = '_tab'; form.appendChild(inp);
    }
    inp.value = id;
  }, true);
  document.addEventListener('click', event => {
    const a = event.target.closest && event.target.closest('a[href]');
    if (!a || a.hasAttribute('download') || a.target === '_blank' || event.ctrlKey || event.metaKey) return;
    const u = internalURL(a.href);
    if (u) a.href = u.href;
  }, true);
  const nativeFetch = window.fetch;
  window.fetch = function (input, init) {
    const isRequest = input instanceof Request;
    const url = isRequest ? input.url : input;
    const u = internalURL(url);
    if (!u) return nativeFetch.call(this, input, init);
    const options = Object.assign({}, init || {});
    const headers = new Headers((options.headers) || (isRequest ? input.headers : undefined));
    headers.set('X-TIST-Tab', id);
    options.headers = headers;
    return nativeFetch.call(this, isRequest ? new Request(u.href, input) : u.href, options);
  };
})();
