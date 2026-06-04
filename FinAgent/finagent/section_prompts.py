"""多智能体章节写作 prompt 载荷与写作指引（行业对比、宏观、MD&A）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .chart_catalog import (
    filter_charts_for_section,
    MARKET_SECTION_BLOCKED_CHART_KEYS,
    OPERATING_QUALITY_BLOCKED_CHART_KEYS,
)
from .narrative_plan import is_macro_section, is_operating_quality_section, section_kind_for_name
from .peer_analysis import FACTOR_LABELS
from .report_writing import build_analytical_evidence, peer_compare_table_writing_rule

_INDUSTRY_METRIC_PRIORITY = (
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "operating_revenue_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
)

_VALUATION_METRICS = frozenset({"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "dividend_yield_ttm"})
_VALUATION_KEY_PARTS = ("pe_ratio", "pb_ratio", "ps_ratio", "dividend_yield")

_DECIMAL_PERCENT_METRICS = frozenset(
    {
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "roe_ttm",
        "net_profit_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "operating_profit_growth_ratio_ttm",
        "gross_profit_growth_ratio_ttm",
        "operating_revenue_growth_ratio_ttm",
        "dividend_yield_ttm",
    }
)

_POINT_PERCENT_METRICS = frozenset({"debt_to_asset_ratio"})
_MULTIPLE_METRICS = frozenset({"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "current_ratio", "quick_ratio"})


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _string_list_or_dicts(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item]


def _is_industry_summary(value: Any) -> bool:
    return isinstance(value, dict) and "metric_rows" in value


def _format_plain_number(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "N/A"
    return f"{number:.2f}"


def _format_percentile(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.0f}%"


def _ordered_industry_metric_keys(metrics: dict[str, Any]) -> list[str]:
    ordered = [key for key in _INDUSTRY_METRIC_PRIORITY if key in metrics]
    ordered.extend(key for key in metrics if key not in ordered)
    return ordered


def _industry_metric_label(key: str, item: Any | None = None) -> str:
    if isinstance(item, dict) and item.get("label"):
        return str(item["label"])
    return FACTOR_LABELS.get(key, key)


def _format_industry_metric_value(key: str, value: Any) -> str:
    number = _float(value)
    if number is None:
        return "N/A"
    if key in _DECIMAL_PERCENT_METRICS:
        return f"{number * 100:.2f}%"
    if key in _POINT_PERCENT_METRICS:
        return f"{number:.2f}%"
    if key in _MULTIPLE_METRICS:
        return f"{number:.2f}x"
    return _format_plain_number(number)


def industry_comparison_prompt_summary(industry_comparison: Any) -> dict[str, Any] | None:
    if not isinstance(industry_comparison, dict):
        return None
    metrics = industry_comparison.get("metrics") if isinstance(industry_comparison.get("metrics"), dict) else {}
    rows = []
    for key in _ordered_industry_metric_keys(metrics):
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "metric": key,
                "label": _industry_metric_label(key, item),
                "target": item.get("target"),
                "mean": item.get("mean"),
                "median": item.get("median"),
                "p25": item.get("p25"),
                "p75": item.get("p75"),
                "percentile": item.get("percentile"),
                "relative_label": item.get("relative_label"),
                "valid_count": item.get("valid_count"),
            }
        )
    cluster = industry_comparison.get("cluster_anomalies")
    cluster_summary = cluster if isinstance(cluster, dict) else {}
    if "points" in cluster_summary:
        cluster_summary = {k: v for k, v in cluster_summary.items() if k != "points"}
    return {
        "industry": industry_comparison.get("industry"),
        "peers": industry_comparison.get("peers"),
        "metric_rows": rows,
        "relative_signals": _string_list_or_dicts(industry_comparison.get("relative_signals"))[:8],
        "cluster_anomalies": cluster_summary,
        "data_notes": _coerce_string_list(industry_comparison.get("data_notes"))[:8],
    }


def operating_quality_industry_summary(industry_comparison: Any) -> dict[str, Any] | None:
    summary = industry_comparison_prompt_summary(industry_comparison)
    if not isinstance(summary, dict):
        return None
    rows = summary.get("metric_rows") if isinstance(summary.get("metric_rows"), list) else []
    summary["metric_rows"] = [row for row in rows if isinstance(row, dict) and row.get("metric") not in _VALUATION_METRICS]
    cluster = summary.get("cluster_anomalies") if isinstance(summary.get("cluster_anomalies"), dict) else {}
    if cluster:
        for key in ("top_contributors", "single_metric_anomalies"):
            items = cluster.get(key)
            if isinstance(items, list):
                valuation_items = [item for item in items if isinstance(item, dict) and item.get("metric") in _VALUATION_METRICS]
                cluster[key] = [item for item in items if isinstance(item, dict) and item.get("metric") not in _VALUATION_METRICS]
                if valuation_items:
                    cluster["valuation_contributors_excluded"] = True
        features = cluster.get("features")
        if isinstance(features, list):
            cluster["operating_quality_features"] = [item for item in features if item not in _VALUATION_METRICS]
    return summary


def industry_comparison_prompt_brief(industry_comparison: Any, *, include_metric_rows: bool = True) -> str:
    summary = (
        industry_comparison_prompt_summary(industry_comparison)
        if not _is_industry_summary(industry_comparison)
        else industry_comparison
    )
    if not isinstance(summary, dict):
        return ""
    industry = summary.get("industry") if isinstance(summary.get("industry"), dict) else {}
    peers = summary.get("peers") if isinstance(summary.get("peers"), dict) else {}
    level = industry.get("selected_level")
    selected_name = industry.get("selected_industry_name") or industry.get(f"level{level}_name") if level else None
    metric_rows = summary.get("metric_rows") if isinstance(summary.get("metric_rows"), list) else []
    notes = _coerce_string_list(summary.get("data_notes"))

    if not metric_rows:
        reason = "；".join(notes[:3]) or "未形成有效同行池。"
        return f"同行对比状态：未形成有效同行池；原因：{reason}写作时只说明数据局限，不得编造行业均值、中位数或聚类结论。"

    peer_count = peers.get("effective_count")
    level_text = f"中信 2019 {level}级行业" if level else "中信 2019 行业"
    heading = selected_name or "所选同行池"
    lines = [f"同行池口径：{level_text}「{heading}」，有效同行 {peer_count} 家。"]
    if include_metric_rows:
        lines.append("可直接用于写作的横向对比要点：")
        for row in metric_rows[:8]:
            key = str(row.get("metric") or "")
            percentile = _float(row.get("percentile"))
            lines.append(
                "- "
                f"{_industry_metric_label(key, row)}：目标公司 {_format_industry_metric_value(key, row.get('target'))}，"
                f"行业中位数 {_format_industry_metric_value(key, row.get('median'))}，"
                f"行业均值 {_format_industry_metric_value(key, row.get('mean'))}，"
                f"行业分位 {_format_percentile(percentile)}，{row.get('relative_label') or '接近行业中位区间'}。"
            )
    else:
        lines.append(
            "横向对比数值由系统机械插入 Markdown 竖表（如「表·同行横向坐标」「表·行业横向坐标」「表·行业估值对比」）；"
            "正文在对应小标题下只写一句定性判断，禁止逐条写本公司/行业中位数/分位。"
        )

    cluster = summary.get("cluster_anomalies") if isinstance(summary.get("cluster_anomalies"), dict) else {}
    if cluster.get("status") == "ok":
        contributors = cluster.get("top_contributors") if isinstance(cluster.get("top_contributors"), list) else []
        contributor_text = "、".join(
            _industry_metric_label(str(item.get("metric") or ""), item) for item in contributors[:3] if isinstance(item, dict)
        )
        noise_text = (
            "被 DBSCAN 标记为噪声点"
            if cluster.get("is_noise")
            else f"未被 DBSCAN 标记为噪声点，所属簇规模 {cluster.get('cluster_size')} 家"
        )
        lines.extend(
            [
                f"DBSCAN 异常识别显示目标公司{noise_text}；异常分数约 {_format_plain_number(cluster.get('anomaly_score'))}。"
                + (f"主要贡献指标为{contributor_text}。" if contributor_text else ""),
            ]
        )
        single_metric = cluster.get("single_metric_anomalies") if isinstance(cluster.get("single_metric_anomalies"), list) else []
        if single_metric:
            single_text = "、".join(
                _industry_metric_label(str(item.get("metric") or ""), item) for item in single_metric[:3] if isinstance(item, dict)
            )
            lines.append(f"同时存在单指标 robust z-score 超过阈值的异常项：{single_text}。")
        if cluster.get("valuation_contributors_excluded"):
            lines.append("DBSCAN 原始贡献指标包含估值因子；经营质量章节只使用非估值贡献项，估值驱动的聚类证据不用于经营质量结论。")
    else:
        reason = cluster.get("reason") or "样本数或有效特征不足"
        lines.append(f"DBSCAN 本次未执行：{reason}；行业判断主要依据分位数和四分位区间。")
    if notes:
        lines.append(f"数据局限：{'；'.join(notes[:3])}")
    return "\n".join(lines)


def _format_rate_delta(delta: float) -> str:
    points = delta * 100 if abs(delta) <= 1 else delta
    sign = "+" if points >= 0 else ""
    return f"{sign}{points:.2f} pct"


def macro_rate_prompt_brief(data: dict[str, Any]) -> str:
    macro = data.get("macro_rate_recent") if isinstance(data.get("macro_rate_recent"), dict) else {}
    ir_rows = macro.get("interbank_rate") if isinstance(macro.get("interbank_rate"), list) else []
    yc_rows = macro.get("yield_curve") if isinstance(macro.get("yield_curve"), list) else []
    if not ir_rows and not yc_rows:
        ir_block = data.get("interbank_rate") if isinstance(data.get("interbank_rate"), dict) else {}
        yc_block = data.get("yield_curve") if isinstance(data.get("yield_curve"), dict) else {}
        ir_rows = ir_block.get("rows") if isinstance(ir_block.get("rows"), list) else []
        yc_rows = yc_block.get("rows") if isinstance(yc_block.get("rows"), list) else []
    if not ir_rows and not yc_rows:
        return "宏观利率数据缺失：本节只说明局限，不得编造 Shibor 或国债收益率。"

    lines = ["可直接引用的无风险利率与短端资金成本："]
    if ir_rows:
        latest = ir_rows[-1] if isinstance(ir_rows[-1], dict) else {}
        prev = ir_rows[max(0, len(ir_rows) - 21)] if isinstance(ir_rows[max(0, len(ir_rows) - 21)], dict) else {}
        date_label = latest.get("date") or "最新"
        lines.append(f"Shibor（{date_label}）：")
        for key, label in (("ON", "隔夜"), ("1W", "1周"), ("1M", "1月"), ("3M", "3月"), ("1Y", "1年")):
            if latest.get(key) is not None:
                change = ""
                if prev.get(key) is not None:
                    delta = _float(latest.get(key)) - _float(prev.get(key))
                    if delta is not None:
                        change = f"，较约20交易日前 {_format_rate_delta(delta)}"
                lines.append(f"- {label} {_format_industry_metric_value(key, latest.get(key))}{change}")
    if yc_rows:
        latest = yc_rows[-1] if isinstance(yc_rows[-1], dict) else {}
        date_label = latest.get("date") or "最新"
        lines.append(f"国债收益率曲线（{date_label}，作无风险利率参考）：")
        for key, label in (("1Y", "1年期"), ("5Y", "5年期"), ("10Y", "10年期"), ("30Y", "30年期")):
            if latest.get(key) is not None:
                lines.append(f"- {label} {_format_industry_metric_value(key, latest.get(key))}")
        y1, y10 = _float(latest.get("1Y")), _float(latest.get("10Y"))
        if y1 is not None and y10 is not None:
            spread = (y10 - y1) * 100 if abs(y10) <= 1 else y10 - y1
            lines.append(f"- 10Y-1Y 期限利差 {spread:.2f} pct")
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    dividend = factor.get("dividend_yield_ttm")
    if dividend is not None:
        lines.append(f"目标股股息率(TTM) {_format_industry_metric_value('dividend_yield_ttm', dividend)}，可与 10Y 国债比较利差。")
    return "\n".join(lines)


def operating_quality_writer_guidance() -> str:
    return (
        "本章节写经营与基本面：优先 annual_financial_analysis、pit、MD&A（基本业务、业务发展、行业与勾稽 crosswalk）"
        "与同行经营类对比；正文结构自由，不必固定八段模板。"
        "盈利、现金流、营运效率多年对比（pit_financials_table / financial_years）可用 Markdown 表格或连贯句子/列表写入。"
        "小标题可按主题组织（如利润表、现金流与营运效率）；系统亦会机械插入对比表，正文写解读与 MD&A 对照。"
        "同行横向对比数值只引用系统「表·同行横向坐标」，正文一句定性即可。"
        "禁止写 PE/PB/PS、股息率、估值分位或估值匹配判断。"
    )


def industry_comparison_writer_guidance(
    section_name: str,
    data: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    if not section_uses_industry_comparison(section_name, plan) or not data.get("industry_comparison"):
        return ""
    brief = str(data.get("industry_comparison_brief") or "").strip()
    if is_operating_quality_section(section_name, plan):
        return (
            peer_compare_table_writing_rule()
            + "本章节必须把同行对比作为经营质量分析坐标。写作要求："
            "1) 小标题「**同行横向坐标**」下只写一句定性判断；"
            "2) 指标对比由系统插入「表·同行横向坐标」，正文不得逐条列举数值；"
            "3) DBSCAN 可用时只解释经营质量相关贡献指标；"
            "行业口径以 industry_comparison_summary 为准。"
            + (f"同行对比写作简报：{brief}" if brief else "")
        )
    if "基本面" in section_name or "估值" in section_name:
        return (
            peer_compare_table_writing_rule()
            + "本章节同行对比写作要求："
            "1) 「**行业横向坐标**」「**行业估值对比**」等小标题下只写一句定性判断；"
            "2) PE/PB/PS 及盈利/杠杆对比数值由系统机械表展示，正文引用表格结论，禁止逐条写分位/中位数；"
            "3) DBSCAN 可用时说明噪声点与贡献指标，不可用时说明样本局限。"
            + (f"同行对比写作简报：{brief}" if brief else "")
        )
    return (
        "本章节可引用 industry_comparison_summary 的异常识别和数据局限作为风险证据；"
        "若同行池无效或 DBSCAN 跳过，只说明局限，不得编造行业结论。"
        + (f"同行对比写作简报：{brief}" if brief else "")
    )


def macro_rate_writer_guidance(
    section_name: str,
    data: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    if not is_macro_section(section_name, plan):
        return ""
    brief = str(data.get("macro_rate_brief") or "").strip()
    return (
        "本章节分析无风险利率（国债收益率曲线）与短端 Shibor，并必须与目标股的估值/股息率/负债率建立逻辑联系；"
        "禁止重复资金与交易结构中的两融余额/融资买入表格、基本面/估值章中的 PE/PB/盈利与现金流多年表、经营质量章中的同行对比段落。"
        "禁止在宏观章写「融资余额从…增至…」类段落或两融 Markdown 表；负债率/股息率利差各用一句话挂钩即可。"
        "数值必须来自 JSON 的 macro_rate_recent 或 macro_rate_brief，禁止写「JSON 未提供」若 brief 中已有数据。"
        "系统会插入 Shibor/国债图，正文引用图表并说明对 DCF 折现率或股息率利差的影响。"
        + (f"宏观利率写作简报：{brief}" if brief else "")
    )


def section_uses_industry_comparison(section_name: str, plan: dict[str, Any] | None = None) -> bool:
    return is_operating_quality_section(section_name, plan) or any(
        token in section_name for token in ("基本面", "估值", "风险")
    )


def _is_valuation_key(key: Any) -> bool:
    text = str(key or "").lower()
    return any(part in text for part in _VALUATION_KEY_PARTS)


def strip_valuation_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_valuation_fields(item) for key, item in value.items() if not _is_valuation_key(key)}
    if isinstance(value, list):
        return [strip_valuation_fields(item) for item in value]
    return value


def mda_context_available(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    ctx = data.get("annual_report_context")
    annual = data.get("annual_analysis")
    if isinstance(ctx, dict) and (ctx.get("mda_excerpt") or ctx.get("mda_crosswalk") or ctx.get("mda_summary")):
        return True
    if isinstance(annual, dict) and (annual.get("mda_excerpt") or annual.get("mda_full_text")):
        return True
    return bool(resolve_mda_text(data))


def resolve_mda_text(data: dict[str, Any]) -> str:
    ctx = data.get("annual_report_context") if isinstance(data.get("annual_report_context"), dict) else {}
    annual = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
    for source in (ctx, annual, data):
        if not isinstance(source, dict):
            continue
        for key in ("mda_excerpt", "mda_full_text", "mda_text"):
            text = str(source.get(key) or "").strip()
            if text:
                return text[:12000]
    return ""


def attach_mda_business_payload(
    payload: dict[str, Any],
    data: dict[str, Any],
    section_name: str,
    *,
    plan: dict[str, Any] | None = None,
) -> None:
    if not mda_context_available(data):
        return
    from .mda_analysis import build_mda_business_brief

    ctx = data.get("annual_report_context") if isinstance(data.get("annual_report_context"), dict) else {}
    annual = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
    mda_text = resolve_mda_text(data)
    kind = section_kind_for_name(section_name, plan)
    crosswalk = ctx.get("mda_crosswalk") if isinstance(ctx.get("mda_crosswalk"), list) else None
    if not crosswalk and isinstance(annual.get("financial_analysis"), dict):
        crosswalk = annual["financial_analysis"].get("mda_crosswalk")
    payload["mda_business_brief"] = build_mda_business_brief(
        mda_text,
        section_kind=kind,
        mda_summary=ctx.get("mda_summary") or (ctx.get("mda_meta") or {}).get("summary"),
        crosswalk=crosswalk if isinstance(crosswalk, list) else None,
    )
    if ctx:
        payload.setdefault("annual_report_context", ctx)
    summary = ctx.get("mda_summary") or (ctx.get("mda_meta") or {}).get("summary")
    if summary:
        payload["mda_summary"] = summary
    if isinstance(crosswalk, list) and crosswalk:
        preview_limit = 8 if is_operating_quality_section(section_name, plan) else 4
        payload["mda_crosswalk_preview"] = crosswalk[:preview_limit]
        if is_operating_quality_section(section_name, plan) or "风险" in section_name:
            payload["mda_crosswalk"] = crosswalk


def mda_business_writer_guidance(
    section_name: str,
    data: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    from .report_writing import mda_business_writing_guide

    kind = section_kind_for_name(section_name, plan)
    guide = mda_business_writing_guide(section_name, section_kind=kind)
    if not mda_context_available(data):
        return guide + " 若 JSON 无 mda_business_brief，只基于量化数据写作并说明 MD&A 未采集。"
    brief = str(data.get("mda_business_brief") or "").strip()
    if brief:
        guide += f" MD&A 业务论述简报（须引用）：{brief}"
    return guide


def compact_data_for_prompt(
    data: dict[str, Any],
    charts: dict[str, str],
    section_name: str,
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .section_validation import section_is_market_kind

    tail = 20 if "量价" in section_name or "技术" in section_name else 12
    payload: dict[str, Any] = {
        "section_name": section_name,
        "order_book_id": data.get("order_book_id"),
        "sec_name": data.get("sec_name"),
        "date_range": [data.get("start_date"), data.get("end_date")],
        "technical": data.get("technical"),
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "analytical_evidence": build_analytical_evidence(data, section_name),
        "capital_flow": {k: v for k, v in data.get("capital_flow", {}).items() if k != "rows"}
        | {"recent_rows": data.get("capital_flow", {}).get("rows", [])[-tail:]},
        "price_recent": data.get("price", {}).get("rows", [])[-tail:],
        "price_change_rate_recent": data.get("price_change_rate", {}).get("rows", [])[-tail:],
        "turnover_recent": data.get("turnover", {}).get("rows", [])[-tail:],
        "securities_margin_recent": data.get("securities_margin", {}).get("rows", [])[-tail:],
        "dividend_recent": data.get("dividend", {}).get("rows", [])[-8:],
        "shares_recent": data.get("shares", {}).get("rows", [])[-8:],
        "factor_history_recent": data.get("factor_history", {}).get("rows", [])[-12:],
        "macro_rate_recent": {
            "interbank_rate": data.get("interbank_rate", {}).get("rows", [])[-12:],
            "yield_curve": data.get("yield_curve", {}).get("rows", [])[-12:],
        },
        "status_checks": {
            "suspended_recent": data.get("suspended", {}).get("rows", [])[-8:],
            "st_recent": data.get("st_stock", {}).get("rows", [])[-8:],
        },
        "charts": charts,
    }
    if section_uses_industry_comparison(section_name, plan):
        industry_summary = (
            operating_quality_industry_summary(data.get("industry_comparison"))
            if is_operating_quality_section(section_name, plan)
            else industry_comparison_prompt_summary(data.get("industry_comparison"))
        )
        payload["industry_comparison_summary"] = industry_summary
        payload["industry_comparison"] = industry_summary
        payload["industry_comparison_brief"] = industry_comparison_prompt_brief(
            industry_summary,
            include_metric_rows=False,
        )
    if is_operating_quality_section(section_name, plan):
        payload["factor"] = strip_valuation_fields(payload.get("factor"))
        payload["factor_history_recent"] = strip_valuation_fields(payload.get("factor_history_recent"))
        payload["dividend_recent"] = []
        payload["charts"] = filter_charts_for_section(payload.get("charts", {}), OPERATING_QUALITY_BLOCKED_CHART_KEYS)
    if section_is_market_kind(section_name, plan):
        payload["factor"] = strip_valuation_fields(payload.get("factor"))
        payload["factor_history_recent"] = []
        payload["pit_financials"] = None
        payload.pop("annual_report_context", None)
        payload.pop("annual_financial_analysis", None)
        payload.pop("mda_business_brief", None)
        payload["securities_margin_recent"] = []
        payload["macro_rate_recent"] = {"interbank_rate": [], "yield_curve": []}
        payload["charts"] = filter_charts_for_section(payload.get("charts", {}), MARKET_SECTION_BLOCKED_CHART_KEYS)
    if is_operating_quality_section(section_name, plan) or "基本面" in section_name or "风险" in section_name:
        payload["pit_financials"] = data.get("pit_financials")
        ctx = data.get("annual_report_context")
        payload["annual_report_context"] = ctx
        if isinstance(ctx, dict):
            payload["mda_crosswalk"] = ctx.get("mda_crosswalk")
            payload["articulation_checks"] = ctx.get("articulation_checks")
        annual = data.get("annual_analysis") if isinstance(data.get("annual_analysis"), dict) else {}
        if annual.get("financial_analysis") and isinstance(annual["financial_analysis"], dict):
            payload["annual_financial_analysis"] = annual["financial_analysis"]
    if is_macro_section(section_name, plan):
        payload["macro_rate_brief"] = macro_rate_prompt_brief({**data, **payload})
        payload["factor"] = {
            key: data.get("factor", {}).get(key)
            for key in ("dividend_yield_ttm", "pe_ratio_ttm", "pb_ratio_ttm", "debt_to_asset_ratio")
            if isinstance(data.get("factor"), dict) and data.get("factor", {}).get(key) is not None
        }
    attach_mda_business_payload(payload, data, section_name, plan=plan)
    return payload
