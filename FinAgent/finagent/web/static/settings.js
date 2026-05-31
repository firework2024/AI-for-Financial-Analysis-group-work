/** 用户 API 设置 */

const settingsEls = {};

function initSettingsElements() {
  Object.assign(settingsEls, {
    modal: document.getElementById("settingsModal"),
    form: document.getElementById("settingsForm"),
    status: document.getElementById("settingsStatus"),
    apiKey: document.getElementById("settingsApiKey"),
    baseUrl: document.getElementById("settingsBaseUrl"),
    model: document.getElementById("settingsModel"),
    chatMaxSteps: document.getElementById("settingsChatMaxSteps"),
    chatAgentMode: document.getElementById("settingsChatAgentMode"),
    openBtn: document.getElementById("openSettingsBtn"),
    mobileOpenBtn: document.getElementById("mobileSettingsBtn"),
    railOpenBtn: document.getElementById("railSettingsBtn"),
    closeBtn: document.getElementById("settingsClose"),
    testBtn: document.getElementById("settingsTestBtn"),
    clearKeyBtn: document.getElementById("settingsClearKeyBtn"),
  });
}

function showSettingsError(message) {
  if (window.App?.toast) {
    window.App.toast(message, "error");
    return;
  }
  const host = document.getElementById("toastHost");
  if (host) {
    const node = document.createElement("div");
    node.className = "toast error";
    node.textContent = message;
    host.appendChild(node);
    window.setTimeout(() => node.remove(), 4000);
    return;
  }
  window.alert(message);
}

function showSettingsMessage(message) {
  if (window.App?.toast) {
    window.App.toast(message);
    return;
  }
  showSettingsError(message);
}

function renderSettingsStatus(settings) {
  if (!settingsEls.status || !settings) return;
  const sourceMap = {
    user: "当前使用你配置的 API Key",
    env: "当前使用服务器默认 API Key",
    none: "尚未配置 API Key，分析/对话将无法调用大模型",
  };
  const masked = settings.api_key_masked ? `（${settings.api_key_masked}）` : "";
  settingsEls.status.innerHTML = `
    <span class="settings-pill ${settings.has_api_key ? "ok" : "warn"}">${sourceMap[settings.api_key_source] || "未知"}</span>
    ${masked ? `<span class="settings-mask">${masked}</span>` : ""}`;
}

function renderSettingsLoading(message = "正在加载 API 设置…") {
  if (!settingsEls.status) return;
  settingsEls.status.innerHTML = `<span class="settings-pill warn">${message}</span>`;
}

function ensureSettingsAuth() {
  const token = window.Auth?.getAuthToken?.();
  if (!token) {
    throw new Error("请先登录后再配置 API");
  }
  if (typeof window.Auth?.authFetch !== "function" && typeof window.Auth?.authHeaders !== "function") {
    throw new Error("登录模块尚未就绪，请刷新页面后重试");
  }
}

async function settingsAuthFetch(path, options = {}) {
  if (typeof window.Auth?.authFetch === "function") {
    return window.Auth.authFetch(path, options);
  }
  const isForm = options.body instanceof FormData;
  const headers = window.Auth.authHeaders(
    isForm ? {} : { "Content-Type": "application/json", ...(options.headers || {}) },
  );
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

function applyChatAgentSettings(settings) {
  const steps = Number(settings?.chat_max_steps);
  const mode = settings?.chat_agent_mode === "single" ? "single" : "loop";
  const stepVal = Number.isFinite(steps) ? Math.max(1, Math.min(8, steps)) : 4;
  [settingsEls.chatMaxSteps, document.getElementById("chatMaxSteps")].forEach((el) => {
    if (el) el.value = String(stepVal);
  });
  [settingsEls.chatAgentMode, document.getElementById("chatAgentMode")].forEach((el) => {
    if (el) el.value = mode;
  });
}

async function loadSettingsForm() {
  ensureSettingsAuth();
  const payload = await settingsAuthFetch("/api/settings");
  const settings = payload.settings || {};
  if (settingsEls.baseUrl) settingsEls.baseUrl.value = settings.openai_base_url || "";
  if (settingsEls.model) settingsEls.model.value = settings.openai_model || "";
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  applyChatAgentSettings(settings);
  renderSettingsStatus(settings);
  return settings;
}

function syncSettingsButtonsVisible(visible = true) {
  const show = Boolean(visible);
  [settingsEls.openBtn, settingsEls.mobileOpenBtn].forEach((button) => {
    button?.classList.toggle("hidden", !show);
  });
}

function openSettingsModal() {
  try {
    ensureSettingsAuth();
  } catch (error) {
    showSettingsError(error.message);
    window.Auth?.ensureAuth?.();
    return;
  }

  settingsEls.modal?.classList.remove("hidden");
  renderSettingsLoading();
  if (window.App?.isMobileLayout?.()) {
    window.App.closeMobileRail?.();
  }

  loadSettingsForm().catch((error) => {
    renderSettingsStatus({ has_api_key: false, api_key_source: "none" });
    if (settingsEls.status) {
      settingsEls.status.innerHTML = `<span class="settings-pill warn">${error.message || "加载失败"}</span>`;
    }
    showSettingsError(error.message || "无法加载 API 设置");
  });
}

function closeSettingsModal() {
  settingsEls.modal?.classList.add("hidden");
}

async function saveSettings(event) {
  event.preventDefault();
  ensureSettingsAuth();
  const steps = parseInt(settingsEls.chatMaxSteps?.value, 10);
  const body = {
    openai_base_url: settingsEls.baseUrl?.value?.trim() ?? "",
    openai_model: settingsEls.model?.value?.trim() ?? "",
    chat_max_steps: Number.isFinite(steps) ? Math.max(1, Math.min(8, steps)) : 4,
    chat_agent_mode: settingsEls.chatAgentMode?.value === "single" ? "single" : "loop",
  };
  const apiKey = settingsEls.apiKey?.value?.trim();
  if (apiKey) body.openai_api_key = apiKey;
  const payload = await settingsAuthFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  applyChatAgentSettings(payload.settings);
  renderSettingsStatus(payload.settings);
  showSettingsMessage("设置已保存");
  closeSettingsModal();
}

async function testSettings() {
  ensureSettingsAuth();
  const apiKey = settingsEls.apiKey?.value?.trim();
  if (apiKey) {
    await settingsAuthFetch("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        openai_api_key: apiKey,
        openai_base_url: settingsEls.baseUrl?.value?.trim() ?? "",
        openai_model: settingsEls.model?.value?.trim() ?? "",
      }),
    });
  }
  const payload = await settingsAuthFetch("/api/settings/test", { method: "POST", body: "{}" });
  showSettingsMessage(payload.message || "连接成功");
  await loadSettingsForm();
}

async function clearSettingsKey() {
  ensureSettingsAuth();
  const payload = await settingsAuthFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ clear_api_key: true }),
  });
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  renderSettingsStatus(payload.settings);
  showSettingsMessage("已清除个人 API Key");
}

function bindSettingsEvents() {
  initSettingsElements();
  document.querySelectorAll(".js-open-settings").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      openSettingsModal();
    });
  });
  settingsEls.railOpenBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    openSettingsModal();
  });
  settingsEls.closeBtn?.addEventListener("click", closeSettingsModal);
  settingsEls.modal?.addEventListener("click", (event) => {
    if (event.target === settingsEls.modal) closeSettingsModal();
  });
  settingsEls.form?.addEventListener("submit", (event) => {
    saveSettings(event).catch((error) => showSettingsError(error.message));
  });
  settingsEls.testBtn?.addEventListener("click", () => {
    testSettings().catch((error) => showSettingsError(error.message));
  });
  settingsEls.clearKeyBtn?.addEventListener("click", () => {
    clearSettingsKey().catch((error) => showSettingsError(error.message));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && settingsEls.modal && !settingsEls.modal.classList.contains("hidden")) {
      closeSettingsModal();
    }
  });
  syncSettingsButtonsVisible(Boolean(window.Auth?.getAuthToken?.()));
}

let chatAgentSaveTimer = null;

async function persistChatAgentSettingsFromRail() {
  try {
    ensureSettingsAuth();
    const steps = parseInt(document.getElementById("chatMaxSteps")?.value, 10);
    const mode = document.getElementById("chatAgentMode")?.value === "single" ? "single" : "loop";
    await settingsAuthFetch("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        chat_max_steps: Number.isFinite(steps) ? Math.max(1, Math.min(8, steps)) : 4,
        chat_agent_mode: mode,
      }),
    });
  } catch (_e) {
    /* 侧栏静默保存，失败下次发消息仍会带当前输入 */
  }
}

function scheduleChatAgentSave() {
  window.clearTimeout(chatAgentSaveTimer);
  chatAgentSaveTimer = window.setTimeout(() => {
    persistChatAgentSettingsFromRail();
  }, 600);
}

function bindChatAgentRailControls() {
  ["chatMaxSteps", "chatAgentMode"].forEach((id) => {
    const el = document.getElementById(id);
    el?.addEventListener("change", scheduleChatAgentSave);
  });
}

window.openSettingsModal = openSettingsModal;
window.loadUserSettings = loadSettingsForm;
window.applyChatAgentSettings = applyChatAgentSettings;
window.syncSettingsButtonsVisible = syncSettingsButtonsVisible;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    bindSettingsEvents();
    bindChatAgentRailControls();
  });
} else {
  bindSettingsEvents();
  bindChatAgentRailControls();
}
