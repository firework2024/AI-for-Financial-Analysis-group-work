"""A-share financial statements via rqdatac."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from backend.utils.ticker_rq import to_rqdatac_id

from .cn_hk_market import fetch_cn_hk_financial_statements
from .rqdata_client import rqdatac_module
from .search import search

logger = logging.getLogger(__name__)

_PIT_FIELDS = [
    "revenue",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "operating_cash_flow",
    "goodwill",
    "accounts_receivable",
    "deducted_profit",
]


def get_financial_statements(ticker: str, periods: int = 8) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}

    rq = rqdatac_module()
    if rq is not None:
        try:
            end = str(date.today())
            start = (date.today() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
            df = rq.get_pit_financials_ex(
                order_book_ids=obid,
                start_date=start,
                end_date=end,
                fields=_PIT_FIELDS,
            )
            if df is not None and not df.empty:
                if isinstance(df.index, pd.MultiIndex):
                    df = df.reset_index()
                else:
                    df = df.reset_index()
                period_col = "quarter" if "quarter" in df.columns else "date"
                labels = sorted(df[period_col].astype(str).unique(), reverse=True)[:periods]
                result: dict[str, Any] = {"periods": labels, "source": "rqdatac", "ticker": obid}
                for field in _PIT_FIELDS:
                    if field in df.columns:
                        result[field] = [
                            safe_series_value(df, period_col, lbl, field) for lbl in labels
                        ]
                return result
        except Exception as exc:
            logger.info("[RQFinancial] pit financials failed: %s", exc)

    short = obid.replace(".XSHG", ".SS").replace(".XSHE", ".SZ").replace(".XBEX", ".BJ")
    em = fetch_cn_hk_financial_statements(short, periods=periods)
    if em:
        em["ticker"] = obid
        em["fallback_used"] = True
        return em
    return {"error": "financials_unavailable", "ticker": obid}


def safe_series_value(df: pd.DataFrame, period_col: str, label: str, field: str) -> Any:
    sub = df[df[period_col].astype(str) == label]
    if sub.empty:
        return None
    val = sub.iloc[-1].get(field)
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return val


def get_financial_statements_summary(ticker: str) -> str:
    data = get_financial_statements(ticker, periods=4)
    if data.get("error"):
        return f"无法获取 {ticker} 财报：{data['error']}"
    periods = data.get("periods") or []
    lines = [f"{ticker} 最近财报摘要（{data.get('source', '')}）："]
    for field in ("revenue", "net_income", "deducted_profit", "operating_cash_flow"):
        vals = data.get(field) or data.get("net_profit")
        if vals and periods:
            pairs = [f"{periods[i]}: {vals[i]}" for i in range(min(len(periods), len(vals))) if vals[i] is not None]
            if pairs:
                lines.append(f"- {field}: " + "; ".join(pairs[:4]))
    return "\n".join(lines)


def get_company_info(ticker: str) -> dict[str, Any]:
    obid = to_rqdatac_id(ticker)
    if not obid:
        return {"error": "invalid_astock_ticker"}
    rq = rqdatac_module()
    info: dict[str, Any] = {"ticker": obid, "currency": "CNY"}
    if rq is not None:
        try:
            inst = rq.instruments(obid)
            info.update(
                {
                    "name": getattr(inst, "symbol", None) or getattr(inst, "abbrev_symbol", None),
                    "listed_date": str(getattr(inst, "listed_date", "") or ""),
                    "sector": getattr(inst, "sector_code", None),
                    "source": "rqdatac",
                }
            )
            end = str(date.today())
            factors = ("pe_ttm", "pb", "market_cap")
            for f in factors:
                try:
                    df = rq.get_factor(obid, factor=f, start_date=end, end_date=end)
                    if df is not None and not df.empty:
                        info[f] = float(df.iloc[-1]) if hasattr(df.iloc[-1], "__float__") else df.iloc[-1]
                except Exception:
                    pass
        except Exception as exc:
            info["error"] = str(exc)
    return info


def get_earnings_estimates(ticker: str) -> dict[str, Any]:
    """一致预期占位：需 rqdatac 另类数据权限时扩展。"""
    obid = to_rqdatac_id(ticker)
    return {"ticker": obid, "estimates": [], "note": "consensus_requires_rqdatac_alt_data", "source": "placeholder"}


def get_eps_revisions(ticker: str) -> dict[str, Any]:
    return get_earnings_estimates(ticker)


def resolve_company_ticker(name: str) -> str | None:
    text = str(name or "").strip()
    if not text:
        return None
    rq = rqdatac_module()
    if rq is not None:
        try:
            df = rq.all_instruments(type="CS", market="cn", date=None)
            if df is not None and not df.empty:
                for col in ("symbol", "abbrev_symbol"):
                    if col in df.columns:
                        hit = df[df[col].astype(str).str.contains(text, na=False)]
                        if not hit.empty:
                            return str(hit.iloc[0].get("order_book_id") or hit.index[0])
        except Exception:
            pass
    try:
        results = search(f"{text} A股 股票代码", max_results=5)
        for item in results or []:
            content = item if isinstance(item, str) else str(item.get("content", ""))
            import re

            m = re.search(r"([0368]\d{5})\.(XSHG|XSHE|SS|SZ)", content.upper())
            if m:
                code = m.group(1)
                return to_rqdatac_id(code)
    except Exception:
        pass
    return None
