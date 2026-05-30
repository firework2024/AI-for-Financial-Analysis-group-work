/** FinAgent 登录 / 注册 */

const AUTH_TOKEN_KEY = "finagent_token";

const authState = {
  user: null,
  token: null,
  ready: false,
};

function getAuthToken() {
  return authState.token || localStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function setAuthToken(token) {
  authState.token = token || "";
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function showAuthGate(mode = "login") {
  const gate = document.getElementById("authGate");
  if (!gate) return;
  gate.classList.remove("hidden");
  document.getElementById("authLoginPanel")?.classList.toggle("hidden", mode !== "login");
  document.getElementById("authRegisterPanel")?.classList.toggle("hidden", mode !== "register");
  document.body.classList.add("auth-locked");
}

function hideAuthGate() {
  document.getElementById("authGate")?.classList.add("hidden");
  document.body.classList.remove("auth-locked");
}

function renderAuthUser() {
  const label = document.getElementById("railUserLabel");
  const logoutBtn = document.getElementById("railLogoutBtn");
  if (label) label.textContent = authState.user?.username ? `@${authState.user.username}` : "";
  if (logoutBtn) logoutBtn.classList.toggle("hidden", !authState.user);
}

async function authFetch(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const headers = authHeaders(isForm ? {} : { "Content-Type": "application/json", ...(options.headers || {}) });
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch (_e) {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

async function fetchCurrentUser() {
  try {
    const payload = await authFetch("/api/auth/me");
    authState.user = payload.user;
    authState.ready = true;
    afterAuthSuccess();
    return authState.user;
  } catch (_error) {
    authState.user = null;
    authState.ready = false;
    setAuthToken("");
    showAuthGate("login");
    return null;
  }
}

function afterAuthSuccess() {
  renderAuthUser();
  hideAuthGate();
  if (typeof window.loadUserSettings === "function") {
    window.loadUserSettings().catch(() => {});
  }
}

async function login(username, password) {
  const payload = await authFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuthToken(payload.token);
  authState.user = payload.user;
  authState.ready = true;
  afterAuthSuccess();
  return payload.user;
}

async function register(username, password) {
  const payload = await authFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setAuthToken(payload.token);
  authState.user = payload.user;
  authState.ready = true;
  afterAuthSuccess();
  return payload.user;
}

async function logout() {
  try {
    await authFetch("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
  } catch (_e) {}
  setAuthToken("");
  authState.user = null;
  authState.ready = false;
  renderAuthUser();
  if (typeof window.resetChatState === "function") window.resetChatState();
  showAuthGate("login");
}

async function ensureAuth() {
  const cached = getAuthToken();
  if (cached) authState.token = cached;
  if (authState.user) return authState.user;
  if (!cached) {
    showAuthGate("login");
    authState.ready = false;
    return null;
  }
  return fetchCurrentUser();
}

function bindAuthEvents() {
  document.getElementById("authLoginForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const username = document.getElementById("authLoginUsername")?.value?.trim();
    const password = document.getElementById("authLoginPassword")?.value || "";
    login(username, password)
      .then(() => window.onAuthReady?.())
      .catch((error) => window.App?.toast?.(error.message, "error"));
  });
  document.getElementById("authRegisterForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const username = document.getElementById("authRegisterUsername")?.value?.trim();
    const password = document.getElementById("authRegisterPassword")?.value || "";
    register(username, password)
      .then(() => window.onAuthReady?.())
      .catch((error) => window.App?.toast?.(error.message, "error"));
  });
  document.getElementById("authShowRegister")?.addEventListener("click", () => showAuthGate("register"));
  document.getElementById("authShowLogin")?.addEventListener("click", () => showAuthGate("login"));
  document.getElementById("railLogoutBtn")?.addEventListener("click", () => {
    logout().catch(() => {});
  });
}

window.Auth = {
  state: authState,
  getAuthToken,
  authHeaders,
  ensureAuth,
  login,
  register,
  logout,
  fetchCurrentUser,
  renderAuthUser,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindAuthEvents);
} else {
  bindAuthEvents();
}
