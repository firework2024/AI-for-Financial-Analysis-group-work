# PROJECT.md

本文档服务于在此仓库中工作的 AI 编码智能体，提供项目引导、积累知识和项目经验，记录推理过程并追踪项目进展。

**维护方式**：遇到或解决问题时，在文末追加结构化条目（时间、代码位置、根因、解决方案）。重复问题需引用历史记录并标注差异。

---

## Project Overview

**核心目标**：参考 [FinSight](FinSight/)（基于 LangGraph + FastAPI + React 的金融分析多智能体系统），搭建自己的金融分析多智能体平台。

FinSight 是一个对话式金融研究平台，支持用户通过自然语言查询股票数据、生成分析报告、设置价格/新闻预警。核心能力包括：
- 7 个 Research Agent（Price、News、Fundamental、Technical、Macro、Risk、DeepSearch）
- 基于 LangGraph 的对话流水线（意图理解 → 规划 → 执行 → 合成 → 渲染）
- RAG 混合检索（dense + sparse + rerank）
- Dashboard 6 个分析 Tab + 5 个 AI Insight Scorer
- SSE 流式输出、会话管理、记忆持久化

---

## Key Dependencies

| 类别 | 依赖 |
|------|------|
| **LLM 框架** | LangChain 1.2、LangGraph 1.0 |
| **后端** | FastAPI、Uvicorn、Pydantic |
| **Agent 工具** | yfinance、Finnhub、Tavily、DuckDuckGo |
| **RAG** | ChromaDB、sentence-transformers（bge-m3）、FlagEmbedding |
| **前端** | React 19、Vite、Zustand 5、ECharts 6、TailwindCSS |
| **数据库** | SQLite（LangGraph checkpoint）、PostgreSQL（docker-compose） |
| **其他** | APScheduler（预警）、ReportLab（PDF 导出） |

---

## Architecture

### 整体架构

```
┌──────────────────────────────────────────────────┐
│                  Frontend (React + Vite)          │
│  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │Dashboard │  │   Chat    │  │ Execution UI  │  │
│  └────┬─────┘  └─────┬─────┘  └───────┬───────┘  │
│       │              │                │           │
└───────┼──────────────┼────────────────┼───────────┘
        │              │                │
     ┌──┴──────────────┴────────────────┴──┐
     │         FastAPI + SSE 流式           │
     │   /chat/supervisor/stream            │
     │   /api/execute                       │
     │   /api/dashboard/*                   │
     └────────────┬─────────────────────────┘
                  │
     ┌────────────┴─────────────────────────┐
     │      LangGraph Pipeline              │
     │                                      │
     │  build_initial_state → reset_turn →  │
     │  prepare_context → chat_respond →    │
     │  understand_request → policy_gate →  │
     │  planner → confirmation_gate →       │
     │  execute_plan → synthesize → render  │
     └────────────┬─────────────────────────┘
                  │
     ┌────────────┴─────────────────────────┐
     │        7 个 Research Agent            │
     │  Price / News / Fundamental /        │
     │  Technical / Macro / Risk / DeepSearch│
     └────────────┬─────────────────────────┘
                  │
     ┌────────────┴─────────────────────────┐
     │    RAG 引擎（bge-m3 + hybrid search） │
     │    Dashboard 数据服务 + 缓存          │
     │    Alert 调度器（价格/新闻预警）       │
     └──────────────────────────────────────┘
```

FinSight项目介绍详见`readme_cn.md`

### 核心模块说明

**1. LangGraph 流水线**（`backend/graph/`）

`runner.py` 构建有向图，节点按顺序执行。关键节点：
- `understand_request.py` — LLM 路由器，判断用户意图（直接回答 / 需要分析 / 警报设置）
- `planner.py` — 生成执行计划（调用 LLM 决定用哪些 Agent/工具）
- `execute_plan_stub.py` — 执行计划步骤（并行调度 Agent，可选 dry-run 或 live 工具）
- `synthesize.py` — 多 Agent 结果合并（LLM 合成 / stub 确定性合成）
- `render_stub.py` — Markdown 渲染输出

**2. 7 个 Research Agent**（`backend/agents/`）

继承自 `base_agent.py` 基类（含 reflection loop、circuit breaker）。每个 Agent 独立处理一类数据：
- `price_agent.py` — 实时/历史价格
- `news_agent.py` — 新闻抓取
- `fundamental_agent.py` — 基本面（财报、估值）
- `technical_agent.py` — 技术指标（RSI、MACD、均线）
- `macro_agent.py` — 宏观经济数据
- `risk_agent.py` — 风险评估
- `deep_search_agent.py` — 深度网络搜索

**3. RAG 引擎**（`backend/rag/`）

- `embedder.py` — bge-m3 嵌入（dense + sparse），可降级为 hash 嵌入
- `hybrid_service.py` — RRF 融合 + 重排序
- `rag_router.py` — 查询路由（SKIP / SECONDARY / PRIMARY / PARALLEL）

**4. Dashboard**（`backend/dashboard/`）

- `data_service.py` — 数据抓取（yfinance、FMP、Finnhub）
- `insights_engine.py` — 5 个 Scorer 并行执行 AI 分析
- `cache.py` — 16 类 TTL 缓存

**5. 前端**（`frontend/src/`）

- `pages/Dashboard.tsx` + `pages/ChatPage.tsx` — 两个主页面
- `store/useStore.ts` — Zustand 全局状态（Chat、Session）
- `store/dashboardStore.ts` — Dashboard 状态管理
- `api/client.ts` — SSE 流式接收

**6. 其他**

- `backend/api/` — FastAPI 路由（chat、dashboard、portfolio、alert、report 等 15+ 路由）
- `backend/services/` — 执行服务 `execution_service.py`、预警调度 `alert_scheduler.py`
- `backend/llm_config.py` — LLM 配置管理（端点轮询、失败冷却、速率限制）

---

## Known Issues & Solutions

### Issue 001: Chat 在 "Executing completed" 后卡住约 5 分钟

- **发生时间**：2026-05-20
- **影响代码位置**：
  - `backend/graph/nodes/execute_plan_stub.py` — RAG pipeline section（约第 1266 行调用 `get_rag_service()` → `hybrid_search()`）
  - `backend/rag/embedder.py` — `_BGEM3Wrapper._load()`（第 141 行）
  - `backend/rag/hybrid_service.py` — `_InMemoryHybridStore.hybrid_search()`（第 467 行调用 `_embed_text()`）
- **问题描述**：用户在 Chat 对话框发送消息后，前端正常显示 Planning → Executing 阶段，但在 "Executing completed" 后停滞约 5 分钟（实测 281 秒），然后突然恢复并输出结果。后续同一话题的对话则正常快速响应。
- **根因**：`execute_plan_stub` 中的 RAG pipeline 在首次请求时触发了 **bge-m3 嵌入模型（BAAI/bge-m3，~2.2GB）的惰性下载和加载**。`_BGEM3Wrapper._load()` → `BGEM3FlagModel("BAAI/bge-m3")` 首次调用时需从 HuggingFace 下载模型文件，在中国网络环境下下载极慢，且没有进度反馈给前端。第二次请求时模型已缓存在内存中，故响应正常。
  - 时序证据：首次请求 Executing done (10.8s) → Synthesize start (292.1s) = 281s 间隙；第二次请求间隙仅 2.7s。
- **解决方案**：将嵌入后端从 `bge-m3` 切换为 `hash`。对于开发环境（RAG `doc_count=0`，无实际检索需求）完全足够，且避免模型下载。
  ```python
  # .env.server 修改
  # RAG_EMBEDDING=bge-m3  ← 旧值
  RAG_EMBEDDING=hash        # 新值
  ```
  修改后需重启后端服务器使配置生效。
- **验证结果**：修复后 Executing → Synthesize 间隙从 281s 降至 **0.0s**。


### Issue 002: Dashboard 技术面/财务报表/同行对比 Tab 数据缺失

- **发生时间**：2026-05-20
- **影响代码位置**：
  - `backend/api/dashboard_router.py` — `v2_fetch_config`（technicals timeout: 8s, financials timeout: 10s, peers timeout: 18s）
  - `backend/dashboard/peer_service.py` — `fetch_peer_comparison()` 内部 `as_completed(timeout=8)`
  - `backend/dashboard/data_service.py` — `fetch_technical_indicators()` / `fetch_financial_statements()` 每次独立调用 yfinance，无数据复用
  - `backend/tools/sec.py` — `get_sec_company_facts_quarterly()` 因 `SEC_USER_AGENT=FinSight` 不含 email 被拒绝
  - `backend/tools/fmp.py` / `backend/tools/env.py` — FMP、Finnhub 等 API Key 均为空，回退失效
- **问题描述**：Dashboard 的"技术面"Tab 报错 `technicals_unavailable`、"财务报表"Tab 数据空白、"同行对比"Tab 显示"暂无同行数据"。Chat 对话中的股票价格和新闻获取正常（通过 Chat Agent）。
- **根因**：这是三层叠加问题：
  1. **超时过低**：技术面指标获取独立调用 yfinance 下载 1年日K线，但超时仅 8s（K线图是 15s——因为 `_run_blocking` 默认超时）。在中国网络环境下 yfinance 可能耗时 10-15s，8s 极易超时。同行对比需串行拉取 7 只股票数据，内部 `as_completed` 超时 8s 不够。
  2. **回退链全部断裂**：FMP（`FMP_API_KEY` 为空）、Finnhub（`FINNHUB_API_KEY` 为空）、SEC EDGAR（`SEC_USER_AGENT=FinSight` 不含 email，SEC 要求 `"用户名 邮箱"` 格式）——三个回退均不可用。
  3. **数据未复用**：K线图已通过 `_load_ohlcv_frame()` 获取 OHLCV DataFrame，但技术面指标和财务数据各自再次独立调用 yfinance，浪费了已加载的数据。
- **解决方案**：
  ```python
  # 1. dashboard_router.py: 增加超时
  # technicals: 8s → 20s
  # financials: 10s → 20s
  # peers: 18s → 30s
  
  # 2. peer_service.py: 增加内部批处理超时
  # as_completed(timeout=8) → as_completed(timeout=15)
  
  # 3. data_service.py: 增加 OHLCV DataFrame 级缓存（60s TTL）
  # _load_ohlcv_frame() 的结果缓存在 _OHLCV_FRAME_CACHE 中，
  # 后续 fetch_technical_indicators() 直接从缓存读取，避免重复 yfinance 请求。
  
  # 4. .env.server / .env: 修复 SEC 回退
  # SEC_USER_AGENT=FinSight → SEC_USER_AGENT=FinSight (finsight@example.com)
  ```
- **可选增强**：
  - 注册免费 Finnhub API Key（`finnhub.io`）以启用同行对比和财务数据回退
  - 注册免费 FMP API Key（`financialmodelingprep.com`）以启用行业权重和持仓数据
- **验证方法**：重启后端后访问 Dashboard 各 Tab，确认技术面、财务报表、同行对比不再报错。

### Issue 003: Research Tab "深度研究" 执行流中断 — SSE 流在 confirmation_gate interrupt 后未正确处理

- **发生时间**：2026-05-20
- **影响代码位置**：
  - `frontend/src/api/client.ts` — `sendMessageStream()`（约第 1030 行）、`executeAgent()`（约第 1090 行）、`resumeExecution()`（约第 1199 行）三处 SSE 流结束检查
  - `backend/api/execution_router.py` — `execute_endpoint()`（约第 152 行）未为 dashboard source 设置 `confirmation_mode`
  - `backend/graph/runner.py` — `ainvoke()`（第 217 行）默认 `confirmation_mode` 为 `"auto"`
- **问题描述**：用户点击 Dashboard Research Tab 的"生成深度报告"按钮后，前端显示 Planner completed 和"执行计划确认"中断提示，但同时抛出 `Execution stream ended unexpectedly (missing done event)` 错误。最终执行状态显示为 `error` 而非 `interrupted`，导致报告无法生成。
- **根因**：这是一个**双层问题**：
  1. **SSE 流处理缺陷**：后端在 `confirmation_gate` 触发 `interrupt()` 时，发送 `type: "interrupt"` 事件后关闭 SSE 流（不发 `done` 事件）。前端 `client.ts` 的 `sendMessageStream()` 和 `executeAgent()` 函数在流结束后检查 `!sawDone && !sawError` 为 true，触发 `"missing done event"` 错误回调，覆盖了已设置的 `interrupted` 状态。
  2. **确认模式默认值错误**：`execution_router.py` 将 `confirmation_mode=None` 透传给 `run_graph_pipeline`，最终在 `runner.ainvoke()` 中默认转为 `"auto"`。而 `auto` 模式下 `output_mode=investment_report` 会触发 `confirmation_gate` 中断。Dashboard Research Tab 没有 InterruptCard 确认 UI，因此执行永远卡在确认阶段。
- **解决方案**（两个修复）：

  **修复 1 — 前端 `client.ts`**：在三处 SSE 流处理函数中增加 `sawInterrupt` 标志位。当收到 `type: "interrupt"` 事件时标记 `sawInterrupt=true`，在流结束检查中排除中断场景：
  ```typescript
  // 增加变量
  let sawInterrupt = false;

  // 包装 onInterrupt 回调
  onInterrupt: (data) => {
    sawInterrupt = true;
    callbacks.onInterrupt?.(data);
  };

  // 修改结尾检查
  if (!sawDone && !sawError && !sawInterrupt) {
    wrappedOnError('Execution stream ended unexpectedly (missing done event)');
  }
  ```

  **修复 2 — 后端 `execution_router.py`**：对 `source` 以 `"dashboard"` 开头的请求，默认将 `confirmation_mode` 设为 `"skip"`：
  ```python
  confirmation_mode = parse_confirmation_mode(request.confirmation_mode)
  if confirmation_mode is None:
      src = (request.source or "").lower()
      confirmation_mode = "skip" if src.startswith("dashboard") else "auto"
  ```
- **验证方法**：访问 Dashboard → Research Tab → 点击"生成深度报告"，观察执行流程是否跳过确认步骤直接执行，且不再抛出 `missing done event` 错误。
