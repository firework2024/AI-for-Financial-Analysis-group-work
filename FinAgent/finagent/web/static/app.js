const state = {
  reports: [],
  filteredReports: [],
  activeReportId: null,
  activeReport: null,
  pollingTaskId: null,
  disclaimer: "",
  searchQuery: "",
  sidebar: "chat",
  view: "chat",
  reportChatOpen: false,
  reportOutlineOpen: typeof window !== "undefined" ? window.innerWidth > 900 : true,
  chatViewAnchor: null,
  tocObserver: null,
  railCollapsed: localStorage.getItem("finagent_rail_collapsed") === "1",
};

const els = {
  serverStatus: document.getElementById("serverStatus"),
  serverStatusText: document.getElementById("serverStatusText"),
  refreshBtn: document.getElementById("refreshBtn"),
  sidebarSearch: document.getElementById("sidebarSearch"),
  analyzeForm: document.getElementById("analyzeForm"),
  submitBtn: document.getElementById("submitBtn"),
  taskBox: document.getElementById("taskBox"),
  taskSpinner: document.getElementById("taskSpinner"),
  taskMessage: document.getElementById("taskMessage"),
  taskMeta: document.getElementById("taskMeta"),
  reportCount: document.getElementById("reportCount"),
  reportList: document.getElementById("reportList"),
  reportsPanel: document.getElementById("reportsPanel"),
  chatSessionsPanel: document.getElementById("chatSessionsPanel"),
  welcomeView: document.getElementById("welcomeView"),
  welcomeChatBtn: document.getElementById("welcomeChatBtn"),
  welcomeChatCardBtn: document.getElementById("welcomeChatCardBtn"),
  welcomeMultiBtn: document.getElementById("welcomeMultiBtn"),
  welcomeReportsBtn: document.getElementById("welcomeReportsBtn"),
  railAnalyze: document.querySelector(".rail-analyze"),
  analyzeAdvancedToggle: document.getElementById("analyzeAdvancedToggle"),
  analyzeAdvancedPanel: document.getElementById("analyzeAdvancedPanel"),
  brandHome: document.getElementById("brandHome"),
  mainStage: document.getElementById("mainStage"),
  rail: document.getElementById("rail"),
  reportView: document.getElementById("reportView"),
  reportLayout: document.getElementById("reportLayout"),
  reportChatMount: document.getElementById("reportChatMount"),
  reportChatToggle: document.getElementById("reportChatToggle"),
  chatDockCloseBtn: document.getElementById("chatDockCloseBtn"),
  railCompose: document.getElementById("railCompose"),
  reportEmptyView: document.getElementById("reportEmptyView"),
  chatView: document.getElementById("chatView"),
  reportTags: document.getElementById("reportTags"),
  reportTitle: document.getElementById("reportTitle"),
  reportSubtitle: document.getElementById("reportSubtitle"),
  openHtmlBtn: document.getElementById("openHtmlBtn"),
  askReportBtn: document.getElementById("askReportBtn"),
  backToChatBtn: document.getElementById("backToChatBtn"),
  chatAttachReportBtn: document.getElementById("chatAttachReportBtn"),
  reportToc: document.getElementById("reportToc"),
  reportBody: document.getElementById("reportBody"),
  reportOutline: document.getElementById("reportOutline"),
  reportOutlineBackdrop: document.getElementById("reportOutlineBackdrop"),
  reportScroll: document.getElementById("reportScroll"),
  reportBindBtn: document.getElementById("reportBindBtn"),
  reportOutlineClose: document.getElementById("reportOutlineClose"),
  reportOutlineToggle: document.getElementById("reportOutlineToggle"),
  reportOutlineToggleHead: document.getElementById("reportOutlineToggleHead"),
  annualSections: document.getElementById("annualSections"),
  multiSections: document.getElementById("multiSections"),
  reportDisclaimer: document.getElementById("reportDisclaimer"),
  welcomeDisclaimer: document.getElementById("welcomeDisclaimer"),
  toastHost: document.getElementById("toastHost"),
  shell: document.querySelector(".shell"),
  mobileBar: document.getElementById("mobileBar"),
  mobileMenuBtn: document.getElementById("mobileMenuBtn"),
  mobileNewChatBtn: document.getElementById("mobileNewChatBtn"),
  mobileBarTitle: document.getElementById("mobileBarTitle"),
  mobileBarSub: document.getElementById("mobileBarSub"),
  railOverlay: document.getElementById("railOverlay"),
  railCollapseBtn: document.getElementById("railCollapseBtn"),
  railExpandBtn: document.getElementById("railExpandBtn"),
  railSettingsBtn: document.getElementById("railSettingsBtn"),
};

function initMarkdownLibs() {
  if (typeof marked !== "undefined") {
    marked.setOptions({ breaks: true, gfm: true });
  }
}

initMarkdownLibs();

function toast(message, type = "info") {
  if (!els.toastHost) return;
  const node = document.createElement("div");
  node.className = `toast${type === "error" ? " error" : ""}`;
  node.textContent = message;
  els.toastHost.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function isMobileLayout() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function openMobileRail() {
  if (!isMobileLayout()) return;
  els.shell?.classList.add("rail-open");
  document.body.classList.add("rail-open");
  els.railOverlay?.setAttribute("aria-hidden", "false");
}

function closeMobileRail() {
  els.shell?.classList.remove("rail-open");
  document.body.classList.remove("rail-open");
  els.railOverlay?.setAttribute("aria-hidden", "true");
}

function toggleMobileRail() {
  if (els.shell?.classList.contains("rail-open")) closeMobileRail();
  else openMobileRail();
}

function syncRailCollapseUi() {
  const collapsed = state.railCollapsed && !isMobileLayout();
  els.shell?.classList.toggle("rail-collapsed", collapsed);
  els.railExpandBtn?.classList.toggle("hidden", !collapsed);
  els.railSettingsBtn?.classList.toggle("hidden", !collapsed || !window.Auth?.state?.user);
  if (els.railCollapseBtn) {
    els.railCollapseBtn.setAttribute("aria-label", collapsed ? "侧栏已收起" : "收起侧栏");
    els.railCollapseBtn.title = collapsed ? "侧栏已收起，请点左侧边缘展开" : "收起侧栏";
  }
}

function setRailCollapsed(collapsed) {
  state.railCollapsed = Boolean(collapsed);
  localStorage.setItem("finagent_rail_collapsed", state.railCollapsed ? "1" : "0");
  syncRailCollapseUi();
}

function syncMobileBar(title, sub = "") {
  if (els.mobileBarTitle) els.mobileBarTitle.textContent = title || "FinAgent";
  if (els.mobileBarSub) {
    els.mobileBarSub.textContent = sub || "";
    const showSub = Boolean(sub);
    els.mobileBarSub.classList.toggle("hidden", !showSub);
    els.mobileBar?.classList.toggle("mobile-bar--has-sub", showSub && isMobileLayout());
  }
}

function syncMobileUi() {
  const chatInput = document.getElementById("chatInput");
  if (chatInput) {
    chatInput.placeholder = isMobileLayout() ? "发消息…" : "输入问题，Shift+Enter 换行…";
  }
}

function updateMobileBarForView(view) {
  if (!isMobileLayout()) return;
  if (view === "welcome") {
    syncMobileBar("FinAgent", "A 股智能研究平台");
    return;
  }
  if (view === "report-empty") {
    syncMobileBar("历史报告", "选择一份报告查看");
    return;
  }
  if (view === "report" && state.activeReport) {
    const ui = state.activeReport._ui || {};
    const reportType = resolveReportType(state.activeReport);
    const sub =
      els.reportSubtitle?.textContent?.trim() ||
      ui.subtitle ||
      (reportType === "annual_analyze" ? "年报分析" : "多智能体研报");
    syncMobileBar(ui.title || state.activeReport.meta?.stock_code || "分析报告", sub);
    return;
  }
  if (view === "chat") {
    const chatState = chatStateRef();
    const session = chatState?.activeSession;
    syncMobileBar(session?.title || "新对话");
  }
}

function hasActiveChatSession() {
  return Boolean(chatStateRef()?.activeSessionId);
}

function rememberChatViewAnchor() {
  if (!els.chatView || !els.mainStage || state.chatViewAnchor) return;
  state.chatViewAnchor = {
    parent: els.mainStage,
    next: els.reportView,
  };
}

function restoreChatViewToStage() {
  if (!els.chatView || !state.chatViewAnchor) return;
  const { parent, next } = state.chatViewAnchor;
  if (next && next.parentNode === parent) {
    parent.insertBefore(els.chatView, next);
  } else {
    parent.appendChild(els.chatView);
  }
  els.chatView.classList.remove("pane-chat--dock");
}

function syncReportChatUi() {
  const open = Boolean(state.reportChatOpen);
  els.reportView?.classList.toggle("report-chat-open", open);
  els.reportChatMount?.setAttribute("aria-hidden", open ? "false" : "true");
  els.reportChatToggle?.setAttribute("aria-expanded", open ? "true" : "false");
  els.reportChatToggle?.classList.toggle("is-active", open);
  els.rail?.classList.toggle("rail--report-chat", open && state.view === "report");
  els.chatDockCloseBtn?.classList.toggle("hidden", !open);
  document.body.classList.toggle("report-chat-drawer-open", open && state.view === "report");
}

function closeReportChatDrawer() {
  if (!state.reportChatOpen) return;
  state.reportChatOpen = false;
  restoreChatViewToStage();
  if (state.view === "report") {
    els.chatView?.classList.add("hidden");
  }
  syncReportChatUi();
}

async function openReportChatDrawer() {
  if (!state.activeReport) {
    toast("请先打开一份报告", "error");
    return false;
  }
  rememberChatViewAnchor();
  if (state.view !== "report") {
    navigate("report");
  }
  state.reportChatOpen = true;
  els.reportChatMount?.appendChild(els.chatView);
  els.chatView?.classList.remove("hidden");
  els.chatView?.classList.add("pane-chat--dock");
  syncReportChatUi();
  setSidebarPanel("reports");

  try {
    if (typeof window.ensureReportChatSession === "function") {
      await window.ensureReportChatSession();
    } else if (typeof window.createChatSessionForReport === "function") {
      await window.createChatSessionForReport();
    }
  } catch (error) {
    toast(error.message || "无法打开对话", "error");
    return false;
  }
  closeMobileRail();
  return true;
}

function toggleReportChatDrawer() {
  if (state.reportChatOpen) {
    closeReportChatDrawer();
    return;
  }
  openReportChatDrawer().catch((e) => toast(e.message, "error"));
}

function navigate(view) {
  if (view !== "report" && state.reportChatOpen) {
    closeReportChatDrawer();
  }
  state.view = view;
  els.welcomeView?.classList.toggle("hidden", view !== "welcome");
  els.chatView?.classList.toggle("hidden", view !== "chat");
  els.reportView?.classList.toggle("hidden", view !== "report");
  els.reportEmptyView?.classList.toggle("hidden", view !== "report-empty");
  if (view === "report" && !state.activeReport) {
    els.reportView?.classList.add("hidden");
    els.reportEmptyView?.classList.remove("hidden");
  }
  if (view === "chat") {
    restoreChatViewToStage();
    els.chatView?.classList.remove("pane-chat--dock");
  }
  if (view === "report" && state.reportChatOpen) {
    els.chatView?.classList.remove("hidden");
  }

  syncReportChatUi();
  updateMobileBarForView(
    view === "report" && !state.activeReport ? "report-empty" : view,
  );
  if (view !== "welcome" && isMobileLayout()) closeMobileRail();
}

function setSidebarPanel(panel) {
  state.sidebar = panel;
  document.querySelectorAll("[data-sidebar]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.sidebar === panel);
  });
  els.chatSessionsPanel?.classList.toggle("hidden", panel !== "chat");
  els.reportsPanel?.classList.toggle("hidden", panel !== "reports");
}

function syncAnalyzeRailLayout() {
  const open = Boolean(els.railAnalyze?.open);
  els.rail?.classList.toggle("rail-analyze-open", open);
  if (open) {
    window.requestAnimationFrame(() => {
      els.railAnalyze?.scrollIntoView({ block: "end", behavior: "smooth" });
    });
  }
}

function toggleAnalyzeAdvanced(event) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  const panel = els.analyzeAdvancedPanel;
  const toggle = els.analyzeAdvancedToggle;
  if (!panel || !toggle) return;
  const expanded = panel.classList.toggle("hidden") === false;
  toggle.setAttribute("aria-expanded", String(expanded));
  if (expanded) {
    window.requestAnimationFrame(() => {
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }
}

function focusMultiAnalyzePanel() {
  setSidebarPanel("chat");
  if (els.railAnalyze && els.railAnalyze.tagName === "DETAILS") {
    els.railAnalyze.open = true;
  }
  syncAnalyzeRailLayout();
  const stockInput = els.analyzeForm?.elements?.stock;
  if (stockInput) {
    window.setTimeout(() => stockInput.focus(), 80);
  }
  if (isMobileLayout()) openMobileRail();
}

function normalizeFilePath(path) {
  let normalized = String(path || "").replace(/\\/g, "/").trim();
  if (!normalized) return "";
  normalized = normalized.replace(/^FinAgent\/outputs\//i, "").replace(/^outputs\//i, "");
  if (/^https?:\/\//i.test(normalized) || normalized.startsWith("data:")) return normalized;
  const marker = "/outputs/";
  const idx = normalized.toLowerCase().lastIndexOf(marker);
  if (idx >= 0) normalized = normalized.slice(idx + marker.length);
  return normalized.replace(/^\/+/, "");
}

function fileUrl(path) {
  const normalized = normalizeFilePath(path);
  if (!normalized) return "";
  return `/files/${encodeURI(normalized)}`;
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const FIGURE_PLACEHOLDER = "FINAGENT_FIGURE_";

function extractMarkdownFigures(text) {
  const figures = [];
  const stripped = String(text).replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt, rawPath) => {
    figures.push({ alt: String(alt || "图表").trim(), path: String(rawPath || "").trim() });
    return `\n\n${FIGURE_PLACEHOLDER}${figures.length - 1}\n\n`;
  });
  return { stripped, figures };
}

function figureHtml(fig) {
  const url = fileUrl(fig.path);
  if (!url) return "";
  return `<figure class="report-figure"><img src="${url}" alt="${escapeHtml(fig.alt)}" loading="lazy" /></figure>`;
}

function injectFigurePlaceholders(html, figures) {
  let result = html;
  figures.forEach((fig, index) => {
    const token = `${FIGURE_PLACEHOLDER}${index}`;
    const block = figureHtml(fig);
    result = result.replace(new RegExp(`<p>\\s*${token}\\s*</p>`, "g"), block);
    result = result.replaceAll(token, block);
  });
  return result;
}

function polishFieldRefs(text) {
  let result = String(text || "");
  const field = "[a-z][a-z0-9_]{1,}";
  const quarter = "20\\d{2}q[1-4]";
  result = result.replace(new RegExp(`[（(]\\s*\`?quarter\`?\\s*为\\s*\`?(${quarter})\`?\\s*[）)]`, "gi"), "");
  result = result.replace(new RegExp(`根据\\s*\`?(${field})\`?\\s*数据[，,]?\\s*`, "gi"), "");
  result = result.replace(new RegExp(`基于\\s*\`?(${field})\`?\\s*数据[，,]?\\s*`, "gi"), "");
  result = result.replace(new RegExp(`基于\\s*\`?(${field})\`?\\s*中`, "gi"), "");
  result = result.replace(new RegExp(`\`?(${field})\`?\\s*字段`, "gi"), "");
  result = result.replace(new RegExp(`基于米筐数据\\s*\`?(${field})\`?\\s*字段[，,]?\\s*`, "gi"), "基于米筐数据，");
  result = result.replace(new RegExp(`JSON\\s*中的\\s*\`?(${field})\`?\\s*`, "gi"), "");
  result = result.replace(new RegExp(`(?<![\`/\\w])(${field}|${quarter})(?![\`\\w])`, "gi"), (_m, token) => {
    if (!token.includes("_") && !new RegExp(`^${quarter}$`, "i").test(token)) return token;
    return `\`${token}\``;
  });
  result = result.replace(/[，,]\s*[，,]/g, "，");
  result = result.replace(/\n{3,}/g, "\n\n");
  return result.trim();
}

function tagFieldRefs(html) {
  return html.replace(/<code>([^<]+)<\/code>/g, '<code class="field-ref">$1</code>');
}

function enhanceReportTables(html) {
  return String(html || "").replace(/<table(\s[^>]*)?>[\s\S]*?<\/table>/gi, (block) => {
    const thCount = (block.match(/<th[\s>]/gi) || []).length;
    const colClass =
      thCount >= 4 ? "metrics-table metrics-table-wide" : "metrics-table metrics-table-compact";
    let table = block;
    if (/class="/i.test(table)) {
      table = table.replace(/class="([^"]*)"/i, (_m, cls) => {
        const cleaned = cls.replace(/\bmetrics-table(?:-\w+)?\b/g, "").trim();
        return `class="${colClass}${cleaned ? ` ${cleaned}` : ""}"`;
      });
    } else {
      table = table.replace(/<table/i, `<table class="${colClass}"`);
    }
    return `<div class="report-table-wrap">${table}</div>`;
  });
}

function renderMarkdown(text, charts = null) {
  if (!text) return "<p>暂无内容</p>";
  initMarkdownLibs();
  if (typeof marked === "undefined") {
    return escapeHtml(String(text)).replace(/\n/g, "<br>");
  }
  const cleaned = cleanChartProse(polishFieldRefs(String(text)));
  const { stripped, figures } = extractMarkdownFigures(cleaned);
  let html = marked.parse(stripped.trim() || " ");
  html = injectFigurePlaceholders(html, figures);
  html = fixImagePaths(html);
  html = html.replace(
    /<p><strong>图注<\/strong>\s([^<]*)<\/p>/g,
    '<p class="figure-note"><strong>图注</strong> $1</p>'
  );
  html = tagFieldRefs(html);
  html = enhanceReportTables(html);
  if (typeof DOMPurify === "undefined") return html;
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ["figure"],
    ADD_ATTR: ["src", "alt", "loading", "class", "target"],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|data|blob):|\/(?:files|charts)\/)/i,
  });
}

const CHART_PATH_PATTERN = String.raw`(?:charts|outputs)[\\/][\w./-]+\.(?:png|jpe?g|gif|webp)`;

function cleanChartProse(text) {
  let result = String(text);
  // 保留 ![caption](charts/...) 内嵌图；仅清理正文中的路径占位引用
  result = result.replace(new RegExp("`(" + CHART_PATH_PATTERN + ")`", "gi"), "");
  result = result.replace(
    /[a-zA-Z0-9_]+\s*图表\s*[（(]\s*`?(charts[\\/][^`)`\s]+\.(?:png|jpe?g|gif|webp))`?\s*[）)]/gi,
    ""
  );
  result = result.replace(
    new RegExp("(?:请参考|参考)\\s*(?:`?(" + CHART_PATH_PATTERN + ")`?\\s*)?(?:图表|上述图表|如下图表)[，,；;：:]?", "gi"),
    ""
  );
  result = result.replace(/`([a-zA-Z0-9_]+\.(?:png|jpe?g|gif|webp))`/gi, "");
  result = result.replace(/\*\*图表解读\*\*[：:][^\n]*(?:charts|outputs)[\\/][^\n。]*。?/gi, "");
  result = result.replace(/\n{3,}/g, "\n\n");
  return result.trim();
}

function fixImagePaths(html) {
  let result = html.replace(/src="(?!https?:|\/(?:files|charts)\/)([^"]+)"/gi, (_match, path) => {
    return `src="${fileUrl(path)}"`;
  });
  result = result.replace(/src='(?!https?:|\/(?:files|charts)\/)([^']+)'/gi, (_match, path) => {
    return `src="${fileUrl(path)}"`;
  });
  return result;
}

async function api(path, options = {}) {
  const headers = typeof window.Auth?.authHeaders === "function"
    ? window.Auth.authHeaders(options.body instanceof FormData ? {} : { "Content-Type": "application/json" })
    : { "Content-Type": "application/json" };
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { ...headers, ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    window.Auth?.logout?.();
    throw new Error("请先登录");
  }
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch (_err) {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

function resolveReportType(reportOrType) {
  if (typeof reportOrType === "string") {
    return reportOrType === "multi_analyze" ? "multi_analyze" : reportOrType === "annual_analyze" ? "annual_analyze" : "unknown";
  }
  const report = reportOrType || {};
  const ui = report._ui || {};
  if (ui.report_type) return String(ui.report_type);
  if (report.sections || report.charts) return "multi_analyze";
  if (report.annual_report || report.signals) return "annual_analyze";
  return "unknown";
}

function reportTypeLabel(type) {
  const resolved = resolveReportType(type);
  if (resolved === "multi_analyze") return "多智能体";
  if (resolved === "annual_analyze") return "年报分析";
  return "报告";
}

function formatDate(value) {
  if (!value) return "";
  return String(value).replace("T", " ").slice(0, 19);
}

function setTaskState(status, message, meta = "") {
  els.taskBox.classList.remove("hidden", "failed", "completed");
  els.taskMessage.textContent = message;
  els.taskMeta.textContent = meta;
  els.taskSpinner.classList.toggle("hidden", status === "completed" || status === "failed");
  els.taskBox.classList.toggle("failed", status === "failed");
  els.taskBox.classList.toggle("completed", status === "completed");
  if (status === "running" || status === "queued") {
    window.requestAnimationFrame(() => {
      els.taskBox?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }
}

function filterReports(reports, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return reports;
  return reports.filter((report) => {
    const haystack = [
      report.stock_code,
      report.title,
      report.subtitle,
      report.filename,
      reportTypeLabel(report.report_type),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(q);
  });
}

function filterSidebarItems(items, query, fields) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) =>
    fields
      .map((field) => String(item[field] || ""))
      .join(" ")
      .toLowerCase()
      .includes(q)
  );
}

function updateChatAttachButton() {
  if (!els.chatAttachReportBtn) return;
  const hasReports = state.reports.length > 0;
  els.chatAttachReportBtn.disabled = !hasReports;
  const chat = chatStateRef?.();
  const boundId = chat?.activeSession?.report_id;
  if (!hasReports) {
    els.chatAttachReportBtn.title = "暂无历史报告，请先生成或上传";
    return;
  }
  if (boundId) {
    const summary = state.reports.find((item) => item.id === boundId);
    const label = summary?.title || boundId.split("_")[0];
    els.chatAttachReportBtn.title = `当前已绑定「${label}」，点击可更换其它报告`;
    return;
  }
  els.chatAttachReportBtn.title = "从历史报告中选择一份绑定到当前对话";
}

function syncReportBindFab() {
  const btn = els.reportBindBtn;
  if (!btn) return;
  const reportId = state.activeReportId;
  const session = chatStateRef()?.activeSession;
  const bound = Boolean(reportId && session?.report_id === reportId);
  btn.disabled = !reportId;
  btn.textContent = bound ? "已绑定" : "绑定";
  btn.classList.toggle("is-bound", bound);
  btn.title = bound ? "已绑定到当前对话，点击可重新绑定" : "将本报告绑定到当前对话";
}

function setActiveReportId(reportId, reportPayload = null) {
  state.activeReportId = reportId || null;
  if (reportPayload) {
    state.activeReport = reportPayload;
  } else if (!reportId) {
    state.activeReport = null;
  }
  renderReportList();
  updateChatAttachButton();
  syncReportBindFab();
  if (typeof window.renderReportPicker === "function") {
    window.renderReportPicker();
  }
}

function renderReportList() {
  state.filteredReports = filterReports(state.reports, state.searchQuery);
  els.reportCount.textContent = String(state.reports.length);
  if (!els.reportList) return;
  if (!state.filteredReports.length) {
    els.reportList.innerHTML = `<div class="empty-state"><p>${state.reports.length ? "没有匹配的报告" : "暂无报告"}</p></div>`;
    updateChatAttachButton();
    return;
  }
  els.reportList.innerHTML = state.filteredReports
    .map((report) => {
      const active = report.id === state.activeReportId ? " active" : "";
      const typeClass = report.report_type === "multi_analyze" ? "multi" : "annual";
      const code = report.stock_code || report.filename.split("_")[0] || "—";
      const bound =
        chatStateRef()?.activeSession?.report_id === report.id
          ? `<span class="tag multi">已绑定对话</span>`
          : "";
      return `
        <div class="rail-item-row">
          <button class="rail-item${active}" data-id="${report.id}" type="button">
            <span class="rail-item-code">${code}</span>
            <span class="rail-item-title">${report.title}</span>
            <span class="rail-item-meta">${report.subtitle || ""}${report.generated_at ? " · " + formatDate(report.generated_at) : ""}</span>
            <span class="tag-row"><span class="tag ${typeClass}">${reportTypeLabel(report.report_type)}</span>${bound}</span>
          </button>
          <button class="rail-item-bind" type="button" data-bind-id="${report.id}" title="绑定到当前对话">绑定</button>
        </div>`;
    })
    .join("");
  updateChatAttachButton();
}

function chatStateRef() {
  return typeof window.getChatState === "function" ? window.getChatState() : null;
}

async function loadReports() {
  const payload = await api("/api/reports");
  state.reports = payload.reports || [];
  state.disclaimer = payload.disclaimer || "";
  els.welcomeDisclaimer.textContent = state.disclaimer;
  renderReportList();
}

async function loadReport(filename, options = {}) {
  const { navigateToReport = true, openChat = false } = options;
  try {
    const report = await api(`/api/reports/${encodeURIComponent(filename)}`);
    setActiveReportId(filename, report);
    if (navigateToReport) {
      renderReportDetail(report);
      const scrollEl = els.reportScroll;
      if (scrollEl) scrollEl.scrollTop = 0;
      setSidebarPanel("reports");
      navigate("report");
      closeMobileRail();
      if (openChat) {
        await openReportChatDrawer();
      }
    }
    return report;
  } catch (error) {
    toast(error.message || "无法打开报告", "error");
    throw error;
  }
}

function fmtMoney(value) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return `${(number / 100000000).toFixed(2)} 亿`;
}

function fmtPct(value, style = "auto") {
  if (value == null || value === "") return "数据缺失";
  const number = Number(value);
  if (Number.isNaN(number)) return "数据缺失";
  if (style === "ratio") return `${(number * 100).toFixed(1)}%`;
  const pct = Math.abs(number) <= 1 ? number * 100 : number;
  return `${pct.toFixed(2)}%`;
}

function fmtTableNum(value) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return number.toFixed(2);
}

function fmtNum(value) {
  if (value == null || value === "") return "数据缺失";
  const number = Number(value);
  if (Number.isNaN(number)) return "数据缺失";
  if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(2)} 亿`;
  if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(2)} 万`;
  return String(Number(number.toFixed(4)));
}

function sectionAnchor(title, used = new Set()) {
  let base = String(title || "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^\w\u4e00-\u9fff-]/gi, "")
    .toLowerCase();
  if (!base) base = "section";
  let anchor = base;
  let index = 2;
  while (used.has(anchor)) {
    anchor = `${base}-${index}`;
    index += 1;
  }
  used.add(anchor);
  return anchor;
}

function tocIdMap(entries) {
  const map = {};
  (entries || []).forEach((item) => {
    if (item?.title && item?.id) map[item.title] = item.id;
  });
  return map;
}

function buildMultiTocFallback(report) {
  const sections = report.sections || {};
  const sectionOrder = getMultiSectionOrder(report);
  const summary = report.executive_summary || report.summary || "";
  const titles = [];
  if (summary.trim()) titles.push("执行摘要");
  titles.push("核心指标速览", ...sectionOrder, "免责声明");
  const used = new Set();
  return titles.map((title) => ({ title, id: sectionAnchor(title, used) }));
}

function buildAnnualTocFallback(report) {
  const dataNotes = report.signals?.data_notes || report.financial_analysis?.data_notes || [];
  const titles = [
    "执行摘要",
    "核心指标",
    "审核后重点信号",
    "经营与财务分析",
    "MD&A 摘要",
  ];
  if (Array.isArray(dataNotes) && dataNotes.length) titles.push("数据说明");
  titles.push("字段来源概览", "免责声明");
  const used = new Set();
  return titles.map((title) => ({ title, id: sectionAnchor(title, used) }));
}

function resolveReportToc(report) {
  if (Array.isArray(report.table_of_contents) && report.table_of_contents.length) {
    return report.table_of_contents;
  }
  const reportType = resolveReportType(report);
  return reportType === "multi_analyze" ? buildMultiTocFallback(report) : buildAnnualTocFallback(report);
}

function setReportOutlineOpen(open) {
  state.reportOutlineOpen = open;
  els.reportBody?.classList.toggle("outline-collapsed", !open);
  els.reportOutlineBackdrop?.setAttribute("aria-hidden", open ? "false" : "true");
  if (els.reportOutlineToggleHead) {
    els.reportOutlineToggleHead.textContent = open ? "收起目录" : "目录";
  }
}

function scrollToReportSection(id) {
  const target = document.getElementById(id);
  const container = els.reportScroll;
  if (!target || !container) return;
  const next = container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - 16;
  container.scrollTo({ top: Math.max(0, next), behavior: "smooth" });
}

function bindReportOutlineEvents() {
  const open = () => setReportOutlineOpen(true);
  const close = () => setReportOutlineOpen(false);
  els.reportOutlineClose?.addEventListener("click", close);
  els.reportOutlineToggle?.addEventListener("click", open);
  els.reportOutlineBackdrop?.addEventListener("click", close);
  els.reportOutlineToggleHead?.addEventListener("click", () => setReportOutlineOpen(!state.reportOutlineOpen));
  setReportOutlineOpen(window.innerWidth > 900);
}

function setupTocScrollSpy(entries) {
  if (state.tocObserver) {
    state.tocObserver.disconnect();
    state.tocObserver = null;
  }
  if (!entries.length || !els.reportScroll) return;
  const idSet = new Set(entries.map((item) => item.id));
  const items = [...document.querySelectorAll(".report-outline-item")];
  state.tocObserver = new IntersectionObserver(
    (records) => {
      const visible = records
        .filter((record) => record.isIntersecting && idSet.has(record.target.id))
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (!visible.length) return;
      const activeId = visible[0].target.id;
      items.forEach((btn) => btn.classList.toggle("active", btn.dataset.target === activeId));
    },
    { root: els.reportScroll, rootMargin: "-20% 0px -55% 0px", threshold: [0, 0.15, 0.4, 1] }
  );
  entries.forEach((entry) => {
    const node = document.getElementById(entry.id);
    if (node) state.tocObserver.observe(node);
  });
}

function renderReportToc(report) {
  const entries = resolveReportToc(report);
  if (!els.reportToc) return tocIdMap(entries);
  if (!entries.length) {
    els.reportToc.innerHTML = "";
    setReportOutlineOpen(false);
    return {};
  }
  setReportOutlineOpen(window.innerWidth > 900 ? state.reportOutlineOpen : false);
  els.reportToc.innerHTML = entries
    .map(
      (item, index) =>
        `<button class="report-outline-item${index === 0 ? " active" : ""}" type="button" data-target="${item.id}">${item.title}</button>`
    )
    .join("");
  els.reportToc.querySelectorAll(".report-outline-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      scrollToReportSection(btn.dataset.target);
      if (window.innerWidth <= 900) setReportOutlineOpen(false);
    });
  });
  setupTocScrollSpy(entries);
  return tocIdMap(entries);
}

function cardSection(title, innerHtml, anchorId, blockClass = "report-block-accent") {
  const id = anchorId || sectionAnchor(title);
  const blockExtra = blockClass ? ` ${blockClass}` : "";
  return `<section class="report-block${blockExtra}" id="${id}">
    <header class="report-section-head"><h2 class="report-section-title">${title}</h2></header>
    <div class="report-section-body">${innerHtml}</div>
  </section>`;
}

function signalSeverityClass(severity) {
  const key = String(severity || "").toLowerCase();
  if (key === "critical") return "signal-card--critical";
  if (key === "high") return "signal-card--high";
  if (key === "medium") return "signal-card--medium";
  if (key === "low") return "signal-card--low";
  return "signal-card--neutral";
}

function signalSeverityLabel(severity) {
  const map = { critical: "严重", high: "高", medium: "中", low: "低" };
  const key = String(severity || "").toLowerCase();
  return map[key] || severity || "—";
}

function renderAnnualHero(report) {
  const meta = report.meta || {};
  const ar = report.annual_report || {};
  const secName = meta.sec_name || ar.sec_name || meta.stock_code || "—";
  const year = meta.report_year || ar.report_year || "—";
  const code = meta.stock_code || meta.order_book_id || ar.order_book_id || "";
  const signals = report.signals || report.financial_analysis || {};
  const displayCount = Array.isArray(signals.display_signals)
    ? signals.display_signals.length
    : Array.isArray(signals.reviewed_signals)
      ? signals.reviewed_signals.length
      : 0;
  const metrics = report.metrics || report.financial_analysis?.metrics || [];
  const metricYears = Array.isArray(metrics) ? metrics.map((m) => m.year).filter(Boolean) : [];

  return `<section class="report-block report-block-hero report-annual-hero" id="annual-report-hero">
    <div class="annual-hero-inner">
      <div class="annual-hero-copy">
        <span class="annual-hero-eyebrow">年报分析</span>
        <h2 class="annual-hero-title">${secName}</h2>
        <p class="annual-hero-meta">${year} 年度报告${code ? ` · ${code}` : ""}</p>
      </div>
      <div class="annual-hero-stats">
        <div class="annual-stat">
          <span class="annual-stat-value">${displayCount}</span>
          <span class="annual-stat-label">重点信号</span>
        </div>
        <div class="annual-stat">
          <span class="annual-stat-value">${metricYears.length || "—"}</span>
          <span class="annual-stat-label">财务年度</span>
        </div>
      </div>
    </div>
  </section>`;
}

function renderAnnualMetricsTable(metrics) {
  if (!Array.isArray(metrics) || !metrics.length) {
    return '<div class="empty">暂无指标表</div>';
  }
  const rows = metrics
    .map(
      (metric) => `
      <tr>
        <td>${metric.year ?? "—"}</td>
        <td>${fmtMoney(metric.revenue)}</td>
        <td>${fmtMoney(metric.net_profit_parent_company)}</td>
        <td>${fmtMoney(metric.cash_flow_from_operating_activities)}</td>
        <td>${fmtPct(metric.gross_margin, "ratio")}</td>
        <td>${fmtTableNum(metric.cash_to_revenue)}</td>
        <td>${fmtTableNum(metric.cash_to_profit)}</td>
        <td>${fmtPct(metric.debt_to_assets, "ratio")}</td>
        <td>${fmtPct(metric.roe, "ratio")}</td>
      </tr>
    `
    )
    .join("");
  return `
    <div class="report-table-wrap">
    <table class="metrics-table metrics-table-wide">
      <thead>
        <tr>
          <th>年份</th><th>营收</th><th>归母净利润</th><th>经营现金流</th>
          <th>毛利率</th><th>收现比</th><th>净现比</th><th>资产负债率</th><th>ROE</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    </div>
  `;
}

function extractExecutiveSummary(text) {
  const cleaned = String(text || "")
    .replace(/^好的[，,][^\n]*(?:\n|$)/u, "")
    .trim();
  const match = cleaned.match(/####\s*核心结论[^\n]*\n+([\s\S]*?)(?:\n---|\n####|$)/);
  if (match) return match[1].trim();
  const paragraphs = cleaned.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
  if (!paragraphs.length) return "";
  const first = paragraphs[0];
  return first.length > 600 ? `${first.slice(0, 600)}…` : first;
}

function renderSignalCard(item, { useSummary = false } = {}) {
  const severity = item.severity || "";
  const category = item.category_cn || item.category || "";
  const summary = String(useSummary ? item.summary : item.title || item.summary || "").trim();
  if (!summary) return "";
  const evidence = String(item.evidence || "").trim().replace(/。$/, "");
  const merged = Number(item.merged_count || 1);
  let body = summary.replace(/。$/, "");
  if (evidence && merged <= 1 && !body.includes(evidence)) {
    body += `（${evidence}）`;
  }
  return `<article class="signal-card ${signalSeverityClass(severity)}">
    <header class="signal-card-head">
      <span class="signal-card-severity">${signalSeverityLabel(severity)}</span>
      ${category ? `<span class="signal-card-category">${category}</span>` : ""}
    </header>
    <p class="signal-card-body">${body}。</p>
  </article>`;
}

function renderDisplaySignals(displaySignals, reviewedSignals) {
  if (Array.isArray(displaySignals) && displaySignals.length) {
    const cards = displaySignals
      .map((item) => renderSignalCard(item, { useSummary: true }))
      .filter(Boolean)
      .join("");
    return cards
      ? `<div class="signal-grid">${cards}</div>`
      : '<div class="empty">未形成可展示的结构化审核信号</div>';
  }
  if (Array.isArray(reviewedSignals) && reviewedSignals.length) {
    const cards = reviewedSignals
      .slice(0, 12)
      .map((item) => renderSignalCard(item))
      .filter(Boolean)
      .join("");
    return cards ? `<div class="signal-grid">${cards}</div>` : '<div class="empty">未形成可展示的结构化审核信号</div>';
  }
  return '<div class="empty">未形成可展示的结构化审核信号</div>';
}

function renderProvenance(provenance) {
  if (!Array.isArray(provenance) || !provenance.length) {
    return '<div class="empty">暂无字段来源信息</div>';
  }
  const items = provenance
    .map((row) => {
      const counts = row.counts || {};
      const year = row.year ?? "—";
      let line = `${year} 年：米筐 ${counts.rqdata || 0} 项，因子回补 ${counts.rqdata_factor || 0} 项，年报回退 ${counts.annual_report || 0} 项，缺失 ${counts.missing || 0} 项`;
      const missing = row.missing_fields || [];
      const totalMissing = Number(row.missing_fields_total || missing.length);
      if (missing.length) {
        let suffix = missing.join("、");
        if (totalMissing > missing.length) suffix += ` 等 ${totalMissing} 项`;
        line += `（${suffix}）`;
      }
      return `<li>${line}。</li>`;
    })
    .join("");
  return `<ul class="plain-list">${items}</ul>`;
}

function latestMarginSnapshot(dataSummary) {
  const margin = dataSummary?.inventory?.securities_margin;
  const rows = margin?.recent_rows;
  if (!Array.isArray(rows) || !rows.length) return {};
  return rows[rows.length - 1] || {};
}

function industryLabel(industry) {
  if (!industry || typeof industry !== "object") return "数据缺失";
  const priority = [
    "first_industry_name",
    "level1_name",
    "selected_industry_name",
    "industry_name",
    "citics_industry_name",
    "sec_industry",
    "industry",
  ];
  for (const key of priority) {
    const value = industry[key];
    if (value != null && value !== "") return String(value);
  }
  for (const [key, value] of Object.entries(industry)) {
    if (value == null || value === "") continue;
    const kl = String(key).toLowerCase();
    if (kl.includes("code")) continue;
    if (kl.includes("name") || kl.endsWith("industry")) return String(value);
  }
  return "数据缺失";
}

function resolveIndustryFromSummary(dataSummary, extraData) {
  const label = industryLabel(dataSummary?.industry);
  if (label !== "数据缺失") return label;
  const block = dataSummary?.industry_comparison?.industry;
  if (block && typeof block === "object") {
    for (const key of ["level1_name", "selected_industry_name", "first_industry_name"]) {
      if (block[key] != null && block[key] !== "") return String(block[key]);
    }
  }
  if (extraData && typeof extraData === "object") {
    const fromData = industryLabel(extraData.industry);
    if (fromData !== "数据缺失") return fromData;
    const cmp = extraData.industry_comparison?.industry;
    if (cmp && typeof cmp === "object") {
      for (const key of ["level1_name", "selected_industry_name", "first_industry_name"]) {
        if (cmp[key] != null && cmp[key] !== "") return String(cmp[key]);
      }
    }
  }
  return label;
}

function perShareDividend(row) {
  if (!row || typeof row !== "object") return null;
  const raw =
    row.dividend_cash_before_tax ?? row.cash_div ?? row.cash_amount ?? row.amount;
  if (raw == null) return null;
  const cash = Number(raw);
  if (!Number.isFinite(cash)) return null;
  const lot = Number(row.round_lot);
  const divisor = Number.isFinite(lot) && lot > 0 ? lot : 1;
  return cash / divisor;
}

function resolveDividendYieldTtm(dataSummary) {
  const factor = dataSummary?.factor || {};
  if (factor.dividend_yield_ttm != null) return factor.dividend_yield_ttm;
  const histRows = dataSummary?.inventory?.factor_history?.recent_rows;
  if (Array.isArray(histRows)) {
    for (let i = histRows.length - 1; i >= 0; i -= 1) {
      const value = histRows[i]?.dividend_yield_ttm;
      if (value != null) return value;
    }
  }
  const close = Number(dataSummary?.technical?.latest_close);
  const divRows = dataSummary?.inventory?.dividend?.recent_rows;
  if (!Number.isFinite(close) || close <= 0 || !Array.isArray(divRows)) return null;
  let total = 0;
  for (const row of divRows) {
    const perShare = perShareDividend(row);
    if (perShare != null && perShare > 0) total += perShare;
  }
  if (total <= 0) return null;
  return total / close;
}

function renderMultiCoreMetrics(dataSummary, extraData) {
  const technical = dataSummary?.technical || {};
  const factor = dataSummary?.factor || {};
  const margin = latestMarginSnapshot(dataSummary);
  const dividendYield = resolveDividendYieldTtm(dataSummary);
  const rows = [
    ["中信一级行业", resolveIndustryFromSummary(dataSummary, extraData)],
    ["最新收盘价", fmtNum(technical.latest_close)],
    ["MA20", fmtNum(technical.ma20)],
    ["MA60", fmtNum(technical.ma60)],
    ["20 日收益率", fmtPct(technical.return_20d)],
    ["60 日收益率", fmtPct(technical.return_60d)],
    ["RSI14", fmtNum(technical.rsi14)],
    ["20 日均量", fmtNum(technical.avg_volume_20d)],
    ["PE(TTM)", fmtNum(factor.pe_ratio_ttm)],
    ["PB(TTM)", fmtNum(factor.pb_ratio_ttm)],
    ["PS(TTM)", fmtNum(factor.ps_ratio_ttm)],
    ["股息率(TTM)", fmtPct(dividendYield)],
    ["总市值", fmtNum(factor.market_cap)],
    ["融资余额", fmtNum(margin.margin_balance)],
    ["融资买入额", fmtNum(margin.buy_on_margin_value)],
  ];
  const body = rows
    .map(([label, value]) => `<tr><td>${label}</td><td>${value}</td></tr>`)
    .join("");
  return `
    <div class="report-table-wrap">
    <table class="metrics-table metrics-table-compact">
      <thead><tr><th>指标</th><th>数值</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
    </div>
  `;
}

function getMultiSectionOrder(report) {
  const sections = report.sections || {};
  const planSections = report.plan?.sections;
  if (Array.isArray(planSections) && planSections.length) {
    const ordered = planSections.filter((name) => sections[name]);
    const rest = Object.keys(sections).filter((name) => !ordered.includes(name));
    return [...ordered, ...rest];
  }
  return Object.keys(sections);
}

function renderAnnualReport(report, anchors = {}) {
  const meta = report.meta || {};
  const analysis = report.financial_analysis || {};
  const signals = report.signals || analysis || {};
  const mda = report.mda || {};
  const metrics = report.metrics || analysis.metrics || [];
  const dataNotes = signals.data_notes || analysis.data_notes || [];
  const narrativeText =
    report.fundamental_narrative || report.summary || report.investment_director || "";
  const executiveSummary = report.executive_summary || extractExecutiveSummary(narrativeText) || "";

  els.multiSections.innerHTML = "";
  els.annualSections.innerHTML = [
    renderAnnualHero(report),
    executiveSummary
      ? cardSection(
          "执行摘要",
          `<div class="prose prose-lead">${renderMarkdown(executiveSummary)}</div>`,
          anchors["执行摘要"],
          "report-block-accent report-block-summary"
        )
      : "",
    cardSection("核心指标", renderAnnualMetricsTable(metrics), anchors["核心指标"]),
    cardSection(
      "审核后重点信号",
      renderDisplaySignals(signals.display_signals || analysis.display_signals, signals.reviewed_signals || analysis.reviewed_signals),
      anchors["审核后重点信号"]
    ),
    cardSection(
      "经营与财务分析",
      `<div class="prose">${renderMarkdown(narrativeText)}</div>`,
      anchors["经营与财务分析"]
    ),
    cardSection(
      "MD&A 摘要",
      `<div class="prose">${renderMarkdown(mda.summary_brief || mda.summary || analysis.mda_summary || "")}</div>`,
      anchors["MD&A 摘要"]
    ),
    dataNotes.length
      ? cardSection("数据说明", `<ul class="plain-list">${dataNotes.map((item) => `<li>${item}</li>`).join("")}</ul>`, anchors["数据说明"])
      : "",
    cardSection("字段来源概览", renderProvenance(report.field_provenance), anchors["字段来源概览"]),
  ]
    .filter(Boolean)
    .join("");

  els.openHtmlBtn.classList.add("hidden");
  els.reportSubtitle.textContent = [
    meta.sec_name || report.annual_report?.sec_name,
    meta.report_year || report.annual_report?.report_year,
    meta.order_book_id || report.annual_report?.order_book_id,
  ]
    .filter(Boolean)
    .join(" · ");
}

function resolveMultiSecName(report) {
  const meta = report.meta || {};
  const data = report.data || {};
  const summary = report.data_summary || {};
  const ui = report._ui || {};
  return ui.sec_name || meta.sec_name || summary.sec_name || data.sec_name || "";
}

function renderMultiReport(report, anchors = {}) {
  els.annualSections.innerHTML = "";
  const sections = report.sections || {};
  const sectionOrder = getMultiSectionOrder(report);
  const validation = report.validation || {};
  const meta = report.meta || {};
  const dataSummary = report.data_summary || {};
  const reportData = report.data || {};

  const validationClass = meta.validation_passed ? "pass" : "fail";
  const validationText = meta.validation_passed
    ? `验证通过 · 得分 ${meta.validation_score ?? validation.score ?? "—"}`
    : `验证待完善 · 得分 ${meta.validation_score ?? validation.score ?? "—"}`;

  const sectionBlocks = sectionOrder
    .map((name) =>
      cardSection(name, `<div class="prose">${renderMarkdown(sections[name] || "")}</div>`, anchors[name])
    )
    .join("");

  const executiveSummary = report.executive_summary || report.summary || "";

  els.multiSections.innerHTML = [
    `<div class="report-block report-block-validation"><div class="validation-banner ${validationClass}">${validationText}</div></div>`,
    executiveSummary
      ? cardSection(
          "执行摘要",
          `<div class="prose prose-lead">${renderMarkdown(executiveSummary)}</div>`,
          anchors["执行摘要"]
        )
      : "",
    cardSection("核心指标速览", renderMultiCoreMetrics(dataSummary, reportData), anchors["核心指标速览"]),
    sectionBlocks,
  ].join("");

  const htmlPath = meta.output_html;
  if (htmlPath) {
    const url = fileUrl(htmlPath);
    els.openHtmlBtn.classList.remove("hidden");
    els.openHtmlBtn.onclick = () => window.open(url, "_blank");
  } else {
    els.openHtmlBtn.classList.add("hidden");
  }

  els.reportSubtitle.textContent = [
    resolveMultiSecName(report),
    meta.order_book_id || report.data?.order_book_id,
    meta.start_date && meta.end_date ? `${meta.start_date} ~ ${meta.end_date}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function renderReportDetail(report) {
  const ui = report._ui || {};
  const reportType = resolveReportType(report);
  const anchors = renderReportToc(report);

  els.reportTags.innerHTML = `
    <span class="tag ${reportType === "multi_analyze" ? "multi" : "annual"}">${reportTypeLabel(reportType)}</span>
    <span class="tag">${formatDate(ui.generated_at || report.meta?.generated_at) || "—"}</span>
  `;
  els.reportTitle.textContent =
    ui.title ||
    (reportType === "multi_analyze"
      ? [report.meta?.stock_code || ui.stock_code, resolveMultiSecName(report), "多智能体报告"].filter(Boolean).join(" ")
      : report.meta?.stock_code) ||
    "分析报告";
  els.reportDisclaimer.textContent = report._disclaimer || state.disclaimer;
  if (anchors["免责声明"] && els.reportDisclaimer?.closest("section")) {
    els.reportDisclaimer.closest("section").id = anchors["免责声明"];
  }

  if (reportType === "multi_analyze") {
    renderMultiReport(report, anchors);
  } else {
    renderAnnualReport(report, anchors);
  }
  els.reportView?.classList.toggle("report-view--annual", reportType === "annual_analyze");
  els.reportView?.classList.toggle("report-view--multi", reportType === "multi_analyze");
  syncReportBindFab();
  updateMobileBarForView(state.view);
}

async function pollTask(taskId, options = {}) {
  const { stayOnChat = false, onComplete = null } = options;
  state.pollingTaskId = taskId;
  const poll = async () => {
    if (state.pollingTaskId !== taskId) return;
    const task = await api(`/api/tasks/${taskId}`);
    setTaskState(task.status, task.message || "处理中…", task.finished_at ? `完成于 ${formatDate(task.finished_at)}` : "");
    if (task.status === "completed") {
      await loadReports();
      const reportId = task.result?.report?.id || task.result?.report_id;
      if (reportId) {
        if (stayOnChat) {
          setActiveReportId(reportId);
          if (typeof onComplete === "function") {
            await onComplete(reportId, task);
          }
        } else {
          await loadReport(reportId);
        }
      } else if (typeof onComplete === "function") {
        await onComplete(null, task);
      }
      els.submitBtn.disabled = false;
      state.pollingTaskId = null;
      return;
    }
    if (task.status === "failed") {
      els.submitBtn.disabled = false;
      state.pollingTaskId = null;
      return;
    }
    setTimeout(poll, 2000);
  };
  await poll();
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!els.analyzeForm) return;
  const formData = new FormData(els.analyzeForm);
  const stock = String(formData.get("stock") || "").trim();
  if (!/^\d{6}$/.test(stock)) {
    toast("请输入 6 位 A 股代码", "error");
    els.analyzeForm.elements.stock?.focus();
    return;
  }

  const lookbackRaw = Number(formData.get("lookback_days"));
  const lookbackDays = Number.isFinite(lookbackRaw) ? lookbackRaw : 260;
  if (lookbackDays < 30 || lookbackDays > 520) {
    toast("回看天数需在 30–520 之间", "error");
    els.analyzeForm.elements.lookback_days?.focus();
    return;
  }

  const payload = {
    stock,
    as_of: formData.get("as_of") || null,
  };
  const useCachedOnly = formData.has("use_cached_only");
  const forceRefresh = formData.has("force_refresh");
  els.submitBtn.disabled = true;
  setTaskState(
    "running",
    useCachedOnly
      ? "正在用本地已入库数据生成多智能体研报（离线）…"
      : forceRefresh
        ? "正在强制刷新并生成多智能体研报…"
        : "正在生成多智能体研报…"
  );

  try {
    const response = await api("/api/multi-analyze", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        lookback_days: lookbackDays,
        use_cached_only: useCachedOnly,
        force_refresh: forceRefresh,
      }),
    });
    await pollTask(response.task_id);
  } catch (error) {
    setTaskState("failed", error.message || "任务启动失败");
    toast(error.message || "任务启动失败", "error");
    els.submitBtn.disabled = false;
  }
}

async function bootstrapAppData() {
  try {
    await api("/api/health");
    els.serverStatus?.classList.add("ok");
    if (els.serverStatusText) els.serverStatusText.textContent = "在线";
    await loadReports();
    if (typeof window.loadChatSessions === "function") {
      await window.loadChatSessions();
    }
  } catch (_error) {
    els.serverStatus?.classList.add("error");
    if (els.serverStatusText) els.serverStatusText.textContent = "离线";
    if (els.reportList) {
      els.reportList.innerHTML = `<div class="empty-state"><p>无法连接后端</p><span>请运行 python -m finagent serve</span></div>`;
    }
  }
}

async function bootstrap() {
  navigate("welcome");

  els.analyzeForm?.addEventListener("submit", handleSubmit);
  els.railAnalyze?.addEventListener("toggle", syncAnalyzeRailLayout);
  els.analyzeAdvancedToggle?.addEventListener("click", toggleAnalyzeAdvanced);
  syncAnalyzeRailLayout();
  els.refreshBtn.addEventListener("click", () => loadReports().catch((e) => toast(e.message, "error")));
  els.sidebarSearch?.addEventListener("input", (event) => {
    state.searchQuery = event.target.value;
    renderReportList();
    if (typeof window.filterChatSessions === "function") window.filterChatSessions(state.searchQuery);
  });
  document.querySelectorAll("[data-sidebar]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.sidebar;
      setSidebarPanel(panel);
      if (panel === "reports") {
        navigate(state.activeReportId ? "report" : "report-empty");
        if (isMobileLayout()) openMobileRail();
        return;
      }
      if (panel === "chat") {
        navigate("chat");
      }
    });
  });
  els.reportList?.addEventListener("click", (event) => {
    const bindBtn = event.target.closest("[data-bind-id]");
    if (bindBtn) {
      event.preventDefault();
      event.stopPropagation();
      if (typeof window.attachReportById === "function") {
        window.attachReportById(bindBtn.dataset.bindId).catch((e) => toast(e.message, "error"));
      }
      return;
    }
    const item = event.target.closest("[data-id]");
    if (!item) return;
    loadReport(item.dataset.id).catch(() => {});
    closeMobileRail();
  });
  els.backToChatBtn?.addEventListener("click", () => {
    if (state.reportChatOpen) {
      closeReportChatDrawer();
      return;
    }
    navigate("welcome");
  });
  els.reportChatToggle?.addEventListener("click", () => toggleReportChatDrawer());
  els.chatDockCloseBtn?.addEventListener("click", () => closeReportChatDrawer());
  rememberChatViewAnchor();
  els.brandHome?.addEventListener("click", () => navigate("welcome"));
  els.brandHome?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      navigate("welcome");
    }
  });
  function startWelcomeChat() {
    setSidebarPanel("chat");
    navigate("chat");
  }

  els.welcomeChatBtn?.addEventListener("click", startWelcomeChat);
  els.welcomeChatCardBtn?.addEventListener("click", startWelcomeChat);
  els.welcomeMultiBtn?.addEventListener("click", focusMultiAnalyzePanel);
  els.welcomeReportsBtn?.addEventListener("click", () => {
    setSidebarPanel("reports");
    navigate(state.activeReportId ? "report" : "report-empty");
    if (isMobileLayout()) openMobileRail();
  });
  els.askReportBtn?.addEventListener("click", () => {
    openReportChatDrawer().catch((e) => toast(e.message || "无法打开对话", "error"));
  });
  els.reportBindBtn?.addEventListener("click", () => {
    if (!state.activeReportId) return;
    if (typeof window.attachReportById !== "function") return;
    window
      .attachReportById(state.activeReportId, { preferActiveReport: true })
      .catch((e) => toast(e.message, "error"));
  });
  els.mobileMenuBtn?.addEventListener("click", toggleMobileRail);
  els.railCollapseBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    setRailCollapsed(true);
  });
  els.railExpandBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    setRailCollapsed(false);
  });
  els.railOverlay?.addEventListener("click", closeMobileRail);
  els.mobileNewChatBtn?.addEventListener("click", () => {
    if (typeof window.createChatSessionQuick === "function") {
      window.createChatSessionQuick();
    }
    closeMobileRail();
  });
  window.addEventListener("resize", () => {
    if (!isMobileLayout()) closeMobileRail();
    syncRailCollapseUi();
    syncMobileUi();
    if (isMobileLayout()) updateMobileBarForView(state.view);
  });
  syncRailCollapseUi();
  syncMobileUi();
  bindReportOutlineEvents();

  const today = new Date().toISOString().slice(0, 10);
  if (els.analyzeForm?.elements.as_of) els.analyzeForm.elements.as_of.value = today;

  if (typeof window.Auth?.ensureAuth === "function") {
    window.onAuthReady = () => bootstrapAppData().catch(() => {});
    const user = await window.Auth.ensureAuth();
    if (user) await bootstrapAppData();
  } else {
    await bootstrapAppData();
  }
}

window.App = {
  state,
  els,
  api,
  toast,
  navigate,
  openReportChatDrawer,
  closeReportChatDrawer,
  toggleReportChatDrawer,
  setSidebarPanel,
  loadReports,
  loadReport,
  setActiveReportId,
  renderReportList,
  updateChatAttachButton,
  syncReportBindFab,
  pollTask,
  setTaskState,
  reportTypeLabel,
  formatDate,
  renderMarkdown,
  openMobileRail,
  focusMultiAnalyzePanel,
  closeMobileRail,
  syncMobileBar,
  updateMobileBarForView,
  isMobileLayout,
  setRailCollapsed,
  syncRailCollapseUi,
};

bootstrap();
