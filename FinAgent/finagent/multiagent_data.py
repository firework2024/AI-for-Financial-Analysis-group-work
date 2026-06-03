"""多智能体报告：米筐/东方财富数据采集与本地财务挂载。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .concurrency import env_flag, finagent_max_workers, parallel_map
from .multiagent_config import FACTOR_CANDIDATES, TOOL_REGISTRY
from .rqdata_client import _init_rqdata
from .peer_analysis import fetch_industry_comparison
from .report_writing import summarize_annual_financial_data
from .section_validation import CHART_QUALITY_REQUIREMENTS

def read_instrument_symbol(instrument: Any) -> str:
    if instrument is None:
        return ""
    if isinstance(instrument, pd.DataFrame):
        if instrument.empty:
            return ""
        instrument = instrument.iloc[0]
    symbol = getattr(instrument, "symbol", None)
    if symbol is None and hasattr(instrument, "get"):
        symbol = instrument.get("symbol")
    return str(symbol or "").strip()


def fetch_sec_name(rqdatac, order_book_id: str, stock_code: str) -> str:
    from .rqdata_quota import rqdata_quota_exhausted

    if rqdatac is not None and not rqdata_quota_exhausted():
        try:
            instrument = safe_rq_call("instruments", lambda: rqdatac.instruments(order_book_id))
        except Exception:
            instrument = None
    else:
        instrument = None
    try:
        if instrument is not None:
            symbol = read_instrument_symbol(instrument)
            if symbol and symbol != stock_code and not symbol.endswith((".XSHG", ".XSHE")):
                return symbol
    except Exception:
        pass
    try:
        from .datastore.db import get_annual_report

        annual = get_annual_report(stock_code)
        if annual and annual.get("sec_name"):
            return str(annual["sec_name"]).strip()
    except Exception:
        pass
    return ""


def data_executor_eastmoney_fallback(
    *,
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """米筐额度用尽时：东方财富日 K + 现货估值，构建与 data_executor 兼容的载荷。"""
    from .chat.quote_sources import fetch_eastmoney_kline_series, fetch_eastmoney_quote
    from .progress import info
    from .stock_utils import calendar_trading_as_of

    stock_code = order_book_id.split(".")[0]
    info(f"量价数据：米筐不可用，改由东方财富拉取 {stock_code} 日 K（约 {lookback_days} 日）")
    rows = fetch_eastmoney_kline_series(stock_code, limit=max(30, lookback_days))
    if not rows:
        raise RuntimeError("米筐额度已用尽，且东方财富 K 线未返回数据，请稍后重试或先完成对话入库。")

    em = fetch_eastmoney_quote(stock_code)
    sec_name = str(em.get("name") or "").strip() or fetch_sec_name(None, order_book_id, stock_code)
    end_date_str = str(rows[-1].get("date") or calendar_trading_as_of(as_of).isoformat())
    start_date_str = str(rows[0].get("date") or end_date_str)
    price_df = pd.DataFrame(rows)
    frames = {"price": flatten_frame(price_df)}
    factor: dict[str, Any] = {}
    if em.get("pe_ttm") is not None:
        factor["pe_ratio_ttm"] = em.get("pe_ttm")
        factor["pe_ratio_ttm_source"] = "eastmoney"
    if em.get("pb") is not None:
        factor["pb_ratio_ttm"] = em.get("pb")
        factor["pb_ratio_ttm_source"] = "eastmoney"
    if em.get("market_cap") is not None:
        factor["market_cap"] = em.get("market_cap")
        factor["market_cap_source"] = "eastmoney"

    payload = {
        "order_book_id": order_book_id,
        "stock_code": stock_code,
        "sec_name": sec_name,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "source": "eastmoney_fallback",
        "rqdata_quota_fallback": True,
        "data_notes": [
            "米筐 API 额度已用尽；量价序列改由东方财富日 K 获取。",
            "两融、资金流向、宏观利率等米筐专属序列本报告可能缺失。",
        ],
        "tool_registry": TOOL_REGISTRY,
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
        "price": frame_summary(frames["price"], tail=max(260, lookback_days)),
        "price_change_rate": {"rows": [], "row_count": 0, "columns": []},
        "turnover": {"rows": [], "row_count": 0, "columns": []},
        "capital_flow": {"rows": [], "row_count": 0, "net_buy_value_sum": None},
        "securities_margin": {"rows": [], "row_count": 0, "columns": []},
        "dividend": {"rows": [], "row_count": 0, "columns": []},
        "shares": {"rows": [], "row_count": 0, "columns": []},
        "suspended": {"rows": [], "row_count": 0, "columns": []},
        "st_stock": {"rows": [], "row_count": 0, "columns": []},
        "industry": {},
        "interbank_rate": {"rows": [], "row_count": 0, "columns": []},
        "yield_curve": {"rows": [], "row_count": 0, "columns": []},
        "factor": factor,
        "factor_history": {"rows": [], "row_count": 0, "columns": []},
        "industry_comparison": {
            "industry": {"source": "citics_2019", "selected_level": None},
            "peers": {
                "selected_level": None,
                "candidate_count": 0,
                "effective_count": 0,
                "order_book_ids": [],
                "sample_order_book_ids": [],
            },
            "metrics": {},
            "relative_signals": [],
            "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": "rqdata_quota"},
            "data_notes": ["行业对比依赖米筐，额度用尽时已跳过。"],
        },
        "technical": technical_summary(frames["price"]),
    }
    enrich_multi_factor_payload(payload, stock_code)
    from .datastore import persist_market_snapshot

    snapshot_id = persist_market_snapshot(payload, lookback_days=lookback_days, source="eastmoney_fallback")
    if snapshot_id is not None:
        payload["data_snapshot_id"] = snapshot_id
    attach_stored_fundamentals(
        payload,
        stock_code,
        workdir=workdir or output_dir.parent,
        use_cached_only=False,
        force_refresh=False,
    )
    enrich_multi_factor_payload(payload, stock_code)
    return payload


def data_executor_agent(
    *,
    order_book_id: str,
    as_of: date,
    lookback_days: int,
    output_dir: Path,
    incremental_after: str | None = None,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    import rqdatac

    from .datastore.market_cache import MarketCacheError, load_executor_payload_from_snapshot, snapshot_usable_for_executor
    from .datastore.snapshot_merge import incremental_fetch_start

    stock_code = order_book_id.split(".")[0]

    def _finalize_cached_payload(cached: dict[str, Any], *, offline: bool) -> dict[str, Any]:
        from .progress import info

        if offline:
            info("量价数据：使用本地已入库序列（离线模式，不访问外网）")
            for note in cached.get("local_cache_warnings") or []:
                info(f"  · {note}")
        else:
            info("量价数据：使用本地 SQLite 已入库数据（跳过米筐拉取）")
        cached["tool_registry"] = TOOL_REGISTRY
        cached["chart_quality_requirements"] = CHART_QUALITY_REQUIREMENTS
        ensure_technical_from_price_rows(cached)
        enrich_multi_factor_payload(cached, stock_code)
        attach_stored_fundamentals(
            cached,
            stock_code,
            workdir=workdir or output_dir.parent,
            use_cached_only=use_cached_only,
            force_refresh=force_refresh,
        )
        enrich_multi_factor_payload(cached, stock_code)
        return cached

    if use_cached_only:
        if force_refresh:
            raise MarketCacheError("不能同时勾选「仅用本地数据」和「强制刷新外网数据」。")
        cached = load_executor_payload_from_snapshot(
            stock_code,
            lookback_days=lookback_days,
            relaxed=True,
            as_of=as_of,
        )
        if not cached:
            raise MarketCacheError(
                "本地没有已保存的报告级量价数据。"
                "请先在对话中对标的完成入库，或取消「仅用本地数据」。"
            )
        return _finalize_cached_payload(cached, offline=True)

    if not force_refresh:
        try:
            from .datastore.db import get_latest_snapshot

            snapshot = get_latest_snapshot(stock_code)
            if snapshot_usable_for_executor(snapshot, as_of=as_of, lookback_days=lookback_days):
                cached = load_executor_payload_from_snapshot(
                    stock_code,
                    lookback_days=lookback_days,
                    relaxed=False,
                    as_of=as_of,
                )
                if cached:
                    return _finalize_cached_payload(cached, offline=False)
        except MarketCacheError:
            raise
        except Exception as exc:
            print(f"[market_cache] load skipped: {type(exc).__name__}: {exc}")

    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted

    if rqdata_quota_exhausted():
        return _finalize_cached_payload(
            data_executor_eastmoney_fallback(
                order_book_id=order_book_id,
                as_of=as_of,
                lookback_days=lookback_days,
                output_dir=output_dir,
                workdir=workdir,
            ),
            offline=False,
        )

    try:
        _init_rqdata(rqdatac)
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="data_executor.init")
            return _finalize_cached_payload(
                data_executor_eastmoney_fallback(
                    order_book_id=order_book_id,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    output_dir=output_dir,
                    workdir=workdir,
                ),
                offline=False,
            )
        raise

    sec_name = fetch_sec_name(rqdatac, order_book_id, stock_code)
    end_date = previous_trading_date(rqdatac, as_of)
    start_date = incremental_fetch_start(
        end_date,
        lookback_days=lookback_days,
        last_end_date=incremental_after,
    )
    fundamentals_start = end_date - timedelta(days=730)
    macro_start = end_date - timedelta(days=120)
    try:
        available_factors = set(rqdatac.get_all_factor_names())
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="get_all_factor_names")
            return _finalize_cached_payload(
                data_executor_eastmoney_fallback(
                    order_book_id=order_book_id,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    output_dir=output_dir,
                    workdir=workdir,
                ),
                offline=False,
            )
        available_factors = set()
    factors = list(dict.fromkeys(name for name in FACTOR_CANDIDATES if name in available_factors))

    rq_tasks: dict[str, Any] = {
        "price": lambda: rqdatac.get_price(
            order_book_id,
            start_date=start_date,
            end_date=end_date,
            frequency="1d",
            fields=["open", "high", "low", "close", "volume", "total_turnover"],
        ),
        "turnover": lambda: safe_rq_call(
            "get_turnover_rate",
            lambda: rqdatac.get_turnover_rate(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "capital": lambda: safe_rq_call(
            "get_capital_flow",
            lambda: rqdatac.get_capital_flow(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "price_change": lambda: safe_rq_call(
            "get_price_change_rate",
            lambda: rqdatac.get_price_change_rate(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "margin": lambda: safe_rq_call(
            "get_securities_margin",
            lambda: rqdatac.get_securities_margin(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "dividend": lambda: safe_rq_call(
            "get_dividend",
            lambda: rqdatac.get_dividend(order_book_id, start_date=fundamentals_start, end_date=end_date),
        ),
        "shares": lambda: safe_rq_call(
            "get_shares",
            lambda: rqdatac.get_shares(order_book_id, start_date=fundamentals_start, end_date=end_date),
        ),
        "suspended": lambda: safe_rq_call(
            "is_suspended",
            lambda: rqdatac.is_suspended(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "st_stock": lambda: safe_rq_call(
            "is_st_stock",
            lambda: rqdatac.is_st_stock(order_book_id, start_date=start_date, end_date=end_date),
        ),
        "industry": lambda: safe_rq_call(
            "get_instrument_industry",
            lambda: rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=1, date=end_date),
        ),
        "interbank_rate": lambda: safe_rq_call(
            "get_interbank_offered_rate",
            lambda: rqdatac.get_interbank_offered_rate(start_date=macro_start, end_date=end_date),
        ),
        "yield_curve": lambda: safe_rq_call(
            "get_yield_curve",
            lambda: rqdatac.get_yield_curve(start_date=macro_start, end_date=end_date),
        ),
    }
    if factors:
        rq_tasks["factor"] = lambda: rqdatac.get_factor(
            order_book_id, factors, start_date=end_date, end_date=end_date
        )
        rq_tasks["factor_history"] = lambda: rqdatac.get_factor(
            order_book_id, factors, start_date=start_date, end_date=end_date
        )

    rq_raw = parallel_map(
        rq_tasks,
        max_workers=finagent_max_workers(),
        parallel=env_flag("FINAGENT_RQDATA_PARALLEL", default=True),
    )

    def _rq_frame(key: str) -> pd.DataFrame:
        value = rq_raw.get(key)
        if isinstance(value, BaseException):
            print(f"[rqdatac] {key} skipped: {type(value).__name__}: {value}")
            return pd.DataFrame()
        if value is None:
            return pd.DataFrame()
        return value if isinstance(value, pd.DataFrame) else pd.DataFrame()

    price = _rq_frame("price")
    if (price.empty and rqdata_quota_exhausted()) or (
        isinstance(rq_raw.get("price"), BaseException) and is_rqdata_quota_error(rq_raw.get("price"))
    ):
        if isinstance(rq_raw.get("price"), BaseException):
            mark_rqdata_quota_exceeded(rq_raw.get("price"), where="price")
        return _finalize_cached_payload(
            data_executor_eastmoney_fallback(
                order_book_id=order_book_id,
                as_of=as_of,
                lookback_days=lookback_days,
                output_dir=output_dir,
                workdir=workdir,
            ),
            offline=False,
        )
    turnover = _rq_frame("turnover")
    capital = _rq_frame("capital")
    price_change = _rq_frame("price_change")
    margin = _rq_frame("margin")
    dividend = _rq_frame("dividend")
    shares = _rq_frame("shares")
    suspended = _rq_frame("suspended")
    st_stock = _rq_frame("st_stock")
    industry = _rq_frame("industry")
    interbank_rate = _rq_frame("interbank_rate")
    yield_curve = _rq_frame("yield_curve")
    factor = _rq_frame("factor")
    factor_history = _rq_frame("factor_history")
    try:
        industry_comparison = fetch_industry_comparison(
            rqdatac,
            order_book_id=order_book_id,
            as_of=end_date,
            available_factors=available_factors,
        )
    except Exception as exc:
        print(f"[peer_analysis] industry comparison skipped: {type(exc).__name__}: {exc}")
        industry_comparison = {
            "industry": {"source": "citics_2019", "selected_level": None},
            "peers": {"selected_level": None, "candidate_count": 0, "effective_count": 0, "order_book_ids": [], "sample_order_book_ids": []},
            "metrics": {},
            "relative_signals": [],
            "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": str(exc)},
            "data_notes": [f"行业对比数据获取失败：{type(exc).__name__}: {exc}"],
        }

    frames = {
        "price": flatten_frame(price),
        "price_change_rate": flatten_frame(price_change),
        "turnover": flatten_frame(turnover),
        "capital_flow": flatten_frame(capital),
        "securities_margin": flatten_frame(margin),
        "dividend": flatten_frame(dividend),
        "shares": flatten_frame(shares),
        "suspended": flatten_frame(suspended),
        "st_stock": flatten_frame(st_stock),
        "industry": flatten_frame(industry),
        "interbank_rate": flatten_frame(interbank_rate),
        "yield_curve": flatten_frame(yield_curve),
        "factor": flatten_frame(factor),
    }
    payload = {
        "order_book_id": order_book_id,
        "stock_code": stock_code,
        "sec_name": sec_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "tool_registry": TOOL_REGISTRY,
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
        "price": frame_summary(frames["price"], tail=max(260, lookback_days)),
        "price_change_rate": frame_summary(frames["price_change_rate"], tail=max(260, lookback_days)),
        "turnover": frame_summary(frames["turnover"], tail=max(260, lookback_days)),
        "capital_flow": capital_flow_summary(frames["capital_flow"]),
        "securities_margin": frame_summary(frames["securities_margin"], tail=max(260, lookback_days)),
        "dividend": frame_summary(frames["dividend"], tail=20),
        "shares": frame_summary(frames["shares"], tail=260),
        "suspended": frame_summary(frames["suspended"], tail=30),
        "st_stock": frame_summary(frames["st_stock"], tail=30),
        "industry": latest_row(frames["industry"]),
        "interbank_rate": frame_summary(frames["interbank_rate"], tail=120),
        "yield_curve": frame_summary(frames["yield_curve"], tail=120),
        "factor": latest_row(frames["factor"]),
        "factor_history": frame_summary(flatten_frame(factor_history), tail=max(260, lookback_days)),
        "industry_comparison": industry_comparison,
        "technical": technical_summary(frames["price"]),
    }
    enrich_multi_factor_payload(payload, stock_code)
    from .datastore import persist_market_snapshot

    snapshot_id = persist_market_snapshot(payload, lookback_days=lookback_days, source="data_executor")
    if snapshot_id is not None:
        payload["data_snapshot_id"] = snapshot_id
    attach_stored_fundamentals(
        payload,
        stock_code,
        workdir=workdir or output_dir.parent,
        use_cached_only=use_cached_only,
        force_refresh=force_refresh,
    )
    enrich_multi_factor_payload(payload, stock_code)
    return payload


def enrich_multi_factor_payload(payload: dict[str, Any], stock_code: str) -> None:
    """多智能体主路径复用对话侧教科书口径的本地估值补全。"""
    try:
        from .chat.data_tools import _apply_derived_financial_factors, _apply_derived_valuation
    except Exception as exc:
        print(f"[fundamentals] factor enrichment skipped: {type(exc).__name__}: {exc}")
        return

    factor = dict(payload.get("factor") or {})
    price_row = latest_series_row(payload.get("price"))
    shares_row = latest_series_row(payload.get("shares"))
    if factor.get("market_cap") is None:
        market_cap = market_cap_from_rows(price_row, shares_row)
        if market_cap is not None:
            factor["market_cap"] = round(market_cap, 2)
            factor["market_cap_source"] = "derived_price_shares"

    factor = _apply_derived_financial_factors(
        factor,
        price_row,
        stock_code,
        technical=payload.get("technical") if isinstance(payload.get("technical"), dict) else None,
    )
    factor = _apply_derived_valuation(
        factor,
        price_row,
        stock_code,
        technical=payload.get("technical") if isinstance(payload.get("technical"), dict) else None,
    )
    if factor:
        payload["factor"] = factor

    try:
        from .core_metrics import enrich_core_metrics

        enrich_core_metrics(payload)
    except Exception as exc:
        print(f"[core_metrics] enrichment skipped: {type(exc).__name__}: {exc}")

    history = payload.get("factor_history")
    rows = history.get("rows") if isinstance(history, dict) else None
    if isinstance(rows, list) and rows:
        latest = dict(rows[-1])
        latest.update({k: v for k, v in factor.items() if k not in latest or latest.get(k) is None})
        rows[-1] = latest
        columns = list(history.get("columns") or [])
        for key in latest:
            if key not in columns:
                columns.append(key)
        history["columns"] = columns


def latest_series_row(summary: Any) -> dict[str, Any]:
    rows = summary.get("rows") if isinstance(summary, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[-1]
    return dict(row) if isinstance(row, dict) else {}


def market_cap_from_rows(price_row: dict[str, Any], shares_row: dict[str, Any]) -> float | None:
    close = safe_number(price_row.get("close"))
    shares = None
    for key in ("total", "total_shares", "total_a", "shares"):
        shares = safe_number(shares_row.get(key))
        if shares and shares > 0:
            break
    if not close or close <= 0 or not shares or shares <= 0:
        return None
    return close * shares


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def attach_stored_fundamentals(
    payload: dict[str, Any],
    stock_code: str,
    *,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
) -> None:
    """挂载本地 SQLite 中的 PIT 财务与年报 MD&A，供经营质量章节深度分析。"""
    try:
        from .chat.data_ingest import AnnualCacheError, ensure_annual_report_in_store

        ensure_annual_report_in_store(
            stock_code,
            workdir=workdir,
            use_cached_only=use_cached_only,
            force_refresh=force_refresh,
        )
    except AnnualCacheError:
        raise
    except Exception as exc:
        print(f"[fundamentals] annual ensure skipped: {type(exc).__name__}: {exc}")

    annual = None
    try:
        from .datastore.db import get_annual_report, get_pit_financials, pit_cache_is_usable

        annual = get_annual_report(stock_code)
        pit = get_pit_financials(stock_code)
        if pit_cache_is_usable(pit):
            payload["pit_financials"] = {
                "rows": pit["rows"],
                "row_count": len(pit["rows"]),
                "report_year": pit.get("report_year"),
                "years": pit.get("years"),
            }
    except Exception as exc:
        print(f"[fundamentals] load cache skipped: {type(exc).__name__}: {exc}")

    if not payload.get("pit_financials"):
        if use_cached_only:
            # 仅用本地数据模式下，禁止触发任何外部财务拉取。
            pass
        else:
            try:
                from .stock_utils import default_as_of
                from .rqdata_client import fetch_financials

                report_year = int((annual or {}).get("report_year") or default_as_of(None).year)
                fetched = fetch_financials(stock_code, report_year, years=3)
                payload["pit_financials"] = {
                    "rows": fetched.rows,
                    "row_count": len(fetched.rows),
                    "report_year": report_year,
                    "years": 3,
                }
            except Exception as exc:
                print(f"[fundamentals] pit_financials fetch skipped: {type(exc).__name__}: {exc}")

    if use_cached_only and not payload.get("pit_financials") and annual:
        fin_rows = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
        if fin_rows:
            payload["pit_financials"] = {
                "rows": fin_rows,
                "row_count": len(fin_rows),
                "report_year": annual.get("report_year"),
                "years": len(fin_rows),
                "source": "annual_report_records",
            }

    if use_cached_only and not payload.get("pit_financials"):
        from .chat.data_ingest import AnnualCacheError

        raise AnnualCacheError(
            "本地没有已保存的财务序列或年报三表。"
            "请先在对话中完成入库，或取消「仅用本地数据」。"
        )

    if not annual:
        if use_cached_only:
            from .chat.data_ingest import AnnualCacheError

            raise AnnualCacheError(
                "本地没有已保存的年报数据。"
                "请先在对话中完成年报/PDF 入库，或取消「仅用本地数据」。"
            )
        return
    from .mda_analysis import build_annual_context_from_store

    # ── 加载年报上下文。multi-agent 路径不再额外生成基本面叙事成品文本。 ──
    try:
        ctx = build_annual_context_from_store(annual, with_narrative=False)
    except Exception as exc:
        print(f"[annual_analysis] context path failed ({type(exc).__name__}: {exc}), falling back to basic context")
        ctx = None
    if ctx:
        # 提取结构化财务分析，保持 annual_report_context 向后兼容。
        financial_analysis_raw = ctx.pop("_financial_analysis_raw", None)
        payload["annual_report_context"] = ctx

        # 注入多智能体专用的 annual_analysis 字段（独立于 pit_financials）
        annual_analysis: dict[str, Any] = {
            "report_year": ctx.get("report_year"),
            "sec_name": ctx.get("sec_name"),
            "financial_data": annual.get("financial_data") or [],
            "financial_analysis": financial_analysis_raw,
            "mda_full_text": annual.get("mda_text") or "",
        }
        if financial_analysis_raw:
            payload["annual_analysis"] = annual_analysis
        return

    # 降级路径：SQLite 有记录但 build_annual_context 返回空
    financial_data = annual.get("financial_data") if isinstance(annual.get("financial_data"), list) else []
    payload["annual_report_context"] = {
        "report_year": annual.get("report_year"),
        "sec_name": annual.get("sec_name"),
        "title": annual.get("title"),
        "mda_excerpt": str(annual.get("mda_text") or "")[:6000],
        "mda_meta": annual.get("mda_meta") or {},
        "financial_years": summarize_annual_financial_data(financial_data),
    }

def previous_trading_date(rqdatac: Any, value: date) -> date:
    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted
    from .stock_utils import calendar_trading_as_of

    if rqdatac is None or rqdata_quota_exhausted():
        return calendar_trading_as_of(value)
    try:
        if rqdatac.is_trading_date(value):
            return value
        return rqdatac.getprevious_trading_date(value)
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where="previous_trading_date")
        return calendar_trading_as_of(value)


def safe_rq_call(name: str, fn: Any) -> Any:
    from .rqdata_quota import is_rqdata_quota_error, mark_rqdata_quota_exceeded, rqdata_quota_exhausted

    if rqdata_quota_exhausted():
        return pd.DataFrame()
    try:
        return fn()
    except Exception as exc:
        if is_rqdata_quota_error(exc):
            mark_rqdata_quota_exceeded(exc, where=name)
            return pd.DataFrame()
        print(f"[rqdatac] {name} skipped: {type(exc).__name__}: {exc}")
        return pd.DataFrame()


def flatten_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.reset_index()
    rename = {"tradedate": "date", "trading_date": "date"}
    frame = frame.rename(columns=rename)
    for col in ("date", "datetime"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col]).dt.date.astype(str)
    return frame


def frame_summary(df: pd.DataFrame, *, tail: int) -> dict[str, Any]:
    return {"rows": records(df.tail(tail)), "row_count": int(len(df)), "columns": list(df.columns)}


def capital_flow_summary(df: pd.DataFrame) -> dict[str, Any]:
    rows = records(df)
    if df.empty:
        return {"rows": rows, "row_count": 0, "net_buy_value_sum": None}
    net = float((df["buy_value"] - df["sell_value"]).sum()) if {"buy_value", "sell_value"}.issubset(df.columns) else None
    return {"rows": rows, "row_count": int(len(df)), "net_buy_value_sum": net, "columns": list(df.columns)}


def latest_row(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    return records(df.tail(1))[0]


def technical_summary(df: pd.DataFrame) -> dict[str, Any]:
    from .price_technical import technical_summary_from_dataframe

    return technical_summary_from_dataframe(df)


def ensure_technical_from_price_rows(payload: dict[str, Any]) -> None:
    from .price_technical import ensure_technical_from_price_rows

    ensure_technical_from_price_rows(payload)


def _markdown_path(path: str, base_dir: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(base_dir.resolve())
    except Exception:
        rel = Path(path)
    return rel.as_posix()


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [json_ready(row) for row in df.to_dict(orient="records")]


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_ready(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value
