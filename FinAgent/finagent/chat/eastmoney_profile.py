"""东方财富深度档案：行情扩展、盘口、资金、F10 摘要、公告、行业对比。"""

from __future__ import annotations

import time
from typing import Any

import requests

from ..cninfo import classify_stock, normalize_stock_code
from .quote_sources import (
    _float,
    _parse_em_trade_date,
    eastmoney_quote_page_url,
    eastmoney_secid,
    fetch_eastmoney_quote,
)

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
_HSF10_HEADERS = {
    **_EM_HEADERS,
    "Referer": "https://emweb.securities.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

_SPOT_EXT = (
    "f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f84,f85,"
    "f116,f117,f152,f153,f161,f162,f167,f168,f169,f170,f171,f177,f178,"
    "f19,f20,f260,f261,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40"
)


def fetch_eastmoney_profile(stock_code: str, *, query: str = "") -> dict[str, Any]:
    """聚合东方财富多接口数据，供对话引用（分段拉取，单段失败不影响其它）。"""
    code = normalize_stock_code(stock_code)
    secid = eastmoney_secid(code)
    _, column, _ = classify_stock(code)
    em_code = f"{'SH' if column == 'sh' else 'SZ'}{code}"

    profile: dict[str, Any] = {
        "stock_code": code,
        "secid": secid,
        "page_url": eastmoney_quote_page_url(code),
    }

    quote = fetch_eastmoney_quote(code)
    if quote.get("close") is not None:
        profile["quote"] = quote

    spot = _safe_call("spot_ext", lambda: _fetch_spot_extended(secid))
    if spot:
        profile["quote_extended"] = spot
        profile.setdefault("quote", {}).update(
            {k: spot[k] for k in ("close", "date", "name", "code") if spot.get(k) is not None}
        )
    if spot and spot.get("order_book"):
        profile["order_book"] = spot["order_book"]
    if spot and spot.get("chinext"):
        profile["chinext"] = spot["chinext"]

    flow = _safe_call("capital_flow", lambda: _fetch_capital_flow(secid))
    if flow:
        profile["capital_flow"] = flow

    survey = _safe_call("company_survey", lambda: _fetch_company_survey(em_code))
    if survey:
        profile["company"] = survey.get("company")
        profile["listing"] = survey.get("listing")

    holders = _safe_call("holders", lambda: _fetch_holder_trend(em_code))
    if holders:
        profile["shareholders"] = holders

    notices = _safe_call("notices", lambda: _fetch_notices(code))
    if notices:
        profile["announcements"] = notices

    industry = _safe_call("industry", lambda: _fetch_industry_row(code))
    if industry:
        profile["industry"] = industry

    f10 = _safe_call("f10_main", lambda: _fetch_f10_main_targets(em_code))
    if not f10:
        f10 = _safe_call("f10_dc", lambda: _fetch_f10_datacenter(code))
    if f10:
        profile["f10_core"] = f10

    profile["summary_text"] = format_profile_text(profile)
    return profile


def attach_profile_to_live(live: dict[str, Any], stock_code: str, query: str = "") -> dict[str, Any]:
    payload = dict(live or {})
    try:
        profile = fetch_eastmoney_profile(stock_code, query=query)
        payload["eastmoney_profile"] = profile
        if profile.get("quote") and not (payload.get("quote") or {}).get("close"):
            payload["quote"] = profile["quote"]
        if profile.get("summary_text"):
            payload["profile_summary"] = profile["summary_text"]
    except Exception as exc:
        payload["eastmoney_profile_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def format_profile_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    q = profile.get("quote") or profile.get("quote_extended") or {}
    if q.get("close") is not None:
        parts.append(
            f"行情：{q.get('date') or ''} 当日收盘价 {q.get('close')} 元，涨跌 {q.get('change')} ({q.get('change_pct')}%)"
        )
    if q.get("prev_close") is not None:
        parts.append(f"昨收(前一日收盘，非当日收盘) {q.get('prev_close')} 元")
    ext = profile.get("quote_extended") or {}
    for label, key in (
        ("量比", "volume_ratio"),
        ("涨停", "limit_up"),
        ("跌停", "limit_down"),
        ("均价", "avg_price"),
        ("振幅", "amplitude"),
        ("外盘", "outer_volume"),
        ("内盘", "inner_volume"),
        ("委比", "bid_ask_ratio"),
        ("委差", "bid_ask_spread"),
    ):
        if ext.get(key) is not None:
            parts.append(f"{label} {ext[key]}")

    book = profile.get("order_book") or {}
    if book.get("asks") or book.get("bids"):
        parts.append(f"盘口：买一 {book.get('best_bid')} / 卖一 {book.get('best_ask')}")

    cy = profile.get("chinext") or {}
    if cy:
        parts.append(
            "创业板指标："
            + "，".join(f"{k}={v}" for k, v in cy.items() if v is not None)
        )

    cf = profile.get("capital_flow") or {}
    if cf.get("date"):
        parts.append(
            f"资金流向({cf['date']})：主力净额 {cf.get('main_net')}，超大单 {cf.get('super_large_net')}，大单 {cf.get('large_net')}"
        )

    comp = profile.get("company") or {}
    if comp.get("name"):
        parts.append(f"公司：{comp.get('name')}（{comp.get('industry_em') or comp.get('industry_csrc')}）")

    f10 = profile.get("f10_core") or {}
    if f10 and "error" not in f10:
        parts.append(
            "F10核心："
            + "，".join(
                f"{k}={v}"
                for k, v in f10.items()
                if v is not None and k not in {"report_date"}
            )[:400]
        )

    ind = profile.get("industry") or {}
    if ind.get("industry_name"):
        parts.append(
            f"行业({ind['industry_name']})：总市值 {ind.get('market_cap')}，行业PE {ind.get('pe_ratio')}，ROE {ind.get('roe')}"
        )

    sh = profile.get("shareholders") or []
    if sh:
        row = sh[0]
        parts.append(
            f"股东户数 {row.get('end_date')}: {row.get('holder_count')} 户，较上期 {row.get('change_pct')}%"
        )

    for item in (profile.get("announcements") or [])[:3]:
        parts.append(f"公告 {item.get('date')}: {item.get('title')}")

    return "；".join(parts)[:2000]


def _safe_call(name: str, fn: Any) -> Any:
    try:
        result = fn()
        if isinstance(result, dict) and result.get("error"):
            return None
        return result
    except Exception:
        return None


def _get_json(url: str, params: dict[str, Any], *, headers: dict[str, str] | None = None) -> Any:
    last_exc: Exception | None = None
    for attempt in range(3):
        time.sleep(0.4 + attempt * 0.5)
        try:
            resp = requests.get(url, params=params, headers=headers or _EM_HEADERS, timeout=14)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
    raise last_exc or RuntimeError("request_failed")


def _fetch_spot_extended(secid: str) -> dict[str, Any]:
    payload = _get_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {
            "secid": secid,
            "fields": _SPOT_EXT,
            "ut": "fa5fd1943c7b386f172d7ef921b690b2",
            "invt": "2",
            "fltt": "2",
        },
    )
    data = (payload or {}).get("data") or {}
    if not data:
        return {}

    close = _float(data.get("f43"))
    prev = _float(data.get("f60"))
    result: dict[str, Any] = {
        "code": str(data.get("f57") or ""),
        "name": str(data.get("f58") or "").strip(),
        "date": _parse_em_trade_date(data.get("f86")),
        "close": close,
        "prev_close": prev,
        "open": _float(data.get("f46")),
        "high": _float(data.get("f44")),
        "low": _float(data.get("f45")),
        "change": _float(data.get("f169")),
        "change_pct": _float(data.get("f170")),
        "volume": data.get("f47"),
        "amount": data.get("f48"),
        "volume_ratio": _float(data.get("f50")),
        "limit_up": _float(data.get("f51")),
        "limit_down": _float(data.get("f52")),
        "turnover_rate": _float(data.get("f168")),
        "pe_ttm": _float(data.get("f162")),
        "pb": _float(data.get("f167")),
        "market_cap": data.get("f116"),
        "float_market_cap": data.get("f117"),
        "amplitude": _float(data.get("f171")),
        "outer_volume": data.get("f177"),
        "inner_volume": data.get("f178"),
        "bid_ask_ratio": _float(data.get("f19")),
        "bid_ask_spread": data.get("f20"),
        "total_shares": data.get("f84"),
        "float_shares": data.get("f85"),
        "order_book": _parse_order_book(data),
        "chinext": _parse_chinext_flags(data),
    }
    if result.get("close") and result.get("amount") and result.get("volume"):
        try:
            vol = float(result["volume"])
            if vol > 0:
                result["avg_price"] = round(float(result["amount"]) / vol, 2)
        except (TypeError, ValueError):
            pass
    return result


def _parse_order_book(data: dict[str, Any]) -> dict[str, Any]:
    """解析买卖五档：买一 f31/f32，卖一 f39/f40，依次类推。"""
    specs = [
        ("买五", "f39", "f40"),
        ("买四", "f37", "f38"),
        ("买三", "f35", "f36"),
        ("买二", "f33", "f34"),
        ("买一", "f31", "f32"),
        ("卖一", "f39", "f40"),
        ("卖二", "f37", "f38"),
        ("卖三", "f35", "f36"),
        ("卖四", "f33", "f34"),
        ("卖五", "f31", "f32"),
    ]
    # 买盘 f31–f40 偶数为价、奇数为量；卖盘在高字段区，分开定义
    bid_specs = [
        ("买五", "f39", "f40"),
        ("买四", "f37", "f38"),
        ("买三", "f35", "f36"),
        ("买二", "f33", "f34"),
        ("买一", "f31", "f32"),
    ]
    ask_specs = [
        ("卖一", "f32", "f31"),
        ("卖二", "f34", "f33"),
        ("卖三", "f36", "f35"),
        ("卖四", "f38", "f37"),
        ("卖五", "f40", "f39"),
    ]
    bids = [_level(label, data, pk, vk) for label, pk, vk in bid_specs]
    bids = [row for row in bids if row]
    asks = [_level(label, data, pk, vk) for label, pk, vk in ask_specs]
    asks = [row for row in asks if row]
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": bids[-1]["price"] if bids else None,
        "best_ask": asks[0]["price"] if asks else None,
    }


def _level(label: str, data: dict[str, Any], price_key: str, vol_key: str) -> dict[str, Any] | None:
    price = _float(data.get(price_key))
    if price is None:
        return None
    return {"label": label, "price": price, "volume": data.get(vol_key)}


def _parse_chinext_flags(data: dict[str, Any]) -> dict[str, Any]:
    after_vol = data.get("f260")
    after_amt = data.get("f261")
    cy: dict[str, Any] = {}
    if after_vol not in (None, "", "-"):
        cy["after_hours_volume"] = after_vol
    if after_amt not in (None, "", "-"):
        cy["after_hours_amount"] = after_amt
    for key, label in (
        ("f262", "is_register"),
        ("f263", "vie_structure"),
        ("f264", "voting_rights_diff"),
        ("f265", "is_profitable"),
    ):
        val = data.get(key)
        if val not in (None, "", "-"):
            cy[label] = _yn(val)
    return cy


def _yn(value: Any) -> str | None:
    if value in (None, "", "-"):
        return None
    try:
        num = int(float(value))
        return "是" if num == 1 else "否"
    except (TypeError, ValueError):
        text = str(value)
        return text if text in {"是", "否"} else text


def _fetch_capital_flow(secid: str) -> dict[str, Any] | None:
    payload = _get_json(
        "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get",
        {
            "secid": secid,
            "lmt": 1,
            "klt": 101,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        },
    )
    klines = ((payload or {}).get("data") or {}).get("klines") or []
    if not klines:
        return None
    parts = str(klines[-1]).split(",")
    if len(parts) < 6:
        return None
    return {
        "date": parts[0],
        "main_net": _float(parts[1]),
        "small_net": _float(parts[2]),
        "medium_net": _float(parts[3]),
        "large_net": _float(parts[4]),
        "super_large_net": _float(parts[5]),
        "main_net_pct": _float(parts[6]) if len(parts) > 6 else None,
    }


def _fetch_company_survey(em_code: str) -> dict[str, Any]:
    payload = _get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
        {"code": em_code},
        headers=_HSF10_HEADERS,
    )
    jbzl = (payload.get("jbzl") or [{}])[0] if isinstance(payload, dict) else {}
    fxxg = (payload.get("fxxg") or [{}])[0] if isinstance(payload, dict) else {}
    company = {
        "name": jbzl.get("ORG_NAME") or jbzl.get("SECURITY_NAME_ABBR"),
        "industry_em": jbzl.get("EM2016"),
        "industry_csrc": jbzl.get("INDUSTRYCSRC1"),
        "chairman": jbzl.get("CHAIRMAN"),
        "website": jbzl.get("ORG_WEB"),
        "address": jbzl.get("ADDRESS"),
        "employees": jbzl.get("EMP_NUM"),
        "reg_capital": jbzl.get("REG_CAPITAL"),
        "profile": (jbzl.get("ORG_PROFILE") or "")[:500],
    }
    listing = {
        "listing_date": fxxg.get("LISTING_DATE") or jbzl.get("LISTING_DATE"),
        "issue_price": fxxg.get("ISSUE_PRICE"),
        "found_date": fxxg.get("FOUND_DATE"),
    }
    return {"company": company, "listing": listing}


def _fetch_holder_trend(em_code: str) -> list[dict[str, Any]]:
    payload = _get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax",
        {"code": em_code},
        headers=_HSF10_HEADERS,
    )
    rows = []
    for item in (payload.get("gdrs") or [])[:4]:
        rows.append(
            {
                "end_date": str(item.get("END_DATE") or "")[:10],
                "holder_count": item.get("HOLDER_TOTAL_NUM"),
                "change_pct": item.get("TOTAL_NUM_RATIO"),
                "avg_hold_amt": item.get("AVG_HOLD_AMT"),
            }
        )
    return rows


def _fetch_notices(stock_code: str) -> list[dict[str, Any]]:
    payload = _get_json(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        {
            "page_size": 6,
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": stock_code,
        },
    )
    items = []
    for row in ((payload.get("data") or {}).get("list") or [])[:6]:
        items.append(
            {
                "date": str(row.get("notice_date") or "")[:10],
                "title": row.get("title_ch") or row.get("title"),
                "category": ((row.get("columns") or [{}])[0] or {}).get("column_name"),
            }
        )
    return items


def _fetch_industry_row(stock_code: str) -> dict[str, Any] | None:
    payload = _get_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        {
            "reportName": "RPT_STOCK_INDUSTRY_STA",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{stock_code}")',
            "pageNumber": 1,
            "pageSize": 1,
            "source": "WEB",
            "client": "WEB",
        },
    )
    rows = ((payload.get("result") or {}).get("data") or [])
    if not rows:
        return None
    row = rows[0]
    return {
        "industry_name": row.get("INDUSTRY_NAME"),
        "stock_count": row.get("STOCK_NUM"),
        "market_cap": row.get("TOTAL_MARKET_CAP"),
        "pe_ratio": row.get("PE_RATIO"),
        "pb_ratio": row.get("PB_RATIO"),
        "roe": row.get("ROE_WEIGHT"),
        "rank_market_cap": row.get("TMC_RANK"),
        "trade_date": str(row.get("TRADE_DATE") or "")[:10],
    }


def _fetch_f10_datacenter(stock_code: str) -> dict[str, Any] | None:
    payload = _get_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        {
            "reportName": "RPT_F10_INDICATOR",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{stock_code}")',
            "pageNumber": 1,
            "pageSize": 1,
            "sortColumns": "REPORT_DATE",
            "sortTypes": -1,
            "source": "WEB",
            "client": "WEB",
        },
    )
    if not (payload or {}).get("success"):
        return None
    rows = ((payload.get("result") or {}).get("data") or [])
    if not rows:
        return None
    row = rows[0]
    return {
        "report_date": row.get("REPORT_DATE"),
        "revenue": row.get("TOTAL_OPERATE_INCOME") or row.get("OPERATE_INCOME"),
        "net_profit": row.get("NETPROFIT") or row.get("PARENT_NETPROFIT"),
        "roe": row.get("ROEJQ") or row.get("ROE"),
        "gross_margin": row.get("GROSS_PROFIT_RATIO") or row.get("GROSS_MARGIN"),
        "net_margin": row.get("NETPROFIT_RATIO"),
        "debt_ratio": row.get("ASSET_LIAB_RATIO"),
        "bps": row.get("BPS"),
        "net_assets": row.get("TOTAL_ASSETS") or row.get("NET_ASSETS"),
    }


def _fetch_f10_main_targets(em_code: str) -> dict[str, Any] | None:
    payload = _get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/MainTargetAjax",
        {"code": em_code},
        headers=_HSF10_HEADERS,
    )
    if not isinstance(payload, dict) or not payload:
        return None
    # 接口返回多期主要指标，取最近一期
    for key in ("zyzb", "gjjzb", "mgzb", "yysr", "jlrun"):
        block = payload.get(key)
        if isinstance(block, list) and block:
            row = block[0]
            return {
                "report_date": row.get("REPORT_DATE") or row.get("REPORTDATE"),
                "revenue": row.get("TOTALOPERATEREVE") or row.get("TOTAL_OPERATE_INCOME"),
                "net_profit": row.get("PARENTNETPROFIT") or row.get("NETPROFIT"),
                "eps": row.get("BASIC_EPS") or row.get("EPS"),
                "roe": row.get("ROEJQ") or row.get("ROE"),
                "gross_margin": row.get("XSMLL") or row.get("GROSS_PROFIT_RATIO"),
                "net_margin": row.get("XSJLL") or row.get("NETPROFIT_RATIO"),
                "debt_ratio": row.get("ZCFZL") or row.get("ASSET_LIAB_RATIO"),
                "bps": row.get("BPS"),
            }
    return None
