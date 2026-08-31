/**
 * Shared helpers used across pages.
 */

/**
 * Escape HTML special characters so untrusted strings can be safely
 * interpolated into innerHTML template strings. Always use this for any
 * value that isn't a fixed literal -- peer display names, filenames, and
 * server error messages (which can echo back attacker-supplied input, e.g.
 * a firewall-rules parser quoting the offending line) are all untrusted.
 *
 * @param {*} value
 * @returns {string}
 */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Wrapper around fetch() that attaches the CSRF token header required by
 * Flask-WTF's CSRFProtect for state-changing requests (POST/PUT/PATCH/DELETE).
 * Safe to use for GET requests too -- the extra header is simply ignored.
 *
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<Response>}
 */
function fetchWithCsrf(url, options) {
  options = options || {};
  const headers = new Headers(options.headers || {});
  if (!headers.has('X-CSRFToken')) {
    headers.set('X-CSRFToken', window.CSRF_TOKEN);
  }
  options.headers = headers;
  return fetch(url, options);
}

/**
 * Shorten a WireGuard public key for display (e.g. in tables/lists),
 * keeping enough of both ends to stay visually distinguishable.
 *
 * @param {string} key
 * @returns {string}
 */
function shortKey(key) {
  if (!key || key.length <= 16) return key;
  return key.slice(0, 8) + '…' + key.slice(-8);
}

/**
 * Read the shared per-peer RX/TX perspective map from localStorage.
 * Keyed by peer public_key; a truthy entry means "show this peer's
 * Throughput chart from its own point of view" (its RX = what it
 * received = what the server sent) instead of the server's default
 * point of view. Set from the Options page; read from the dashboard.
 *
 * @returns {Object<string, boolean>}
 */
function loadPeerPerspectiveMap() {
  try {
    return JSON.parse(localStorage.getItem('rxTxPeerPerspective') || '{}');
  } catch (e) {
    return {};
  }
}

/**
 * Persist the per-peer RX/TX perspective map to localStorage.
 *
 * @param {Object<string, boolean>} map
 */
function savePeerPerspectiveMap(map) {
  localStorage.setItem('rxTxPeerPerspective', JSON.stringify(map));
}
