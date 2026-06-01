# AShareSight — A股金融分析多智能体平台 方案

## Context

基于 FinSight（LangGraph + FastAPI + React 的金融分析多智能体系统），创建一个 A 股版本 `AShareSight`。核心变化：**美股→A股**、**yfinance→rqdatac**、**移除 RAG**、**前端全面换皮**。项目放在 `D:\BigFiles\AI-for-Financial-Analysis-group-work\AShareSight\`，与 FinSight 并列。

---

## Phase 0: 项目脚手架 & 清理

**目标**：复制 FinSight → AShareSight，删除 RAG、美股/港股相关代码。

### 操作清单

1. **复制项目**：`cp -r FinSight AShareSight`（排除 `.venv/`、`node_modules/`、`__pycache__/`）
2. **删除 `backend/rag/` 整个目录**
3. **删除美股/港股工具文件**：`backend/tools/price.py`、`financial.py`、`finnhub.py`、`sec.py`、`fmp.py`、`alpha_vantage.py`、`fred.py` 等美国数据源
4. **删除 RAG 相关测试和前端页面**
5. **清理 `requirements.txt`**：移除 `chromadb`、`sentence-transformers`、`FlagEmbedding`、`sentencepiece`、`transformers`、`ragas`、`yfinance`、`finnhub-python`
6. **添加 `rqdatac>=1.0.0`**
7. **新建 `.env`**（只保留 A 股必需配置）
8. **清空旧数据库**：删除 `portfolio.db` 和会话存储文件，从零开始

---

## Phase 1: 数据层 — rqdatac 工具模块

**目标**：用 rqdatac 替换所有数据源，保留东方财富作为 fallback。

### rqdatac 已验证的能力范围

通过查询 rqdatac API 文档，确认以下数据类别可用：

| 类别 | 可用 | 对应函数 |
|------|------|---------|
| 股票行情（OHLCV） | ✅ | `get_price()` |
| 财务三表（利润/负债/现金流） | ✅ | `get_pit_financials_ex()` |
| 估值指标（PE/PB/PS/市值） | ✅ | `get_factor()` + `fundamentals` |
| 技术因子（换手率/量比等） | ✅ | `get_factor()` / `get_turnover_rate()` |
| 指数成分股 | ✅ | `index_components()` |
| 行业分类（申万） | ✅ | `get_instrument_industry()` / `get_industry()` |
| 板块/概念股 | ✅ | `get_concept()` / `get_concept_list()` |
| 资金流向（北向/南向） | ✅ | `get_capital_flow()` / `get_stock_connect()` |
| 龙虎榜 | ✅ | `get_abnormal_stocks()` |
| 涨跌停/停牌/ST 信息 | ✅ | `is_suspended()` / `is_st_stock()` |
| 宏观指标（M2/CPI/PPI/PMI） | ✅ | `econ.get_money_supply()` / `econ.get_factors()` |
| 准备金率/存贷利率 | ✅ | `econ.get_reserve_ratio()` |
| 公司公告 | ✅ | `get_announcement()` |
| 一致预期（分析师预测） | ✅ | 另类数据模块（需查参考文档详参） |
| 新闻舆情（含情感指标） | ✅ | `news.get_stock_news()`（需额外 `pip install rqdatac_news`） |
| 龙虎榜详情（机构席位） | ✅ | `get_abnormal_stocks_detail()` |
| 大宗交易 | ✅ | `get_block_trade()` |
| 股东信息 | ✅ | `get_main_shareholder()` / `get_holder_number()` |

### Ticker 格式约定

**内部统一用 rqdatac 原生格式**：
- `000001.XSHE` — 深圳（原 .SZ）
- `600000.XSHG` — 上海（原 .SS）
- `830000.XBEX` — 北京（原 .BJ）

API 入参同时接受简短格式，内部自动转换。

### 1.1 新建 `backend/tools/rqdata_price.py`

| 原函数 | rqdatac 替代 |
|--------|-------------|
| `get_stock_price()` | `get_price(order_book_ids, fields=['close','open','high','low','volume'])` + 计算涨跌幅 |
| `get_stock_historical_data()` | `get_price(ticker, start_date, end_date, frequency)` |
| `get_performance_comparison()` | 批量 `get_price()` |
| `get_factor_exposure()` | `get_factor(order_book_ids, factor, start_date, end_date)` |
| `get_option_chain_metrics()` | **移除**（A 股个股无期权，且已决定不保留 ETF 期权） |

**新增 A 股特有函数**：
- `get_limit_board_info()` — 涨跌停价格/距离（主板±10%/科创±20%/北交±30%）
- `get_suspension_info()` — 停牌/复牌信息
- `get_st_status()` — ST/*ST 风险警示状态

### 1.2 新建 `backend/tools/rqdata_financial.py`

| 原函数 | rqdatac 替代 |
|--------|-------------|
| `get_financial_statements()` | `get_pit_financials_ex()` 查询三表关键字段 |
| `get_company_info()` | `get_factor()` + `instruments()` 获取基本信息 |
| `get_earnings_estimates()` | 一致预期模块（参考参考文档详参） |
| `resolve_company_ticker()` | 中文公司名→代码查找 |

CAS（中国会计准则）特有字段：
- 扣非净利润（`deducted_profit`）
- 经营活动现金流（`operating_cash_flow`）
- 商誉（`goodwill`）
- 应收账款（`accounts_receivable`）

### 1.3 改造 `backend/tools/cn_hk_market.py`
- 改为：**rqdatac 为主，东方财富为 fallback**
- 移除港股相关函数（`detect_market("HK")` 路径保留但标记为已弃用）
- `fetch_cn_hk_quote_metrics()` → rqdatac first → Eastmoney
- `fetch_cn_hk_kline()` → rqdatac first → Eastmoney
- `fetch_cn_hk_financial_statements()` → rqdatac first → Eastmoney

### 1.4 重写 `backend/tools/news.py`

**新闻主数据源：`rqdatac.news.get_stock_news()`**
- 返回字段：`title`（标题）、`original_time`（发布时间）、`url`（原文链接）、`source`（来源）、`news_emotion_indicator`（情感标识）、`company_relevance`（相关度）
- 信息量足够作为 Agent 新闻分析的输入（标题+情感+来源），需要深度阅读时通过 `url` 抓取全文
- 需要额外安装 `pip install rqdatac_news`，与主 rqdatac 包分开
- 数据从 2017 年至今，每半小时更新

**中文财经媒体信源评分**：
```python
_AUTHORITATIVE_DOMAIN_HINTS = (
    "eastmoney.com",     # 东方财富
    "sina.com.cn",       # 新浪财经
    "10jqka.com.cn",     # 同花顺
    "cls.cn",            # 财联社
    "yicai.com",         # 第一财经
    "caixin.com",        # 财新
    "cninfo.com.cn",     # 巨潮资讯（官方披露）
    "sse.com.cn",        # 上交所
    "szse.cn",           # 深交所
    "csrc.gov.cn",       # 证监会
    "pbc.gov.cn",        # 人民银行
)
```

**数据流**：rqdatac.news 为主 → 东方财富 API 补充 → Tavily 搜索 fallback

### 1.5 重写 `backend/tools/macro.py`
- FRED 数据 → 中国宏观指标，使用 `rqdatac.econ` 模块
- 删除美联储/美国CPI/非农等全部美国宏观指标

### 1.6 新建 `backend/utils/ticker_rq.py`
Ticker 格式双向转换：
- `000001.XSHE` ↔ `000001.SZ`（深交所）
- `600000.XSHG` ↔ `600000.SS`（上交所）
- `830000.XBEX` ↔ `830000.BJ`（北交所）
- 主板/创业板/科创板/北交所 市场识别
- `is_valid_astock_ticker()` 验证函数

### 1.7 更新 `backend/tools/__init__.py`
移除所有 yfinance/Finnhub/FRED/US 相关导出，替换为 rqdatac 函数导出。

### 1.8 Web 搜索策略（决策说明）

由于 Tavily 在国内网络环境下可能不稳定，DuckDuckGo 已被屏蔽，采用以下策略：
- **主要数据源**：rqdatac 结构化数据 + 东方财富新闻 API（稳定可靠，覆盖 95% 需求）
- **补充搜索**：保留 Tavily 作为可选的通用搜索 fallback（非关键路径）
- 不引入 DuckDuckGo
- 未来可扩展：用户如需更强的中文搜索能力，可自行接入百度搜索 API 或搜狗搜索

---

## Phase 2: Agent 适配（7 个 Agent）

**目标**：全部适配 A 股 + rqdatac，prompt 中国化。

### 各 Agent 修改要点

| Agent | 关键修改 |
|-------|---------|
| **PriceAgent** | 数据源：`["rqdatac","eastmoney","search"]`；货币 USD→CNY；移除期权 IV/PCR/Skew；替换为换手率/量比/涨跌停距离/龙虎榜信号 |
| **FundamentalAgent** | 中文指标标签；CAS 特有指标（扣非净利润、商誉、应收账款周转）；行业分类改为申万分类 |
| **NewsAgent** | 中国财经媒体域名；提示词新增政策影响/龙虎榜/大宗交易/北向资金 |
| **TechnicalAgent** | 涨跌停板距离 ±10%/±20%/±30%；中文 K 线形态（十字星/锤子线）；T+1 制度提示 |
| **MacroAgent** | 指标：LPR/PMI/M2/Shibor/10Y国债利率/社融/CPI/PPI/GDP；数据源：`rqdatac.econ` |
| **RiskAgent** | 新增中国特有风险：商誉减值/大股东减持/质押爆仓/ST退市/审计非标意见/北向流出 |
| **DeepSearchAgent** | 中国搜索信号术语（预增/预减/扭亏）；中国网站解析适配 |

### 已移除的功能
- **期权分析**：全部移除（PriceAgent 中的 options 相关代码）
- **ETF 分析**：全部移除
- **美股/港股数据**：全部移除（包括中概股 ADR 对比）

### `base_agent.py`
基本不变（DI 注入模式，接口层无变化）。

---

## Phase 3: Dashboard 适配

**目标**：6 个 Tab 全部切换 A 股数据。

### 3.1 `backend/dashboard/data_service.py`（最大改动，~1800 行）
- `fetch_snapshot()` → `get_price()` + `get_factor()`（PE/PB/市值）
- `fetch_financial_statements()` → `get_pit_financials_ex()`
- `fetch_valuation()` → `get_factor()`（pe_ttm/pb/ps_ttm/market_cap）
- `fetch_technical_indicators()` → rqdatac 数据 + 原有计算
- `fetch_analyst_targets()` → 一致预期模块
- `fetch_macro_snapshot()` → `econ.get_factors()` / `econ.get_money_supply()`
- `fetch_news()` → 东方财富 API
- `fetch_recommendations()` → 一致预期评级
- 所有 `$` → `¥`，`USD` → `CNY`

### 3.2 `backend/dashboard/peer_service.py`
- US 行业 → **申万行业分类**（食品饮料/银行/医药生物/电子/电力设备等）
- 默认同行：沪深 300 成分股（`index_components('000300.XSHG')`）
- 动态同行过滤：`get_instrument_industry()` + 同行业搜索
- 移除 Finnhub 依赖

### 3.3 `backend/dashboard/insights_engine.py` & `scorers.py`
- 5 个 Scorer 全部重写 prompt 为 A 股视角
- 新增：政策面、资金面（北向）、情绪面

### 3.4 `backend/dashboard/schemas.py`
- ActiveAsset 增加 `market: Literal["SH","SZ","BJ"]`
- 移除 `equity_type: Literal["us", "cn", "hk"]` 中的 `"us"` 和 `"hk"`

### 3.5 `backend/api/dashboard_router.py`
- 默认 watchlist：`600519.XSHG`（贵州茅台）、`300750.XSHE`（宁德时代）、`600036.XSHG`（招商银行）、`000858.XSHE`（五粮液）、`601318.XSHG`（中国平安）
- Asset resolver 支持 rqdatac 格式 + 简短格式
- 指数识别：上证综指/深证成指/创业板指/科创50/沪深300

---

## Phase 4: LangGraph Pipeline 调整

| 文件 | 修改 |
|------|------|
| `graph/nodes/execute_plan_stub.py` | 移除 RAG imports 及 context 注入；工具适配更新 |
| `graph/nodes/understand_request.py` | "美股"→"A股"；中文公司名→ticker 映射更新；移除港股识别 |
| `graph/nodes/planner.py` | A 股市场规则（T+1、涨跌停、交易时间 9:30-15:00） |
| `graph/nodes/synthesize.py` | 货币/市场术语中国化；移除 RAG context 注入 |
| `graph/nodes/render_stub.py` | 免责声明："本报告仅供参考，不构成投资建议。数据来源：米筐(RQData)" |
| `graph/nodes/resolve_subject.py` | A 股 ticker 6 位编码识别 |
| `graph/runner.py` | 结构不变 |
| `graph/adapters/tool_adapter.py` | 工具名映射更新 |

---

## Phase 5: 其他服务适配

### 5.1 Alert（预警调度）
- 默认监控：A 股蓝筹
- 通知模板 CNY
- 交易时间改为北京时间 9:30-15:00

### 5.2 Portfolio（投资组合）
- ticker 格式验证改为 A 股
- 默认示例持仓改为 A 股（清空旧数据）

### 5.3 PDF 导出
- 中文字体：**Microsoft YaHei**（系统自带，无需额外下载）
- ReportLab 注册 `C:\Windows\Fonts\msyh.ttc`
- 表格标签中文化

### 5.4 Workbench / Morning Brief
- 早报时间：北京时间 9:00（开盘前 30 分钟）
- 内容：A 股指数 + 隔夜外盘影响
- 移除美股早报模板

### 5.5 `backend/api/main.py`
- 移除 RAG lifecycle hooks
- FastAPI title：`AShareSight API`
- 描述改为 A 股金融分析

---

## Phase 6: 前端全面换皮

**设计原则**：从 FinSight 的"暗黑交易终端"风格 → AShareSight 的"中式专业金融平台"风格。

### 6.1 CSS 变量主题

```css
/* Light */
--ash-bg: #f5f2ed;           /* 暖白纸色 */
--ash-bg-secondary: #ede8e0;
--ash-card: #fffefb;
--ash-panel: #ffffff;
--ash-border: #d4cdc2;
--ash-text: #2c2416;         /* 深棕墨色 */
--ash-text-secondary: #6b5e4a;
--ash-primary: #c82828;      /* 中国红 */

/* Dark */
--ash-bg: #1a1410;           /* 深墨色 */
--ash-card: #2a2218;
--ash-text: #ebe4d5;

/* 红涨绿跌（中国习惯，与西方相反） */
--ash-up: #c82828;
--ash-down: #1a8a4a;
```

### 6.2 Tailwind 配置
- 命名空间 `fin` → `ash`
- 字体：`Microsoft YaHei`（系统字体，零加载成本）
- 正文字号：16px，行高 1.6

### 6.3 布局 & 组件
- Card border-radius 8px→10px，更柔和的阴影
- 品牌标识替换
- 70+ 组件文件批量替换 CSS 类名 `fin-` → `ash-`
- 关键组件：StockHeader（红涨绿跌）、DashboardTabs（中式标签样式）
- 涨跌颜色与西方相反

### 6.4 ECharts 主题
- 红涨绿跌配色
- 暖色调色板

### 6.5 Store & 默认值
- localStorage key：`finsight-*` → `asharesight-*`
- 默认 ticker：`600519.XSHG`（贵州茅台）
- 移除 RAG Inspector 相关代码
- 移除所有"美股"、"港股"相关文案

---

## Phase 7: 配置、测试、文档

1. `.env.example`：只含 RQData 连接信息 + LLM 配置
2. 测试 fixtures：US ticker → A 股 ticker，USD → CNY
3. 删除 RAG / US / HK 测试用例
4. Docker：移除 ChromaDB 服务
5. 创建中文文档 `readme_cn.md`

---

## 文件改动汇总

| 类别 | 操作 | 数量 |
|------|------|------|
| 删除（RAG + 美股/港股 + 期权/ETF） | 删除 | ~35 个文件 |
| 新建（rqdatac 工具层） | 创建 | ~4 个文件 |
| 重写（Agent + Dashboard） | 大改 | ~15 个文件 |
| 适配（Pipeline + 服务） | 中改 | ~20 个文件 |
| 前端换皮 | 批量替换 + 重改 | ~70 个文件 |

---

## 风险

| 风险 | 缓解 |
|------|------|
| rqdatac 某些数据不可用 | 东方财富 fallback |
| 频率限制 | 复用 Circuit Breaker |
| CAS vs GAAP 差异 | 更新指标映射 |
| Microsoft YaHei 在非 Windows 系统缺失 | fallback 链：YaHei → Noto Sans SC → sans-serif |

---

## 验证方案

- **Phase 1**：`get_stock_price('000001.XSHE')` → 返回 CNY 价格
- **Phase 2**：PriceAgent → `research("分析贵州茅台")` → 数据来自 rqdatac
- **Phase 3**：`GET /api/dashboard/data?symbol=600519.XSHG` → 6 Tab 正常
- **Phase 4**：Chat → "茅台估值如何" → 全 Pipeline 正常
- **Phase 6**：前端 → 视觉换皮验证、light/dark 切换
- **Phase 7**：运行测试套件
