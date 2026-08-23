// API base URL. Empty string = same-origin (default: this frontend is served
// by the Flask app itself, see app/__init__.py). If you host the frontend
// separately (e.g. a static host), point this at the deployed backend URL:
//   const API_BASE = 'https://your-api.onrender.com';
const API_BASE = '';

function getToken() {
  return localStorage.getItem('token');
}
function setToken(token) {
  localStorage.setItem('token', token);
}
function clearToken() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
}
function getUser() {
  try {
    return JSON.parse(localStorage.getItem('user'));
  } catch {
    return null;
  }
}
function setUser(user) {
  localStorage.setItem('user', JSON.stringify(user));
}
function isLoggedIn() {
  return !!getToken();
}

/**
 * Thin fetch() wrapper for the JSON API. Throws on non-2xx with `.status`
 * and `.data` (the parsed error body, shaped {error, message} by the backend)
 * attached, so callers can show `err.message` directly.
 */
async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    const err = new Error('Could not reach the server. Is the API running?');
    err.status = 0;
    throw err;
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    // no/invalid JSON body — fine for e.g. 204s
  }

  if (!res.ok) {
    const message = (data && (data.message || data.error)) || `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/** Where a freshly logged-in/registered user should land, absent a `next` param. */
function landingPageFor(role) {
  if (role === 'organiser') return '/organiser.html';
  if (role === 'admin') return '/admin.html';
  return '/index.html';
}

/** Redirect to login if not authenticated, optionally gating by role. Returns the user or null (after redirecting). */
function requireAuth(role) {
  const user = getUser();
  if (!isLoggedIn() || !user) {
    location.href = `/login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
    return null;
  }
  if (role && user.role !== role) {
    showAlert(`This page is for ${role}s only. You're signed in as a ${user.role}.`, 'error');
    return null;
  }
  return user;
}

/** Show a dismiss-on-next-call alert inside a container with id="alertBox". */
function showAlert(message, kind = 'error', containerId = 'alertBox') {
  const box = document.getElementById(containerId);
  if (!box) {
    console.warn('showAlert: no #' + containerId + ' on this page:', message);
    return;
  }
  box.innerHTML = `<div class="alert alert-${kind === 'error' ? 'error' : kind}">${escapeHtml(message)}</div>`;
}
function clearAlert(containerId = 'alertBox') {
  const box = document.getElementById(containerId);
  if (box) box.innerHTML = '';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

function formatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  return d.toLocaleString(undefined, {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function formatMoney(n) {
  if (n === null || n === undefined) return '—';
  return `₹${Number(n).toFixed(2)}`;
}
