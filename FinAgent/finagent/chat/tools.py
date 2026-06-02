"""对话工具编排：按意图收集证据，供模型选用；库与接口用于验证而非硬性束缚。"""

from __future__ import annotations

from typing import Any

from ..datastore.query import extract_report_year, query_needs_stored_data
from ..env import project_root
from .data_ingest import ensure_stored_data, live_quote_has_data
from .data_tools import (
    fetch_market_snapshot,
    fetch_valuation_snapshot,
    live_quote_available,
    needs_live_data,
    resolve_stocks_for_chat,
)
from .intent import QueryIntent, classify_query_intent, is_fundamental_narrative_hit
from .metrics import extract_financial_facts, extract_valuation_facts, fields_for_metrics, is_valuation_focus, slim_factor_block
from .quote_sources import supplement_live_with_web_quote
from .stock_codes import merge_session_stock_codes
from .store import ChatSession
from .web_search import (
    DISCLOSURE_HINTS,
    FOLLOWUP_HINTS,
    FINANCIAL_METRIC_HINTS,
    QUOTE_HINTS,
    detect_search_intent,
    needs_web_search,
    search_web,
)


def gather_tool_context(query: str, session: ChatSession) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """收集与本问相关的工具证据；支持会话内多只股票。"""
    intent = classify_query_intent(query, session)
    stocks = resolve_stocks_for_chat(query, session)
    if stocks:
        merge_session_stock_codes(session, stocks)
    primary = stocks[0] if stocks else None
    recent_user = _recent_user_messages(session)
    tool_calls: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "stock_code": primary,
        "stock_codes": stocks,
        "intent": intent.to_dict(),
        "answer_guidance": intent.answer_guidance(),
        "data_ingest": None,
        "data_api": None,
        "live_data": None,
        "live_by_stock": {},
        "data_by_stock": {},
        "web_search": None,
        "evidence_summary": None,
    }

    if stocks:
        merge_session_stock_codes(session, stocks)

    ingest_actions: list[dict[str, Any]] = []
    valuation_only = is_valuation_focus(intent.focused_metrics)
    focused_factor_fields = set(fields_for_metrics(intent.focused_metrics or [])) & {
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "net_profit_parent_company_margin_ttm",
        "roe_ttm",
        "debt_to_asset_ratio",
        "current_ratio",
        "quick_ratio",
        "ps_ratio_ttm",
        "net_profit_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "operating_profit_growth_ratio_ttm",
        "gross_profit_growth_ratio_ttm",
        "operating_revenue_growth_ratio_ttm",
    }

    for code in stocks:
        stale_quote = False
        if intent.want_live_quote and not valuation_only:
            try:
                from ..datastore.market_cache import local_price_volume_available, market_is_current

                stale_quote = local_price_volume_available(code) and not market_is_current(code)
            except Exception:
                stale_quote = False
        should_ingest = (not valuation_only) and (
            intent.want_background_ingest
            or (intent.want_live_quote and query_needs_stored_data(query))
            or stale_quote
        )
        if not should_ingest:
            continue
        ingest_result = ensure_stored_data(code, query, workdir=project_root())
        if ingest_result:
            ingest_actions.append({"stock_code": code, **ingest_result})
            tool_calls.append(
                {
                    "tool": "ensure_stored_data",
                    "stock_code": code,
                    "ok": bool(ingest_result.get("ok")),
                    "gaps": ingest_result.get("requested_gaps"),
                }
            )
    if ingest_actions:
        payload["data_ingest"] = {"stocks": ingest_actions, "ok": any(i.get("ok") for i in ingest_actions)}

    for code in stocks:
        data_api = None
        if intent.want_data_api:
            data_api = query_data_api(code, query, intent=intent)
            if data_api:
                payload["data_by_stock"][code] = data_api
                tool_calls.append(
                    {
                        "tool": "data_api",
                        "stock_code": code,
                        "ok": not data_api.get("error"),
                        "scope": intent.data_scope,
                        "snapshot_id": (data_api.get("snapshot") or {}).get("id"),
                    }
                )
        if code == primary:
            payload["data_api"] = data_api

        wants_live = intent.valuation_focus or intent.want_live_quote or needs_live_data(query) or bool(focused_factor_fields)
        if wants_live:
            live: dict[str, Any] | None = None
            if ingest_actions:
                for item in ingest_actions:
                    if item.get("stock_code") != code:
                        continue
                    for action in item.get("actions") or []:
                        if action.get("live") and action.get("gap") in (
                            "quote_refresh",
                            "market_history",
                            "market_snapshot",
                        ):
                            live = action["live"]
                            break
            if valuation_only:
                live = fetch_valuation_snapshot(code)
            elif not live_quote_has_data(live):
                live = fetch_market_snapshot(code)
            if not valuation_only:
                live = supplement_live_with_web_quote(live, code, query)
            payload["live_by_stock"][code] = live
            tool_calls.append(
                {
                    "tool": "fetch_valuation_snapshot" if valuation_only else "fetch_market_snapshot",
                    "stock_code": code,
                    "ok": bool((live or {}).get("factor")) or live_quote_available(live),
                    "source": (live or {}).get("source"),
                }
            )
            if code == primary:
                payload["live_data"] = live

    if _should_web_search(
        query,
        intent=intent,
        stock=primary,
        recent_user_messages=recent_user,
        live_data=payload.get("live_data"),
    ):
        web_query = _resolve_web_query(query, session, primary)
        search_intent = detect_search_intent(web_query)
        max_results = 8 if (search_intent.disclosure or extract_report_year(web_query)) else 5
        web = search_web(web_query, stock_code=primary, max_results=max_results)
        payload["web_search"] = web
        tool_calls.append(
            {
                "tool": "web_search",
                "provider": web.get("provider"),
                "ok": bool(web.get("results")) and not web.get("error"),
                "result_count": len(web.get("results") or []),
            }
        )

    payload["evidence_summary"] = _build_evidence_summary(payload, intent)
    stocks = payload.get("stock_codes") or []
    if len(stocks) > 1:
        extra = (
            f"会话含 {len(stocks)} 只：{'、'.join(stocks)}；"
            f"若问题涉及「他们/这几家」，须逐只覆盖，也可按用户要求只讲其中几只。"
        )
        if intent.valuation_focus:
            extra = (
                f"会话含 {len(stocks)} 只：{'、'.join(stocks)}；"
                f"须逐只回答所问估值指标；缺失时可用 price/shares/pit 推导 PE 并注明口径；"
                f"禁止出现列表外的股票。"
            )
        payload["answer_guidance"] = f"{payload['answer_guidance']} {extra}"
    return payload, tool_calls


def query_data_api(stock_code: str, query: str, *, intent: QueryIntent | None = None) -> dict[str, Any] | None:
    try:
        from ..datastore import list_snapshots, query_stored_data

        scope = intent.data_scope if intent else "auto"
        stored = query_stored_data(stock_code, query, tail=25, scope=scope)
        snapshots = list_snapshots(stock_code, limit=5)
        if stored is None and not snapshots:
            return {
                "stock_code": stock_code,
                "snapshots": [],
                "stored": None,
                "scope": scope,
                "hint": "本地数据库暂无该股票数据，可先运行多智能体/年报分析。",
            }
        if stored is None:
            return {
                "stock_code": stock_code,
                "snapshots": snapshots,
                "stored": None,
                "scope": scope,
                "hint": "本地库有快照但与本问关联弱；请优先 tools.live_data 或其它证据。",
            }
        return {
            "stock_code": stock_code,
            "snapshots": snapshots,
            "stored": stored,
            "scope": scope,
        }
    except Exception as exc:
        return {"stock_code": stock_code, "error": f"{type(exc).__name__}: {exc}"}


def _build_evidence_summary(payload: dict[str, Any], intent: QueryIntent) -> dict[str, Any]:
    summary: dict[str, Any] = {"intent": intent.to_dict(), "stocks": payload.get("stock_codes") or []}
    quotes: dict[str, Any] = {}
    for code, live in (payload.get("live_by_stock") or {}).items():
        quote = (live or {}).get("quote") or {}
        if quote.get("close") is not None:
            quotes[code] = {
                "date": quote.get("date") or live.get("end_date"),
                "close": quote.get("close"),
                "change_pct": quote.get("change_pct"),
            }
    if quotes:
        summary["quotes"] = quotes
        summary["has_quote"] = True
    live = payload.get("live_data") or {}
    quote = live.get("quote") or {}
    if quote.get("close") is not None and not quotes:
        summary["has_quote"] = True
        summary["quote"] = {
            "date": quote.get("date") or live.get("end_date"),
            "close": quote.get("close"),
            "change_pct": quote.get("change_pct"),
            "source": live.get("source"),
        }
    labels = list(intent.focused_metrics or [])
    stored = ((payload.get("data_api") or {}).get("stored")) or {}
    if labels and is_valuation_focus(labels):
        val = extract_valuation_facts(payload.get("live_by_stock") or {}, labels)
        if val:
            summary["valuation_facts"] = val
    elif labels:
        facts = extract_financial_facts(stored, labels)
        if facts:
            summary["financial_facts"] = facts
    return summary


def _should_web_search(
    query: str,
    *,
    intent: QueryIntent,
    stock: str | None,
    recent_user_messages: list[str],
    live_data: dict[str, Any] | None = None,
) -> bool:
    if needs_web_search(query, recent_user_messages=recent_user_messages):
        return True
    q = str(query or "")
    if any(h in q for h in DISCLOSURE_HINTS):
        return True
    if extract_report_year(q):
        return True
    if stock and intent.quote_primary:
        if live_quote_available(live_data):
            return False
        return True
    if stock and any(h in q for h in QUOTE_HINTS):
        from .web_search import _explicit_web_quote_request

        if live_quote_available(live_data):
            return False
        if _explicit_web_quote_request(q):
            return True
        return False
    if stock and any(h in q for h in FINANCIAL_METRIC_HINTS):
        return any(h in q for h in ("搜", "联网", "巨潮", "东方财富", "同花顺", "官网", "网上", "查", "去查"))
    return False


def _recent_user_messages(session: ChatSession) -> list[str]:
    return [message.content for message in session.messages if message.role == "user"][-6:]


def _resolve_web_query(query: str, session: ChatSession, stock_code: str | None) -> str:
    text = str(query or "").strip()
    recent = [message.content for message in session.messages if message.role == "user"][-4:]
    context = " ".join([text, *recent[-3:]])
    if any(h in text for h in FOLLOWUP_HINTS) and len(text) <= 20:
        for message in reversed(session.messages):
            if message.role not in {"user", "assistant"} or message.content.strip() == text:
                continue
            prior = message.content.strip()
            if prior:
                context = f"{prior} {text}"
                text = prior
                break
    enriched = _web_query(text, stock_code)
    year = extract_report_year(context)
    if stock_code:
        try:
            from ..datastore.db import get_annual_report

            record = get_annual_report(stock_code, report_year=year) if year else get_annual_report(stock_code)
            sec_name = str((record or {}).get("sec_name") or "").strip()
            if sec_name and sec_name not in enriched:
                enriched = f"{stock_code} {sec_name} {enriched}"
        except Exception:
            pass
    if year and str(year) not in enriched:
        enriched = f"{stock_code or ''} {year}年 {enriched}".strip()
    if any(h in context for h in DISCLOSURE_HINTS) and "site:" not in enriched:
        enriched = f"{enriched} 年度报告 营业收入 净利润"
    return enriched.strip()


def _web_query(query: str, stock_code: str | None) -> str:
    text = str(query or "").strip()
    if stock_code and stock_code not in text:
        return f"{stock_code} {text}"
    return text
