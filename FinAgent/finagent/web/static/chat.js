/** FinAgent 对话视图 */

const chatState = {
  sessions: [],
  filteredSessions: [],
  activeSessionId: null,
  activeSession: null,
  sending: false,
};

const chatEls = {};

function initChatElements() {
  Object.assign(chatEls, {
    chatView: document.getElementById("chatView"),
    chatTitle: document.getElementById("chatTitle"),
    chatHeadSub: document.getElementById("chatHeadSub"),
    chatSessions: document.getElementById("chatSessions"),
    chatMessages: document.getElementById("chatMessages"),
    chatInput: document.getElementById("chatInput"),
    chatSendBtn: document.getElementById("chatSendBtn"),
    chatNewBtn: document.getElementById("chatNewBtn"),
    chatDeleteBtn: document.getElementById("chatDeleteBtn"),
    chatDropZone: document.getElementById("chatDropZone"),
    chatPdfInput: document.getElementById("chatPdfInput"),
    chatAttachReportBtn: document.getElementById("chatAttachReportBtn"),
    chatAnalyzeBtn: document.getElementById("chatAnalyzeBtn"),
    chatStockInput: document.getElementById("chatStockInput"),
    chatContextPill: document.getElementById("chatContextPill"),
    reportPickerModal: document.getElementById("reportPickerModal"),
    reportPickerList: document.getElementById("reportPickerList"),
    reportPickerClose: document.getElementById("reportPickerClose"),
  });
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadChatSessions() {
  const payload = await api("/api/chat/sessions");
  chatState.sessions = payload.sessions || [];
  chatState.filteredSessions = chatState.sessions;
  renderChatSessions();
}

function filterChatSessions(query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) {
    chatState.filteredSessions = chatState.sessions;
  } else {
    chatState.filteredSessions = chatState.sessions.filter((session) =>
      [session.title, session.stock_code, session.pdf_name, session.report_id]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }
  renderChatSessions();
}

function renderChatSessions() {
  if (!chatEls.chatSessions) return;
  const list = chatState.filteredSessions;
  if (!list.length) {
    chatEls.chatSessions.innerHTML = `<div class="chat-empty">暂无对话，点「新对话」开始</div>`;
    return;
  }
  chatEls.chatSessions.innerHTML = list
    .map((session) => {
      const active = session.id === chatState.activeSessionId ? " active" : "";
      const meta = [session.stock_code, session.pdf_name, session.report_id?.split("_")[0]]
        .filter(Boolean)
        .slice(0, 2)
        .join(" · ");
      return `
        <div class="chat-session-row${active}">
          <button class="chat-session-item${active}" type="button" data-chat-id="${session.id}">
            <strong>${escapeHtml(session.title || "新对话")}</strong>
            <span>${escapeHtml(meta || "无附件")}</span>
          </button>
          <button class="chat-session-delete" type="button" data-delete-id="${session.id}" aria-label="删除对话" title="删除对话">×</button>
        </div>`;
    })
    .join("");
}

function formatChatMessageBody(msg) {
  const text = String(msg.content || "");
  if (msg.role === "user") {
    return escapeHtml(text).replace(/\n/g, "<br>");
  }
  if (typeof window.App?.renderMarkdown === "function") {
    return window.App.renderMarkdown(text);
  }
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function scrollChatToBottom() {
  const scroller = chatEls.chatDropZone || chatEls.chatMessages;
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
}

function chatThinkingHtml() {
  return `
    <div class="chat-msg chat-msg-assistant chat-msg-pending" id="chatThinking">
      <div class="chat-avatar" aria-hidden="true"><img src="/assets/logo.png" alt="" class="chat-avatar-img"></div>
      <div class="chat-bubble-wrap">
        <div class="chat-bubble chat-thinking" aria-label="正在思考">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>`;
}

function setChatThinking(active) {
  if (!chatEls.chatMessages) return;
  chatEls.chatMessages.querySelector("#chatThinking")?.remove();
  if (active) {
    chatEls.chatMessages.insertAdjacentHTML("beforeend", chatThinkingHtml());
    scrollChatToBottom();
  }
}

function renderChatMessages(session) {
  if (!chatEls.chatMessages) return;
  const messages = session?.messages || [];
  if (!messages.length) {
    chatEls.chatMessages.innerHTML = `
      <div class="chat-welcome-card">
        <img class="chat-welcome-icon" src="/assets/logo.png" alt="">
        <h3>有什么可以帮你？</h3>
        <p>上传 PDF、绑定历史报告，或直接提问。FinAgent 会结合上下文给出可追溯的分析。</p>
        <div class="chat-suggestions">
          <button class="chat-suggestion" type="button" data-prompt="这份报告的核心风险是什么？">
            <span class="chat-suggestion-label">解读报告核心风险</span>
            <span class="chat-suggestion-hint">基于已绑定报告快速摘要</span>
          </button>
          <button class="chat-suggestion" type="button" data-prompt="最近估值水平如何？">
            <span class="chat-suggestion-label">分析当前估值水平</span>
            <span class="chat-suggestion-hint">PE、PB 与历史分位</span>
          </button>
          <button class="chat-suggestion" type="button" data-prompt="查一下最新融资余额">
            <span class="chat-suggestion-label">查询最新融资数据</span>
            <span class="chat-suggestion-hint">自动调用行情工具</span>
          </button>
        </div>
      </div>`;
    chatEls.chatMessages.querySelectorAll(".chat-suggestion").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!chatEls.chatInput) return;
        chatEls.chatInput.value = btn.dataset.prompt || "";
        chatEls.chatInput.dispatchEvent(new Event("input"));
        chatEls.chatInput.focus();
      });
    });
    return;
  }
  chatEls.chatMessages.innerHTML = messages
    .map((msg) => {
      const role = msg.role === "user" ? "user" : "assistant";
      const avatar =
        role === "user"
          ? "你"
          : '<img src="/assets/logo.png" alt="" class="chat-avatar-img">';
      const body = formatChatMessageBody(msg);
      const bubbleClass = role === "assistant" ? "chat-bubble prose chat-prose" : "chat-bubble";
      const tools =
        Array.isArray(msg.tool_calls) && msg.tool_calls.length
          ? `<div class="chat-tools">${msg.tool_calls.map((t) => `<span>${escapeHtml(t.tool || "tool")}</span>`).join("")}</div>`
          : "";
      return `
        <div class="chat-msg chat-msg-${role}">
          <div class="chat-avatar" aria-hidden="true">${avatar}</div>
          <div class="chat-bubble-wrap">
            <div class="${bubbleClass}">${body}${tools}</div>
          </div>
        </div>`;
    })
    .join("");
  scrollChatToBottom();
}

function toastBootstrapStatus(session) {
  const boot = session?.data_bootstrap;
  if (!boot || boot.status === "running") return;
  if (boot.status === "completed") {
    App.toast(boot.message || "数据已入库", "success");
    return;
  }
  if (boot.status === "failed") {
    App.toast(boot.error || boot.message || "数据预加载失败", "error");
  }
}

async function pollSessionBootstrap(sessionId) {
  const maxPolls = 150;
  for (let i = 0; i < maxPolls; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    if (chatState.activeSessionId !== sessionId) return;
    try {
      const session = await api(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
      const boot = session.data_bootstrap;
      if (chatState.activeSessionId === sessionId && boot?.status === "running") {
        chatState.activeSession = session;
        updateChatHeader(session);
      }
      if (!boot || boot.status !== "running") {
        if (chatState.activeSessionId === sessionId) {
          chatState.activeSession = session;
          updateChatHeader(session);
          await loadChatSessions();
        }
        toastBootstrapStatus(session);
        return;
      }
    } catch (_e) {
      return;
    }
  }
  if (chatState.activeSessionId === sessionId) {
    App.toast("入库时间较长（可能在下载年报 PDF），请稍候或刷新对话列表查看状态", "info");
    pollSessionBootstrap(sessionId);
  }
}

function updateChatHeader(session) {
  if (chatEls.chatTitle) {
    chatEls.chatTitle.textContent = session?.title || "新对话";
  }
  if (!chatEls.chatContextPill) return;
  const bits = [];
  if (session?.report_id) bits.push(`报告 ${session.report_id.split("_")[0]}`);
  if (session?.pdf_name) bits.push(`PDF · ${session.pdf_name}`);
  const codes = Array.isArray(session?.stock_codes) ? session.stock_codes.filter(Boolean) : [];
  if (codes.length > 1) bits.push(`标的 ${codes.join("、")}`);
  else if (session?.stock_code) bits.push(`代码 ${session.stock_code}`);
  const boot = session?.data_bootstrap;
  if (boot?.status === "running") {
    const cur = boot.current || boot.stock_code;
    bits.push(cur ? `入库中 ${cur}…` : "入库中…");
  }
  if (boot?.status === "completed") bits.push("已入库");
  if (boot?.status === "failed") bits.push("入库失败");
  if (!bits.length) {
    chatEls.chatContextPill.innerHTML = `<span class="context-pill muted">拖 PDF 或绑定报告后开始提问</span>`;
  } else {
    chatEls.chatContextPill.innerHTML = bits.map((bit) => `<span class="context-pill">${escapeHtml(bit)}</span>`).join("");
  }
  const subText = bits.length ? bits.join(" · ") : "上传 PDF 或绑定报告后开始提问";
  if (chatEls.chatHeadSub) {
    chatEls.chatHeadSub.textContent = subText;
  }
  if (chatEls.chatDeleteBtn) {
    chatEls.chatDeleteBtn.disabled = !chatState.activeSessionId;
  }
  if (App.isMobileLayout?.()) {
    App.syncMobileBar(session?.title || "新对话", bits.join(" · "));
  }
}

async function openChatSession(sessionId) {
  const session = await api(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
  chatState.activeSessionId = sessionId;
  chatState.activeSession = session;
  if (session.report_id) {
    App.setActiveReportId(session.report_id);
  }
  renderChatSessions();
  renderChatMessages(session);
  updateChatHeader(session);
  syncChatStockInput(session);
  if (session.data_bootstrap?.status === "running") {
    App.toast(session.data_bootstrap.message || "正在后台下载年报并入库…", "info");
    pollSessionBootstrap(sessionId);
  }
  App.navigate("chat");
  App.setSidebarPanel("chat");
  App.renderReportList();
}

async function deleteChatSession(sessionId) {
  const targetId = String(sessionId || "").trim();
  if (!targetId) return;
  if (!window.confirm("确定删除这条对话？删除后无法恢复。")) return;

  await api(`/api/chat/sessions/${encodeURIComponent(targetId)}`, { method: "DELETE" });
  const wasActive = chatState.activeSessionId === targetId;
  if (wasActive) {
    chatState.activeSessionId = null;
    chatState.activeSession = null;
    renderChatMessages(null);
    updateChatHeader(null);
  }
  await loadChatSessions();
  if (wasActive && chatState.sessions.length) {
    await openChatSession(chatState.sessions[0].id);
  }
  App.toast("对话已删除");
}

function chatStocksPayload() {
  const raw = String(chatEls.chatStockInput?.value || "").trim();
  if (!raw) return {};
  if (/^\d{6}$/.test(raw)) return { stock_code: raw };
  return { stocks: raw };
}

function syncChatStockInput(session) {
  if (!chatEls.chatStockInput || !session) return;
  const codes = session.stock_codes;
  if (Array.isArray(codes) && codes.length) {
    chatEls.chatStockInput.value = codes.join(", ");
  } else if (session.stock_code) {
    chatEls.chatStockInput.value = session.stock_code;
  }
}

async function createChatSession() {
  const stock = String(chatEls.chatStockInput?.value || "").trim();
  if (!stock) {
    App.toast("可填写股票代码或公司名（多只请用逗号分隔），新建对话将自动入库", "info");
  }
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: "新对话",
      ...chatStocksPayload(),
    }),
  });
  await loadChatSessions();
  await openChatSession(payload.id);
}

async function sendChatMessage() {
  if (chatState.sending || !chatEls.chatInput) return;
  const text = chatEls.chatInput.value.trim();
  if (!text) return;
  if (!chatState.activeSessionId) {
    await createChatSession();
  }
  chatState.sending = true;
  chatEls.chatSendBtn.disabled = true;
  const pending = text;
  chatEls.chatInput.value = "";
  chatState.activeSession = chatState.activeSession || { messages: [] };
  chatState.activeSession.messages = [...(chatState.activeSession.messages || []), { role: "user", content: pending }];
  renderChatMessages(chatState.activeSession);
  setChatThinking(true);
  try {
    const payload = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({
        message: pending,
        ...chatStocksPayload(),
      }),
    });
    chatState.activeSession = payload.session;
    renderChatMessages(payload.session);
    updateChatHeader(payload.session);
    syncChatStockInput(payload.session);
    if (payload.session?.data_bootstrap?.status === "running") {
      App.toast(payload.session.data_bootstrap.message || "正在识别股票并入库…", "info");
      pollSessionBootstrap(chatState.activeSessionId);
    }
    await loadChatSessions();
  } catch (error) {
    App.toast(error.message || "发送失败", "error");
  } finally {
    setChatThinking(false);
    chatState.sending = false;
    chatEls.chatSendBtn.disabled = false;
    chatEls.chatInput?.focus();
  }
}

async function uploadChatPdf(file) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    App.toast("请上传 PDF 文件", "error");
    return;
  }
  if (!chatState.activeSessionId) {
    await createChatSession();
  }
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/upload`, {
    method: "POST",
    credentials: "same-origin",
    headers: window.Auth?.authHeaders?.() || {},
    body: form,
  });
  if (!response.ok) {
    let detail = "上传失败";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_e) {}
    throw new Error(detail);
  }
  const payload = await response.json();
  chatState.activeSession = payload.session;
  renderChatMessages(payload.session);
  updateChatHeader(payload.session);
  await loadChatSessions();
  App.toast("PDF 已解析并加入对话上下文");
}

async function ensureReportsLoaded() {
  if (!App.state.reports.length) {
    await App.loadReports();
  }
}

function closeReportPicker() {
  chatEls.reportPickerModal?.classList.add("hidden");
}

function sessionHasHistory(session) {
  return Array.isArray(session?.messages) && session.messages.length > 0;
}

function reportStockPrefix(reportId) {
  const prefix = String(reportId || "").split("_")[0];
  return /^\d{6}$/.test(prefix) ? prefix : null;
}

async function createContextIsolatedSession(stockCode = null) {
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: "新对话",
      ...( /^\d{6}$/.test(String(stockCode || "")) ? { stock_code: String(stockCode) } : {}),
    }),
  });
  await loadChatSessions();
  await openChatSession(payload.id);
}

async function ensureIsolatedSessionForReport(reportId) {
  if (!chatState.activeSessionId) return;
  const session = chatState.activeSession;
  if (!sessionHasHistory(session)) return;
  const currentReportId = session?.report_id || null;
  if (!currentReportId || currentReportId === reportId) return;

  const targetReport = (App.state.reports || []).find((item) => item.id === reportId);
  const targetStock = targetReport?.stock_code || reportStockPrefix(reportId) || null;
  await createContextIsolatedSession(targetStock);
  App.toast("已为新报告创建独立对话，避免上下文混淆");
}

async function ensureIsolatedSessionForAnalyze(stock) {
  if (!chatState.activeSessionId) return;
  const session = chatState.activeSession;
  if (!sessionHasHistory(session)) return;
  const currentStock = String(session?.stock_code || "");
  const currentReportStock = reportStockPrefix(session?.report_id || "");
  const mismatch =
    (currentStock && currentStock !== stock) ||
    (currentReportStock && currentReportStock !== stock);
  if (!mismatch) return;
  await createContextIsolatedSession(stock);
  App.toast("检测到股票已切换，已创建新对话");
}

function renderReportPicker() {
  if (!chatEls.reportPickerList) return;
  const reports = App.state.reports || [];
  if (!reports.length) {
    chatEls.reportPickerList.innerHTML = `<div class="chat-empty">暂无历史报告，请先在侧栏生成分析</div>`;
    return;
  }
  const boundId = chatState.activeSession?.report_id;
  chatEls.reportPickerList.innerHTML = reports
    .map((report) => {
      const active = report.id === App.state.activeReportId ? " active" : "";
      const bound = report.id === boundId ? " · 当前对话已绑定" : "";
      const code = report.stock_code || report.filename?.split("_")[0] || "—";
      const meta = [App.reportTypeLabel(report.report_type), report.generated_at ? App.formatDate(report.generated_at) : ""]
        .filter(Boolean)
        .join(" · ");
      return `
        <button class="report-picker-item${active}" type="button" data-pick-id="${report.id}">
          <span class="report-picker-copy">
            <span class="report-picker-title">${code} · ${escapeHtml(report.title || report.id)}</span>
            <span class="report-picker-meta">${escapeHtml(meta)}${bound}</span>
          </span>
          <span class="report-picker-bind">绑定</span>
        </button>`;
    })
    .join("");
}

async function openReportPicker() {
  await ensureReportsLoaded();
  if (!App.state.reports.length) {
    App.toast("暂无历史报告，请先生成分析", "error");
    return;
  }
  renderReportPicker();
  chatEls.reportPickerModal?.classList.remove("hidden");
}

async function attachReportById(reportId) {
  if (!reportId) {
    App.toast("请选择一份报告", "error");
    return;
  }
  await ensureReportsLoaded();
  if (!chatState.activeSessionId) {
    await createChatSession();
  }
  await ensureIsolatedSessionForReport(reportId);
  const session = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/attach-report`, {
    method: "POST",
    body: JSON.stringify({ report_id: reportId }),
  });
  chatState.activeSession = session;
  App.setActiveReportId(reportId);
  renderChatSessions();
  renderChatMessages(session);
  updateChatHeader(session);
  syncChatStockInput(session);
  await loadChatSessions();
  closeReportPicker();
  App.navigate("chat");
  App.setSidebarPanel("chat");
  App.closeMobileRail?.();
  App.toast("报告已绑定到当前对话");
}

async function attachActiveReportToChat() {
  await ensureReportsLoaded();
  if (!App.state.reports.length) {
    App.toast("暂无历史报告，请先在侧栏生成分析", "error");
    return;
  }
  if (App.state.activeReportId) {
    return attachReportById(App.state.activeReportId);
  }
  await openReportPicker();
}

async function analyzeInChat() {
  const stock = String(chatEls.chatStockInput?.value || "").trim();
  if (!/^\d{6}$/.test(stock)) {
    App.toast("请输入 6 位股票代码", "error");
    return;
  }
  if (!chatState.activeSessionId) {
    await createChatSession();
  }
  await ensureIsolatedSessionForAnalyze(stock);
  const response = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/analyze`, {
    method: "POST",
    body: JSON.stringify({ stock, mode: "multi" }),
  });
  App.setTaskState("running", "正在生成报告并写入对话…");
  App.els.taskBox.classList.remove("hidden");
  App.navigate("chat");
  App.setSidebarPanel("chat");
  await App.pollTask(response.task_id, {
    stayOnChat: true,
    onComplete: async (reportId) => {
      if (reportId) {
        App.setActiveReportId(reportId);
      }
      await openChatSession(chatState.activeSessionId);
    },
  });
  App.toast("报告已生成并绑定到对话");
}

function bindChatEvents() {
  initChatElements();
  chatEls.chatNewBtn?.addEventListener("click", () => createChatSession().catch((e) => App.toast(e.message, "error")));
  chatEls.chatDeleteBtn?.addEventListener("click", () => {
    if (!chatState.activeSessionId) return;
    deleteChatSession(chatState.activeSessionId).catch((e) => App.toast(e.message, "error"));
  });
  chatEls.chatSendBtn?.addEventListener("click", () => sendChatMessage());
  chatEls.chatInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChatMessage();
    }
  });
  chatEls.chatInput?.addEventListener("input", () => {
    if (!chatEls.chatInput) return;
    chatEls.chatInput.style.height = "auto";
    chatEls.chatInput.style.height = `${Math.min(chatEls.chatInput.scrollHeight, 160)}px`;
  });
  chatEls.chatAttachReportBtn?.addEventListener("click", () => attachActiveReportToChat().catch((e) => App.toast(e.message, "error")));
  chatEls.chatAnalyzeBtn?.addEventListener("click", () => analyzeInChat().catch((e) => App.toast(e.message, "error")));
  chatEls.reportPickerClose?.addEventListener("click", closeReportPicker);
  chatEls.reportPickerModal?.addEventListener("click", (event) => {
    if (event.target === chatEls.reportPickerModal) closeReportPicker();
  });
  chatEls.reportPickerList?.addEventListener("click", (event) => {
    const item = event.target.closest("[data-pick-id]");
    if (!item) return;
    attachReportById(item.dataset.pickId).catch((e) => App.toast(e.message, "error"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && chatEls.reportPickerModal && !chatEls.reportPickerModal.classList.contains("hidden")) {
      closeReportPicker();
    }
  });
  chatEls.chatPdfInput?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) uploadChatPdf(file).catch((e) => App.toast(e.message, "error"));
    event.target.value = "";
  });
  chatEls.chatSessions?.addEventListener("click", (event) => {
    const deleteBtn = event.target.closest("[data-delete-id]");
    if (deleteBtn) {
      event.preventDefault();
      event.stopPropagation();
      deleteChatSession(deleteBtn.dataset.deleteId).catch((e) => App.toast(e.message, "error"));
      return;
    }
    const item = event.target.closest("[data-chat-id]");
    if (!item) return;
    openChatSession(item.dataset.chatId).catch((e) => App.toast(e.message, "error"));
  });

  const drop = chatEls.chatDropZone;
  if (drop) {
    ["dragenter", "dragover"].forEach((name) => {
      drop.addEventListener(name, (event) => {
        event.preventDefault();
        drop.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      drop.addEventListener(name, (event) => {
        event.preventDefault();
        drop.classList.remove("dragover");
      });
    });
    drop.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) uploadChatPdf(file).catch((e) => App.toast(e.message, "error"));
    });
  }
}

window.resetChatState = () => {
  chatState.sessions = [];
  chatState.filteredSessions = [];
  chatState.activeSessionId = null;
  chatState.activeSession = null;
  renderChatSessions();
  renderChatMessages(null);
  updateChatHeader(null);
};

window.openChatWithReport = () => attachActiveReportToChat().catch((e) => App.toast(e.message, "error"));
window.attachReportById = attachReportById;
window.renderReportPicker = renderReportPicker;
window.getChatState = () => chatState;
window.loadChatSessions = loadChatSessions;
window.filterChatSessions = filterChatSessions;
window.createChatSessionQuick = () => createChatSession().catch((e) => App.toast(e.message, "error"));

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindChatEvents);
} else {
  bindChatEvents();
}
