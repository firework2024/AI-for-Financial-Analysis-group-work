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

### FinSight 快速开始

本节面向从零开始搭建 FinSight 的开发者，涵盖克隆后的准备工作、启动/关闭方式以及推荐的上手路径。

#### 克隆后的准备工作

**1. Python 虚拟环境与后端依赖**

```bash
cd FinSight
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

**2. 前端依赖**

```bash
cd frontend
pnpm install
cd ..
```

**3. 配置环境变量**

FinSight 有两份环境配置文件：

| 文件 | 用途 | 关键配置项 |
|------|------|-----------|
| `.env.server` | 后端运行时配置 | LLM API Key、数据库、数据源 API Key、RAG 模式 |
| `.env` | 前端编译期配置 + 部分后端回退 | SEC User-Agent、RAG 设置等 |

```bash
# 从模板创建（如果不存在）
copy .env.server.example .env.server
```

**必填配置**（否则应用无法启动）：

```ini
# .env.server — LLM API（以 MiniMax-M2.7 为例）
OPENAI_COMPATIBLE_API_KEY=sk-xxx
OPENAI_COMPATIBLE_API_BASE=https://api.minimaxi.com/v1
OPENAI_COMPATIBLE_MODEL=MiniMax-M2.7
```

**建议修改的配置**（当前已修改，参见 Issue 001）：

```ini
# .env.server — 将 RAG 嵌入模型改为 hash（开发环境无需下载 2.2GB 的 bge-m3）
RAG_EMBEDDING=hash
```

**推荐注册的免费 API Key**（仅推荐，不完成不影响使用，参见 Issue 002）：

| API | 注册地址 | 用途 | 没有的影响 |
|-----|---------|------|-----------|
| Finnhub | `finnhub.io` | 同行对比、财务数据回退 | 同行 Tab 可能无数据 |
| FMP | `financialmodelingprep.com` | 行业权重、持仓数据 | 部分指标回退链断裂 |

**4. 验证 SEC User-Agent（可选）**

```ini
# .env — 确保格式为"应用名 (邮箱)"
SEC_USER_AGENT=FinSight (finsight@example.com)
```

#### 启动与关闭 FinSight

**启动后端**（需要先激活虚拟环境）：

```bash
cd D:\BigFiles\AI-for-Financial-Analysis-group-work\AShareSight
..\FinSight\.venv\Scripts\activate
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

> `--reload` 可在代码变更时自动重启，开发阶段推荐开启。

**启动前端**（新开一个终端）：

```bash
cd D:\BigFiles\AI-for-Financial-Analysis-group-work\AShareSight\frontend
npm run dev
# 前端地址: http://localhost:5173
```

启动后访问 `http://localhost:5173` 即可使用。

**关闭服务**：

```bash
# 关闭前端：在终端按 Ctrl+C 或关闭终端窗口
# 关闭后端：在终端按 Ctrl+C

# 如果端口被占用，查找并杀掉进程：
# netstat -ano | findstr :8000     Windows
# lsof -i :8000                    Linux/Mac
# taskkill /PID <PID> /F            Windows
# kill -9 <PID>                     Linux/Mac
```

#### 推荐上手路径

建议先用三十分钟阅读FinSight文件夹里的`readme_cn.md`，然后上手实操。

实操请按照以下顺序逐步熟悉 FinSight，每步验证通过后再进入下一步：

**Step 1 — 确认基础可用性**

1. 启动后端和前端
2. 在 Chat 对话框发送 `AAPL 当前股价`，确认能收到正常响应
3. 如果 Chat 在 "Executing completed" 后卡住超过 30 秒，检查 `.env.server` 中 `RAG_EMBEDDING=hash` 是否生效（参见 Issue 001）

**Step 2 — 探索 Dashboard**

1. 搜索 `GOOGL` 或 `AAPL` 进入 Dashboard
2. 依次点击各 Tab：总览、财务、技术、新闻、同行、研究
3. 如果技术面/财务报表/同行对比 Tab 报错或数据空白：
   - 后端已应用超时修复（参见 Issue 002）
   - 若仍失败，需注册 Finnhub/FMP API Key
4. Research Tab → 点击"生成深度报告"，确认不再报 `missing done event`（参见 Issue 003）

**Step 3 — 深入 LLM 配置**

理解 `backend/llm_config.py` 的工作原理：
- 支持多个 LLM 端点轮询与失败冷却
- 可在 `.env.server` 中通过 `LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC` 控制冷却时间
- `LANGGRAPH_PLANNER_MODE=llm` 和 `LANGGRAPH_SYNTHESIZE_MODE=llm` 分别控制规划器和合成器使用 LLM 模式

**Step 4 — 理解 LangGraph 流水线**

阅读后端核心文件，跟踪一次完整的请求处理流程：

```
backend/graph/runner.py          → 图构建入口
backend/graph/nodes/understand_request.py → 意图理解
backend/graph/nodes/planner.py   → 规划执行步骤
backend/graph/nodes/execute_plan_stub.py → 并行执行 Agent
backend/graph/nodes/synthesize.py → 多 Agent 结果合并
backend/graph/nodes/confirmation_gate.py → 人工确认门控
```

---

## AShareSight 改造进度

> 基于 FinSight 创建 A 股版本 `AShareSight/`，替换数据源为 rqdatac，移除 RAG，完成后将进行前端换皮。

### 已完成 (2026-05-21)

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 0** | 复制 FinSight → `AShareSight/`，删除 `backend/rag/` 目录（10文件），删除美股工具（price/financial/finnhub/sec/fmp/alpha_vantage/fred），清理 `requirements.txt`，创建 `.env` | ✅ |
| **Phase 1** | 新建 `rqdata_price.py`、`rqdata_financial.py`、`rqdata_config.py`；重写 `news.py`（主数据源 `rqdatac.news.get_stock_news()`）、`macro.py`（中国宏观指标）、`env.py`、`screener.py`；新建 `utils/ticker_rq.py`；更新 `cn_hk_market.py`、`__init__.py` | ✅ |
| **Phase 2** | 7 个 Agent 全部适配 A 股：PriceAgent（rqdatac/eastmoney/search，移除期权）、FundamentalAgent（yfinance→rqdatac）、NewsAgent（finnhub→rqdatac）、MacroAgent（FRED→rqdatac）、RiskAgent（yfinance_fallback→eastmoney）、DeepSearchAgent | ✅ |
| **Phase 3** | Dashboard 层适配：`data_service.py` 重写（yfinance→rqdatac）、`peer_service.py` 改为申万行业分类、`asset_resolver.py` 改为 A 股识别、`dashboard_router.py` 默认 watchlist 改为 A 股蓝筹 | ✅ |
| **Phase 4** | LangGraph Pipeline 清理：`execute_plan_stub.py` 移除 RAG imports 和 `rag_context`/`rag_stats` artifact keys | ✅ |
| **Phase 5** | `main.py` 清理（移除 RAG lifecycle/scheduler/auth）；`system_router.py` 重写（移除全部 `/diagnostics/rag/*` 路由）；`ticker_mapping.py` 重写为 A 股 ticker；`langchain_tools.py` 适配 | ✅ |
| **Phase 6** | **前端全面换皮**：CSS 变量 `--fin-*` → `--ash-*`，暖白纸色/深墨色主题，Microsoft YaHei 字体，中国红 (#c82828) 主色，红涨绿跌；Tailwind 命名空间 `fin`→`ash`；70+ 组件批量替换；品牌重命名 `FinSight`→`AShareSight`（Sidebar/WelcomePage/Dashboard）；移除 RAG 观测导航；localStorage 键 `finsight-*`→`asharesight-*`；ECharts 主题适配 | ✅ |
| **rqdatac 安装** | `rqdatac==3.5.2` + `rqdatac_news` 安装到 FinSight .venv | ✅ |
| **Phase 7 测试清理** | 删除 RAG/US/SEC/Finnhub 相关测试 | ✅ |

### 待完成

| 内容 | 说明 |
|------|------|
| **README 文档** | 创建 `AShareSight/readme_cn.md` |

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

### Issue 004: rqdatac.news 无权限（PermissionDenied），新闻数据为空

- **发生时间**：2026-05-21
- **影响代码位置**：
  - `backend/tools/news.py` — `_fetch_rqdata_news()` 调用 `rqdatac.news.get_stock_news()` 返回 `PermissionDenied`
  - `backend/agents/news_agent.py` — `analyze_stream()` 和 `_initial_search()` 中函数名错误（`_fetch_with_rqdatac_news_news` / `_search_company_news` 不存在）
  - `backend/agents/news_agent.py` — `_fetch_search_news()` 误将 `search()` 返回的字符串当 list 遍历（`'str' object has no attribute 'get'`）
  - `backend/langchain_tools.py` — `get_company_news()` 调用 `get_stock_news()` 时传参错误（`limit=` 应为 `max_results=`，且传入了不存在的 `fast=`）
- **问题描述**：在 Chat 中询问"贵州茅台最新新闻"时，NewsAgent 返回答非所问的内容（实际是 PriceAgent 的股价数据），或返回"未找到相关新闻"。根本原因是新闻数据源全线断裂。
- **根因**：
  1. **RQData license 不含新闻权限**：RQDATAC2_CONF 许可证允许获取行情/财务/因子等数据，但 `news.get_stock_news` 需要额外付费订阅。调用返回 `rqdatac.share.errors.PermissionDenied: permission denied: news.get_stock_news`。
  2. **回退链全部断裂**：Tavily 无 API Key（`TAVILY_API_KEY` 为空）、DDGS 在公司网络不可用、Wikipedia 被金融查询跳过
  3. **函数名翻译错误**：从 FinSight 迁移时 `analyze_stream` 和 `_initial_search` 中的工具函数名未被正确更新
  4. **search() 返回值类型不匹配**：`search()` 返回格式化字符串（str），但 `_fetch_search_news` 按 `list[dict]` 遍历
  5. **langchain_tools 参数名错误**：`get_company_news()` 调用 `get_stock_news(ticker, limit=limit, fast=fast)`，但 `get_stock_news` 签名为 `(ticker, days=7, max_results=20, min_relevance=0.0)` — `limit` 和 `fast` 都不是有效参数，每次调用抛出 `TypeError`，被 except 捕获后返回错误字符串而非新闻数据。因此即使数据源已修复，Chat 流程中工具层仍然返回空数据。
- **解决方案**：
  1. **新增东方财富搜索 API** 作为主要新闻源（免费，无需 API Key）：
     - `backend/tools/news.py` 新增 `_fetch_eastmoney_news()`，调用 `search-api-web.eastmoney.com/search/jsonp` 接口
     - 注意：必须使用 `urllib.request` 而非 `requests.get()`，因为 `requests` 可能对 URL 做二次编码导致 API 返回不同结果
  2. **修复 NewsAgent 函数名**：`_fetch_with_rqdatac_news_news` → `get_stock_news`；`_search_company_news` → `search`
  3. **修复 `_fetch_search_news`**：从字符串中正则提取标题/URL，替代 `r.get("title")` 的 dict 遍历
  4. **修复 `langchain_tools.py` 参数名**：`get_company_news()` 改为 `_get_company_news(ticker, max_results=limit)`，去掉 `fast=` 参数
  5. 数据源优先级：东方财富 → rqdatac（保留，当 license 升级后可自动生效） → 网页搜索
- **验证结果**：`GET /api/stock/news/600519.XSHG` 返回 20 条新闻（来自证券时报、第一财经、21世纪经济报道等），Eastmoney API 正常工作。

### Issue 005: Dashboard 财务/估值/同行对比数据不显示

- **发生时间**：2026-05-21
- **影响代码位置**：
  - `backend/dashboard/data_service.py` — `fetch_financial_statements()` 中 `rqdatac.get_pit_financials_ex()` 参数错误；`fetch_valuation()` 和 `fetch_snapshot()` 中 rqdatac 因子名错误
  - `backend/dashboard/peer_service.py` — `fetch_peer_comparison()` 返回字段名不符合 Pydantic 模型
- **问题描述**：Dashboard 的"财务"Tab 显示空白（利润表、资产负债表等全部为 `--`），"估值"区域仅总市值有数据（PE/PB/P/S 等均为空白），"同行对比"Tab 显示"暂无同行数据"。后端日志报 Pydantic 校验错误或 rqdatac API 参数缺失。
- **根因**：
  1. **`get_pit_financials_ex` 参数名错误**：原代码传 `start_date=`/`end_date=`，但该函数要求 `start_quarter=`/`end_quarter=`（格式 `2025q1`），每次调用抛出 `TypeError: missing a required argument: 'start_quarter'`。
  2. **会计字段名不匹配**：使用的 `total_operating_revenue`、`operating_profit`、`basic_eps` 等不是有效字段。正确名称：`operating_revenue`、`profit_from_operation`、`basic_earnings_per_share`、`net_profit_deduct_non_recurring_pnl`、`cash_flow_from_operating_activities` 等。
  3. **日期列名不匹配**：rqdatac 返回的 DataFrame 日期列名为 `info_date`（非 `date`/`day`/`report_date`）。
  4. **估值因子名全部错误**（最隐蔽）：`get_factor()` 使用的 `pe_ttm`、`pb_lf`、`ps_ttm`、`dividend_yield_ratio` 在 rqdatac 中均不存在。只有 `market_cap` 碰巧正确。正确因子名为 `pe_ratio`、`pb_ratio_lf`、`ps_ratio`、`dividend_yield`。此外输出字段名应使用 Pydantic 模型要求的 `trailing_pe`、`price_to_book`、`price_to_sales`（而非 `pe_ttm`、`pb`、`ps_ttm`）。
  5. **同行对比返回字段名错误**：`fetch_peer_comparison` 返回 `symbol`，但 `PeerComparisonData` 模型要求 `subject_symbol`；`peers` 列表应为 `PeerMetrics` 对象列表，但返回了纯字符串列表。
  6. **财务期间标签用公告日期而非报告期**（2026-05-21 补充）：`_to_period()` 接收的是 `info_date`（公告日期）而非 `quarter`（报告期）。例如 2026Q1 季报于 4 月 25 日公告，`_to_period("2026-04-25")` 将 4 月映射为 Q2，错误得出 `2026Q2`。加上 `get_pit_financials_ex` 返回的 DataFrame 有 `quarter` 列（`2024q1`/`2025q2` 等）但代码未曾使用，导致利润表表头显示 "2026Q2 2026Q2 2026Q2 2026Q2 2026Q2 2025Q4 2025Q4 2025Q3"。
  7. **缺少按报告期去重**（2026-05-21 补充）：部分股票可能有多个修订版，叠加错误的 period 标签造成表头严重重复。
  8. **`gross_profit` 未包含在返回结果中**（2026-05-21 补充）：rqdatac 已查询 `gross_profit` 字段，但 `fetch_financial_statements` 的 `result` dict 未包含该键，导致利润表缺少"毛利润"行、盈利能力趋势图缺少毛利率计算。
  9. **市盈率（Forward）和 EV/EBITDA 缺失**（2026-05-21 补充）：`fetch_valuation()` 的因子查询列表缺少 `pe_ratio_2`（预测市盈率，即 Forward PE）和 `ev_to_ebitda`，这两个因子在 rqdatac 中可用但未请求。虽然返回值中已有 `forward_pe` 和 `ev_to_ebitda` 的键，但始终为 `None`，前端 ValuationGrid 对应显示 "--"。
- **解决方案**：
  1. `get_pit_financials_ex`: `start_date`/`end_date` → `start_quarter`/`end_quarter`（格式 `YYYYqN`）
  2. 财务字段名：`total_operating_revenue` → `operating_revenue`，`operating_profit` → `profit_from_operation`，`basic_eps` → `basic_earnings_per_share`，`deducted_profit` → `net_profit_deduct_non_recurring_pnl`，`operating_cash_flow` → `cash_flow_from_operating_activities` 等
  3. 日期列搜索列表增加 `info_date`
  4. 估值因子名：`pe_ttm` → `pe_ratio`，`pb_lf` → `pb_ratio_lf`，`ps_ttm` → `ps_ratio`，`dividend_yield_ratio` → `dividend_yield`。输出字段名：`pe_ttm` → `trailing_pe`，`pb` → `price_to_book`，`ps_ttm` → `price_to_sales`
  5. 同行对比：`symbol` → `subject_symbol`；`peers` 改为包含 `{"symbol", "trailing_pe", "price_to_book", "market_cap"}` 的字典列表
  6. **财务期间标签修复**：新增 `quarter` 到 `period_col` 搜索列表（优先于 `info_date`）；新增 `_period_label()` 函数直接处理 `quarter` 列的值（`2024q1` → `2024Q1`），替代 `_to_period()` 的日期转换。关键区别：`quarter` 列是报告期（如 `2026Q1`），`info_date` 是公告日期（如 `2026-04-25`）。
  7. **按报告期去重**：`groupby(quarter, as_index=False).first()` — 对同一报告期的多条修订版只保留最新一条（按 `info_date` 降序排序后取 first）。
  8. **补充 `gross_profit`**：在 `result` dict 中添加 `gross_profit` 键。
  9. **补充 Forward PE 和 EV/EBITDA**：在 `fetch_valuation()` 的因子查询列表中加入 `pe_ratio_2` 和 `ev_to_ebitda`；在返回 dict 中加入 `forward_pe` 和 `ev_to_ebitda`，校验逻辑与其他因子一致（列存在 + pd.notna）。
- **验证结果**：`GET /api/dashboard?symbol=600519.XSHG` 返回 `success: True`，`valuation.trailing_pe=19.85`，`valuation.price_to_book=6.06`，`valuation.price_to_sales=9.54`，`market_cap=1.64T`。`financials` 包含完整营收/EPS/总资产数据。`peers` 返回 7 个同行指标。**期间标签修复验证**：`periods` 从 `['2026Q2','2026Q2','2026Q2','2026Q2','2026Q2','2025Q4','2025Q4','2025Q3']`（8 个仅有 3 个唯一值）变更为 `['2026Q1','2025Q4','2025Q3','2025Q2','2025Q1','2024Q4','2024Q3','2024Q2']`（8/8 唯一，倒序正确）。`gross_profit` 字段正常返回。**Forward PE 和 EV/EBITDA 修复验证**：`forward_pe=15.07`（600519.XSHG，基于 rqdatac pe_ratio_2 因子），`ev_to_ebitda=48.97`，估值指标 6 宫格全部有值。

**Bug 10 (2026-05-22): EPS 预期 vs 实际图表无数据** — `fetch_earnings_history()` 返回字段名（`period`/`eps`）与前端 `EarningsHistoryEntry` 模型（`quarter`/`eps_actual`/`eps_estimate`/`surprise_pct`）不匹配，图表显示"暂无盈利数据"。
- **根因**：迁移时的存根，直接调用 `fetch_financial_statements` 后以原字段名返回，未映射为模型期望的字段。
- **解决方案**：重写 `fetch_earnings_history()`：先改为年度 EPS（从 `get_pit_financials_ex` 取季度数据，按 FY 汇总，尝试匹配 `forecast_eps` 因子但当前 license 无此因子），后应要求改回季度 EPS——直接复用 `fetch_financial_statements(periods=8)` 的结果，映射为 `{quarter, eps_actual}`，反转顺序为时间升序。
- **代码位置**：`backend/dashboard/data_service.py:504` — `fetch_earnings_history()`；`frontend/src/components/dashboard/tabs/financial/EarningsSurpriseChart.tsx` — 标题改为"季度 EPS"
- **验证结果**：返回 8 个季度（2024Q2→2026Q1），EPS 数值正确，时间升序。

**Bug 11 (2026-05-22): 顶部快照 EPS 显示 "--"** — 总市值/P/E/P/B 正常，仅 EPS 空白。
- **根因**：`fetch_cn_hk_quote_metrics()` 中 `get_factor(earnings_per_share)` 今天（周六）盘前因子未更新，`iloc[-1]` 取到 NaN 行。`pe_ratio` 和 `pb_ratio_lf` 恰好在同一行有值是因为更新周期不同。
- **解决方案**：回溯扫描（`for i in range(len(fdf)-1, -1, -1)`）取第一个有数据的行，与 `fetch_valuation()` 相同的修复模式。
- **代码位置**：`backend/dashboard/data_service.py:146-166` — `fetch_cn_hk_quote_metrics()` 因子查询部分
- **验证结果**：EPS=21.76（600519.XSHG），与 P/E=19.85 和 price=1311 一致。
