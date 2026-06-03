"""核心指标速览补全：行业名称与股息率（米筐缺失或快照 meta 不全时）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

_INDUSTRY_NAME_KEYS = (
    "first_industry_name",
    "level1_name",
    "selected_industry_name",
    "industry_name",
    "citics_industry_name",
    "second_industry_name",
    "level2_name",
)

_DIVIDEND_AMOUNT_KEYS = ("dividend_cash_before_tax", "cash_div", "cash_amount", "amount")


def industry_has_display_name(industry: dict[str, Any] | None) -> bool:
    if not isinstance(industry, dict) or not industry:
        return False
    for key in _INDUSTRY_NAME_KEYS:
        value = industry.get(key)
        if value not in (None, ""):
            return True
    for key, value in industry.items():
        if value in (None, ""):
            continue
        key_lower = str(key).lower()
        if "code" in key_lower:
            continue
        if "name" in key_lower or key_lower.endswith("industry"):
            return True
    return False


def _industry_from_eastmoney(stock_code: str) -> dict[str, Any]:
    code = str(stock_code or "").strip().split(".")[0]
    if not code or len(code) != 6:
        return {}
    try:
        from ..cninfo import classify_stock, normalize_stock_code
        from ..chat.eastmoney_profile import _fetch_company_survey, _fetch_industry_row

        code = normalize_stock_code(code)
        _, column, _ = classify_stock(code)
        em_code = f"{'SH' if column == 'sh' else 'SZ'}{code}"
        survey = _fetch_company_survey(em_code)
        company = survey.get("company") if isinstance(survey.get("company"), dict) else {}
        for key in ("industry_em", "industry_csrc"):
            name = company.get(key)
            if name not in (None, ""):
                return {"first_industry_name": str(name), "industry_source": key}
        row = _fetch_industry_row(code)
        if isinstance(row, dict) and row.get("industry_name"):
            return {
                "first_industry_name": str(row["industry_name"]),
                "industry_source": "eastmoney_industry_sta",
            }
    except Exception:
        return {}
    return {}


def resolve_industry_dict(data: dict[str, Any]) -> dict[str, Any]:
    industry = dict(data.get("industry") or {}) if isinstance(data.get("industry"), dict) else {}
    if industry_has_display_name(industry):
        return industry

    comparison = data.get("industry_comparison")
    if isinstance(comparison, dict):
        block = comparison.get("industry")
        if isinstance(block, dict):
            for src, dst in (
                ("level1_name", "first_industry_name"),
                ("selected_industry_name", "first_industry_name"),
                ("first_industry_name", "first_industry_name"),
                ("level2_name", "second_industry_name"),
            ):
                value = block.get(src)
                if value not in (None, ""):
                    industry.setdefault(dst, value)
    if industry_has_display_name(industry):
        return industry

    stock_code = str(data.get("stock_code") or data.get("order_book_id") or "").split(".")[0]
    fallback = _industry_from_eastmoney(stock_code)
    if fallback:
        industry.update(fallback)
    return industry


def _parse_row_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).split("T", 1)[0][:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _latest_close(data: dict[str, Any]) -> float | None:
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    close = technical.get("latest_close")
    if close is not None:
        try:
            number = float(close)
            if number > 0:
                return number
        except (TypeError, ValueError):
            pass
    for block_key in ("price",):
        block = data.get(block_key)
        rows = None
        if isinstance(block, dict):
            rows = block.get("rows") or block.get("recent_rows")
        if isinstance(rows, list) and rows:
            last = rows[-1]
            if isinstance(last, dict) and last.get("close") is not None:
                try:
                    number = float(last["close"])
                    if number > 0:
                        return number
                except (TypeError, ValueError):
                    pass
    return None


def _dividend_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    block = data.get("dividend")
    if isinstance(block, dict):
        rows = block.get("rows") or block.get("recent_rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    inventory = data.get("inventory") if isinstance(data.get("inventory"), dict) else {}
    inv_div = inventory.get("dividend")
    if isinstance(inv_div, dict):
        rows = inv_div.get("recent_rows") or inv_div.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _per_share_dividend(row: dict[str, Any]) -> float | None:
    amount = None
    for key in _DIVIDEND_AMOUNT_KEYS:
        if row.get(key) is not None:
            amount = row.get(key)
            break
    if amount is None:
        return None
    try:
        cash = float(amount)
    except (TypeError, ValueError):
        return None
    lot = row.get("round_lot")
    try:
        lot_f = float(lot) if lot not in (None, "", 0) else 1.0
    except (TypeError, ValueError):
        lot_f = 1.0
    if lot_f <= 0:
        lot_f = 1.0
    return cash / lot_f


def derive_dividend_yield_ttm(data: dict[str, Any]) -> float | None:
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    existing = factor.get("dividend_yield_ttm")
    if existing is not None:
        try:
            return float(existing)
        except (TypeError, ValueError):
            pass

    history = data.get("factor_history")
    if isinstance(history, dict):
        rows = history.get("rows")
        if isinstance(rows, list):
            for row in reversed(rows):
                if not isinstance(row, dict):
                    continue
                value = row.get("dividend_yield_ttm")
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue

    close = _latest_close(data)
    if not close or close <= 0:
        return None

    end = _parse_row_date(data.get("end_date")) or date.today()
    start = end - timedelta(days=370)
    total = 0.0
    for row in _dividend_rows(data):
        event_date = _parse_row_date(row.get("ex_dividend_date") or row.get("payable_date") or row.get("book_closure_date"))
        if event_date is None or event_date < start or event_date > end:
            continue
        per_share = _per_share_dividend(row)
        if per_share is not None and per_share > 0:
            total += per_share
    if total <= 0:
        return None
    return total / close


def enrich_core_metrics(data: dict[str, Any]) -> None:
    """就地补全行业与股息率，供报告 HTML/前端 data_summary 使用。"""
    industry = resolve_industry_dict(data)
    if industry:
        data["industry"] = industry

    factor = dict(data.get("factor") or {}) if isinstance(data.get("factor"), dict) else {}
    derived_yield = derive_dividend_yield_ttm(data)
    if derived_yield is not None and factor.get("dividend_yield_ttm") is None:
        factor["dividend_yield_ttm"] = derived_yield
        factor["dividend_yield_ttm_source"] = factor.get("dividend_yield_ttm_source") or "derived_dividend_ttm"
        data["factor"] = factor
