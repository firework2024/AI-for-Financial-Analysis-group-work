"""对话中按需拉取米筐数据快照。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ..stock_utils import default_as_of, normalize_stock_code, to_order_book_id
from ..env import load_dotenv

if TYPE_CHECKING:
    from .store import ChatSession

LIVE_DATA_HINTS = (
    "最新",
    "最近",
    "现在",
    "当前",
    "今天",
    "实时",
    "股价",
    "收盘",
    "开盘",
    "融资",
    "pe",
    "pb",
    "rsi",
    "macd",
    "均线",
    "市值",
    "换手率",
    "行情",
    "k线",
    "现价",
    "涨跌",
)

_LIVE_DATA_GENERIC = ("查一下", "帮我看", "拉一下", "更新一下")

_PLURAL_REF_HINTS = (
    "他们",
    "它们",
    "这些",
    "这家",
    "几家",
    "多个",
    "各只",
    "分别",
    "对比",
    "都",
    "几个公司",
    "这几只",
    "这几家",
)

_STOCK_ALIASES: dict[str, str] = {
    "阳光电源": "300274",
    "宁德时代": "300750",
    "贵州茅台": "600519",
    "茅台": "600519",
    "平安银行": "000001",
    "万科": "000002",
    "万科a": "000002",
    "比亚迪": "002594",
    "比亚迪股份": "002594",
    "隆基绿能": "601012",
    "工商银行": "601398",
    "招商银行": "600036",
    "中国平安": "601318",
    "寒武纪": "688256",
    "中芯国际": "688981",
    "芯国际": "688981",
    "海光信息": "688041",
    "海光": "688041",
}


def needs_live_data(query: str) -> bool:
    q = str(query or "").lower()
    if any(hint in q for hint in LIVE_DATA_HINTS):
        return True
    if any(h in q for h in _LIVE_DATA_GENERIC):
        return any(h in q for h in ("股价", "行情", "收盘", "pe", "pb", "融资", "市值", "换手", "最新"))
    return False


def extract_stock_code(text: str, fallback: str | None = None) -> str | None:
    match = re.search(r"\b([036]\d{5})\b", str(text or ""))
    if match:
        return match.group(1)
    return fallback


def build_chat_context_blob(
    session: ChatSession | None,
    query: str,
    *,
    max_messages: int = 14,
    max_chars_per_message: int = 700,
) -> str:
    """拼接本轮问题与近期对话（含助手回复），供识别公司名/代码。"""
    parts: list[str] = []
    q = str(query or "").strip()
    if q:
        parts.append(q)
    if not session:
        return " ".join(parts)

    for message in session.messages[-max_messages:]:
        role = str(getattr(message, "role", "") or "")
        if role not in {"user", "assistant"}:
            continue
        text = str(getattr(message, "content", "") or "").strip()
        if not text or text == q:
            continue
        parts.append(text[:max_chars_per_message])
    return " ".join(parts)


def _codes_from_session_dialogue(session: ChatSession | None, query: str) -> list[str]:
    from .stock_codes import parse_stock_codes_text

    if not session:
        return parse_stock_codes_text(query)

    found: list[str] = []
    seen: set[str] = set()

    def _merge(codes: list[str]) -> None:
        for code in codes:
            if code not in seen:
                seen.add(code)
                found.append(code)

    _merge(parse_stock_codes_text(query))
    _merge(parse_stock_codes_text(build_chat_context_blob(session, query)))

    for message in reversed(session.messages):
        if str(getattr(message, "role", "") or "") not in {"user", "assistant"}:
            continue
        _merge(parse_stock_codes_text(str(getattr(message, "content", "") or "")))
        if len(found) >= 8:
            break

    for item in session.chunks or []:
        meta = item.get("meta") if isinstance(item, dict) else {}
        chunk_stock = str((meta or {}).get("stock_code") or "").strip()
        if re.fullmatch(r"\d{6}", chunk_stock):
            _merge([chunk_stock])
        _merge(parse_stock_codes_text(str(item.get("text") or "")[:800]))

    return found[:8]


def resolve_stock_from_message(text: str, session: ChatSession | None = None) -> str | None:
    """从文本及会话（含助手历史）解析单只股票。"""
    code = _resolve_code_from_text(str(text or ""))
    if code:
        return code
    codes = _codes_from_session_dialogue(session, text)
    return codes[0] if codes else None


def _query_refers_session_stocks(query: str) -> bool:
    q = str(query or "")
    if any(h in q for h in _PLURAL_REF_HINTS):
        return True
    return "公司" in q and len(q) <= 28 and any(h in q.lower() for h in ("pe", "pb", "ps", "估值", "市值"))


def _query_continues_session_topic(query: str, session: ChatSession | None) -> bool:
    """短追问（如「总资产」「他们的 PE」）沿用本会话已绑定标的。"""
    if not session:
        return False
    codes = list(getattr(session, "stock_codes", None) or []) or (
        [session.stock_code] if getattr(session, "stock_code", None) else []
    )
    if not codes:
        return False
    if _query_refers_session_stocks(query):
        return True
    q = str(query or "").strip()
    if len(q) > 32:
        return False
    from .intent import classify_query_intent
    from .stock_codes import parse_stock_codes_text

    if classify_query_intent(query, session).want_data_api and not parse_stock_codes_text(query):
        return True
    return False


def resolve_stocks_for_chat(
    query: str,
    session: ChatSession | None = None,
    *,
    sidebar_code: str | None = None,
    sidebar_stocks: str | None = None,
) -> list[str]:
    """对话选股：本条消息 + 侧栏 + 整段对话（含助手回复）+ 已绑定 session。"""
    from .stock_codes import normalize_stock_codes_list, parse_stock_codes_text

    session_codes = list(getattr(session, "stock_codes", None) or []) if session else []
    if not session_codes and session and session.stock_code:
        session_codes = [session.stock_code]

    mentioned = parse_stock_codes_text(query)
    if mentioned:
        return normalize_stock_codes_list(mentioned)

    if session_codes and _query_continues_session_topic(query, session):
        return normalize_stock_codes_list(session_codes)

    dialogue_codes = _codes_from_session_dialogue(session, query)
    if dialogue_codes:
        return normalize_stock_codes_list(dialogue_codes)

    side = normalize_stock_codes_list(None, single=sidebar_code, text=sidebar_stocks)
    if side:
        return side
    return normalize_stock_codes_list(session_codes)


def resolve_stock_for_chat(
    query: str,
    session: ChatSession | None = None,
    *,
    sidebar_code: str | None = None,
    sidebar_stocks: str | None = None,
) -> str | None:
    stocks = resolve_stocks_for_chat(
        query, session, sidebar_code=sidebar_code, sidebar_stocks=sidebar_stocks
    )
    return stocks[0] if stocks else None


def resolve_stock_code(
    query: str,
    session: ChatSession | None = None,
    *,
    sidebar_code: str | None = None,
    sidebar_stocks: str | None = None,
) -> str | None:
    """兼容旧调用：返回主股票代码。"""
    return resolve_stock_for_chat(
        query, session, sidebar_code=sidebar_code, sidebar_stocks=sidebar_stocks
    )


def _resolve_code_from_text(text: str) -> str | None:
    code = extract_stock_code(text)
    if code:
        return normalize_stock_code(code)
    code = _code_from_aliases(text)
    if code:
        return code
    code = _code_from_cninfo_name(text)
    if code:
        return normalize_stock_code(code)
    code = _code_from_sec_name(text)
    if code:
        return normalize_stock_code(code)
    return None


def sec_name_for_code(stock_code: str) -> str | None:
    code = normalize_stock_code(stock_code)
    try:
        from ..datastore.db import get_annual_report

        row = get_annual_report(code)
        if row and row.get("sec_name"):
            return str(row["sec_name"]).strip()
    except Exception:
        pass
    try:
        from ..cninfo import _load_stock_name_map

        for name, mapped in _load_stock_name_map().items():
            if mapped == code:
                return name
    except Exception:
        pass
    for name, mapped in _STOCK_ALIASES.items():
        if mapped == code:
            return name
    return None


def _code_from_aliases(text: str) -> str | None:
    q = str(text or "")
    for name, code in sorted(_STOCK_ALIASES.items(), key=lambda item: -len(item[0])):
        if name in q:
            return code
    return None


def _code_from_cninfo_name(text: str) -> str | None:
    try:
        from ..cninfo import lookup_stock_code_by_name

        return lookup_stock_code_by_name(text)
    except Exception:
        return None


def _code_from_sec_name(text: str) -> str | None:
    q = str(text or "").strip()
    if len(q) < 2:
        return None
    try:
        from ..datastore.db import _locked_connect

        with _locked_connect() as conn:
            row = conn.execute(
                """
                SELECT stock_code FROM annual_report_records
                WHERE sec_name IS NOT NULL AND ? LIKE '%' || sec_name || '%'
                ORDER BY report_year DESC
                LIMIT 1
                """,
                (q,),
            ).fetchone()
        return str(row["stock_code"]) if row else None
    except Exception:
        return None


def _safe_metric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return num


def _metric_ratio(numerator: Any, denominator: Any) -> float | None:
    num = _safe_metric(numerator)
    den = _safe_metric(denominator)
    if num is None or den in (None, 0):
        return None
    return num / den


def _metric_growth(current: Any, previous: Any) -> float | None:
    cur = _safe_metric(current)
    prev = _safe_metric(previous)
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


def _average_balance(current: Any, previous: Any) -> float | None:
    cur = _safe_metric(current)
    prev = _safe_metric(previous)
    if cur is None or cur <= 0:
        return None
    if prev is None or prev <= 0:
        return cur
    return (cur + prev) / 2


def _extract_annual_field(entry: dict[str, Any], field: str) -> float | None:
    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else entry
    payload = fields.get(field) if isinstance(fields, dict) else None
    if isinstance(payload, dict):
        return _safe_metric(payload.get("value"))
    return _safe_metric(payload)


def _financial_row_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    year_raw = row.get("year") or row.get("report_year")
    try:
        year = int(year_raw)
    except (TypeError, ValueError):
        year = 0
    return (year, str(row.get("quarter") or ""))


def _local_financial_rows(stock_code: str) -> tuple[list[dict[str, Any]], str | None]:
    """读取最原始财务行：优先 PIT 三表缓存，其次年报抽取的 financial_data。"""
    try:
        from ..datastore.db import get_annual_report, get_pit_financials
    except Exception:
        return [], None

    pit = get_pit_financials(stock_code)
    pit_rows = [row for row in (pit or {}).get("rows") or [] if isinstance(row, dict)]
    if pit_rows:
        return sorted(pit_rows, key=_financial_row_sort_key), "pit"

    annual = get_annual_report(stock_code)
    annual_rows: list[dict[str, Any]] = []
    for entry in (annual or {}).get("financial_data") or []:
        if not isinstance(entry, dict):
            continue
        row = {
            "year": entry.get("year") or entry.get("report_year"),
            "quarter": entry.get("quarter"),
        }
        for field in (
            "revenue",
            "operating_revenue",
            "cost_of_goods_sold",
            "net_profit",
            "net_profit_parent_company",
            "profit_from_operation",
            "gross_profit",
            "total_assets",
            "total_liabilities",
            "current_assets",
            "current_liabilities",
            "inventory",
            "equity_parent_company",
        ):
            value = _extract_annual_field(entry, field)
            if value is not None:
                row[field] = value
        if len(row) > 2:
            annual_rows.append(row)
    return sorted(annual_rows, key=_financial_row_sort_key), "annual" if annual_rows else None


def _financial_value(row: dict[str, Any] | None, *fields: str) -> float | None:
    if not row:
        return None
    for field in fields:
        value = _safe_metric(row.get(field))
        if value is not None:
            return value
    return None


def _set_derived_factor(
    factor: dict[str, Any],
    field: str,
    value: float | None,
    source: str,
    *,
    scale: float = 1.0,
    precision: int = 4,
) -> None:
    if factor.get(field) is not None or value is None:
        return
    factor[field] = round(value * scale, precision)
    factor[f"{field}_source"] = source


def _apply_derived_financial_factors(
    factor: dict[str, Any],
    quote: dict[str, Any],
    stock_code: str,
    *,
    technical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """用原始财务字段补全常见 factor；不依赖 PS/EPS 等二级衍生指标。"""
    out = dict(factor)
    rows, row_source = _local_financial_rows(stock_code)
    if not rows:
        return out

    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    source = f"derived_{row_source or 'financial'}"

    revenue = _financial_value(latest, "revenue", "operating_revenue")
    prev_revenue = _financial_value(previous, "revenue", "operating_revenue")
    cost = _financial_value(latest, "cost_of_goods_sold")
    prev_cost = _financial_value(previous, "cost_of_goods_sold")
    gross_profit = _financial_value(latest, "gross_profit")
    if gross_profit is None and revenue is not None and cost is not None:
        gross_profit = revenue - cost
    prev_gross_profit = _financial_value(previous, "gross_profit")
    if prev_gross_profit is None and prev_revenue is not None and prev_cost is not None:
        prev_gross_profit = prev_revenue - prev_cost

    net_profit = _financial_value(latest, "net_profit")
    prev_net_profit = _financial_value(previous, "net_profit")
    parent_profit = _financial_value(latest, "net_profit_parent_company")
    prev_parent_profit = _financial_value(previous, "net_profit_parent_company")
    operating_profit = _financial_value(latest, "profit_from_operation")
    prev_operating_profit = _financial_value(previous, "profit_from_operation")
    assets = _financial_value(latest, "total_assets")
    liabilities = _financial_value(latest, "total_liabilities")
    current_assets = _financial_value(latest, "current_assets")
    current_liabilities = _financial_value(latest, "current_liabilities")
    inventory = _financial_value(latest, "inventory")
    equity = _financial_value(latest, "equity_parent_company")
    prev_equity = _financial_value(previous, "equity_parent_company")
    avg_equity = _average_balance(equity, prev_equity)

    _set_derived_factor(out, "gross_profit_margin_ttm", _metric_ratio(gross_profit, revenue), source)
    _set_derived_factor(out, "net_profit_margin_ttm", _metric_ratio(net_profit, revenue), source)
    _set_derived_factor(
        out,
        "net_profit_parent_company_margin_ttm",
        _metric_ratio(parent_profit, revenue),
        source,
    )
    _set_derived_factor(out, "roe_ttm", _metric_ratio(parent_profit, avg_equity), source)
    _set_derived_factor(out, "debt_to_asset_ratio", _metric_ratio(liabilities, assets), source, scale=100)
    _set_derived_factor(out, "current_ratio", _metric_ratio(current_assets, current_liabilities), source)
    quick_assets = None
    if current_assets is not None and inventory is not None:
        quick_assets = current_assets - inventory
    _set_derived_factor(out, "quick_ratio", _metric_ratio(quick_assets, current_liabilities), source)

    market_cap = _safe_metric(out.get("market_cap"))
    price = _resolve_local_price(stock_code, quote=quote, technical=technical, factor=out)
    shares = _resolve_local_total_shares(stock_code, price=price, market_cap=market_cap)
    if market_cap is None and price and shares:
        market_cap = price * shares
        out["market_cap"] = round(market_cap, 2)
        out["market_cap_source"] = "derived_price_shares"

    _set_derived_factor(out, "ps_ratio_ttm", _metric_ratio(market_cap, revenue), source, precision=2)
    _set_derived_factor(
        out,
        "operating_revenue_growth_ratio_ttm",
        _metric_growth(revenue, prev_revenue),
        source,
    )
    _set_derived_factor(out, "net_profit_growth_ratio_ttm", _metric_growth(net_profit, prev_net_profit), source)
    _set_derived_factor(
        out,
        "net_profit_parent_company_growth_ratio_ttm",
        _metric_growth(parent_profit, prev_parent_profit),
        source,
    )
    _set_derived_factor(
        out,
        "operating_profit_growth_ratio_ttm",
        _metric_growth(operating_profit, prev_operating_profit),
        source,
    )
    _set_derived_factor(
        out,
        "gross_profit_growth_ratio_ttm",
        _metric_growth(gross_profit, prev_gross_profit),
        source,
    )
    return out


def _margin_as_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1:
        return value / 100
    return value


def _derive_pe_from_factor_fields(factor: dict[str, Any]) -> float | None:
    """兜底：PE = PS / 归母净利率；不用普通净利率替代归母口径。"""
    ps = _safe_metric(factor.get("ps_ratio_ttm"))
    parent_margin = _margin_as_ratio(_safe_metric(factor.get("net_profit_parent_company_margin_ttm")))
    if not ps or ps <= 0 or not parent_margin or parent_margin <= 0:
        return None
    return round(ps / parent_margin, 2)


def _resolve_local_price(
    stock_code: str,
    *,
    quote: dict[str, Any],
    technical: dict[str, Any] | None,
    factor: dict[str, Any],
) -> float | None:
    for value in (
        quote.get("close"),
        (technical or {}).get("latest_close"),
    ):
        price = _safe_metric(value)
        if price and price > 0:
            return price
    try:
        from ..datastore.db import get_latest_snapshot, load_series

        snapshot = get_latest_snapshot(stock_code)
        if snapshot:
            series = load_series(int(snapshot["id"]), ["price"], tail=1)
            rows = (series.get("price") or {}).get("rows") or []
            if rows:
                price = _safe_metric(rows[-1].get("close"))
                if price and price > 0:
                    return price
    except Exception:
        pass
    return None


def _resolve_local_net_profit(stock_code: str) -> tuple[float | None, str | None]:
    """归母净利润：优先 pit 财务，其次年报 financial_data。"""
    try:
        from ..datastore.db import get_annual_report, get_pit_financials
    except Exception:
        return None, None

    pit = get_pit_financials(stock_code)
    rows = (pit or {}).get("rows") or []
    if rows:
        latest = max(rows, key=lambda row: str(row.get("quarter") or row.get("year") or ""))
        net_profit = _safe_metric(latest.get("net_profit_parent_company"))
        if net_profit and net_profit > 0:
            label = str(latest.get("quarter") or latest.get("year") or "")
            return net_profit, f"pit:{label}" if label else "pit"

    annual = get_annual_report(stock_code)
    financial_data = (annual or {}).get("financial_data") or []
    best_year: int | None = None
    best_profit: float | None = None
    for entry in financial_data:
        if not isinstance(entry, dict):
            continue
        year_raw = entry.get("year") or entry.get("report_year")
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            continue
        fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else entry
        payload = fields.get("net_profit_parent_company") if isinstance(fields, dict) else None
        if isinstance(payload, dict):
            value = _safe_metric(payload.get("value"))
        else:
            value = _safe_metric(payload)
        if value and value > 0 and (best_year is None or year >= best_year):
            best_year = year
            best_profit = value
    if best_profit:
        return best_profit, f"annual:{best_year}" if best_year else "annual"
    return None, None


def _resolve_local_total_shares(
    stock_code: str,
    *,
    price: float | None,
    market_cap: float | None,
) -> float | None:
    try:
        from ..datastore.db import get_latest_snapshot, load_series

        snapshot = get_latest_snapshot(stock_code)
        if snapshot:
            series = load_series(int(snapshot["id"]), ["shares"], tail=1)
            share_rows = (series.get("shares") or {}).get("rows") or []
            if share_rows:
                row = share_rows[-1]
                for key in ("total", "total_shares", "total_a_shares", "shares"):
                    shares = _safe_metric(row.get(key))
                    if shares and shares > 0:
                        return shares
    except Exception:
        pass
    if market_cap and price and price > 0:
        return market_cap / price
    return None


def _resolve_local_equity(stock_code: str) -> float | None:
    try:
        from ..datastore.db import get_annual_report, get_pit_financials
    except Exception:
        return None

    pit = get_pit_financials(stock_code)
    rows = (pit or {}).get("rows") or []
    if rows:
        latest = max(rows, key=lambda row: str(row.get("quarter") or row.get("year") or ""))
        equity = _safe_metric(latest.get("equity_parent_company"))
        if equity and equity > 0:
            return equity

    annual = get_annual_report(stock_code)
    financial_data = (annual or {}).get("financial_data") or []
    best_year: int | None = None
    best_equity: float | None = None
    for entry in financial_data:
        if not isinstance(entry, dict):
            continue
        year_raw = entry.get("year") or entry.get("report_year")
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            continue
        fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else entry
        payload = fields.get("equity_parent_company") if isinstance(fields, dict) else None
        if isinstance(payload, dict):
            value = _safe_metric(payload.get("value"))
        else:
            value = _safe_metric(payload)
        if value and value > 0 and (best_year is None or year >= best_year):
            best_year = year
            best_equity = value
    return best_equity


def _derive_pe_from_primitives(
    stock_code: str,
    *,
    quote: dict[str, Any],
    technical: dict[str, Any] | None,
    factor: dict[str, Any],
) -> tuple[float | None, str | None]:
    """用最原始字段估算静态 PE：总市值/净利润 或 股价×股本/净利润。"""
    price = _resolve_local_price(stock_code, quote=quote, technical=technical, factor=factor)
    market_cap = _safe_metric(factor.get("market_cap"))
    net_profit, profit_src = _resolve_local_net_profit(stock_code)
    if not net_profit or net_profit <= 0:
        return None, None

    shares = _resolve_local_total_shares(stock_code, price=price, market_cap=market_cap)
    if (not market_cap or market_cap <= 0) and price and shares:
        market_cap = price * shares

    if market_cap and market_cap > 0:
        pe = round(market_cap / net_profit, 2)
        note = profit_src or "local"
        if shares and price:
            return pe, f"derived_cap_profit:{note}"
        return pe, f"derived_market_cap_profit:{note}"

    if price and shares and shares > 0:
        pe = round(price * shares / net_profit, 2)
        return pe, f"derived_price_shares_profit:{profit_src or 'local'}"

    return None, None


def _derive_pb_from_primitives(
    stock_code: str,
    *,
    quote: dict[str, Any],
    technical: dict[str, Any] | None,
    factor: dict[str, Any],
) -> float | None:
    market_cap = _safe_metric(factor.get("market_cap"))
    price = _resolve_local_price(stock_code, quote=quote, technical=technical, factor=factor)
    shares = _resolve_local_total_shares(stock_code, price=price, market_cap=market_cap)
    if (not market_cap or market_cap <= 0) and price and shares:
        market_cap = price * shares
    if not market_cap or market_cap <= 0:
        return None
    equity = _resolve_local_equity(stock_code)
    if not equity or equity <= 0:
        return None
    return round(market_cap / equity, 2)


def _apply_derived_valuation(
    factor: dict[str, Any],
    quote: dict[str, Any],
    stock_code: str,
    *,
    technical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """东方财富仍缺 PE/PB 时，用本地最原始字段推算（不依赖 PS/EPS 现成因子）。"""
    out = dict(factor)

    if out.get("pe_ratio_ttm") is None:
        pe, source = _derive_pe_from_primitives(
            stock_code,
            quote=quote,
            technical=technical,
            factor=out,
        )
        if pe is None:
            pe = _derive_pe_from_factor_fields(out)
            source = "derived_ps_parent_margin" if pe is not None else None
        if pe is not None and source:
            out["pe_ratio_ttm"] = pe
            out["pe_ratio_ttm_source"] = source.split(":", 1)[0]

    if out.get("pb_ratio_ttm") is None:
        pb = _derive_pb_from_primitives(stock_code, quote=quote, technical=technical, factor=out)
        if pb is not None:
            out["pb_ratio_ttm"] = pb
            out["pb_ratio_ttm_source"] = "derived_equity"

    return out


def _enrich_valuation_payload(payload: dict[str, Any], stock_code: str) -> dict[str, Any]:
    """factor 缺 PE/PB 时用东方财富 spot 兜底（不拉全量行情）。"""
    code = normalize_stock_code(stock_code)
    live = dict(payload or {})
    live["stock_code"] = code
    factor = dict(live.get("factor") or {})
    quote = dict(live.get("quote") or {})
    technical = live.get("technical") if isinstance(live.get("technical"), dict) else None
    factor = _apply_derived_financial_factors(factor, quote, code, technical=technical)
    needs_pe = factor.get("pe_ratio_ttm") is None and quote.get("pe_ttm") is None
    needs_pb = factor.get("pb_ratio_ttm") is None and quote.get("pb") is None
    if not needs_pe and not needs_pb:
        live["factor"] = factor
        if quote:
            live["quote"] = quote
        return live

    try:
        from .quote_sources import fetch_eastmoney_quote

        em = fetch_eastmoney_quote(code)
    except Exception:
        em = {}

    if needs_pe:
        pe = em.get("pe_ttm")
        if pe is not None:
            factor["pe_ratio_ttm"] = pe
            factor["pe_ratio_ttm_source"] = "eastmoney"
            quote.setdefault("pe_ttm", pe)
    if needs_pb:
        pb = em.get("pb")
        if pb is not None:
            factor["pb_ratio_ttm"] = pb
            factor["pb_ratio_ttm_source"] = "eastmoney"
            quote.setdefault("pb", pb)
    if em.get("name") and not live.get("sec_name"):
        live["sec_name"] = em.get("name")
    if em.get("date") and not live.get("end_date"):
        live["end_date"] = em.get("date")
        quote.setdefault("date", em.get("date"))
    if em.get("close") is not None and quote.get("close") is None:
        quote["close"] = em.get("close")
    if needs_pe and factor.get("pe_ratio_ttm") is None and em.get("error"):
        live["eastmoney_error"] = em.get("error")

    if needs_pe or needs_pb:
        factor = _apply_derived_financial_factors(factor, quote, code, technical=technical)
        factor = _apply_derived_valuation(
            factor,
            quote,
            code,
            technical=technical,
        )
        if needs_pe and factor.get("pe_ratio_ttm") is not None and quote.get("pe_ttm") is None:
            quote["pe_ttm"] = factor["pe_ratio_ttm"]

    if factor:
        live["factor"] = factor
    if quote:
        live["quote"] = quote
    if em and not em.get("error"):
        live.setdefault("source", live.get("source") or "eastmoney")
    return live


def fetch_valuation_snapshot(stock_code: str) -> dict[str, Any]:
    """估值类问题：优先本地快照 factor，缺 PE 时用东方财富兜底。"""
    code = normalize_stock_code(stock_code)
    local = _local_snapshot_fallback(code)
    if isinstance(local, dict) and local:
        payload = {**local, "stock_code": code, "valuation_only": True}
        payload.setdefault("source", "local_db")
        enriched = _enrich_valuation_payload(payload, code)
        factor = (enriched.get("factor") or {})
        if factor.get("pe_ratio_ttm") is not None or factor.get("pb_ratio_ttm") is not None:
            return enriched
    slim = fetch_market_snapshot(code, lookback_days=30, incremental=True)
    slim["valuation_only"] = True
    slim["stock_code"] = code
    return _enrich_valuation_payload(slim, code)


def fetch_market_snapshot(
    stock_code: str,
    *,
    as_of: str | None = None,
    lookback_days: int = 60,
    incremental: bool = True,
) -> dict[str, Any]:
    load_dotenv()
    from pathlib import Path

    code = normalize_stock_code(stock_code)
    order_book_id = to_order_book_id(code)
    as_of_date = default_as_of(as_of)
    market_context = _market_context(as_of_date)
    base: dict[str, Any] = {
        "stock_code": code,
        "order_book_id": order_book_id,
        "as_of": as_of_date.isoformat(),
        "market_context": market_context,
    }

    incremental_after: str | None = None
    if incremental:
        try:
            from ..datastore.db import get_latest_snapshot

            latest = get_latest_snapshot(code)
            if latest and latest.get("end_date"):
                incremental_after = str(latest["end_date"])
        except Exception:
            incremental_after = None

    try:
        from ..multiagent import data_executor_agent

        data = data_executor_agent(
            order_book_id=order_book_id,
            as_of=as_of_date,
            lookback_days=lookback_days,
            output_dir=Path("outputs"),
            incremental_after=incremental_after,
        )
    except Exception as exc:
        fallback = _local_snapshot_fallback(code)
        err_payload = {**base, "error": f"{type(exc).__name__}: {exc}", "source": "rqdata_error"}
        if fallback:
            err_payload.update(fallback)
            factor = _apply_derived_financial_factors(
                dict(err_payload.get("factor") or {}),
                dict(err_payload.get("quote") or {}),
                code,
                technical=err_payload.get("technical") if isinstance(err_payload.get("technical"), dict) else None,
            )
            err_payload["factor"] = _apply_derived_valuation(
                factor,
                dict(err_payload.get("quote") or {}),
                code,
                technical=err_payload.get("technical") if isinstance(err_payload.get("technical"), dict) else None,
            )
            err_payload["note"] = "米筐拉取失败，已回退本地数据库最近快照。"
        return err_payload

    price_rows = (data.get("price") or {}).get("rows") or []
    technical = data.get("technical") or {}
    end_date = str(data.get("end_date") or "")
    quote = _build_quote_summary(price_rows, technical, end_date)
    payload = {
        **base,
        "sec_name": data.get("sec_name"),
        "end_date": end_date,
        "source": "rqdata",
        "quote": quote,
        "technical": technical,
        "factor": data.get("factor"),
        "industry": data.get("industry"),
        "price_tail": price_rows[-5:],
        "margin_tail": (data.get("securities_margin") or {}).get("rows", [])[-5:],
        "pit_financials_tail": (data.get("pit_financials") or {}).get("rows", [])[-3:],
    }
    if not quote.get("close"):
        fallback = _local_snapshot_fallback(code)
        if fallback:
            payload.update({k: v for k, v in fallback.items() if k not in payload or not payload.get(k)})
            payload["note"] = "米筐未返回有效收盘价，已补充本地数据库快照。"
    payload["factor"] = _apply_derived_financial_factors(
        dict(payload.get("factor") or {}),
        dict(payload.get("quote") or {}),
        code,
        technical=payload.get("technical") if isinstance(payload.get("technical"), dict) else None,
    )
    return payload


def live_quote_available(live: dict[str, Any] | None) -> bool:
    if not live:
        return False
    quote = live.get("quote") or {}
    if quote.get("close") is not None:
        return True
    tech = live.get("technical") or {}
    return tech.get("latest_close") is not None


def _market_context(as_of_date: date) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "as_of": as_of_date.isoformat(),
        "weekday": as_of_date.weekday(),
        "is_weekend": as_of_date.weekday() >= 5,
    }
    last_trade = _guess_last_trading_date(as_of_date)
    ctx["last_trading_date_guess"] = last_trade.isoformat()
    notes: list[str] = []
    if ctx["is_weekend"]:
        notes.append(
            f"{as_of_date.isoformat()} 为周末，A 股无实时行情；"
            f"最近交易日收盘价见 quote（约 {last_trade.isoformat()}）。"
        )
    try:
        import rqdatac

        from ..multiagent import _init_rqdata

        _init_rqdata(rqdatac)
        if rqdatac.is_trading_date(as_of_date):
            notes.append(f"{as_of_date.isoformat()} 为交易日，quote 对应当日或最近可用收盘。")
        else:
            prev = rqdatac.get_previous_trading_date(as_of_date)
            ctx["last_trading_date"] = str(prev)
            notes.append(f"{as_of_date.isoformat()} 非交易日，行情截至 {prev}。")
    except Exception:
        if not ctx["is_weekend"]:
            notes.append("交易日历以米筐为准；周末请引用最近交易日收盘价。")
    ctx["notes"] = notes
    return ctx


def _guess_last_trading_date(as_of_date: date) -> date:
    cursor = as_of_date
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _build_quote_summary(
    price_rows: list[dict[str, Any]],
    technical: dict[str, Any],
    end_date: str,
) -> dict[str, Any]:
    last_row = price_rows[-1] if price_rows else {}
    prev_row = price_rows[-2] if len(price_rows) >= 2 else {}
    close = technical.get("latest_close")
    if close is None and last_row.get("close") is not None:
        close = last_row.get("close")
    trade_date = end_date or last_row.get("date")
    prev_close = prev_row.get("close")
    change_pct = None
    if close is not None and prev_close not in (None, 0):
        try:
            change_pct = round((float(close) / float(prev_close) - 1) * 100, 4)
        except (TypeError, ValueError):
            change_pct = None
    return {
        "date": trade_date,
        "close": close,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "open": last_row.get("open"),
        "high": last_row.get("high"),
        "low": last_row.get("low"),
        "volume": last_row.get("volume"),
    }


def _local_snapshot_fallback(stock_code: str) -> dict[str, Any] | None:
    try:
        from ..datastore.db import get_latest_snapshot, load_series
        from ..datastore.query import query_stored_data
    except Exception:
        return None

    stored = query_stored_data(stock_code, "股价 收盘 行情", tail=5)
    snapshot = get_latest_snapshot(stock_code)
    if not snapshot and not stored:
        return None

    technical = (stored or {}).get("technical") or (snapshot or {}).get("meta", {}).get("technical") or {}
    factor = (stored or {}).get("factor") or (snapshot or {}).get("meta", {}).get("factor") or {}
    price_rows: list[dict[str, Any]] = []
    if stored and stored.get("series"):
        price_rows = (stored["series"].get("price") or {}).get("rows") or []
    elif snapshot:
        series = load_series(int(snapshot["id"]), ["price"], tail=5)
        price_rows = (series.get("price") or {}).get("rows") or []

    end_date = str((snapshot or {}).get("end_date") or "")
    quote = _build_quote_summary(price_rows, technical, end_date)
    if not quote.get("close") and not technical:
        return None

    return {
        "source": "local_db",
        "end_date": end_date,
        "quote": quote,
        "technical": technical,
        "factor": factor,
        "price_tail": price_rows[-5:],
        "snapshot": {
            "id": (snapshot or {}).get("id"),
            "as_of": (snapshot or {}).get("as_of"),
            "end_date": end_date,
        },
    }
