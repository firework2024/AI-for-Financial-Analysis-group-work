/** 用户设置（大模型 / 对话 / 性能） */

const settingsEls = {};
const SETTINGS_TAB_KEY = "finagent_settings_tab";

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
    maxWorkers: document.getElementById("settingsMaxWorkers"),
    autoIngest: document.getElementById("settingsAutoIngest"),
    bootstrapLookback: document.getElementById("settingsBootstrapLookback"),
    annualMaxAge: document.getElementById("settingsAnnualMaxAge"),
    validationRounds: document.getElementById("settingsValidationRounds"),
    placementRounds: document.getElementById("settingsPlacementRounds"),
    skipReviseScore: document.getElementById("settingsSkipReviseScore"),
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

function renderSettingsLoading(message = "正在加载设置…") {
  if (!settingsEls.status) return;
  settingsEls.status.innerHTML = `<span class="settings-pill warn">${message}</span>`;
}

function setSettingsTab(tabId) {
  const id = ["llm", "chat", "perf"].includes(tabId) ? tabId : "llm";
  document.querySelectorAll("[data-settings-tab]").forEach((tab) => {
    const active = tab.getAttribute("data-settings-tab") === id;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-settings-panel]").forEach((panel) => {
    const show = panel.getAttribute("data-settings-panel") === id;
    panel.classList.toggle("hidden", !show);
    if (show) {
      panel.removeAttribute("hidden");
    } else {
      panel.setAttribute("hidden", "");
    }
  });
  try {
    localStorage.setItem(SETTINGS_TAB_KEY, id);
  } catch (_e) {}
}

function bindSettingsTabs() {
  document.querySelectorAll("[data-settings-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      setSettingsTab(tab.getAttribute("data-settings-tab"));
    });
  });
  let saved = "llm";
  try {
    saved = localStorage.getItem(SETTINGS_TAB_KEY) || "llm";
  } catch (_e) {}
  setSettingsTab(saved);
}

function validatePerformancePayload(payload) {
  const checks = [
    ["max_workers", 1, 12],
    ["bootstrap_lookback_days", 30, 365],
    ["annual_max_age_days", 0, 3650],
    ["validation_max_rounds", 0, 5],
    ["chart_placement_max_rounds", 1, 5],
    ["validation_skip_revise_min_score", 0, 100],
  ];
  for (const [key, min, max] of checks) {
    const value = Number(payload[key]);
    if (!Number.isFinite(value) || value < min || value > max) {
      throw new Error(`性能参数「${key}」须在 ${min}–${max} 之间`);
    }
  }
  return payload;
}

function ensureSettingsAuth() {
  const token = window.Auth?.getAuthToken?.();
  if (!token) {
    throw new Error("请先登录后再打开设置");
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

function clampAgentSteps(raw) {
  const steps = Number(raw);
  return Number.isFinite(steps) ? Math.max(1, Math.min(8, Math.round(steps))) : 4;
}

function updateAgentControlUI(root, { mode, steps }) {
  if (!root) return;
  const modeVal = mode === "single" ? "single" : "loop";
  const stepVal = clampAgentSteps(steps);
  const modeInput = root.querySelector("[data-agent-mode-input]");
  const stepsInput = root.querySelector("[data-agent-steps-input]");
  const stepsRange = root.querySelector("[data-agent-steps-range]");
  const stepsValue = root.querySelector("[data-agent-steps-value]");
  const stepsBlock = root.querySelector("[data-agent-steps]");

  if (modeInput) modeInput.value = modeVal;
  if (stepsInput) stepsInput.value = String(stepVal);
  if (stepsRange) stepsRange.value = String(stepVal);
  if (stepsValue) stepsValue.textContent = String(stepVal);

  root.querySelectorAll("[data-agent-mode-tab]").forEach((tab) => {
    const active = tab.getAttribute("data-agent-mode-tab") === modeVal;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-pressed", active ? "true" : "false");
  });

  if (stepsBlock) {
    const off = modeVal === "single";
    stepsBlock.classList.toggle("is-disabled", off);
    stepsBlock.classList.toggle("is-hidden", off);
    stepsBlock.setAttribute("aria-hidden", off ? "true" : "false");
  }
}

function updateComposerAgentBadge() {
  const badge = document.getElementById("composerAgentBadge");
  const mode = document.getElementById("chatAgentMode")?.value === "single" ? "single" : "loop";
  const steps = clampAgentSteps(document.getElementById("chatMaxSteps")?.value);
  if (!badge) return;
  badge.textContent = mode === "single" ? "快速" : `深度 · ${steps} 步`;
}

const COMPOSER_AGENT_OPEN_KEY = "finagent_composer_agent_open";

function bindComposerAgentCollapse() {
  const details = document.getElementById("composerAgentControl");
  if (!details || details.tagName !== "DETAILS") return;
  details.open = localStorage.getItem(COMPOSER_AGENT_OPEN_KEY) === "1";
  details.addEventListener("toggle", () => {
    localStorage.setItem(COMPOSER_AGENT_OPEN_KEY, details.open ? "1" : "0");
  });
}

function applyChatAgentSettings(settings) {
  const steps = clampAgentSteps(settings?.chat_max_steps);
  const mode = settings?.chat_agent_mode === "single" ? "single" : "loop";
  document.querySelectorAll("[data-agent-control]").forEach((root) => {
    updateAgentControlUI(root, { mode, steps });
  });
  updateComposerAgentBadge();
}

function wireAgentControlBlock(root, onChange) {
  if (!root || root.dataset.agentWired === "1") return;
  root.dataset.agentWired = "1";

  const modeInput = root.querySelector("[data-agent-mode-input]");
  const stepsInput = root.querySelector("[data-agent-steps-input]");
  const stepsRange = root.querySelector("[data-agent-steps-range]");

  const emit = () => {
    updateComposerAgentBadge();
    onChange?.();
  };

  const setMode = (mode) => {
    updateAgentControlUI(root, {
      mode,
      steps: stepsInput?.value ?? stepsRange?.value ?? 4,
    });
    emit();
  };

  const setSteps = (raw) => {
    updateAgentControlUI(root, {
      mode: modeInput?.value ?? "loop",
      steps: raw,
    });
    emit();
  };

  root.querySelectorAll("[data-agent-mode-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      setMode(tab.getAttribute("data-agent-mode-tab"));
    });
  });

  stepsRange?.addEventListener("input", () => setSteps(stepsRange.value));
  root.querySelector("[data-agent-steps-down]")?.addEventListener("click", () => {
    setSteps(clampAgentSteps(stepsInput?.value) - 1);
  });
  root.querySelector("[data-agent-steps-up]")?.addEventListener("click", () => {
    setSteps(clampAgentSteps(stepsInput?.value) + 1);
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
  applyPerformanceSettings(settings.performance || {});
  renderSettingsStatus(settings);
  return settings;
}

function applyPerformanceSettings(perf) {
  if (settingsEls.maxWorkers) settingsEls.maxWorkers.value = String(perf.max_workers ?? 4);
  if (settingsEls.autoIngest) settingsEls.autoIngest.checked = perf.auto_ingest_on_new_chat !== false;
  if (settingsEls.bootstrapLookback) settingsEls.bootstrapLookback.value = String(perf.bootstrap_lookback_days ?? 90);
  if (settingsEls.annualMaxAge) settingsEls.annualMaxAge.value = String(perf.annual_max_age_days ?? 120);
  if (settingsEls.validationRounds) settingsEls.validationRounds.value = String(perf.validation_max_rounds ?? 2);
  if (settingsEls.placementRounds) settingsEls.placementRounds.value = String(perf.chart_placement_max_rounds ?? 2);
  if (settingsEls.skipReviseScore) settingsEls.skipReviseScore.value = String(perf.validation_skip_revise_min_score ?? 88);
}

function collectPerformancePayload() {
  return validatePerformancePayload({
    max_workers: Number(settingsEls.maxWorkers?.value || 4),
    auto_ingest_on_new_chat: Boolean(settingsEls.autoIngest?.checked),
    bootstrap_lookback_days: Number(settingsEls.bootstrapLookback?.value || 90),
    annual_max_age_days: Number(settingsEls.annualMaxAge?.value || 120),
    validation_max_rounds: Number(settingsEls.validationRounds?.value || 2),
    chart_placement_max_rounds: Number(settingsEls.placementRounds?.value || 2),
    validation_skip_revise_min_score: Number(settingsEls.skipReviseScore?.value || 88),
  });
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
  document.body.classList.add("settings-modal-open");
  renderSettingsLoading();
  if (window.App?.isMobileLayout?.()) {
    window.App.closeMobileRail?.();
  }

  loadSettingsForm().catch((error) => {
    renderSettingsStatus({ has_api_key: false, api_key_source: "none" });
    if (settingsEls.status) {
      settingsEls.status.innerHTML = `<span class="settings-pill warn">${error.message || "加载失败"}</span>`;
    }
    showSettingsError(error.message || "无法加载设置");
  });
}

function closeSettingsModal() {
  settingsEls.modal?.classList.add("hidden");
  document.body.classList.remove("settings-modal-open");
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
    performance: collectPerformancePayload(),
  };
  const apiKey = settingsEls.apiKey?.value?.trim();
  if (apiKey) body.openai_api_key = apiKey;
  const payload = await settingsAuthFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  if (settingsEls.apiKey) settingsEls.apiKey.value = "";
  applyChatAgentSettings(payload.settings);
  applyPerformanceSettings(payload.settings?.performance || {});
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

function openSettingsOnTab(tabId) {
  openSettingsModal();
  setSettingsTab(tabId);
}

function bindSettingsEvents() {
  initSettingsElements();
  bindSettingsTabs();
  document.querySelectorAll(".js-open-settings").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const tab = button.getAttribute("data-settings-open");
      if (tab) openSettingsOnTab(tab);
      else openSettingsModal();
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
  document.querySelectorAll("[data-agent-control]").forEach((root) => {
    const persist = root.hasAttribute("data-agent-persist");
    wireAgentControlBlock(root, persist ? scheduleChatAgentSave : undefined);
  });
}

window.openSettingsModal = openSettingsModal;
window.openSettingsOnTab = openSettingsOnTab;
window.loadUserSettings = loadSettingsForm;
window.applyChatAgentSettings = applyChatAgentSettings;
window.syncSettingsButtonsVisible = syncSettingsButtonsVisible;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    bindSettingsEvents();
    bindChatAgentRailControls();
    bindComposerAgentCollapse();
  });
} else {
  bindSettingsEvents();
  bindChatAgentRailControls();
  bindComposerAgentCollapse();
}
