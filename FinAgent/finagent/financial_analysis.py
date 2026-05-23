from __future__ import annotations

from typing import Any

from .fields import FIELD_MAP
from .framework import load_financial_framework_excerpt
from .env import get_env
from .llm import financial_analysis_agent


def analyze_financials(
    enriched_rows: list[dict[str, Any]],
    metric_factor_values: dict[int, dict[str, float]] | None = None,
    company_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = sorted(enriched_rows, key=lambda item: item["year"])
    metrics = [_metrics_for_row(row) for row in rows]
    _add_trend_metrics(metrics)
    _apply_metric_factor_fallbacks(metrics, metric_factor_values or {})

    if get_env("OPENAI_API_KEY"):
        try:
            analysis = financial_analysis_agent(
                evidence=_build_llm_evidence(rows, metrics, company_context or {}),
                framework_text=load_financial_framework_excerpt(),
                company_context=company_context or {},
            )
            analysis["metrics"] = metrics
            return analysis
        except Exception:
            pass

    positive: list[str] = []
    negative: list[str] = []

    latest = metrics[-1] if metrics else {}
    previous = metrics[-2] if len(metrics) >= 2 else {}

    _compare_growth(positive, negative, latest, previous, "revenue", "营业总收入")
    _compare_growth(positive, negative, latest, previous, "net_profit_parent_company", "归母净利润")
    _compare_growth(positive, negative, latest, previous, "cash_flow_from_operating_activities", "经营现金流净额")

    if _gt(latest.get("gross_margin"), previous.get("gross_margin")):
        positive.append("毛利率较上一年提升，盈利效率指标呈积极变化。")
    elif _lt(latest.get("gross_margin"), previous.get("gross_margin")):
        negative.append("毛利率较上一年下降，盈利效率指标呈消极变化。")

    if _ge(latest.get("cash_to_revenue"), 1):
        positive.append("收现比不低于 1，收入现金回收表现较好。")
    elif latest.get("cash_to_revenue") is not None:
        negative.append("收现比低于 1，收入转化为现金的表现偏弱。")

    if _ge(latest.get("cash_to_profit"), 1):
        positive.append("净现比不低于 1，利润转化为经营现金流表现较好。")
    elif latest.get("cash_to_profit") is not None:
        negative.append("净现比低于 1，利润转化为经营现金流表现偏弱。")

    if _gt(latest.get("free_cash_flow"), 0):
        positive.append("自由现金流为正，经营现金流覆盖资本开支后仍有结余。")
    elif latest.get("free_cash_flow") is not None:
        negative.append("自由现金流为负，资本开支后现金留存承压。")

    if latest.get("debt_to_assets") is not None and latest["debt_to_assets"] <= 0.5:
        positive.append("资产负债率不高于 50%，杠杆指标处于较稳健区间。")
    elif latest.get("debt_to_assets") is not None and latest["debt_to_assets"] >= 0.7:
        negative.append("资产负债率不低于 70%，杠杆指标偏高。")

    if _gt(latest.get("inventory_growth"), latest.get("revenue_growth")):
        negative.append("存货增速高于收入增速，营运资产占用指标偏消极。")
    if _gt(latest.get("receivable_growth"), latest.get("revenue_growth")):
        negative.append("应收账款增速高于收入增速，回款相关指标偏消极。")

    if not positive:
        positive.append("未识别到明确的积极财务数据信号。")
    if not negative:
        negative.append("未识别到明确的消极财务数据信号。")

    return {
        "positive_signals": positive,
        "negative_signals": negative,
        "data_notes": _data_notes(rows),
        "metrics": metrics,
    }


def _build_llm_evidence(rows: list[dict[str, Any]], metrics: list[dict[str, Any]], company_context: dict[str, Any]) -> dict[str, Any]:
    key_fields = [
        "revenue",
        "operating_revenue",
        "cost_of_goods_sold",
        "net_profit",
        "net_profit_parent_company",
        "net_profit_deduct_non_recurring_pnl",
        "cash_flow_from_operating_activities",
        "cash_received_from_sales_of_goods",
        "cash_paid_for_asset",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_liabilities",
        "inventory",
        "bill_accts_receivable",
        "bill_receivable",
        "contract_liabilities",
        "equity_parent_company",
        "undistributed_profit",
        "short_term_loans",
        "non_current_liability_due_one_year",
        "long_term_loans",
        "bond_payable",
        "lease_liabilities",
        "selling_expense",
        "ga_expense",
        "r_n_d",
        "financing_expense",
        "adjust_asset_impairment",
        "adjust_credit_asset_impairment",
    ]
    evidence_rows: list[dict[str, Any]] = []
    for row, metric in zip(rows, metrics, strict=False):
        fields = row["fields"]
        evidence_rows.append(
            {
                "year": row["year"],
                "quarter": row["quarter"],
                "source_counts": _source_counts(fields),
                "field_snapshot": {
                    field: {
                        "value": fields.get(field, {}).get("value"),
                        "source": fields.get(field, {}).get("source"),
                    }
                    for field in key_fields
                    if field in fields
                },
                "metric_snapshot": {
                    key: metric.get(key)
                    for key in (
                        "revenue",
                        "net_profit",
                        "net_profit_parent_company",
                        "gross_margin",
                        "cash_to_revenue",
                        "cash_to_profit",
                        "free_cash_flow",
                        "capex_intensity",
                        "current_ratio",
                        "quick_ratio",
                        "debt_to_assets",
                        "interest_bearing_debt",
                        "roe",
                        "roa",
                        "asset_turnover",
                        "inventory_turnover",
                        "receivable_turnover",
                        "fixed_asset_turnover",
                        "equity_multiplier",
                    )
                },
                "trend_snapshot": {
                    key: metric.get(key)
                    for key in (
                        "revenue_growth",
                        "net_profit_growth",
                        "net_profit_parent_company_growth",
                        "cash_flow_from_operating_activities_growth",
                        "inventory_growth",
                        "receivable_growth",
                    )
                },
            }
        )

    return {
        "company_context": company_context,
        "rows": evidence_rows,
        "data_quality": _data_quality_summary(rows),
    }


def _source_counts(fields: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in fields.values():
        source = item.get("source")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _data_quality_summary(rows: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for row in rows:
        missing = sum(1 for item in row["fields"].values() if item["source"] == "missing")
        factor = sum(1 for item in row["fields"].values() if item["source"] == "rqdata_factor")
        annual = sum(1 for item in row["fields"].values() if item["source"] == "annual_report")
        notes.append(f"{row['year']} 年：rqdata_factor={factor}, annual_report={annual}, missing={missing}")
    return notes


def _metrics_for_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = row["fields"]

    def val(name: str) -> float | None:
        return fields.get(name, {}).get("value")

    revenue = val("revenue") or val("operating_revenue")
    cost = val("cost_of_goods_sold")
    net_profit = val("net_profit")
    equity = val("equity_parent_company")
    assets = val("total_assets")
    current_assets = val("current_assets")
    current_liabilities = val("current_liabilities")
    inventory = val("inventory")
    liabilities = val("total_liabilities")
    operating_cash = val("cash_flow_from_operating_activities")
    sales_cash = val("cash_received_from_sales_of_goods")
    capex = val("cash_paid_for_asset")
    receivable = val("bill_accts_receivable")

    metrics = {
        "year": row["year"],
        "quarter": row["quarter"],
        "revenue": revenue,
        "net_profit": net_profit,
        "net_profit_parent_company": val("net_profit_parent_company"),
        "cash_flow_from_operating_activities": operating_cash,
        "cost_of_goods_sold": cost,
        "total_assets": assets,
        "gross_margin": _ratio(None if revenue is None or cost is None else revenue - cost, revenue),
        "selling_expense_ratio": _ratio(val("selling_expense"), revenue),
        "ga_expense_ratio": _ratio(val("ga_expense"), revenue),
        "rnd_ratio": _ratio(val("r_n_d"), revenue),
        "financing_expense_ratio": _ratio(val("financing_expense"), revenue),
        "cash_to_revenue": _ratio(sales_cash, revenue),
        "cash_to_profit": _ratio(operating_cash, net_profit),
        "free_cash_flow": None if operating_cash is None or capex is None else operating_cash - capex,
        "capex_intensity": _ratio(capex, revenue),
        "current_ratio": _ratio(current_assets, current_liabilities),
        "quick_ratio": _ratio(None if current_assets is None or inventory is None else current_assets - inventory, current_liabilities),
        "debt_to_assets": _ratio(liabilities, assets),
        "interest_bearing_debt": _sum_values(
            val("short_term_loans"),
            val("non_current_liability_due_one_year"),
            val("long_term_loans"),
            val("bond_payable"),
            val("lease_liabilities"),
        ),
        "roe": _ratio(val("net_profit_parent_company"), equity),
        "roa": _ratio(net_profit, assets),
        "asset_turnover": _ratio(revenue, assets),
        "inventory_turnover": None,
        "receivable_turnover": None,
        "fixed_asset_turnover": None,
        "equity_multiplier": _ratio(assets, equity),
        "inventory": inventory,
        "receivable": receivable,
        "fixed_assets": val("net_fixed_assets"),
    }
    return metrics


def _add_trend_metrics(metrics: list[dict[str, Any]]) -> None:
    for index, metric in enumerate(metrics):
        if index == 0:
            continue
        previous = metrics[index - 1]
        for key in (
            "revenue",
            "net_profit",
            "net_profit_parent_company",
            "cash_flow_from_operating_activities",
            "inventory",
            "receivable",
        ):
            metric[f"{key}_growth"] = _growth(metric.get(key), previous.get(key))
        metric["asset_turnover"] = _ratio(metric.get("revenue"), _avg(metric.get("total_assets"), previous.get("total_assets")))
        metric["inventory_turnover"] = _ratio(metric.get("cost_of_goods_sold"), _avg(metric.get("inventory"), previous.get("inventory")))
        metric["receivable_turnover"] = _ratio(metric.get("revenue"), _avg(metric.get("receivable"), previous.get("receivable")))
        metric["fixed_asset_turnover"] = _ratio(metric.get("revenue"), _avg(metric.get("fixed_assets"), previous.get("fixed_assets")))


def _apply_metric_factor_fallbacks(metrics: list[dict[str, Any]], metric_factor_values: dict[int, dict[str, float]]) -> None:
    for metric in metrics:
        year_values = metric_factor_values.get(metric["year"], {})
        sources = metric.setdefault("metric_sources", {})
        for key, value in year_values.items():
            if metric.get(key) is None:
                metric[key] = value
                sources[key] = "rqdata_factor"


def _compare_growth(positive: list[str], negative: list[str], latest: dict[str, Any], previous: dict[str, Any], key: str, label: str) -> None:
    growth = _growth(latest.get(key), previous.get(key))
    latest[f"{key}_growth"] = growth
    if growth is None:
        return
    if growth > 0:
        positive.append(f"{label}同比增长 {growth:.1%}，规模指标呈积极变化。")
    elif growth < 0:
        negative.append(f"{label}同比下降 {abs(growth):.1%}，规模指标呈消极变化。")


def _data_notes(rows: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for row in rows:
        missing = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "missing"]
        fallback = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "annual_report"]
        factor = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "rqdata_factor"]
        if factor:
            notes.append(f"{row['year']} 年有 {len(factor)} 个字段使用米筐因子接口回补。")
        if fallback:
            notes.append(f"{row['year']} 年有 {len(fallback)} 个字段使用年报文本回退。")
        if missing:
            notes.append(f"{row['year']} 年有 {len(missing)} 个字段缺失。")
    return notes or ["米筐核心字段未发现缺失。"]


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def _sum_values(*values: float | None) -> float | None:
    present = [item for item in values if item is not None]
    return sum(present) if present else None


def _growth(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous in (None, 0):
        return None
    return latest / previous - 1


def _avg(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return (left + right) / 2


def _gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left > right


def _lt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left < right


def _ge(left: float | None, right: float | int) -> bool:
    return left is not None and left >= right
