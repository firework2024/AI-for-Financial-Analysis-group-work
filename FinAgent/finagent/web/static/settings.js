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
    openBtn: document.getElementById("openSettingsBtn"),
    closeBtn: document.getElementById("settingsClose"),
    testBtn: document.getElementById("settingsTestBtn"),
    clearKeyBtn: document.getElementById("settingsClearKeyBtn"),
  });
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

async function loadSettingsForm() {
  const payload = await window.Auth.authFetch("/api/settings");
  const settings = payload.settings || {};
  if (settingsEls.baseUrl) settingsEls.baseUrl.value = settings.openai_base_url || "";
  if (settingsEls.model) settingsEls.model.value = settings.openai_model || "";
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  renderSettingsStatus(settings);
  return settings;
}

function openSettingsModal() {
  loadSettingsForm()
    .then(() => settingsEls.modal?.classList.remove("hidden"))
    .catch((error) => window.App?.toast?.(error.message, "error"));
}

function closeSettingsModal() {
  settingsEls.modal?.classList.add("hidden");
}

async function saveSettings(event) {
  event.preventDefault();
  const body = {
    openai_base_url: settingsEls.baseUrl?.value?.trim() ?? "",
    openai_model: settingsEls.model?.value?.trim() ?? "",
  };
  const apiKey = settingsEls.apiKey?.value?.trim();
  if (apiKey) body.openai_api_key = apiKey;
  const payload = await window.Auth.authFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  renderSettingsStatus(payload.settings);
  window.App?.toast?.("API 设置已保存");
  closeSettingsModal();
}

async function testSettings() {
  const apiKey = settingsEls.apiKey?.value?.trim();
  if (apiKey) {
    await window.Auth.authFetch("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        openai_api_key: apiKey,
        openai_base_url: settingsEls.baseUrl?.value?.trim() ?? "",
        openai_model: settingsEls.model?.value?.trim() ?? "",
      }),
    });
  }
  const payload = await window.Auth.authFetch("/api/settings/test", { method: "POST", body: "{}" });
  window.App?.toast?.(payload.message || "连接成功");
  await loadSettingsForm();
}

async function clearSettingsKey() {
  const payload = await window.Auth.authFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ clear_api_key: true }),
  });
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  renderSettingsStatus(payload.settings);
  window.App?.toast?.("已清除个人 API Key");
}

function bindSettingsEvents() {
  initSettingsElements();
  settingsEls.openBtn?.addEventListener("click", openSettingsModal);
  settingsEls.closeBtn?.addEventListener("click", closeSettingsModal);
  settingsEls.modal?.addEventListener("click", (event) => {
    if (event.target === settingsEls.modal) closeSettingsModal();
  });
  settingsEls.form?.addEventListener("submit", (event) => {
    saveSettings(event).catch((error) => window.App?.toast?.(error.message, "error"));
  });
  settingsEls.testBtn?.addEventListener("click", () => {
    testSettings().catch((error) => window.App?.toast?.(error.message, "error"));
  });
  settingsEls.clearKeyBtn?.addEventListener("click", () => {
    clearSettingsKey().catch((error) => window.App?.toast?.(error.message, "error"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && settingsEls.modal && !settingsEls.modal.classList.contains("hidden")) {
      closeSettingsModal();
    }
  });
}

window.openSettingsModal = openSettingsModal;
window.loadUserSettings = loadSettingsForm;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindSettingsEvents);
} else {
  bindSettingsEvents();
}
