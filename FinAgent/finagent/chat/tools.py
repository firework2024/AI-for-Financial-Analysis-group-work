"""对话工具编排：按意图收集证据，供模型选用；库与接口用于验证而非硬性束缚。"""

from __future__ import annotations

from typing import Any

from ..datastore.query import extract_report_year, query_needs_stored_data
from ..env import project_root
from .data_ingest import ensure_stored_data, live_quote_has_data
from .data_tools import (
    fetch_market_snapshot,
    live_quote_available,
    needs_live_data,
    resolve_stock_code,
)
from .intent import QueryIntent, classify_query_intent, is_fundamental_narrative_hit
from .quote_sources import supplement_live_with_web_quote
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
    """收集与本问相关的工具证据；具体用哪条由模型结合 intent 与 question 判断。"""
    intent = classify_query_intent(query, session)
    stock = resolve_stock_code(query, session)
    recent_user = _recent_user_messages(session)
    tool_calls: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "stock_code": stock,
        "intent": intent.to_dict(),
        "answer_guidance": intent.answer_guidance(),
        "data_ingest": None,
        "data_api": None,
        "live_data": None,
        "web_search": None,
        "evidence_summary": None,
    }

    if stock and not session.stock_code:
        session.stock_code = stock

    ingest_result: dict[str, Any] | None = None
    should_ingest = stock and (
        intent.want_background_ingest
        or (intent.want_live_quote and query_needs_stored_data(query))
    )
    if should_ingest:
        ingest_result = ensure_stored_data(stock, query, workdir=project_root())
        if ingest_result:
            payload["data_ingest"] = ingest_result
            tool_calls.append(
                {
                    "tool": "ensure_stored_data",
                    "stock_code": stock,
                    "ok": bool(ingest_result.get("ok")),
                    "gaps": ingest_result.get("requested_gaps"),
                }
            )

    if stock and intent.want_data_api:
        data_api = query_data_api(stock, query, intent=intent)
        if data_api:
            payload["data_api"] = data_api
            tool_calls.append(
                {
                    "tool": "data_api",
                    "stock_code": stock,
                    "ok": not data_api.get("error"),
                    "scope": intent.data_scope,
                    "snapshot_id": (data_api.get("snapshot") or {}).get("id"),
                }
            )

    if stock and (intent.want_live_quote or needs_live_data(query)):
        live: dict[str, Any] | None = None
        if ingest_result:
            for action in ingest_result.get("actions") or []:
                if action.get("gap") == "market_snapshot" and action.get("live"):
                    live = action["live"]
                    break
        if not live_quote_has_data(live):
            live = fetch_market_snapshot(stock)
        live = supplement_live_with_web_quote(live, stock, query)
        payload["live_data"] = live
        tool_calls.append(
            {
                "tool": "fetch_market_snapshot",
                "stock_code": stock,
                "ok": live_quote_available(live),
                "source": (live or {}).get("source"),
            }
        )

    if _should_web_search(
        query,
        intent=intent,
        stock=stock,
        recent_user_messages=recent_user,
        live_data=payload.get("live_data"),
    ):
        web_query = _resolve_web_query(query, session, stock)
        search_intent = detect_search_intent(web_query)
        max_results = 8 if (search_intent.disclosure or extract_report_year(web_query)) else 5
        web = search_web(web_query, stock_code=stock, max_results=max_results)
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
    return payload, tool_calls


def query_data_api(stock_code: str, query: str, *, intent: QueryIntent | None = None) -> dict[str, Any] | None:
    try:
        from ..datastore import list_snapshots, query_stored_data

        scope = (intent.data_scope if intent else "auto")
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
    live = payload.get("live_data") or {}
    quote = live.get("quote") or {}
    summary: dict[str, Any] = {
        "intent": intent.to_dict(),
        "has_quote": quote.get("close") is not None,
    }
    if quote.get("close") is not None:
        summary["quote"] = {
            "date": quote.get("date") or live.get("end_date"),
            "close": quote.get("close"),
            "change_pct": quote.get("change_pct"),
            "source": live.get("source"),
        }
    stored = (payload.get("data_api") or {}).get("stored") or {}
    if stored.get("series"):
        summary["local_series"] = list(stored.get("matched_keys") or [])
    if stored.get("annual_report") and not intent.quote_primary:
        ar = stored["annual_report"]
        summary["annual"] = {"report_year": ar.get("report_year"), "sec_name": ar.get("sec_name")}
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
            if message.role != "user" or message.content.strip() == text:
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
