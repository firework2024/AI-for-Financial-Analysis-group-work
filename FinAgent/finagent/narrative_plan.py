"""采数后的叙事规划：压缩 data briefing、章节 kind 路由、定制报告标题。

briefing 中的叙事角度仅为提示，供 planner / 写作 Agent 参考，非必须执行的指令清单。
"""

from __future__ import annotations

from typing import Any

from .chart_catalog import MARKET_TECH_SECTION
from .report_writing import summarize_pit_rows

CAPITAL_SECTION = "资金与交易结构"
MACRO_SECTION = "宏观利率背景"
RISK_SECTION = "综合风险与数据局限"

PLANNING_GUIDANCE_NOTE = (
    "optional_narrative_angles（及兼容字段 narrative_signals）仅为采数后的可选叙事角度，"
    "请结合公司实际与数据覆盖取舍，不必逐条套用或照抄措辞。"
)


def data_briefing_planner_preamble() -> str:
    return (
        "\n\n已采集数据摘要（供参考：可据实拟定 report_title、narrative_thesis 与章节；"
        "叙事角度条目为提示而非硬性清单）："
    )

ALLOWED_SECTION_KINDS = frozenset(
    {"operating_quality", "market", "valuation", "capital", "macro", "risk"}
)

OPERATING_QUALITY_SECTION = "经营质量分析"


def infer_section_kind(section_name: str) -> str | None:
    name = str(section_name or "")
    if any(k in name for k in ("经营质量", "盈利质量", "财务质量")):
        return "operating_quality"
    if any(k in name for k in ("量价", "技术面", "技术因素", "趋势")):
        return "market"
    if any(k in name for k in ("估值", "股息")) and not any(k in name for k in ("经营", "质量")):
        return "valuation"
    if any(k in name for k in ("资金", "两融", "融资", "融券", "成交结构")):
        return "capital"
    if any(k in name for k in ("宏观", "利率", "Shibor", "国债", "曲线")):
        return "macro"
    if any(k in name for k in ("风险", "局限")):
        return "risk"
    if any(k in name for k in ("基本面", "财务")):
        return "operating_quality"
    return None


def section_kind_for_name(section_name: str, plan: dict[str, Any] | None = None) -> str | None:
    if plan:
        for spec in plan.get("sections") or []:
            if isinstance(spec, dict) and str(spec.get("name") or "") == section_name:
                raw = str(spec.get("kind") or "").strip().lower()
                if raw in ALLOWED_SECTION_KINDS:
                    return raw
                break
    return infer_section_kind(section_name)


def is_operating_quality_section(section_name: str, plan: dict[str, Any] | None = None) -> bool:
    kind = section_kind_for_name(section_name, plan)
    if kind == "operating_quality":
        return True
    if kind:
        return False
    name = str(section_name or "")
    return OPERATING_QUALITY_SECTION in name or "经营质量" in name


def _row_count(block: Any) -> int:
    if isinstance(block, dict):
        if isinstance(block.get("row_count"), int):
            return int(block["row_count"])
        rows = block.get("rows")
        if isinstance(rows, list):
            return len(rows)
    return 0


def build_plan_data_briefing(data: dict[str, Any]) -> dict[str, Any]:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    industry = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    pit = data.get("pit_financials") if isinstance(data.get("pit_financials"), dict) else {}
    pit_rows = pit.get("rows") if isinstance(pit.get("rows"), list) else []
    annual_ctx = data.get("annual_report_context") if isinstance(data.get("annual_report_context"), dict) else {}

    coverage = {
        "price": _row_count(data.get("price")),
        "margin": _row_count(data.get("securities_margin")),
        "capital_flow": _row_count(data.get("capital_flow")),
        "factor_snapshot": bool(factor),
        "pit_rows": len(pit_rows),
        "annual_report": bool(annual_ctx),
    }

    signals: list[str] = []
    r20, r60 = technical.get("return_20d"), technical.get("return_60d")
    if r20 is not None and r60 is not None:
        try:
            r20f, r60f = float(r20), float(r60)
            if r20f < -0.05 and r60f > 0.08:
                signals.append("（可选）若与基本面一致，可考虑从「强势中的调整」切入")
            elif r20f > 0.1 and r60f > 0.15:
                signals.append("（可选）短中期共振上行时，可酌情突出趋势与资金配合")
            elif r20f < -0.08 and r60f < -0.05:
                signals.append("（可选）趋势偏弱时，可先承认压力再谈基本面缓冲")
        except (TypeError, ValueError):
            pass

    pe = factor.get("pe_ratio_ttm")
    if pe is not None:
        try:
            if float(pe) > 40:
                signals.append("（可选）估值偏高时，可与盈利增速或行业对比挂钩")
            elif float(pe) < 15:
                signals.append("（可选）估值偏低或偏成熟时，可酌情强调股息与现金流")
        except (TypeError, ValueError):
            pass

    return {
        "stock_code": data.get("stock_code"),
        "sec_name": data.get("sec_name"),
        "order_book_id": data.get("order_book_id"),
        "industry": {
            k: industry.get(k)
            for k in ("first_industry_name", "second_industry_name", "third_industry_name")
            if industry.get(k)
        },
        "date_range": [data.get("start_date"), data.get("end_date")],
        "technical_highlights": {
            k: technical.get(k)
            for k in (
                "latest_close",
                "return_5d",
                "return_20d",
                "return_60d",
                "ma20",
                "ma60",
                "rsi14",
                "volatility_20d",
            )
            if technical.get(k) is not None
        },
        "factor_highlights": {
            k: factor.get(k)
            for k in ("pe_ratio_ttm", "pb_ratio_lf", "ps_ratio_ttm", "dividend_yield_ttm", "market_cap")
            if factor.get(k) is not None
        },
        "data_coverage": coverage,
        "pit_summary": summarize_pit_rows(pit_rows[-8:]) if pit_rows else [],
        "annual_years": (annual_ctx.get("financial_years") or [])[:4] if annual_ctx else [],
        "planning_guidance": PLANNING_GUIDANCE_NOTE,
        "optional_narrative_angles": signals,
        "narrative_signals": signals,
        "missing_or_thin": [
            k for k, v in coverage.items() if v in (0, False) and k in ("pit_rows", "annual_report", "factor_snapshot")
        ],
    }


def build_planner_fallback_sections(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """按已采集数据覆盖生成章节计划；非固定五节模板。"""
    if not isinstance(data, dict) or not data:
        return [
            {
                "name": "综合分析与数据局限",
                "agent": "risk_synthesis_writer",
                "data": ["all_collected_data"],
                "kind": "risk",
            }
        ]

    sections: list[dict[str, Any]] = []
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    pit = data.get("pit_financials") if isinstance(data.get("pit_financials"), dict) else {}
    pit_rows = pit.get("rows") if isinstance(pit.get("rows"), list) else []
    annual_ctx = data.get("annual_report_context") if isinstance(data.get("annual_report_context"), dict) else {}

    if _row_count(data.get("price")) > 0 or any(technical.get(k) is not None for k in ("latest_close", "return_20d", "ma20")):
        sections.append(
            {
                "name": MARKET_TECH_SECTION,
                "agent": "market_tech_writer",
                "data": ["get_price", "get_price_change_rate", "get_turnover_rate"],
                "kind": "market",
            }
        )
    if pit_rows or annual_ctx or factor:
        sections.append(
            {
                "name": OPERATING_QUALITY_SECTION,
                "agent": "fundamental_writer",
                "data": ["get_factor", "get_pit_financials_ex", "get_dividend", "get_shares"],
                "kind": "operating_quality",
            }
        )
    if _row_count(data.get("securities_margin")) > 0 or _row_count(data.get("capital_flow")) > 0:
        sections.append(
            {
                "name": CAPITAL_SECTION,
                "agent": "capital_flow_writer",
                "data": ["get_capital_flow", "get_securities_margin"],
                "kind": "capital",
            }
        )
    if _row_count(data.get("interbank_rate")) > 0 or _row_count(data.get("yield_curve")) > 0:
        sections.append(
            {
                "name": MACRO_SECTION,
                "agent": "macro_rate_writer",
                "data": ["get_interbank_offered_rate", "get_yield_curve"],
                "kind": "macro",
            }
        )

    sections.append(
        {
            "name": RISK_SECTION,
            "agent": "risk_synthesis_writer",
            "data": ["all_collected_data", "is_suspended", "is_st_stock"],
            "kind": "risk",
        }
    )
    return sections
