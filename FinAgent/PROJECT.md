本文件为当前仓库中的任何编码 AI agent 提供工作指引，积累项目知识与实践经验，并记录推理过程和项目进展。维护要求：每当遇到或解决一个问题时，都要以追加方式记录结构化条目，至少包含时间背景、受影响代码位置、根因、解决方案；如果是重复问题，必须引用历史记录位置并说明本次差异。

## Project Overview

`FinAgent` 是一个围绕 A 股年报构建的本地命令行工作流，当前目标是把“年报获取、MD&A 提取、财务数据获取、财务分析智能体、投资总监智能体、报告输出”连成一条可重复执行的分析链路。

当前仓库内容主要包括：

- `finagent/`：核心 Python 包，负责工作流编排、新浪财经年报纯文本获取、MD&A 提取、米筐数据获取、财务字段回退、LLM 提示词构造和报告输出。
- `tests/`：针对代码分类、MD&A 提取、字段回退、`.env` 加载等关键行为的单元测试。
- `财务分析智能体_知识框架提炼.md`：财务分析智能体的分析框架原文，当前 LLM 财务分析路径会直接读取该文档作为约束输入。
- `巨潮资讯网年报批量下载指南.md`：巨潮资讯查询与 PDF 下载方式说明（**当前主数据源已切换至新浪财经，见下文**）。
- `README.md`：用户向说明，偏运行和使用层面。
- `annual_reports/`、`outputs/`：运行产物目录。

项目当前的核心任务：

1. 从新浪财经获取正式年报纯文本。
2. 从年报中提取 MD&A 文本。
3. 从米筐获取近三年 `q4` 财务数据，并在字段或指标缺失时进行回补。
4. 让财务分析智能体先识别结构化财务信号与组合异常，再在知识框架约束下输出 `positive_signals`、`negative_signals`、`key_risks`、`reviewed_signals`、`data_notes`。
5. 让投资总监智能体结合 MD&A 与财务分析结果生成最终总结。

## Key Dependencies

- `requests`：调用新浪财经接口获取年报纯文本。
- `pandas`：处理米筐返回的 DataFrame。
- `PyMuPDF`：从 PDF 中提取全文。
- `rqdatac`：获取财务原始字段与因子回补数据。
- `openai`：驱动财务分析智能体和投资总监智能体的大模型调用。

## Architecture

整体上，项目是“一条工作流 + 几个功能模块”的结构，统一入口是 `python -m finagent analyze ...`，实际执行由 `finagent.workflow.run()` 负责串联。

```mermaid
flowchart TD
    A["CLI: `python -m finagent analyze`"] --> B["`workflow.run()`"]
    B --> C["`env.load_dotenv()`"]
    B --> D["`sina_finance.latest_annual_report()`"]
    D --> E["`save_report_text()` → text file"]
    E --> G["`pdf_text.extract_mda()`"]
    B --> H["`rqdata_client.fetch_financials()`"]
    B --> I["`rqdata_client.fetch_factor_fallbacks()`"]
    B --> J["`rqdata_client.fetch_metric_factor_fallbacks()`"]
    H --> K["raw financial rows"]
    I --> L["field-level factor fallbacks"]
    K --> M["`fallback.apply_financial_fallbacks()`"]
    L --> M
    E -.-> M
    M --> N["enriched financial data"]
    N --> O["`financial_analysis.analyze_financials()`"]
    O --> P["Rule signals + LLM review or local review"]
    G --> Q["MD&A text"]
    P --> R["`llm.investment_director_analysis()`"]
    Q --> R
    R --> S["director summary"]
    P --> T["`report.render_markdown()`"]
    S --> T
    T --> U["`outputs/*.md` + `outputs/*.json`"]
```

### Overview

模块职责按数据流拆分如下：

- `cli.py`：
  负责命令行参数解析，当前只暴露 `analyze` 子命令。
- `workflow.py`：
  主编排层，负责按固定顺序调用各模块，并写出 Markdown / JSON 结果。
- `stock_utils.py`：
  提供 A 股代码分类、格式化、年份解析等通用工具函数，被其他模块复用。
- `sina_finance.py`：
  负责从新浪财经获取年报纯文本（替代原有的 cninfo PDF 下载路径），直接返回可用的文本内容。
- `cninfo.py`：
  巨潮资讯网数据获取模块（遗留/备用），保留用于回退。
- `pdf_text.py`：
  负责全文提取和 MD&A 定位；当前通过标题模式 + 目录命中规避逻辑做切分。
- `rqdata_client.py`：
  负责米筐原始财务字段获取，以及通过 `get_factor` 做字段级和指标级回补。
- `fallback.py`：
  把米筐原始字段、米筐因子回补和年报文本回退合并成统一的 `fields[field] = {value, source}` 结构。
- `financial_analysis.py`：
  先把字段加工成结构化指标与证据，再识别结构化财务信号与组合异常，最后根据环境决定走 LLM 审核路径还是本地规则审核路径。
- `signals.py`：
  负责单指标财务信号、异常组合信号和信号矩阵汇总，是财务分析链路的规则层。
- `llm.py`：
  存放两个模型入口：`financial_signal_review_agent()` 和 `investment_director_analysis()`，前者审核规则信号，后者负责投资总监层总结。
- `report.py`：
  将结构化结果渲染成 Markdown 报告，并负责写文件。
- `framework.py`：
  读取 `财务分析智能体_知识框架提炼.md`，供财务分析 LLM 提示词使用。
- `env.py`：
  读取项目根目录 `.env`，统一提供 `get_env()`。

### Important Code

最关键的执行主线在 [workflow.py](D:/BigFiles/FinAgent/finagent/workflow.py)：

1. `load_dotenv()`：确保 `.env` 中的 `OPENAI_API_KEY`、`RQDATAC2_CONF` 等在运行前可用。
2. `latest_annual_report()`：通过新浪财经接口获取最新正式年报（含纯文本正文）。
3. `save_report_text()`：保存文本到本地缓存。
4. `extract_mda()`：从纯文本中提取 MD&A 片段（无需 PDF 解析）。
5. `fetch_financials()`：取近三年 `q4` 三表字段。
6. `fetch_factor_fallbacks()`、`fetch_metric_factor_fallbacks()`：用 LYR 因子补字段和指标。
7. `apply_financial_fallbacks()`：形成带来源标记的统一字段结构。
8. `analyze_financials()`：生成财务分析智能体结果。
9. `investment_director_analysis()`：生成投资总监总结。
10. `render_markdown()`：输出用户可读报告。

### Key Implementation Steps

#### 1. 年报获取

新浪财经查询核心在 `sina_finance.latest_annual_report()`。它会：

- 通过 HTTP GET 请求 `ndbg.phtml` 列表页，解析公告 ID 和标题。
- 使用正则过滤 `摘要`、`英文版`、`更正`、`修订`、`补充` 等非正式版本。
- 通过详情页提取纯文本（从最大 `<td>` 标签取得），无需 PDF 解析。
- 自动处理 GBK 编码，通过 `parse_report_year()` 从标题中抽出报告年份。

#### 2. MD&A 提取

`pdf_text.extract_mda()` 的核心思路是：

- 输入为纯文本（来自新浪财经的 HTML 提取，无需 PDF 解析）。
- 通过 `START_PATTERNS` 找”管理层讨论与分析 / 经营情况讨论与分析 / 董事会报告”。
- 使用 `_looks_like_toc_hit()` 排除目录中的假命中。
- 通过 `END_PATTERNS` 在后续正文中寻找“第四节”等边界。

这部分设计的重点不是通用 OCR，而是尽量在现有文本 PDF 上稳定切出可供后续模型使用的 MD&A 正文。

#### 3. 财务数据与回退

`rqdata_client.py` 当前有三条取数路径：

- `fetch_financials()`：`get_pit_financials_ex` 拿三表原始字段。
- `fetch_factor_fallbacks()`：对原始字段用 `_lyr_n` 因子做字段级回补。
- `fetch_metric_factor_fallbacks()`：对本地因缺少上期余额算不出的指标，用 LYR 因子补齐。

`fallback.apply_financial_fallbacks()` 最终把每个字段统一成：

```python
{
    "value": 123.0,
    "source": "rqdata" | "rqdata_factor" | "annual_report" | "missing",
}
```

这层统一结构非常关键，因为后续 `financial_analysis.py` 和 `report.py` 都依赖这个 schema。

#### 4. 财务分析智能体

当前实现已经调整为“规则引擎先识别结构化信号 + LLM 审核解释 + 本地规则兜底”。

- 规则层：
  `analyze_financials()` 会先生成 `metrics`，再调用 `signals.detect_structured_signals()` 与 `signals.detect_compound_signals()` 形成 `raw_signals`。
- LLM 审核路径：
  当存在 `OPENAI_API_KEY` 时，`analyze_financials()` 会把 `company_context`、`framework_text`、财务证据与结构化信号一起送给 `llm.financial_signal_review_agent()`。
- 本地规则兜底：
  如果没有 `OPENAI_API_KEY`，或模型调用异常，就退回到本地审核逻辑，仍然返回同一套结构化字段，并对高风险负面信号做强制保留。

当前财务分析输出必须满足：

- `reviewed_signals`
- `positive_signals`
- `negative_signals`
- `key_risks`
- `data_notes`

其中 `reviewed_signals` 为结构化对象数组，其他字段为字符串数组，并由 `_normalize_financial_analysis_output()` 统一清洗。

#### 5. 投资总监智能体

`llm.investment_director_analysis()` 接收：

- `mda_text`
- `financial_analysis`
- `company_context`

它不会重新取数，而是站在“解释整合层”，把财务分析结果和 MD&A 做印证、覆盖性检查和总结。未配置模型密钥时，会回退到 `_local_summary()`。

### Other Modules

- `fields.py`：集中维护三表字段名、中文名和语义归属。
- `env.py`：轻量 `.env` 解析器，不依赖 `python-dotenv`。
- `report.py`：目前以 Markdown 为主，JSON 为完整中间结果。
- `tests/test_*.py`：覆盖目录命中规避、字段回补顺序、指标回补、`.env` 读取等关键行为。

## Known Issues & Solutions

### [2026-05-27] 财务分析角色错位，LLM 直接承担首轮识别职责

- 时间背景：
  2026-05-27 按照《260527修改方案.md》对财务分析链路做结构性改造。
- 受影响代码位置：
  `finagent/financial_analysis.py`、`finagent/llm.py`、`finagent/report.py`、`tests/test_financial_analysis.py`。
- 根因：
  原实现让 LLM 直接从指标和证据生成正负面结论，规则层只承担极少量兜底文案，导致信号不可追溯、难以排序过滤，也无法保证高风险指标不会在模型输出中漏掉。
- 解决方案：
  新增 `finagent/signals.py` 作为规则层，先输出 `structured_signals` 和 `compound_signals`；`financial_analysis.py` 改为“指标计算 -> 规则识别 -> LLM 审核/本地审核 -> 高风险信号保底”；`llm.py` 增加 `financial_signal_review_agent()` 审核入口；`report.py` 新增关键风险和审核后重点信号展示；测试补充组合信号与高风险信号保留断言。

### [2026-05-27] 真实命令行验证时，米筐额度错误暴露为长堆栈

- 时间背景：
  2026-05-27 在本机执行 `python -m finagent analyze --stock 600519 --as-of 2026-05-27` 做真实链路验证时触发。
- 受影响代码位置：
  `finagent/rqdata_client.py`、`finagent/cli.py`。
- 根因：
  米筐底层抛出 `QuotaExceeded` 时，原实现直接把底层异常堆栈暴露到命令行，用户难以判断这属于外部额度问题还是本地代码缺陷。
- 解决方案：
  在 `rqdata_client.py` 增加统一的米筐调用包装和错误格式化；对 `Quota exceeded` 输出明确中文提示；`cli.py` 捕获异常后只输出可读错误信息，不再把整段 traceback 直接打印给终端用户。
