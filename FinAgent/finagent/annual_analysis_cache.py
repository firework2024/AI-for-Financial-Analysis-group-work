"""年报财务分析结果缓存（SQLite），避免 multi 重复跑 analyze_financials。"""

from __future__ import annotations

import json
from typing import Any


def _analysis_fingerprint(financial_data: list[dict[str, Any]], mda_text: str) -> str:
    try:
        payload = {"rows": len(financial_data), "mda_len": len(mda_text or "")}
        if financial_data:
            payload["last_year"] = financial_data[-1].get("year")
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except Exception:
        return ""


def load_cached_financial_analysis(annual: dict[str, Any]) -> dict[str, Any] | None:
    raw = annual.get("financial_analysis")
    if not isinstance(raw, dict) or not raw.get("metrics"):
        return None
    fp = str(annual.get("financial_analysis_fingerprint") or "")
    current = _analysis_fingerprint(
        annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else [],
        str(annual.get("mda_text") or ""),
    )
    if fp and current and fp != current:
        return None
    return raw


def persist_financial_analysis_cache(
    *,
    stock_code: str,
    report_year: int,
    financial_data: list[dict[str, Any]],
    mda_text: str,
    analysis: dict[str, Any],
) -> None:
    from .datastore.db import update_annual_financial_analysis

    fingerprint = _analysis_fingerprint(financial_data, mda_text)
    update_annual_financial_analysis(
        stock_code,
        report_year,
        analysis=analysis,
        fingerprint=fingerprint,
    )


def compute_financial_analysis(
    annual: dict[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    cached = load_cached_financial_analysis(annual)
    if cached is not None:
        return cached

    from .financial_analysis import analyze_financials
    from .mda_analysis import enrich_financial_analysis_with_mda

    financial_data = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
    mda_text = str(annual.get("mda_text") or "")
    company_context = {
        "stock_code": annual.get("stock_code"),
        "sec_name": annual.get("sec_name"),
        "report_year": annual.get("report_year"),
    }
    analysis = analyze_financials(financial_data, {}, company_context)
    analysis = enrich_financial_analysis_with_mda(analysis, mda_text)

    if persist and annual.get("stock_code") and annual.get("report_year") is not None:
        try:
            persist_financial_analysis_cache(
                stock_code=str(annual["stock_code"]),
                report_year=int(annual["report_year"]),
                financial_data=financial_data,
                mda_text=mda_text,
                analysis=analysis,
            )
        except Exception as exc:
            print(f"[annual_analysis_cache] persist skipped: {type(exc).__name__}: {exc}")
    return analysis
