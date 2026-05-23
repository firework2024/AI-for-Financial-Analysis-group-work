from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .cninfo import to_order_book_id
from .fields import FIELD_NAMES

METRIC_FACTOR_MAP = {
    "asset_turnover": "total_asset_turnover_lyr",
    "inventory_turnover": "inventory_turnover_lyr",
    "receivable_turnover": "account_receivable_turnover_rate_lyr",
    "fixed_asset_turnover": "fixed_asset_turnover_lyr",
    "current_ratio": "current_ratio_lyr",
    "quick_ratio": "quick_ratio_lyr",
    "debt_to_assets": "debt_to_asset_ratio_lyr",
    "gross_margin": "gross_profit_margin_lyr",
    "cash_conversion_cycle": "cash_conversion_cycle_lyr",
}


@dataclass
class FinancialFetchResult:
    rows: list[dict[str, Any]]
    order_book_id: str
    quarters: list[str]


def fetch_financials(stock_code: str, report_year: int, years: int = 3) -> FinancialFetchResult:
    import rqdatac

    rqdatac.init()
    order_book_id = to_order_book_id(stock_code)
    start_year = report_year - years + 1
    start_quarter = f"{start_year}q4"
    end_quarter = f"{report_year}q4"
    df = rqdatac.get_pit_financials_ex(
        order_book_id,
        fields=FIELD_NAMES,
        start_quarter=start_quarter,
        end_quarter=end_quarter,
        statements="latest",
        market="cn",
    )
    if df is None or df.empty:
        rows = [{"year": year, "quarter": f"{year}q4"} for year in range(start_year, report_year + 1)]
    else:
        rows = _frame_to_rows(df)
    wanted = [f"{year}q4" for year in range(start_year, report_year + 1)]
    by_quarter = {row["quarter"]: row for row in rows}
    completed = []
    for quarter in wanted:
        row = by_quarter.get(quarter, {"quarter": quarter, "year": int(quarter[:4])})
        completed.append(row)
    return FinancialFetchResult(completed, order_book_id, wanted)


def fetch_factor_fallbacks(order_book_id: str, report_year: int, years: int, as_of: date) -> dict[int, dict[str, float]]:
    import rqdatac

    rqdatac.init()
    factor_date = _factor_date(rqdatac, as_of)
    all_names = set(rqdatac.get_all_factor_names())
    factors: list[str] = []
    factor_to_target: dict[str, tuple[int, str]] = {}
    for offset in range(years):
        year = report_year - offset
        for field in FIELD_NAMES:
            factor = f"{field}_lyr_{offset}"
            if factor in all_names:
                factors.append(factor)
                factor_to_target[factor] = (year, field)
    if not factors:
        return {}
    df = rqdatac.get_factor(order_book_id, factors, start_date=factor_date, end_date=factor_date)
    if df is None or df.empty:
        return {}
    row = df.iloc[-1]
    result: dict[int, dict[str, float]] = {}
    for factor, (year, field) in factor_to_target.items():
        value = row.get(factor)
        if value is None or pd.isna(value):
            continue
        result.setdefault(year, {})[field] = float(value)
    return result


def fetch_metric_factor_fallbacks(order_book_id: str, report_year: int, years: int, as_of: date) -> dict[int, dict[str, float]]:
    import rqdatac

    rqdatac.init()
    all_names = set(rqdatac.get_all_factor_names())
    factors = [factor for factor in METRIC_FACTOR_MAP.values() if factor in all_names]
    if not factors:
        return {}

    result: dict[int, dict[str, float]] = {}
    start_year = report_year - years + 1
    for year in range(start_year, report_year + 1):
        query_date = min(as_of, date(year + 1, 4, 30))
        factor_date = _factor_date(rqdatac, query_date)
        df = rqdatac.get_factor(order_book_id, factors, start_date=factor_date, end_date=factor_date)
        if df is None or df.empty:
            continue
        row = df.iloc[-1]
        for metric, factor in METRIC_FACTOR_MAP.items():
            value = row.get(factor)
            if value is None or pd.isna(value):
                continue
            result.setdefault(year, {})[metric] = float(value)
    return result


def _factor_date(rqdatac_module: Any, as_of: date) -> date:
    try:
        if rqdatac_module.is_trading_date(as_of):
            return as_of
        return rqdatac_module.get_previous_trading_date(as_of)
    except Exception:
        return as_of


def _frame_to_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    frame = df.reset_index()
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        raw = item.to_dict()
        quarter = str(raw.get("quarter"))
        row: dict[str, Any] = {"quarter": quarter, "year": int(quarter[:4])}
        for key in FIELD_NAMES:
            value = raw.get(key)
            row[key] = None if pd.isna(value) else float(value)
        for meta in ("info_date", "rice_create_tm", "if_adjusted"):
            if meta in raw and not pd.isna(raw[meta]):
                row[meta] = str(raw[meta])
        rows.append(row)
    return rows
