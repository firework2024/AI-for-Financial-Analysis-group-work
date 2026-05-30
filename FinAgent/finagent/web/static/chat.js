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
      <div class="chat-welcome-msg">
        <h3>开始研究对话</h3>
        <p>拖 PDF 到页面、绑定左侧报告，或直接提问。需要最新数据时可以说「查一下最新融资/估值」。</p>
      </div>`;
    return;
  }
  chatEls.chatMessages.innerHTML = messages
    .map((msg) => {
      const role = msg.role === "user" ? "user" : "assistant";
      const body = escapeHtml(msg.content).replace(/\n/g, "<br>");
      const tools =
        Array.isArray(msg.tool_calls) && msg.tool_calls.length
          ? `<div class="chat-tools">${msg.tool_calls.map((t) => `<span>${escapeHtml(t.tool || "tool")}</span>`).join("")}</div>`
          : "";
      return `<div class="chat-msg chat-msg-${role}"><div class="chat-bubble">${body}${tools}</div></div>`;
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
  if (session?.pdf_name) bits.push(`PDF ${session.pdf_name}`);
  if (session?.stock_code) bits.push(session.stock_code);
  chatEls.chatContextPill.textContent = bits.length ? bits.join(" · ") : "拖 PDF 或绑定报告后开始提问";
}

async function openChatSession(sessionId) {
  const session = await api(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
  chatState.activeSessionId = sessionId;
  chatState.activeSession = session;
  renderChatSessions();
  renderChatMessages(session);
  updateChatHeader(session);
  if (session.stock_code && chatEls.chatStockInput) {
    chatEls.chatStockInput.value = session.stock_code;
  }
  App.navigate("chat");
  App.setSidebarPanel("chat");
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

async function attachActiveReportToChat() {
  if (!state.activeReportId) {
    App.toast("请先在左侧打开一份报告", "error");
    return;
  }
  if (!chatState.activeSessionId) {
    await createChatSession();
  }
  const session = await api(`/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/attach-report`, {
    method: "POST",
    body: JSON.stringify({ report_id: state.activeReportId }),
  });
  chatState.activeSession = session;
  renderChatMessages(session);
  updateChatHeader(session);
  await loadChatSessions();
  App.navigate("chat");
  App.setSidebarPanel("chat");
  App.toast("报告已绑定到当前对话");
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
  setTaskState("running", "正在生成报告并写入对话…");
  els.taskBox.classList.remove("hidden");
  await pollTask(response.task_id);
  await openChatSession(chatState.activeSessionId);
  App.toast("报告已生成");
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
window.loadChatSessions = loadChatSessions;
window.filterChatSessions = filterChatSessions;
window.createChatSessionQuick = () => createChatSession().catch((e) => App.toast(e.message, "error"));

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindChatEvents);
} else {
  bindChatEvents();
}
