"""MD&A 与报表勾稽：结构化检查 + 管理层表述检索对照。"""

from __future__ import annotations

from typing import Any


def build_articulation_checks(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """基于三表衍生指标生成勾稽检查项（不依赖 MD&A）。"""
    if not metrics:
        return []
    latest = metrics[-1]
    year = latest.get("year")
    checks: list[dict[str, Any]] = []

    np_val = latest.get("net_profit_parent_company")
    ocf = latest.get("cash_flow_from_operating_activities")
    cash_to_profit = latest.get("cash_to_profit")
    if np_val is not None and cash_to_profit is not None:
        if np_val > 0 and cash_to_profit < 0:
            checks.append(
                _check(
                    theme="利润与经营现金流背离",
                    category="earnings_quality",
                    year=year,
                    statement_fact=f"{year} 年归母净利润 {np_val:.2f}，净现比 {cash_to_profit:.2f}（为负）",
                    implication="利润表盈利但经营现金流未能覆盖利润，需核查非现金损益与营运资本变动。",
                )
            )
        elif np_val > 0 and cash_to_profit < 0.8:
            checks.append(
                _check(
                    theme="利润现金含量偏低",
                    category="earnings_quality",
                    year=year,
                    statement_fact=f"{year} 年归母净利润 {np_val:.2f}，净现比 {cash_to_profit:.2f}",
                    implication="利润转化为经营现金流效率偏弱。",
                )
            )

    npg = latest.get("net_profit_parent_company_growth")
    ocfg = latest.get("cash_flow_from_operating_activities_growth")
    if npg is not None and ocfg is not None and npg > 0.05 and ocfg < -0.05:
        checks.append(
            _check(
                theme="利润增长与经营现金流变动背离",
                category="earnings_quality",
                year=year,
                statement_fact=f"{year} 年归母净利润同比 {npg:.1%}，经营现金流同比 {ocfg:.1%}",
                implication="利润改善未同步体现在经营现金流，存在利润质量风险。",
            )
        )

    cash_to_revenue = latest.get("cash_to_revenue")
    revenue = latest.get("revenue")
    if cash_to_revenue is not None and cash_to_revenue < 1.0 and revenue is not None:
        checks.append(
            _check(
                theme="收入收现比低于1",
                category="cash_quality",
                year=year,
                statement_fact=f"{year} 年营收 {revenue:.2f}，收现比 {cash_to_revenue:.2f}",
                implication="收入中有相当比例尚未转化为销售回款。",
            )
        )

    inv_g = latest.get("inventory_growth")
    rev_g = latest.get("revenue_growth")
    if inv_g is not None and rev_g is not None and inv_g > rev_g + 0.05:
        checks.append(
            _check(
                theme="存货增速快于收入",
                category="operating_efficiency",
                year=year,
                statement_fact=f"{year} 年收入增速 {rev_g:.1%}，存货增速 {inv_g:.1%}",
                implication="可能存在去库存压力或备货激进。",
            )
        )

    recv_g = latest.get("receivable_growth")
    if recv_g is not None and rev_g is not None and recv_g > rev_g + 0.05:
        checks.append(
            _check(
                theme="应收增速快于收入",
                category="operating_efficiency",
                year=year,
                statement_fact=f"{year} 年收入增速 {rev_g:.1%}，应收增速 {recv_g:.1%}",
                implication="回款节奏可能滞后于收入确认。",
            )
        )

    fcf = latest.get("free_cash_flow")
    if fcf is not None and np_val is not None and np_val > 0 and fcf < 0:
        checks.append(
            _check(
                theme="盈利但自由现金流为负",
                category="cash_quality",
                year=year,
                statement_fact=f"{year} 年归母净利润 {np_val:.2f}，自由现金流 {fcf:.2f}",
                implication="资本开支或营运资本占用吞噬经营现金流。",
            )
        )

    if len(metrics) >= 2:
        prev = metrics[-2]
        gm_now = latest.get("gross_margin")
        gm_prev = prev.get("gross_margin")
        npm_now = _safe_ratio(latest.get("net_profit_parent_company"), latest.get("revenue"))
        npm_prev = _safe_ratio(prev.get("net_profit_parent_company"), prev.get("revenue"))
        if (
            gm_now is not None
            and gm_prev is not None
            and npm_now is not None
            and npm_prev is not None
            and gm_now > gm_prev + 0.005
            and npm_now < npm_prev - 0.005
        ):
            checks.append(
                _check(
                    theme="毛利率改善但净利率下滑",
                    category="profitability",
                    year=year,
                    statement_fact=(
                        f"{year} 年毛利率 {gm_now:.1%}（前一年 {gm_prev:.1%}），"
                        f"净利率 {npm_now:.1%}（前一年 {npm_prev:.1%}）"
                    ),
                    implication="费用、减值或非经常性损益侵蚀毛利改善。",
                )
            )

    return checks


def build_mda_financial_crosswalk(
    mda_text: str,
    *,
    financial_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """将报表勾稽项与审核信号，映射到 MD&A 原文段落。"""
    from .datastore.annual_text import search_mda_hits

    text = str(mda_text or "").strip()
    metrics = financial_analysis.get("metrics") or []
    crosswalk: list[dict[str, Any]] = []

    for check in build_articulation_checks(metrics):
        item = dict(check)
        item["mda_hits"] = search_mda_hits(text, check["theme"], top_k=2) if text else []
        item["mda_available"] = bool(item["mda_hits"])
        item["source"] = "articulation"
        crosswalk.append(item)

    for signal in (financial_analysis.get("reviewed_signals") or [])[:8]:
        title = str(signal.get("title") or "").strip()
        if not title:
            continue
        query = " ".join(
            part
            for part in (
                title,
                str(signal.get("category_cn") or signal.get("category") or ""),
                str(signal.get("explanation") or "")[:40],
            )
            if part
        )
        hits = search_mda_hits(text, query, top_k=2) if text else []
        crosswalk.append(
            {
                "theme": title,
                "category": signal.get("category"),
                "year": signal.get("year"),
                "statement_fact": str(signal.get("evidence") or signal.get("explanation") or ""),
                "implication": str(signal.get("explanation") or ""),
                "mda_hits": hits,
                "mda_available": bool(hits),
                "source": "reviewed_signal",
                "polarity": signal.get("polarity"),
                "severity": signal.get("severity"),
            }
        )
    return crosswalk


def enrich_financial_analysis_with_mda(
    financial_analysis: dict[str, Any],
    mda_text: str,
) -> dict[str, Any]:
    """在财务分析结果上附加勾稽检查与 MD&A 对照包。"""
    from .progress import info

    enriched = dict(financial_analysis)
    metrics = enriched.get("metrics") or []
    enriched["articulation_checks"] = build_articulation_checks(metrics)
    checks = enriched["articulation_checks"]
    enriched["mda_crosswalk"] = build_mda_financial_crosswalk(mda_text, financial_analysis=enriched)
    crosswalk = enriched["mda_crosswalk"]
    info(f"MD&A 勾稽检查: {len(checks)} 项, MD&A 对照: {len(crosswalk)} 条")
    return enriched


def build_annual_context_from_store(
    annual: dict[str, Any],
    *,
    with_narrative: bool = False,
) -> dict[str, Any] | None:
    """从 SQLite 年报记录构建含勾稽的多智能体上下文。

    当 ``with_narrative=True`` 时，额外调用基本面叙事 LLM 并注入
    ``fundamental_narrative`` 与 ``_financial_analysis_raw`` 字段。
    """
    if not annual:
        return None
    financial_data = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
    mda_text = str(annual.get("mda_text") or "")
    context: dict[str, Any] = {
        "report_year": annual.get("report_year"),
        "sec_name": annual.get("sec_name"),
        "title": annual.get("title"),
        "mda_meta": annual.get("mda_meta") or {},
        "mda_summary": (annual.get("mda_meta") or {}).get("summary"),
    }
    if not financial_data:
        context["mda_excerpt"] = mda_text[:6000]
        context["mda_crosswalk"] = build_mda_financial_crosswalk(
            mda_text, financial_analysis={"metrics": [], "reviewed_signals": []}
        )
        return context

    from .annual_analysis_cache import compute_financial_analysis

    analysis = compute_financial_analysis(annual, persist=True)
    from .report_writing import summarize_annual_financial_data

    context.update(
        {
            "financial_years": summarize_annual_financial_data(financial_data),
            "metrics": analysis.get("metrics"),
            "articulation_checks": analysis.get("articulation_checks"),
            "mda_crosswalk": analysis.get("mda_crosswalk"),
            "reviewed_signals": (analysis.get("reviewed_signals") or [])[:8],
            "mda_excerpt": mda_text[:6000],
            "_financial_analysis_raw": analysis,
        }
    )

    if with_narrative:
        from .llm import fundamental_narrative_analysis

        company_context = {
            "stock_code": annual.get("stock_code"),
            "sec_name": annual.get("sec_name"),
            "report_year": annual.get("report_year"),
        }
        try:
            context["fundamental_narrative"] = fundamental_narrative_analysis(
                mda_text, analysis, company_context
            )
        except Exception as exc:
            context["fundamental_narrative"] = (
                f"经营与财务叙事生成失败（{type(exc).__name__}: {exc}），"
                "请参考下方财务信号审核与 MD&A 勾稽信息。"
            )
            context["_narrative_error"] = str(exc)

    return context


_MDA_BUSINESS_QUERY_GROUPS: dict[str, str] = {
    "basic_business": "主营业务 主要产品 经营模式 业务范围 核心竞争力",
    "business_development": "业务发展 经营情况 报告期 业绩变动 产销量",
    "industry_outlook": "行业 市场需求 竞争格局 机遇 挑战",
    "strategy": "发展战略 经营计划 未来展望 投入 研发",
    "risk_disclosure": "风险因素 经营风险 面临的主要风险 不确定性",
}

_SECTION_KIND_MDA_GROUPS: dict[str, tuple[str, ...]] = {
    "market": ("basic_business", "industry_outlook", "business_development"),
    "valuation": ("basic_business", "business_development", "strategy"),
    "capital": ("business_development", "industry_outlook"),
    "macro": ("business_development", "strategy", "risk_disclosure"),
    "operating_quality": ("basic_business", "business_development", "industry_outlook", "strategy"),
    "risk": ("risk_disclosure", "business_development", "industry_outlook"),
}


def build_mda_business_brief(
    mda_text: str,
    *,
    section_kind: str | None = None,
    mda_summary: str | None = None,
    crosswalk: list[dict[str, Any]] | None = None,
    max_excerpt_len: int = 200,
    hits_per_group: int = 1,
) -> str:
    """按章节类型从 MD&A 抽取基本业务/业务发展等管理层表述，供各章写作引用。"""
    from .datastore.annual_text import search_mda_hits

    lines: list[str] = []
    summary = str(mda_summary or "").strip()
    if summary:
        lines.append(f"MD&A 摘要：{summary[:400]}")

    groups = _SECTION_KIND_MDA_GROUPS.get(str(section_kind or "").strip().lower())
    if not groups:
        groups = ("basic_business", "business_development", "industry_outlook")

    text = str(mda_text or "").strip()
    if text:
        for group_key in groups:
            query = _MDA_BUSINESS_QUERY_GROUPS.get(group_key, group_key)
            hits = search_mda_hits(text, query, top_k=hits_per_group)
            for hit in hits:
                excerpt = str(hit.get("text") or "").strip().replace("\n", " ")
                if len(excerpt) > max_excerpt_len:
                    excerpt = excerpt[:max_excerpt_len].rstrip() + "…"
                if excerpt:
                    label = {
                        "basic_business": "基本业务",
                        "business_development": "业务发展",
                        "industry_outlook": "行业与需求",
                        "strategy": "战略与展望",
                        "risk_disclosure": "风险披露",
                    }.get(group_key, group_key)
                    lines.append(f"{label}：{excerpt}")

    if isinstance(crosswalk, list) and crosswalk:
        for item in crosswalk[:3]:
            hits = item.get("mda_hits") or []
            if not hits:
                continue
            theme = str(item.get("theme") or "勾稽项").strip()
            excerpt = str(hits[0].get("text") or "").strip().replace("\n", " ")
            if len(excerpt) > max_excerpt_len:
                excerpt = excerpt[:max_excerpt_len].rstrip() + "…"
            if excerpt:
                lines.append(f"与「{theme}」相关的 MD&A：{excerpt}")

    if not lines:
        return "年报 MD&A 已采集但未检索到与本节相关的业务表述；本节只基于量化数据写作并说明局限。"
    return " ".join(lines[:8])


def format_crosswalk_markdown(crosswalk: list[dict[str, Any]], *, limit: int = 10) -> str:
    """渲染 MD&A 与报表勾稽对照（Markdown）。"""
    if not crosswalk:
        return "_暂无 MD&A 与报表勾稽数据；请先运行年报分析（analyze）以采集 MD&A 与三表。_"
    lines: list[str] = []
    for item in crosswalk[:limit]:
        theme = item.get("theme") or "勾稽项"
        fact = str(item.get("statement_fact") or "").strip()
        implication = str(item.get("implication") or "").strip()
        lines.append(f"### {theme}")
        if fact:
            lines.append(f"- **报表事实**：{fact.rstrip('。')}。")
        if implication:
            lines.append(f"- **分析含义**：{implication.rstrip('。')}。")
        hits = item.get("mda_hits") or []
        if hits:
            lines.append("- **MD&A 相关表述**：")
            for hit in hits[:2]:
                excerpt = str(hit.get("text") or "").strip().replace("\n", " ")
                if len(excerpt) > 220:
                    excerpt = excerpt[:220].rstrip() + "…"
                lines.append(f"  - {excerpt}")
        else:
            lines.append("- **MD&A 相关表述**：未检索到直接对应段落（可能未披露或表述在 MD&A 其他章节）。")
        lines.append("")
    return "\n".join(lines).strip()


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return None
        return num / den
    except (TypeError, ValueError):
        return None


def _check(
    *,
    theme: str,
    category: str,
    year: Any,
    statement_fact: str,
    implication: str,
) -> dict[str, Any]:
    return {
        "theme": theme,
        "category": category,
        "year": year,
        "statement_fact": statement_fact,
        "implication": implication,
        "question_for_mda": f"MD&A 如何解释「{theme}」？",
    }
