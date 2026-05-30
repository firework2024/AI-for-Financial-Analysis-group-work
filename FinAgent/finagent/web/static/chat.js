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
    chatSessions: document.getElementById("chatSessions"),
    chatMessages: document.getElementById("chatMessages"),
    chatInput: document.getElementById("chatInput"),
    chatSendBtn: document.getElementById("chatSendBtn"),
    chatNewBtn: document.getElementById("chatNewBtn"),
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
        <button class="chat-session-item${active}" type="button" data-chat-id="${session.id}">
          <strong>${escapeHtml(session.title || "新对话")}</strong>
          <span>${escapeHtml(meta || "无附件")}</span>
        </button>`;
    })
    .join("");
}

function renderChatMessages(session) {
  if (!chatEls.chatMessages) return;
  const messages = session?.messages || [];
  if (!messages.length) {
    chatEls.chatMessages.innerHTML = `
      <div class="chat-welcome-card">
        <div class="chat-welcome-icon">F</div>
        <h3>开始研究对话</h3>
        <p>拖入 PDF、绑定左侧报告，或直接提问。需要最新行情时可以说「查一下最新融资余额」。</p>
        <div class="chat-suggestions">
          <button class="chat-suggestion" type="button" data-prompt="这份报告的核心风险是什么？">解读报告风险</button>
          <button class="chat-suggestion" type="button" data-prompt="最近估值水平如何？">估值水平</button>
          <button class="chat-suggestion" type="button" data-prompt="查一下最新融资余额">最新融资数据</button>
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
      const avatar = role === "user" ? "你" : "F";
      const body = escapeHtml(msg.content).replace(/\n/g, "<br>");
      const tools =
        Array.isArray(msg.tool_calls) && msg.tool_calls.length
          ? `<div class="chat-tools">${msg.tool_calls.map((t) => `<span>${escapeHtml(t.tool || "tool")}</span>`).join("")}</div>`
          : "";
      return `
        <div class="chat-msg chat-msg-${role}">
          <div class="chat-avatar" aria-hidden="true">${avatar}</div>
          <div class="chat-bubble-wrap">
            <div class="chat-bubble">${body}${tools}</div>
          </div>
        </div>`;
    })
    .join("");
  chatEls.chatMessages.scrollTop = chatEls.chatMessages.scrollHeight;
}

function updateChatHeader(session) {
  if (chatEls.chatTitle) {
    chatEls.chatTitle.textContent = session?.title || "新对话";
  }
  if (!chatEls.chatContextPill) return;
  const bits = [];
  if (session?.report_id) bits.push(`报告 ${session.report_id.split("_")[0]}`);
  if (session?.pdf_name) bits.push(`PDF · ${session.pdf_name}`);
  if (session?.stock_code) bits.push(`代码 ${session.stock_code}`);
  if (!bits.length) {
    chatEls.chatContextPill.innerHTML = `<span class="context-pill muted">拖 PDF 或绑定报告后开始提问</span>`;
    return;
  }
  chatEls.chatContextPill.innerHTML = bits.map((bit) => `<span class="context-pill">${escapeHtml(bit)}</span>`).join("");
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
  if (session.stock_code && chatEls.chatStockInput) {
    chatEls.chatStockInput.value = session.stock_code;
  }
  App.navigate("chat");
  App.setSidebarPanel("chat");
  App.renderReportList();
}

async function createChatSession() {
  const stock = String(chatEls.chatStockInput?.value || "").trim();
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: "新对话",
      ...( /^\d{6}$/.test(stock) ? { stock_code: stock } : {}),
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
  try {
    const payload = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message: pending }),
    });
    chatState.activeSession = payload.session;
    renderChatMessages(payload.session);
    updateChatHeader(payload.session);
    await loadChatSessions();
  } catch (error) {
    App.toast(error.message || "发送失败", "error");
  } finally {
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
  const session = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/attach-report`, {
    method: "POST",
    body: JSON.stringify({ report_id: reportId }),
  });
  chatState.activeSession = session;
  App.setActiveReportId(reportId);
  renderChatSessions();
  renderChatMessages(session);
  updateChatHeader(session);
  await loadChatSessions();
  closeReportPicker();
  App.navigate("chat");
  App.setSidebarPanel("chat");
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
