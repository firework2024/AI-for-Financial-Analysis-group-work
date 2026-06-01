"""对话工具编排：本地数据库、实时行情、网页搜索。"""

from __future__ import annotations

from typing import Any

from .data_tools import extract_stock_code, fetch_market_snapshot, needs_live_data
from .store import ChatSession
from .web_search import (
    FOLLOWUP_HINTS,
    FINANCIAL_METRIC_HINTS,
    needs_web_search,
    search_web,
)


def gather_tool_context(query: str, session: ChatSession) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """按问题触发工具，返回 (tools_payload, tool_calls)。"""
    stock = session.stock_code or extract_stock_code(query)
    recent_user = _recent_user_messages(session)
    tool_calls: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "stock_code": stock,
        "data_api": None,
        "live_data": None,
        "web_search": None,
    }

    if stock:
        data_api = query_data_api(stock, query)
        if data_api:
            payload["data_api"] = data_api
            tool_calls.append(
                {
                    "tool": "data_api",
                    "stock_code": stock,
                    "ok": not data_api.get("error"),
                    "snapshot_id": (data_api.get("snapshot") or {}).get("id"),
                }
            )

    if stock and needs_live_data(query):
        live = fetch_market_snapshot(stock)
        payload["live_data"] = live
        tool_calls.append(
            {
                "tool": "fetch_market_snapshot",
                "stock_code": stock,
                "ok": "error" not in (live or {}),
            }
        )

    if _should_web_search(query, stock=stock, recent_user_messages=recent_user):
        web_query = _resolve_web_query(query, session, stock)
        web = search_web(web_query, stock_code=stock)
        payload["web_search"] = web
        tool_calls.append(
            {
                "tool": "web_search",
                "provider": web.get("provider"),
                "ok": bool(web.get("results")) and not web.get("error"),
                "result_count": len(web.get("results") or []),
            }
        )

    return payload, tool_calls


def query_data_api(stock_code: str, query: str) -> dict[str, Any] | None:
    try:
        from ..datastore import list_snapshots, query_stored_data

        stored = query_stored_data(stock_code, query, tail=25)
        snapshots = list_snapshots(stock_code, limit=5)
        if stored is None and not snapshots:
            return {
                "stock_code": stock_code,
                "snapshots": [],
                "stored": None,
                "hint": "本地数据库暂无该股票数据，可先运行多智能体/年报分析。",
            }
        return {
            "stock_code": stock_code,
            "snapshots": snapshots,
            "stored": stored,
        }
    except Exception as exc:
        return {"stock_code": stock_code, "error": f"{type(exc).__name__}: {exc}"}


def _should_web_search(
    query: str,
    *,
    stock: str | None,
    recent_user_messages: list[str],
) -> bool:
    if needs_web_search(query, recent_user_messages=recent_user_messages):
        return True
    q = str(query or "")
    if stock and any(h in q for h in FINANCIAL_METRIC_HINTS):
        return any(h in q for h in ("搜", "联网", "巨潮", "东方财富", "同花顺", "官网", "网上", "查一下"))
    return False


def _recent_user_messages(session: ChatSession) -> list[str]:
    return [message.content for message in session.messages if message.role == "user"][-6:]


def _resolve_web_query(query: str, session: ChatSession, stock_code: str | None) -> str:
    text = str(query or "").strip()
    if any(h in text for h in FOLLOWUP_HINTS) and len(text) <= 16:
        for message in reversed(session.messages):
            if message.role != "user" or message.content.strip() == text:
                continue
            prior = message.content.strip()
            if prior:
                return _web_query(prior, stock_code)
    return _web_query(text, stock_code)


def _web_query(query: str, stock_code: str | None) -> str:
    text = str(query or "").strip()
    if stock_code and stock_code not in text:
        return f"{stock_code} {text}"
    return text
