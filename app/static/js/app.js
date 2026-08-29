/**
 * Shared helpers used across pages.
 */

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
