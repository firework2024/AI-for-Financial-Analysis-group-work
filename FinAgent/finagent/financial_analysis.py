from __future__ import annotations

from typing import Any

from .env import get_env
from .fields import FIELD_MAP
from .framework import load_financial_framework_excerpt
from .llm import financial_signal_review_agent
from .signals import CATEGORY_LABELS, POLARITY_RANK, SEVERITY_RANK, detect_compound_signals, detect_structured_signals, summarize_signals


def analyze_financials(
    enriched_rows: list[dict[str, Any]],
    metric_factor_values: dict[int, dict[str, float]] | None = None,
    company_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = sorted(enriched_rows, key=lambda item: item["year"])
    metrics = [_metrics_for_row(row) for row in rows]
    _add_trend_metrics(metrics)
    _apply_metric_factor_fallbacks(metrics, metric_factor_values or {})

    signal_pack = _build_signal_pack(rows, metrics)
    print(f"  -> 规则层信号汇总: {signal_pack.get('signal_summary', {})}")

    evidence = _build_llm_evidence(rows, metrics, signal_pack, company_context or {})

    if get_env("OPENAI_API_KEY"):
        print("  -> 检测到 OPENAI_API_KEY，走 LLM 审核路径")
        try:
            analysis = financial_signal_review_agent(
                evidence=evidence,
                framework_text=load_financial_framework_excerpt(),
                company_context=company_context or {},
            )
            return _finalize_signal_review(analysis, signal_pack, rows, metrics)
        except Exception as exc:
            print(f"  -> LLM 调用失败 ({exc})，回退到本地规则审核")
    else:
        print("  -> 未检测到 OPENAI_API_KEY，走本地规则审核路径")

    return _finalize_signal_review(_local_signal_review(signal_pack), signal_pack, rows, metrics)


def _build_signal_pack(rows: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    structured_signals = detect_structured_signals(rows, metrics)
    compound_signals = detect_compound_signals(rows, metrics)
    combined = structured_signals + compound_signals
    return {
        "structured_signals": structured_signals,
        "compound_signals": compound_signals,
        "signal_summary": summarize_signals(combined),
    }


def _finalize_signal_review(
    analysis: dict[str, Any],
    signal_pack: dict[str, Any],
    rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_signals = _all_raw_signals(signal_pack)
    reviewed_signals = _sort_reviewed_signals(
        _dedupe_reviewed_signals(
            _enforce_required_signals(
                raw_signals,
                analysis.get("reviewed_signals", []),
            )
        )
    )
    if not reviewed_signals and raw_signals:
        reviewed_signals = [_reviewed_signal_from_rule(signal, source="rule_only") for signal in raw_signals]
        reviewed_signals = _sort_reviewed_signals(reviewed_signals)

    positive_signals = _dedupe_strings(analysis.get("positive_signals") or _signal_sentences(reviewed_signals, "positive"))
    negative_signals = _dedupe_strings(analysis.get("negative_signals") or _signal_sentences(reviewed_signals, "negative"))
    if not positive_signals:
        positive_signals = ["未识别到明确的积极财务信号。"]
    if not negative_signals:
        negative_signals = ["未识别到明确的消极财务信号。"]

    data_notes = _dedupe_strings([*analysis.get("data_notes", []), *_data_notes(rows)])
    key_risks = _dedupe_strings(analysis.get("key_risks") or _derive_key_risks(reviewed_signals))

    return {
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "key_risks": key_risks,
        "reviewed_signals": reviewed_signals,
        "raw_signals": signal_pack,
        "data_notes": data_notes,
        "metrics": metrics,
    }


def _local_signal_review(signal_pack: dict[str, Any]) -> dict[str, Any]:
    reviewed_signals = [_reviewed_signal_from_rule(signal, source="rules") for signal in _all_raw_signals(signal_pack)]
    reviewed_signals = _sort_reviewed_signals(reviewed_signals)
    return {
        "reviewed_signals": reviewed_signals,
        "positive_signals": _signal_sentences(reviewed_signals, "positive"),
        "negative_signals": _signal_sentences(reviewed_signals, "negative"),
        "key_risks": _derive_key_risks(reviewed_signals),
        "data_notes": [],
    }


def _reviewed_signal_from_rule(signal: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "category": signal["category"],
        "category_cn": signal.get("category_cn", CATEGORY_LABELS.get(signal["category"], signal["category"])),
        "polarity": signal["polarity"],
        "severity": signal["severity"],
        "title": signal.get("title") or signal.get("description") or signal.get("metric_cn") or signal.get("metric"),
        "explanation": signal.get("description") or signal.get("title") or "",
        "evidence": signal.get("evidence") or "",
        "metrics": signal.get("related_metrics") or [signal.get("metric")],
        "confidence": signal.get("confidence", "medium"),
        "source": source,
        "source_signal_id": signal.get("id"),
        "type": signal.get("type", "single"),
    }


def _enforce_required_signals(
    raw_signals: list[dict[str, Any]],
    reviewed_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewed = [dict(item) for item in reviewed_signals]
    reviewed_signal_ids = {item.get("source_signal_id") for item in reviewed if item.get("source_signal_id")}
    reviewed_metrics = {
        metric
        for item in reviewed
        for metric in item.get("metrics", [])
        if isinstance(metric, str) and metric
    }
    reviewed_text = " ".join(
        f"{item.get('title', '')} {item.get('explanation', '')} {item.get('evidence', '')}"
        for item in reviewed
    )

    required = [
        signal
        for signal in raw_signals
        if signal["polarity"] == "negative" and signal["severity"] in {"high", "critical"}
    ]

    for signal in required:
        if signal["id"] in reviewed_signal_ids:
            continue
        signal_metrics = {
            metric
            for metric in signal.get("related_metrics") or [signal.get("metric")]
            if isinstance(metric, str) and metric
        }
        if signal_metrics and reviewed_metrics.intersection(signal_metrics):
            continue
        if signal.get("title") and signal["title"] in reviewed_text:
            continue
        if signal.get("description") and signal["description"] in reviewed_text:
            continue
        reviewed.append(_reviewed_signal_from_rule(signal, source="rule_enforced"))
    return reviewed


def _all_raw_signals(signal_pack: dict[str, Any]) -> list[dict[str, Any]]:
    return [*signal_pack.get("structured_signals", []), *signal_pack.get("compound_signals", [])]


def _signal_sentences(reviewed_signals: list[dict[str, Any]], polarity: str) -> list[str]:
    items: list[str] = []
    for signal in reviewed_signals:
        if signal.get("polarity") != polarity:
            continue
        title = signal.get("title", "").strip()
        explanation = signal.get("explanation", "").strip()
        if title and explanation and title not in explanation:
            items.append(f"{title}：{explanation}")
        elif explanation:
            items.append(explanation)
        elif title:
            items.append(title)
    return items


def _derive_key_risks(reviewed_signals: list[dict[str, Any]]) -> list[str]:
    high_priority = [
        item
        for item in reviewed_signals
        if item.get("polarity") == "negative" and item.get("severity") in {"critical", "high"}
    ]
    risks = [
        f"{item.get('category_cn', CATEGORY_LABELS.get(item.get('category', ''), item.get('category', '')))}风险"
        for item in high_priority
    ]
    if risks:
        return risks

    fallback: list[str] = []
    for item in reviewed_signals:
        if item.get("polarity") == "negative":
            fallback.append(item.get("title") or item.get("explanation") or "")
    return [item for item in fallback if item][:3]


def _sort_reviewed_signals(reviewed_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        reviewed_signals,
        key=lambda item: (
            SEVERITY_RANK.get(item.get("severity", ""), 99),
            POLARITY_RANK.get(item.get("polarity", ""), 99),
            0 if item.get("type") == "compound" else 1,
            item.get("category", ""),
            item.get("title", ""),
        ),
    )


def _dedupe_reviewed_signals(reviewed_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in reviewed_signals:
        source_signal_id = item.get("source_signal_id")
        metrics = ",".join(sorted(str(metric) for metric in item.get("metrics", []) if metric))
        key = source_signal_id or f"{item.get('category')}|{item.get('severity')}|{item.get('title')}|{metrics}"
        deduped[key] = item
    return list(deduped.values())


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen[text] = None
    return list(seen)


def _build_llm_evidence(
    rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    signal_pack: dict[str, Any],
    company_context: dict[str, Any],
) -> dict[str, Any]:
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
                        "net_profit_deduct_non_recurring_pnl",
                        "gross_margin",
                        "selling_expense_ratio",
                        "ga_expense_ratio",
                        "financing_expense_ratio",
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
                        "net_profit_deduct_non_recurring_pnl_growth",
                        "cash_flow_from_operating_activities_growth",
                        "inventory_growth",
                        "receivable_growth",
                        "interest_bearing_debt_growth",
                    )
                },
            }
        )

    return {
        "company_context": company_context,
        "rows": evidence_rows,
        "signals": signal_pack,
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
    receivable = _sum_values(val("bill_accts_receivable"), val("bill_receivable"))

    metrics = {
        "year": row["year"],
        "quarter": row["quarter"],
        "revenue": revenue,
        "net_profit": net_profit,
        "net_profit_parent_company": val("net_profit_parent_company"),
        "net_profit_deduct_non_recurring_pnl": val("net_profit_deduct_non_recurring_pnl"),
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
            "net_profit_deduct_non_recurring_pnl",
            "cash_flow_from_operating_activities",
            "inventory",
            "receivable",
            "interest_bearing_debt",
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
