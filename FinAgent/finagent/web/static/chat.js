/** FinAgent 对话视图 */

const chatState = {
  sessions: [],
  filteredSessions: [],
  activeSessionId: null,
  activeSession: null,
  sending: false,
  bootstrapToastKeys: new Set(),
  bootstrapModalDismissed: new Set(),
  bootstrapModalEpoch: "",
  bootstrapPolls: new Map(),
  coverageCache: new Map(),
  coverageFetchInFlight: new Set(),
  syncingData: false,
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
    chatSyncDataBtn: document.getElementById("chatSyncDataBtn"),
    chatStockInput: document.getElementById("chatStockInput"),
    chatMaxSteps: document.getElementById("chatMaxSteps"),
    chatAgentMode: document.getElementById("chatAgentMode"),
    chatContextPill: document.getElementById("chatContextPill"),
    reportPickerModal: document.getElementById("reportPickerModal"),
    reportPickerList: document.getElementById("reportPickerList"),
    reportPickerClose: document.getElementById("reportPickerClose"),
    bootstrapModal: document.getElementById("bootstrapModal"),
    bootstrapModalMessage: document.getElementById("bootstrapModalMessage"),
    bootstrapModalSpinner: document.getElementById("bootstrapModalSpinner"),
    bootstrapModalDismiss: document.getElementById("bootstrapModalDismiss"),
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
            <strong>${escapeHtml(sessionTitleDisplay(session))}</strong>
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

function renderChatWelcomeHtml(session) {
  const bound = reportLabelForSession(session);
  const lead = bound
    ? `已绑定「${escapeHtml(bound.title)}」，可直接追问结论、风险点、财务指标或股价。`
    : "上传 PDF、绑定历史报告，或直接提问。FinAgent 会结合上下文给出可追溯的分析。";
  return `
      <div class="chat-welcome-card">
        <img class="chat-welcome-icon" src="/assets/logo.png" alt="">
        <h3>有什么可以帮你？</h3>
        <p>${lead}</p>
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
}

function renderChatMessages(session) {
  if (!chatEls.chatMessages) return;
  const messages = messagesForDisplay(session);
  if (!messages.length) {
    chatEls.chatMessages.innerHTML = renderChatWelcomeHtml(session);
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
      return `
        <div class="chat-msg chat-msg-${role}">
          <div class="chat-avatar" aria-hidden="true">${avatar}</div>
          <div class="chat-bubble-wrap">
            <div class="${bubbleClass}">${body}</div>
          </div>
        </div>`;
    })
    .join("");
  scrollChatToBottom();
}

function sessionStockCodes(session) {
  const codes = Array.isArray(session?.stock_codes) ? session.stock_codes.filter(Boolean) : [];
  if (codes.length) return codes;
  return session?.stock_code ? [session.stock_code] : [];
}

function bootstrapStockSummary(boot, codes) {
  const stocks = boot?.stocks && typeof boot.stocks === "object" ? boot.stocks : {};
  const statuses = codes.map((code) => String(stocks[code]?.status || "").trim()).filter(Boolean);
  const hasDetail = statuses.length > 0;
  const ready = statuses.filter((status) => ["completed", "skipped"].includes(status)).length;
  const running = statuses.filter((status) => ["pending", "running"].includes(status)).length;
  const failed = statuses.filter((status) => status === "failed").length;
  return {
    hasDetail,
    ready,
    running,
    failed,
    total: codes.length || statuses.length,
    allReady: hasDetail && codes.length > 0 && ready === codes.length,
    hasRunning: running > 0,
    hasPartial: hasDetail && ready > 0 && ready < (codes.length || statuses.length),
  };
}

function buildDataStatusContext(session) {
  if (!session) return null;
  const boot = session.data_bootstrap;
  const codes = sessionStockCodes(session);
  const codeLabel = codes.length ? codes.join("、") : "";
  const summary = bootstrapStockSummary(boot, codes);

  if (boot?.status === "running" || summary.hasRunning) {
    const cur = boot.current || boot.stock_code || codes[0] || "";
    return {
      pills: [
        `<span class="context-pill context-pill--progress"><span class="data-status-dot" aria-hidden="true"></span>入库中 · ${escapeHtml(cur || "…")}</span>`,
      ],
      sub: boot.message || "行情 / 财务 / 年报准备中，完成后可直接提问",
    };
  }
  if (boot?.status === "completed" && codes.length && summary.allReady) {
    const cov = primaryCoverageFromBoot(boot, codes[0]);
    const annualHint = cov?.annual_report?.fresh ? "含年报" : "年报按需";
    return {
      pills: [
        `<span class="context-pill context-pill--ready"><span class="data-status-dot" aria-hidden="true"></span>基础数据就绪 · ${escapeHtml(codeLabel)}</span>`,
      ],
      sub: `行情与财务序列已同步；${annualHint}`,
    };
  }
  if ((boot?.status === "partial" || summary.hasPartial) && codes.length) {
    return {
      pills: [
        `<span class="context-pill context-pill--progress"><span class="data-status-dot" aria-hidden="true"></span>部分就绪 · ${escapeHtml(codeLabel)}</span>`,
      ],
      sub: boot.message || `已完成 ${summary.ready}/${summary.total}，其余标的待重试或仍在处理`,
    };
  }
  if (boot?.status === "completed" && codes.length) {
    return {
      pills: [
        `<span class="context-pill context-pill--bound-stock"><span class="data-status-dot" aria-hidden="true"></span>入库状态待确认 · ${escapeHtml(codeLabel)}</span>`,
      ],
      sub: "未找到完整入库明细，避免误判为已就绪；可刷新或重新触发入库",
    };
  }
  if (boot?.status === "failed") {
    return {
      pills: [
        `<span class="context-pill context-pill--failed"><span class="data-status-dot" aria-hidden="true"></span>入库失败</span>`,
        ...(codeLabel
          ? [`<span class="context-pill context-pill--bound-stock">已绑定 · ${escapeHtml(codeLabel)}</span>`]
          : []),
      ],
      sub: boot.error || boot.message || "请检查米筐/网络配置后重试",
    };
  }
  if (codes.length) {
    const cached = chatState.coverageCache.get(codes[0]);
    if (cached?.gaps?.length) {
      const gapLabels = {
        quote_refresh: "行情增量",
        market_history: "量价历史",
        market_snapshot: "量价历史",
        pit_financials: "财务",
        annual_report: "年报",
      };
      const missing = cached.gaps.map((g) => gapLabels[g] || g).join("、");
      return {
        pills: [
          `<span class="context-pill context-pill--bound-stock"><span class="data-status-dot" aria-hidden="true"></span>已绑定 · ${escapeHtml(codeLabel)}</span>`,
          `<span class="context-pill context-pill--progress">缺 ${escapeHtml(missing)}</span>`,
        ],
        sub: "可直接提问；缺项会在对话中自动补拉，或点「同步数据」",
      };
    }
    return {
      pills: [
        `<span class="context-pill context-pill--bound-stock"><span class="data-status-dot" aria-hidden="true"></span>已绑定 · ${escapeHtml(codeLabel)}</span>`,
      ],
      sub: "可直接提问；缺数据时会自动入库",
    };
  }
  return null;
}

function toastBootstrapStatus(_session) {
  /* 入库状态改由 composer 区 data-status pill 展示，不再弹 Toast */
}

function analyzeIntroReportId(content) {
  const match = String(content || "").match(/报告已生成[（(]([^）)]+)[）)]/);
  return match ? match[1].trim() : null;
}

function isStaleAnalyzeIntroMessage(msg, session) {
  if (!msg || msg.role !== "assistant") return false;
  const introId = analyzeIntroReportId(msg.content);
  if (!introId) return false;
  const bound = session?.report_id;
  if (!bound) return false;
  return introId !== bound;
}

function messagesForDisplay(session) {
  const raw = session?.messages || [];
  return raw.filter((msg) => !isStaleAnalyzeIntroMessage(msg, session));
}

function dismissBootstrapModalForSession(sessionId) {
  const sid = String(sessionId || "").trim();
  if (sid) chatState.bootstrapModalDismissed.add(sid);
  hideBootstrapModal();
}

function showBootstrapModal(session) {
  const boot = session?.data_bootstrap;
  const sid = String(session?.id || chatState.activeSessionId || "").trim();
  if (!boot || boot.status !== "running" || !chatEls.bootstrapModal) return;
  if (sid && chatState.bootstrapModalDismissed.has(sid)) return;
  const cur = boot.current || boot.stock_code;
  const titleEl = document.getElementById("bootstrapModalTitle");
  if (titleEl) titleEl.textContent = "正在入库";
  if (chatEls.bootstrapModalMessage) {
    chatEls.bootstrapModalMessage.textContent =
      boot.message || (cur ? `${cur} 入库中…` : "后台下载数据中…");
  }
  if (chatEls.bootstrapModalSpinner) {
    chatEls.bootstrapModalSpinner.className = "bootstrap-spinner";
  }
  chatEls.bootstrapModal.classList.remove("hidden");
}

function hideBootstrapModal() {
  chatEls.bootstrapModal?.classList.add("hidden");
}

function syncBootstrapModal(session) {
  /* 统一数据状态条替代浮动入库弹窗 */
  hideBootstrapModal();
}

function reportLabelForSession(session) {
  const reportId = session?.report_id;
  if (!reportId) return null;
  const summary = (App.state?.reports || []).find((item) => item.id === reportId);
  const code = summary?.stock_code || reportStockPrefix(reportId) || reportId.split("_")[0];
  const title = summary?.title || (code ? `${code} 多智能体研报` : reportId);
  return { code, title, reportId };
}

function buildComposerContext(session) {
  if (!session) return { pills: [], sub: "上传 PDF 或绑定报告后开始提问" };

  const pills = [];
  const bound = reportLabelForSession(session);
  if (bound) {
    pills.push(
      `<span class="context-pill context-pill--bound" title="${escapeHtml(bound.reportId)}">报告 · <strong>${escapeHtml(bound.title)}</strong></span>`,
    );
  } else if (session.pdf_name) {
    pills.push(`<span class="context-pill context-pill--bound">PDF · ${escapeHtml(session.pdf_name)}</span>`);
  }

  const dataStatus = buildDataStatusContext(session);
  if (dataStatus) {
    pills.push(...dataStatus.pills);
    return { pills, sub: dataStatus.sub };
  }

  if (pills.length) {
    return { pills, sub: "基于已绑定报告追问；侧栏可更换报告" };
  }
  return { pills: [], sub: "拖 PDF、绑定报告，或直接输入公司名提问" };
}

function primaryCoverageFromBoot(boot, code) {
  const stocks = boot?.stocks && typeof boot.stocks === "object" ? boot.stocks : {};
  return stocks[code]?.coverage || null;
}

function invalidateSessionCoverage(session) {
  for (const code of sessionStockCodes(session)) {
    chatState.coverageCache.delete(code);
  }
}

async function refreshSessionCoverage(session, { force = false } = {}) {
  const codes = sessionStockCodes(session).slice(0, 3);
  if (!codes.length) return;
  const toFetch = force ? codes : codes.filter((code) => !chatState.coverageCache.has(code));
  if (!toFetch.length) return;

  const flightKey = toFetch.join(",");
  if (chatState.coverageFetchInFlight.has(flightKey)) return;
  chatState.coverageFetchInFlight.add(flightKey);
  try {
    await Promise.all(
      toFetch.map(async (code) => {
        try {
          const cov = await api(`/api/data/stocks/${encodeURIComponent(code)}/coverage`);
          chatState.coverageCache.set(code, cov);
        } catch {
          /* 忽略单只覆盖查询失败 */
        }
      }),
    );
  } finally {
    chatState.coverageFetchInFlight.delete(flightKey);
  }
}

async function syncSessionData(mode = "full") {
  if (!chatState.activeSessionId) {
    App.toast("请先创建或打开对话", "error");
    return;
  }
  const session = chatState.activeSession;
  const codes = sessionStockCodes(session);
  if (!codes.length) {
    App.toast("请先在侧栏或输入框填写股票代码", "error");
    return;
  }
  if (chatState.syncingData) return;
  chatState.syncingData = true;
  setSyncDataBusy(true);
  try {
    const payload = await api(
      `/api/chat/sessions/${encodeURIComponent(chatState.activeSessionId)}/bootstrap`,
      {
        method: "POST",
        body: JSON.stringify({ mode: mode === "force" ? "force" : mode === "light" ? "light" : "full" }),
      },
    );
    chatState.activeSession = payload;
    chatState.bootstrapModalDismissed.delete(payload.id);
    invalidateSessionCoverage(payload);
    updateChatHeader(payload);
    pollSessionBootstrap(payload.id);
    App.toast(mode === "force" ? "正在强制刷新全部数据…" : "正在同步本地数据…");
  } catch (err) {
    App.toast(err.message || "同步失败", "error");
  } finally {
    chatState.syncingData = false;
    setSyncDataBusy(false);
  }
}

function setSyncDataBusy(busy) {
  if (!chatEls.chatSyncDataBtn) return;
  chatEls.chatSyncDataBtn.disabled = busy || !sessionStockCodes(chatState.activeSession).length;
  const label = chatEls.chatSyncDataBtn.querySelector("[data-sync-label]");
  if (label) label.textContent = busy ? "同步中…" : "同步数据";
}

function syncComposerChrome(session, options = {}) {
  const bound = Boolean(session?.report_id);
  if (chatEls.chatAttachReportBtn) {
    const text = bound ? "更换报告" : "绑定报告";
    const label = chatEls.chatAttachReportBtn.querySelector("[data-bind-label]");
    if (label) {
      label.textContent = text;
    } else {
      const nodes = [...chatEls.chatAttachReportBtn.childNodes];
      const textNode = nodes.find((n) => n.nodeType === Node.TEXT_NODE && String(n.textContent || "").trim());
      if (textNode) textNode.textContent = ` ${text}`;
    }
  }
  App.updateChatAttachButton?.();
  setSyncDataBusy(chatState.syncingData);
  if (options.skipCoverageRefresh || !session || !sessionStockCodes(session).length) {
    return;
  }
  const codes = sessionStockCodes(session);
  const needsFetch = options.forceCoverage || codes.some((code) => !chatState.coverageCache.has(code));
  if (!needsFetch) return;
  refreshSessionCoverage(session, { force: Boolean(options.forceCoverage) })
    .then(() => updateChatHeader(session, { skipCoverageRefresh: true }))
    .catch(() => {});
}

async function pollSessionBootstrap(sessionId) {
  if (chatState.bootstrapPolls.has(sessionId)) return;
  const pollToken = Symbol(sessionId);
  chatState.bootstrapPolls.set(sessionId, pollToken);
  const batchPolls = 150;
  try {
    while (chatState.activeSessionId === sessionId && chatState.bootstrapPolls.get(sessionId) === pollToken) {
      for (let i = 0; i < batchPolls; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (chatState.activeSessionId !== sessionId || chatState.bootstrapPolls.get(sessionId) !== pollToken) return;
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
              invalidateSessionCoverage(session);
              updateChatHeader(session, { forceCoverage: true });
              await loadChatSessions();
            }
            toastBootstrapStatus(session);
            return;
          }
        } catch (_e) {
          return;
        }
      }
      App.toast("入库时间较长（可能在下载年报 PDF），请稍候或刷新对话列表查看状态", "info");
    }
  } finally {
    if (chatState.bootstrapPolls.get(sessionId) === pollToken) {
      chatState.bootstrapPolls.delete(sessionId);
    }
  }
}

function sessionTitleDisplay(session) {
  let title = String(session?.title || "新对话").trim();
  if (!title || title === "新对话") return "新对话";
  const cut = title.split(/\s*数据预加载完成/)[0].split(/\s*入库完成/)[0].trim();
  return cut.slice(0, 32) || title;
}

function updateChatHeader(session, options = {}) {
  if (chatEls.chatTitle) {
    chatEls.chatTitle.textContent = sessionTitleDisplay(session);
  }
  const ctx = buildComposerContext(session);
  if (chatEls.chatContextPill) {
    chatEls.chatContextPill.innerHTML = ctx.pills.length
      ? ctx.pills.join("")
      : `<span class="context-pill muted">拖 PDF、绑定报告，或直接问公司名</span>`;
  }
  if (chatEls.chatHeadSub) {
    chatEls.chatHeadSub.textContent = ctx.sub;
    chatEls.chatHeadSub.classList.toggle("hidden", Boolean(ctx.pills.length));
  }
  if (chatEls.chatDeleteBtn) {
    chatEls.chatDeleteBtn.disabled = !chatState.activeSessionId;
  }
  syncComposerChrome(session, options);
  syncBootstrapModal(session);
  if (App.isMobileLayout?.()) {
    const mobileSub = ctx.pills.length ? ctx.sub : "";
    App.syncMobileBar(session?.title || "新对话", mobileSub);
  }
}

async function openChatSession(sessionId, options = {}) {
  const { stayOnReport = false, clearStockInput = false } = options;
  const session = await api(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
  chatState.activeSessionId = sessionId;
  chatState.activeSession = session;
  if (session.report_id) {
    App.setActiveReportId(session.report_id);
  }
  if (!stayOnReport) {
    App.navigate("chat");
    App.setSidebarPanel("chat");
    App.closeReportChatDrawer?.();
  }
  renderChatSessions();
  renderChatMessages(session);
  updateChatHeader(session);
  if (clearStockInput && chatEls.chatStockInput) {
    chatEls.chatStockInput.value = "";
  } else {
    syncChatStockInput(session);
  }
  if (session.data_bootstrap?.status === "running") {
    pollSessionBootstrap(sessionId);
  } else {
    toastBootstrapStatus(session);
  }
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

function chatAgentPayload() {
  const steps = parseInt(chatEls.chatMaxSteps?.value, 10);
  const mode = chatEls.chatAgentMode?.value === "single" ? "single" : "loop";
  return {
    chat_max_steps: Number.isFinite(steps) ? Math.max(1, Math.min(8, steps)) : 4,
    chat_agent_mode: mode,
  };
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

function chatSessionTitle(stocksPayload) {
  if (stocksPayload.stock_code) return `${stocksPayload.stock_code} 研报问答`;
  if (stocksPayload.stocks) {
    const label = String(stocksPayload.stocks).split(/[,，、\s]+/).find((s) => s.trim())?.trim();
    if (label) return `${label} 研报问答`;
  }
  return "新对话";
}

async function createChatSession(options = {}) {
  const { stayOnReport = false, resetStockInput = false } = options;
  const stocksPayload = chatStocksPayload();
  const hadSidebarStock = Boolean(stocksPayload.stock_code || stocksPayload.stocks);
  if (resetStockInput && chatEls.chatStockInput && !hadSidebarStock) {
    chatEls.chatStockInput.value = "";
  }
  const stock = String(chatEls.chatStockInput?.value || "").trim();
  if (!stock && !stayOnReport && !hadSidebarStock) {
    App.toast("侧栏股票可选；在对话里直接问公司名也会自动识别并入库", "info");
  }
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: chatSessionTitle(stocksPayload),
      ...stocksPayload,
    }),
  });
  chatState.bootstrapModalDismissed.delete(payload.id);
  await loadChatSessions();
  await openChatSession(payload.id, { stayOnReport, clearStockInput: resetStockInput && !hadSidebarStock });
}

async function ensureReportChatSession() {
  const reportId = App.state?.activeReportId;
  if (!reportId) {
    throw new Error("请先打开一份报告");
  }
  const bound = chatState.activeSession?.report_id;
  if (chatState.activeSessionId && bound === reportId) {
    await openChatSession(chatState.activeSessionId, { stayOnReport: true });
    return;
  }
  await createChatSessionForReport();
}

async function createChatSessionForReport() {
  const reportId = App.state?.activeReportId;
  const report = App.state?.activeReport;
  const stock = report?.stock_code || reportStockPrefix(reportId);
  const title = stock ? `${stock} 研报问答` : "新对话";
  if (chatEls.chatStockInput && stock) {
    chatEls.chatStockInput.value = stock;
  }
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      ...(stock ? { stock_code: stock } : {}),
    }),
  });
  chatState.bootstrapModalDismissed.delete(payload.id);
  await loadChatSessions();
  await openChatSession(payload.id, { stayOnReport: true });
  if (reportId) {
    await attachReportById(reportId, { preferActiveReport: true });
  }
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
        ...chatAgentPayload(),
      }),
    });
    chatState.activeSession = payload.session;
    renderChatMessages(payload.session);
    updateChatHeader(payload.session);
    syncChatStockInput(payload.session);
    if (payload.session?.data_bootstrap?.status === "running") {
      pollSessionBootstrap(chatState.activeSessionId);
    } else {
      toastBootstrapStatus(payload.session);
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
  App.syncReportBindFab?.();
  await loadChatSessions();
  closeReportPicker();
  if (App.state.view === "report") {
    App.renderReportList?.();
  } else {
    App.navigate("chat");
    App.setSidebarPanel("chat");
  }
  App.closeMobileRail?.();
  App.toast("报告已绑定到当前对话");
  App.syncReportBindFab?.();
}

async function attachActiveReportToChat(options = {}) {
  const { preferActiveReport = false } = options;
  await ensureReportsLoaded();
  if (!App.state.reports.length) {
    App.toast("暂无历史报告，请先在侧栏生成分析", "error");
    return;
  }
  const onReportView =
    preferActiveReport && App.state.view === "report" && App.state.activeReportId;
  const alreadyBound = chatState.activeSession?.report_id === App.state.activeReportId;
  if (onReportView && !alreadyBound) {
    return attachReportById(App.state.activeReportId);
  }
  await openReportPicker();
}

function bindChatEvents() {
  initChatElements();
  chatEls.chatNewBtn?.addEventListener("click", () =>
    createChatSession({ resetStockInput: true }).catch((e) => App.toast(e.message, "error")),
  );
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
  chatEls.chatSyncDataBtn?.addEventListener("click", () => syncSessionData("full").catch((e) => App.toast(e.message, "error")));
  chatEls.chatSyncDataBtn?.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    syncSessionData("force").catch((e) => App.toast(e.message, "error"));
  });
  chatEls.reportPickerClose?.addEventListener("click", closeReportPicker);
  chatEls.bootstrapModalDismiss?.addEventListener("click", (event) => {
    event.stopPropagation();
    dismissBootstrapModalForSession(chatState.activeSessionId);
  });
  chatEls.reportPickerModal?.addEventListener("click", (event) => {
    if (event.target === chatEls.reportPickerModal) closeReportPicker();
  });
  chatEls.reportPickerList?.addEventListener("click", (event) => {
    const item = event.target.closest("[data-pick-id]");
    if (!item) return;
    attachReportById(item.dataset.pickId).catch((e) => App.toast(e.message, "error"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (chatEls.reportPickerModal && !chatEls.reportPickerModal.classList.contains("hidden")) {
      closeReportPicker();
      return;
    }
    if (chatEls.bootstrapModal && !chatEls.bootstrapModal.classList.contains("hidden")) {
      dismissBootstrapModalForSession(chatState.activeSessionId);
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

window.openChatWithReport = () =>
  attachActiveReportToChat({ preferActiveReport: true }).catch((e) => App.toast(e.message, "error"));
window.attachReportById = attachReportById;
window.renderReportPicker = renderReportPicker;
window.getChatState = () => chatState;
window.loadChatSessions = loadChatSessions;
window.filterChatSessions = filterChatSessions;
window.createChatSessionQuick = () =>
  createChatSession({ resetStockInput: true }).catch((e) => App.toast(e.message, "error"));
window.createChatSessionForReport = () => createChatSessionForReport().catch((e) => App.toast(e.message, "error"));
window.ensureReportChatSession = () => ensureReportChatSession().catch((e) => App.toast(e.message, "error"));

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindChatEvents);
} else {
  bindChatEvents();
}
