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
