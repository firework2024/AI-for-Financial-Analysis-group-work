const state = {
  reports: [],
  activeReportId: null,
  activeReport: null,
  pollingTaskId: null,
  disclaimer: "",
};

const els = {
  serverStatus: document.getElementById("serverStatus"),
  refreshBtn: document.getElementById("refreshBtn"),
  analyzeForm: document.getElementById("analyzeForm"),
  submitBtn: document.getElementById("submitBtn"),
  taskBox: document.getElementById("taskBox"),
  taskSpinner: document.getElementById("taskSpinner"),
  taskMessage: document.getElementById("taskMessage"),
  taskMeta: document.getElementById("taskMeta"),
  reportCount: document.getElementById("reportCount"),
  reportList: document.getElementById("reportList"),
  welcomeView: document.getElementById("welcomeView"),
  welcomeDisclaimer: document.getElementById("welcomeDisclaimer"),
  reportView: document.getElementById("reportView"),
  reportTags: document.getElementById("reportTags"),
  reportTitle: document.getElementById("reportTitle"),
  reportSubtitle: document.getElementById("reportSubtitle"),
  openHtmlBtn: document.getElementById("openHtmlBtn"),
  summaryCard: document.getElementById("summaryCard"),
  summaryContent: document.getElementById("summaryContent"),
  annualSections: document.getElementById("annualSections"),
  multiSections: document.getElementById("multiSections"),
  reportDisclaimer: document.getElementById("reportDisclaimer"),
};

marked.setOptions({ breaks: true, gfm: true });

function normalizeFilePath(path) {
  return String(path || "")
    .replace(/^outputs[\\/]/, "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "");
}

function fileUrl(path) {
  const normalized = normalizeFilePath(path);
  return normalized ? `/files/${normalized}` : "";
}

function renderMarkdown(text, charts = null) {
  if (!text) return "<p>暂无内容</p>";
  let source = cleanChartProse(String(text));
  let html = fixImagePaths(marked.parse(source));
  html = html.replace(
    /<p><strong>图注<\/strong>\s([^<]*)<\/p>/g,
    '<p class="figure-note"><strong>图注</strong> $1</p>'
  );
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ["target"],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|data|blob):|\/files\/)/i,
  });
}

const CHART_PATH_PATTERN = String.raw`(?:charts|outputs)[\\/][\w./-]+\.(?:png|jpe?g|gif|webp)`;

function cleanChartProse(text) {
  let result = String(text);
  result = result.replace(new RegExp("!\\[[^\\]]*\\]\\((" + CHART_PATH_PATTERN + ")\\)", "gi"), "");
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
  return html.replace(/src="(?!https?:|\/files\/)([^"]+)"/g, (_match, path) => {
    return `src="${fileUrl(path)}"`;
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
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

function reportTypeLabel(type) {
  if (type === "multi_analyze") return "多智能体";
  if (type === "annual_analyze") return "年报分析";
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
}

function renderReportList() {
  els.reportCount.textContent = String(state.reports.length);
  if (!state.reports.length) {
    els.reportList.innerHTML = '<div class="empty">暂无报告，请先运行分析</div>';
    return;
  }
  els.reportList.innerHTML = state.reports
    .map((report) => {
      const active = report.id === state.activeReportId ? " active" : "";
      const typeClass = report.report_type === "multi_analyze" ? "multi" : "annual";
      const score =
        report.validation_score != null
          ? `<span class="tag">验证 ${report.validation_score}</span>`
          : "";
      return `
        <button class="report-item${active}" data-id="${report.id}" type="button">
          <h3>${report.title}</h3>
          <p>${report.subtitle || ""}${report.generated_at ? " · " + formatDate(report.generated_at) : ""}</p>
          <div class="tags">
            <span class="tag ${typeClass}">${reportTypeLabel(report.report_type)}</span>
            ${score}
          </div>
        </button>
      `;
    })
    .join("");
}

async function loadReports() {
  const payload = await api("/api/reports");
  state.reports = payload.reports || [];
  state.disclaimer = payload.disclaimer || "";
  els.welcomeDisclaimer.textContent = state.disclaimer;
  renderReportList();
}

async function loadReport(filename) {
  const report = await api(`/api/reports/${encodeURIComponent(filename)}`);
  state.activeReportId = filename;
  state.activeReport = report;
  renderReportList();
  renderReportDetail(report);
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

function cardSection(title, innerHtml) {
  return `<section class="card"><h3>${title}</h3>${innerHtml}</section>`;
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
    <table class="metrics-table metrics-table-wide">
      <thead>
        <tr>
          <th>年份</th><th>营收</th><th>归母净利润</th><th>经营现金流</th>
          <th>毛利率</th><th>收现比</th><th>净现比</th><th>资产负债率</th><th>ROE</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
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

function renderDisplaySignals(displaySignals, reviewedSignals) {
  if (Array.isArray(displaySignals) && displaySignals.length) {
    const items = displaySignals
      .map((item) => {
        const severity = item.severity || "";
        const category = item.category_cn || item.category || "";
        let summary = String(item.summary || "").trim().replace(/。$/, "");
        const evidence = String(item.evidence || "").trim().replace(/。$/, "");
        const merged = Number(item.merged_count || 1);
        if (!summary) return "";
        let text = `<strong>[${severity}/${category}]</strong> ${summary}`;
        if (evidence && merged <= 1 && !summary.includes(evidence)) {
          text += `（${evidence}）`;
        }
        return `<li>${text}。</li>`;
      })
      .filter(Boolean)
      .join("");
    return items ? `<ul class="signal-list">${items}</ul>` : '<div class="empty">未形成可展示的结构化审核信号</div>';
  }
  if (Array.isArray(reviewedSignals) && reviewedSignals.length) {
    const items = reviewedSignals
      .slice(0, 12)
      .map((item) => {
        const severity = item.severity || "";
        const category = item.category_cn || item.category || "";
        const title = item.title || "";
        const evidence = item.evidence || "";
        return `<li><strong>[${severity}/${category}]</strong> ${title}${evidence ? `（${evidence}）` : ""}。</li>`;
      })
      .join("");
    return `<ul class="signal-list">${items}</ul>`;
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
  for (const [key, value] of Object.entries(industry)) {
    if (String(key).toLowerCase().includes("industry") && value != null && value !== "") {
      return String(value);
    }
  }
  for (const value of Object.values(industry)) {
    if (value != null && value !== "") return String(value);
  }
  return "数据缺失";
}

function renderMultiCoreMetrics(dataSummary) {
  const technical = dataSummary?.technical || {};
  const factor = dataSummary?.factor || {};
  const industry = dataSummary?.industry || {};
  const margin = latestMarginSnapshot(dataSummary);
  const rows = [
    ["中信一级行业", industryLabel(industry)],
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
    ["股息率(TTM)", fmtPct(factor.dividend_yield_ttm)],
    ["总市值", fmtNum(factor.market_cap)],
    ["融资余额", fmtNum(margin.margin_balance)],
    ["融资买入额", fmtNum(margin.buy_on_margin_value)],
  ];
  const body = rows
    .map(([label, value]) => `<tr><td>${label}</td><td>${value}</td></tr>`)
    .join("");
  return `
    <table class="metrics-table metrics-table-compact">
      <thead><tr><th>指标</th><th>数值</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
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

function renderAnnualReport(report) {
  const meta = report.meta || {};
  const analysis = report.financial_analysis || {};
  const signals = report.signals || analysis || {};
  const mda = report.mda || {};
  const metrics = report.metrics || analysis.metrics || [];
  const dataNotes = signals.data_notes || analysis.data_notes || [];
  const directorText = report.summary || report.investment_director || "";

  els.multiSections.innerHTML = "";
  els.annualSections.innerHTML = [
    cardSection("核心指标", renderAnnualMetricsTable(metrics)),
    cardSection(
      "审核后重点信号",
      renderDisplaySignals(signals.display_signals || analysis.display_signals, signals.reviewed_signals || analysis.reviewed_signals)
    ),
    cardSection("投资总监分析", `<div class="markdown">${renderMarkdown(directorText)}</div>`),
    cardSection(
      "MD&A 摘要",
      `<div class="markdown">${renderMarkdown(mda.summary_brief || mda.summary || analysis.mda_summary || "")}</div>`
    ),
    dataNotes.length
      ? cardSection("数据说明", `<ul class="plain-list">${dataNotes.map((item) => `<li>${item}</li>`).join("")}</ul>`)
      : "",
    cardSection("字段来源概览", renderProvenance(report.field_provenance)),
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

function renderMultiReport(report) {
  els.annualSections.innerHTML = "";
  const sections = report.sections || {};
  const sectionOrder = getMultiSectionOrder(report);
  const charts = report.charts || {};
  const validation = report.validation || {};
  const meta = report.meta || {};
  const dataSummary = report.data_summary || {};

  const validationClass = meta.validation_passed ? "pass" : "fail";
  const validationText = meta.validation_passed
    ? `验证通过 · 得分 ${meta.validation_score ?? validation.score ?? "—"}`
    : `验证待完善 · 得分 ${meta.validation_score ?? validation.score ?? "—"}`;

  const sectionBlocks = sectionOrder
    .map(
      (name) =>
        cardSection(
          name,
          `<div class="markdown">${renderMarkdown(sections[name] || "", charts)}</div>`
        )
    )
    .join("");

  const chartCards = Object.entries(charts)
    .map(([name, path]) => {
      const url = fileUrl(path);
      return `
        <figure class="chart-card">
          <img src="${url}" alt="${name}" loading="lazy">
          <figcaption>${name}</figcaption>
        </figure>
      `;
    })
    .join("");

  els.multiSections.innerHTML = [
    `<section class="card"><div class="validation-banner ${validationClass}">${validationText}</div></section>`,
    cardSection("核心指标速览", renderMultiCoreMetrics(dataSummary)),
    sectionBlocks,
    cardSection("图表总览", `<div class="chart-grid">${chartCards || '<div class="empty">暂无图表</div>'}</div>`),
  ].join("");

  const htmlPath = meta.output_html;
  if (htmlPath) {
    const url = fileUrl(htmlPath);
    els.openHtmlBtn.classList.remove("hidden");
    els.openHtmlBtn.onclick = () => window.open(url, "_blank");
  } else {
    els.openHtmlBtn.classList.add("hidden");
  }

  els.reportSubtitle.textContent = [meta.order_book_id, meta.start_date && meta.end_date ? `${meta.start_date} ~ ${meta.end_date}` : ""]
    .filter(Boolean)
    .join(" · ");
}

function renderReportDetail(report) {
  const ui = report._ui || {};
  const reportType = ui.report_type || (report.sections ? "multi_analyze" : "annual_analyze");

  els.welcomeView.classList.add("hidden");
  els.reportView.classList.remove("hidden");

  els.reportTags.innerHTML = `
    <span class="tag ${reportType === "multi_analyze" ? "multi" : "annual"}">${reportTypeLabel(reportType)}</span>
    <span class="tag">${formatDate(ui.generated_at || report.meta?.generated_at)}</span>
  `;
  els.reportTitle.textContent = ui.title || report.meta?.stock_code || "分析报告";
  els.reportDisclaimer.textContent = report._disclaimer || state.disclaimer;

  const directorText = report.summary || report.investment_director || "";
  const executiveSummary =
    report.executive_summary || (reportType === "annual_analyze" ? extractExecutiveSummary(directorText) : report.summary) || "";
  els.summaryContent.innerHTML = renderMarkdown(executiveSummary);
  els.summaryCard.classList.toggle("hidden", !executiveSummary);
  els.summaryCard.querySelector("h3").textContent = "执行摘要";

  if (reportType === "multi_analyze") {
    renderMultiReport(report);
  } else {
    renderAnnualReport(report);
  }
}

async function pollTask(taskId) {
  state.pollingTaskId = taskId;
  const poll = async () => {
    if (state.pollingTaskId !== taskId) return;
    const task = await api(`/api/tasks/${taskId}`);
    setTaskState(task.status, task.message || "处理中…", task.finished_at ? `完成于 ${formatDate(task.finished_at)}` : "");
    if (task.status === "completed") {
      await loadReports();
      const reportId = task.result?.report?.id;
      if (reportId) await loadReport(reportId);
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
  const formData = new FormData(els.analyzeForm);
  const stock = String(formData.get("stock") || "").trim();
  if (!/^\d{6}$/.test(stock)) {
    alert("请输入 6 位 A 股代码");
    return;
  }

  const payload = {
    stock,
    as_of: formData.get("as_of") || null,
  };
  const mode = formData.get("mode");
  els.submitBtn.disabled = true;
  setTaskState("running", mode === "multi" ? "正在启动多智能体分析…" : "正在启动年报分析…");

  try {
    let response;
    if (mode === "multi") {
      response = await api("/api/multi-analyze", {
        method: "POST",
        body: JSON.stringify({ ...payload, lookback_days: Number(formData.get("lookback_days") || 260) }),
      });
    } else {
      response = await api("/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          years: Number(formData.get("years") || 3),
          no_download_cache: Boolean(formData.get("no_download_cache")),
        }),
      });
    }
    await pollTask(response.task_id);
  } catch (error) {
    setTaskState("failed", error.message || "任务启动失败");
    els.submitBtn.disabled = false;
  }
}

async function bootstrap() {
  els.analyzeForm.addEventListener("submit", handleSubmit);
  els.refreshBtn.addEventListener("click", loadReports);
  els.reportList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-id]");
    if (!item) return;
    loadReport(item.dataset.id).catch((error) => alert(error.message));
  });

  const today = new Date().toISOString().slice(0, 10);
  els.analyzeForm.elements.as_of.value = today;

  try {
    await api("/api/health");
    els.serverStatus.classList.add("ok");
    await loadReports();
  } catch (_error) {
    els.serverStatus.classList.add("error");
    els.reportList.innerHTML = '<div class="empty">无法连接后端，请先运行 python -m finagent serve</div>';
  }
}

bootstrap();
