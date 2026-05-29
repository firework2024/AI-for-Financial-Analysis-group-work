# FinAgent 年报智能体工作流

FinAgent 是一个以 A 股年报为核心的本地命令行工作流。它会自动获取巨潮资讯网年报 PDF，提取最新年报中的 MD&A 文本，从米筐 RQData 获取最近三年年报口径财务数据，并生成两层分析结果：

- 财务分析智能体：先由规则引擎识别结构化财务信号和异常组合，再由 LLM 在 `财务分析智能体_知识框架提炼.md` 的约束下审核、归纳和解释这些信号，输出积极信号、消极信号、关键风险和可追溯的审核结果。
- 投资总监智能体：结合 MD&A 文本和财务数据分析结果，解释数据变化并输出总结分析。

## 快速开始

```powershell
# 1. 进入项目目录
cd FinAgent

# 2. 安装依赖（首次或更换 Python 环境时执行一次）
pip install -e .

# 3. 配置 .env：复制示例并填入你的密钥
copy .env.example .env
#    然后编辑 .env，至少填写 OPENAI_API_KEY；如使用兼容服务再改 OPENAI_BASE_URL / OPENAI_MODEL

# 4. 运行年报分析（生成结构化 Markdown 报告，推荐入口）
python -m finagent analyze --stock 600519 --as-of 2026-05-29

# 5. 可选：运行多智能体研究报告（量价/资金/图表，支持并行加速）
python -m finagent multi-analyze --stock 600519 --as-of 2026-05-29
```

运行结束后，报告输出在 `outputs/` 目录：

- `analyze`：`outputs/{代码}_{年份}_report.md` 与 `.json`
- `multi-analyze`：`outputs/{代码}_multi_agent_report.md`、`.json` 及 `outputs/charts/...` 图表

> 提示：`.env` 须放在 `FinAgent` 目录下（与 `finagent` 包同级）。未配置 `OPENAI_API_KEY` 时会回退到本地规则摘要模式，不调用大模型。

### 并行与性能

`multi-analyze` 在延续原有功能的基础上做了并行化：米筐数据拉取、各章节写作与修订都使用线程池并发，提升速度与稳定性。并发线程数由环境变量 `FINAGENT_MAX_WORKERS` 控制（默认 `4`）。若触发 API 速率限制（如 429）或网络超时，可在 `.env` 中将其调小为 `2` 或 `3`：

```env
FINAGENT_MAX_WORKERS=4
```

## 工作流

1. 输入 A 股股票代码和查询截止日期。
2. 从巨潮资讯网查询正式年报，自动过滤摘要、英文版、更正、修订、补充等版本。
3. 下载最新年报 PDF 到 `annual_reports/`。
4. 使用 PyMuPDF 提取全文，并优先定位“管理层讨论与分析 / 经营情况讨论与分析”等 MD&A 正文。
5. 使用米筐 `rqdatac.get_pit_financials_ex` 获取最近三年 `q4` 年报口径财务数据。
6. 对米筐三表接口缺失字段执行字段级回退：先尝试用米筐 `get_factor` 的 LYR 因子回补，再尝试从年报文本中提取，仍找不到则设为 `None`，并记录来源。
7. 本地计算财务指标，先用规则引擎识别结构化信号和异常组合，再把财务证据、结构化信号和 `财务分析智能体_知识框架提炼.md` 一起送入大模型做审核；如果未配置 `OPENAI_API_KEY`，则回退到本地规则审核模式。
8. 生成 Markdown 报告和 JSON 中间结果。

## 环境要求

建议使用 Python 3.10 以上。项目依赖写在 `pyproject.toml` 中，核心依赖包括：

- `requests`
- `pandas`
- `PyMuPDF`
- `rqdatac`
- `openai`

安装依赖：

```powershell
pip install -e .
```

如果当前环境已经安装这些包，也可以直接运行。

## `.env` 配置

项目会自动读取仓库根目录的 `.env` 文件，并把其中的变量注入到当前进程。系统环境变量如果已经存在，会优先保留，不会被 `.env` 覆盖。

你可以参考 [.env.example](D:/BigFiles/FinAgent/.env.example) 新建本地 `.env`，常用配置如下：

```env
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
RQDATAC2_CONF=
```

## 米筐配置

财务数据默认通过本机米筐配置初始化：

```python
rqdatac.init()
```

因此需要满足以下任一条件：

- 已配置 `RQDATAC2_CONF`
- 本机已有可用的米筐机构授权配置
- 本地 `rqdatac-client` 或账号配置可被 `rqdatac.init()` 正常读取

当前实现只支持 A 股，股票代码会自动转换为米筐格式，例如：

- `600519` -> `600519.XSHG`
- `300750` -> `300750.XSHE`

## 大模型配置

投资总监智能体通过环境变量接入 OpenAI 或兼容 OpenAI API 的模型服务：

```powershell
$env:OPENAI_API_KEY="你的密钥"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

`OPENAI_BASE_URL` 和 `OPENAI_MODEL` 可不填；未配置 `OPENAI_API_KEY` 时，财务分析和投资总监都会使用本地规则摘要模式，不会调用外部模型。
如果你把这些值写进 `.env`，程序启动时会自动读取。

## 使用方法

分析单只股票：

```powershell
python -m finagent analyze --stock 600519 --as-of 2026-05-23
```

指定输出路径：

```powershell
python -m finagent analyze --stock 600519 --as-of 2026-05-23 --output outputs/600519_report.md
```

常用参数：

- `--stock`：必填，6 位 A 股代码。
- `--as-of`：查询截止日期，格式 `YYYY-MM-DD`。不填则使用当天。
- `--years`：财务数据年数，默认 `3`。
- `--output`：Markdown 报告输出路径。
- `--no-download-cache`：忽略本地 PDF 缓存，重新下载年报。

## 输出文件

默认输出到 `outputs/`：

- `*_report.md`：可阅读的 Markdown 分析报告。
- `*_report.json`：完整中间结果，包含年报元数据、MD&A 摘要、字段级财务数据、字段来源、结构化原始信号、审核后信号、财务分析智能体输出、投资总监输出。

年报 PDF 会保存到：

```text
annual_reports/
```

## 财务字段与分析口径

首版使用米筐新版三表字段名，覆盖资产负债表、利润表、现金流量表的核心项目，例如：

- 资产负债表：总资产、流动资产、货币资金、应收账款、存货、固定资产、在建工程、商誉、负债、短债、长债、合同负债、归母权益、未分配利润。
- 利润表：营业总收入、营业收入、营业成本、营业利润、净利润、归母净利润、扣非净利润、销售费用、管理费用、研发费用、财务费用、资产减值损失、信用减值损失。
- 现金流量表：经营现金流净额、销售商品收到的现金、资本开支、投资现金流、筹资现金流。

本地计算指标包括：

- 毛利率、费用率、收现比、净现比
- 自由现金流、资本开支强度
- 流动比率、速动比率、资产负债率、有息负债
- ROE、ROA、资产周转率、存货周转率、应收账款周转率、固定资产周转率
- 杜邦相关指标和跨报表勾稽信号

对于第一年样本这类缺少前一年余额的情况，工作流会用米筐 `get_factor` 的 LYR 衍生指标补充部分周转率、流动性和杠杆指标，并在 JSON 的 `metric_sources` 中标记来源。

财务分析智能体在模型模式下会把这份知识框架原文作为提示词的一部分，因此它不是“读一段通用说明后自由发挥”，而是被框架显式约束的审核器。规则层会先产出：

- `structured_signals`：单指标结构化信号。
- `compound_signals`：多指标组合异常信号。
- `reviewed_signals`：LLM 或本地规则审核后的重点信号，保留类别、方向、强度、证据和指标关联。
- `key_risks`：面向报告展示的关键风险短语。

## 数据回退逻辑

字段级数据来源有三种：

- `rqdata`：米筐直接返回。
- `rqdata_factor`：米筐三表接口为空，但通过 `get_factor` 的 LYR 财务因子回补。
- `annual_report`：米筐为空，从年报文本中回退提取。
- `missing`：米筐和年报文本中都未找到，字段值设为 `None`。

回退逻辑是字段级的，不会因为某个字段缺失而丢弃整张表。

## 测试

运行测试：

```powershell
python -m pytest -q
```

当前测试覆盖：

- 股票代码市场分类
- 年报年份识别
- 字段级回退与缺失标记
- MD&A 提取时跳过目录命中
- 财务分析智能体输出结构、组合信号识别，以及“不做买卖判断”边界

## 当前限制

- 首版只支持 A 股年报。
- 财务数据主口径为最近三年 `q4` 年报期，不使用季度滚动口径作为主口径。
- 年报文本回退依赖 PDF 文本质量，复杂表格和扫描件可能无法稳定提取。
- 未接入行业横向比较、估值、市场价格和可视化。
- 未配置 `OPENAI_API_KEY` 时，财务分析和投资总监输出都会是本地摘要模式，不是完整大模型分析。
