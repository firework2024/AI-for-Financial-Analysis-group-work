# 修复多智能体 fundamental_writer 分析深度不足

## Context

对比两份报告后发现，多智能体的"经营质量分析"章节尽管已经改用投资总监式 prompt，但分析深度远不如单独年报分析的投资总监。根因是**数据管道**问题，不是 prompt 问题。

### 差距诊断

对比 600900 的单独年报报告和 600900 多智能体报告，四条关键差距：

1. **财务报表数据缺失**。多智能体报告写着"本数据窗口未提供直接现金流量表数据"，但单独年报报告有完整的经营现金流、净现比、收现比、自由现金流、资本开支强度数据。多智能体只拿到了 factor TTM 快照，没拿到完整的三表。

2. **MD&A 交叉验证缺失**。单独年报几乎每段都在做"报表数据 + MD&A 解释 + 独立判断"的三者对照。多智能体版完全没有 MD&A 引用。

3. **矛盾识别从系统化变成碎片化**。单独年报有结构化的"核心矛盾汇总"表格，多智能体版把矛盾信息散落在叙述中。

4. **数据精度差距**。单独年报有精确的分业务收入/成本表格、多年对比表，多智能体版大量使用"推测""尚无法判断"等措辞。

### 根因定位

问题出在 `_attach_stored_fundamentals()` + `_compact_data_for_prompt()` 这条链路：

- **`_attach_stored_fundamentals()`** 依赖 SQLite 中已有通过 `workflow.run()` 预处理的年报记录。如果缓存命中，数据其实拿到了（financial_analysis、MD&A、signals、crosswalk 等都在 `annual_report_context` 和 `annual_analysis` 里）。如果缓存未命中，只能拿到裸 PIT 财务数据，没有分析信号、没有 MD&A 交叉验证。

- **`_compact_data_for_prompt()`** 把获取的完整财务分析拆成了碎片——`reviewed_signals[:8]`、`positive_signals[:6]`、`mda_excerpt[:6000]`、单独的 `mda_crosswalk`、单独的 `articulation_checks`。而单独年报路径是把整个 `financial_analysis` dict（14K chars）作为**一个连贯块**传给投资总监，模型看到的是一张完整的财务画像。

- 行业对比数据（`industry_comparison`）被作为额外的 layer 加上去，但因为底层财务数据已经是碎片，行业对比只能挂在 shallow 的分析上。

### 修复思路

三条修改，都只动多智能体链路：

1. **把"年报预处理"做成多智能体的前置步骤**，确保数据一定可用（不依赖用户先手动跑一次 `workflow.run()`）
2. **重构数据传递给 fundamental_writer 的方式**，让它看到和单独年报投资总监一样的"完整财务画像"，再把行业对比作为"额外的镜子"叠加上去
3. **确保图表系统不受影响**——年报财务图 + 行业对比图都继续正常生成和挂载

---

## 修改方案

### 改动一：确保年报数据在多智能体运行时一定可用

**文件**：`finagent/multiagent.py`，函数 `_attach_stored_fundamentals()`（约第 497-566 行）

**问题**：当前逻辑是"先查 SQLite 缓存 → 没有再兜底取 PIT 裸数据"。如果缓存为空（用户没先跑 `workflow.run()`），就只有裸的 PIT 财务行，没有经过 `analyze_financials()` + `enrich_financial_analysis_with_mda()` 的分析结果，MD&A 也没有。

**改法**：在缓存为空时，不再只拿裸 PIT 数据就完了，而是**现场跑一次完整的年报分析**。

具体来说，当 `get_annual_report()` 返回 None 时：

```
1. 调用现有 rqdata_client.fetch_financials(stock_code, report_year, years=3) 拿三表
2. 把 financial_data 组织成 analyze_financials() 需要的格式
3. 调用 workflow.run() 里的 PDF 获取 / MD&A 提取逻辑（或复用已有的 extract_mda 等函数）
4. 调用 analyze_financials() + enrich_financial_analysis_with_mda() 生成完整分析
5. 把结果存回 SQLite（调用现有的 save 函数）
6. 继续后续流程（与缓存命中路径汇合）
```

**实现方式**：在 `_attach_stored_fundamentals()` 里，当 `annual` 为 None 时，新增一个 `_ensure_annual_report_available(stock_code)` 辅助函数调用，它内部检查是否需要触发 PDF→MD&A→三表→分析的完整流程。完成后重新查缓存。

这样无论用户是否先跑过单独年报分析，多智能体都能拿到同样完整的基础数据。

### 改动二：重构 fundamental_writer 的数据传递

**文件**：`finagent/multiagent.py`，函数 `_compact_data_for_prompt()`（约第 1719-1781 行）  
**文件**：`finagent/multiagent.py`，新增 `_build_operating_quality_context()` 函数  
**文件**：`finagent/report_writing.py`，函数 `build_analytical_evidence()`（约第 253-338 行）

**问题**：当前 `_compact_data_for_prompt()` 把年报分析拆成 5+ 个独立键（`pit_financials`、`annual_report_context`、`mda_crosswalk`、`articulation_checks`、`annual_financial_analysis`），每项都是截断版。模型要自己在脑子里把这些碎片拼回来。

**改法**：新增一个 `_build_operating_quality_context()` 函数，把所有年报相关的数据**重新组装成一个连贯的字典**，结构模仿单独年报投资总监收到的 prompt：

```python
def _build_operating_quality_context(data: dict) -> dict:
    """为经营质量分析构建完整的、连贯的财务画像。
    
    模仿 standalone 投资总监 prompt 的结构：
    一份完整的财务分析 dict + MD&A 全文 + 勾稽对照 + 勾稽检查。
    再加上行业对比作为额外的分析视角。
    """
    ctx = data.get("annual_report_context") or {}
    annual = data.get("annual_analysis") or {}
    
    result = {
        # ── 完整财务画像（对标 standalone 的 financial_analysis）──
        "company": {
            "stock_code": data.get("stock_code"),
            "sec_name": data.get("sec_name"),
            "order_book_id": data.get("order_book_id"),
        },
        "financial_analysis": annual.get("financial_analysis") or {},
        "financial_years": ctx.get("financial_years"),
        "metrics": ctx.get("metrics"),
        
        # ── MD&A 与勾稽（对标 standalone 的 mda_text + crosswalk + articulation）──
        "mda_full_text": ctx.get("mda_excerpt") or str(
            (ctx.get("mda_meta") or {}).get("mda_raw", "")
        )[:12000],
        "mda_summary": ctx.get("mda_summary"),
        "mda_crosswalk": ctx.get("mda_crosswalk"),
        "articulation_checks": ctx.get("articulation_checks"),
        "reviewed_signals": ctx.get("reviewed_signals"),
        
        # ── 同行对比（增量，standalone 没有的）──
        "industry_comparison": _build_industry_profile_for_quality(data.get("industry_comparison")),
        
        # ── 补充：PIT 裸数据作为 backup ──
        "pit_financials": data.get("pit_financials"),
        
        # ── 数据可用性标记 ──
        "data_availability": {
            "has_annual_report": bool(annual.get("financial_analysis")),
            "has_mda": bool(ctx.get("mda_excerpt")),
            "has_industry_comparison": bool(data.get("industry_comparision")),
        },
    }
    return result
```

然后在 `_compact_data_for_prompt()` 的 `_is_operating_quality_section` 分支里，把分散的 5+ 个键替换成**一个** `operating_quality_context` 键，同时保留 `pit_financials` 和 `analytical_evidence` 给其他用途。

**关键设计原则**：
- 不删掉已有键（`annual_report_context`、`mda_crosswalk` 等），只是在经营质量分析路径上**额外加一个整合版**。这样其他章节（如风险综合）不受影响。
- `_build_industry_profile_for_quality()` 只暴露非估值同行指标（毛利率、净利率、ROE、增长率、杠杆率、流动性），估值指标留给其他需要它们的章节。

### 改动三：确保年报财务图 + 行业对比图都正常

**文件**：`finagent/chart_plots.py`，函数 `chart_agent()` 和 `_plot_annual_financial_charts()`

**当前状态检查**：
- 年报财务图（`revenue_profit_trend`、`profit_vs_cashflow`、`free_cashflow_trend`、`margin_roe_trend`）依赖 `annual_analysis.financial_data` 生成
- 行业对比图（`industry_profitability_compare`、`industry_growth_leverage_compare`、`industry_dbscan_anomaly`）依赖 `industry_comparison` 生成
- 两者目前在 chart_agent 中已经存在并能正常生成

**需要确认的点**：
1. 改动一确保 `annual_analysis.financial_data` 一定能被填充（目前只在缓存命中时填充，兜底路径不填充）
2. `chart_agent()` 的图表生成不需要改——它直接从 `data` dict 找数据，只要 data 里有就能生成
3. `chart_catalog.py` 中经营质量分析的图表候选不需要改——已经是经营质量相关图

**实际上不需要改图表代码**。只需要确保改动一后 `data["annual_analysis"]["financial_data"]` 在兜底路径里也被填充就行了。

### 改动四：fundamental_writer prompt 里传递全新整合数据

**文件**：`finagent/multiagent.py`，函数 `_write_section()`（约第 1037-1073 行）

当前 `_write_section()` 调用 `_compact_data_for_prompt()` 拿到 payload，然后 `json.dumps(data, ensure_ascii=False)[:24000]` 截断传给 LLM。

修改后，`_compact_data_for_prompt()` 返回的 payload 里对经营质量分析会多一个 `operating_quality_context` 键。prompt 的文字指令也需要同步更新：

```
当前：
"优先引用 analytical_evidence 中的日期、窗口统计与多年表；"
"若有 mda_crosswalk，在盈利/现金流/风险相关段落中用「报表…，MD&A…」对照写法融入"

改为：
"优先使用 operating_quality_context 中的完整财务画像：financial_analysis（全部信号+指标）、"
"financial_years（多年对比）、metrics（~40+ 指标）、mda_full_text（管理层讨论原文）、"
"mda_crosswalk（报表与 MD&A 勾稽对照）、articulation_checks（三表勾稽异常检测）。"
"写作时对每个关键判断都要做「报表数据 + MD&A 管理层解释 + 独立判断」三者对照。"
"然后使用 industry_comparison 将结论放在同行坐标中验证（经营指标分位、均值、中位数）。"
```

### 改动五（可选但有价值）：数据可用性检查 + 报告如实标注

在 `data_executor_agent()` 返回前，检查年报数据实际可用情况，写入 `data_quality` 字段供报告末尾的"数据与工具说明"使用。

当前报告写着"缺失：年报三表"，如果改动一生效后数据到位，这个标注应该自动消失。

### 涉及文件清单

| 文件                                          | 修改内容                                                     | 风险等级           |
| --------------------------------------------- | ------------------------------------------------------------ | ------------------ |
| `multiagent.py:_attach_stored_fundamentals()` | 增加缓存未命中时的完整年报分析兜底                           | 中（新增函数调用） |
| `multiagent.py:_compact_data_for_prompt()`    | 经营质量分析路径新增 `operating_quality_context` 整合键      | 低（只新增键）     |
| `multiagent.py` 新增函数                      | `_ensure_annual_report_available()`、`_build_operating_quality_context()`、`_build_industry_profile_for_quality()` | 低（新函数）       |
| `multiagent.py:_write_section()`              | prompt 文字更新以引用新数据键                                | 低（改字符串）     |
| `multiagent.py:_attach_stored_fundamentals()` | 兜底路径也填充 `annual_analysis.financial_data`              | 低                 |
| `chart_plots.py`                              | 不需要改                                                     | 无                 |
| `chart_catalog.py`                            | 不需要改                                                     | 无                 |

### 接口保证

- `data["annual_report_context"]` — 保持不变，其他章节继续使用
- `data["annual_analysis"]` — 保持不变，chart_agent 继续读取 `financial_data`
- `data["industry_comparison"]` — 保持不变，chart_agent 继续读取
- 新增的 `operating_quality_context` 只在 `_compact_data_for_prompt()` 的经营质量分析路径里构建，不影响其他章节
- `build_analytical_evidence()` — 不需要改，它继续为所有章节构建通用 evidence

---

## Verification

1. **数据可用性测试**：删除 600900 的 SQLite 年报缓存，运行 `multi-analyze --stock 600900`，确认报告不再出现"缺失：年报三表"，且经营质量分析包含现金流量表和 MD&A 引用

2. **图表完整性测试**：确认生成的报告里同时包含：
   - 年报财务图（revenue_profit_trend、profit_vs_cashflow、free_cashflow_trend、margin_roe_trend）
   - 行业对比图（industry_profitability_compare、industry_growth_leverage_compare、industry_dbscan_anomaly）

3. **分析深度验证**：对比修改后的多智能体报告和单独年报报告，确认：
   - 有 MD&A 交叉引用（"报表显示…，MD&A 披露…"）
   - 有完整的现金流质量分析（经营现金流、净现比、收现比、自由现金流）
   - 有"核心矛盾汇总"式的结构化矛盾呈现
   - 有同行对比（分位、均值/中位数、DBSCAN）

4. **回归测试**：运行全量测试确保不改坏其他功能
   ```
   uv run --with pytest pytest -q
   ```

5. **接口一致性**：确认 `_compact_data_for_prompt()` 对非经营质量分析章节的输出不变；确认 `chart_agent()` 仍能正常从 `data` 读取所有需要的数据