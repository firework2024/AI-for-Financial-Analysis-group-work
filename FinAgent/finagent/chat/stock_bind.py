"""对话中识别股票代码/公司名称并决定是否触发入库。"""

from __future__ import annotations

import re
from typing import Any

from .data_ingest import chat_bootstrap_enabled
from .stock_codes import merge_session_stock_codes, normalize_stock_codes_list, parse_stock_codes_text, stocks_display_label
from .store import ChatSession

_INGEST_HINTS = (
    "入库",
    "拉取",
    "下载数据",
    "获取数据",
    "加载数据",
    "导入数据库",
    "预处理",
    "写入数据库",
    "更新数据",
)
_STOCK_CONTEXT_HINTS = (
    "分析",
    "看看",
    "了解下",
    "研究",
    "对比",
    "怎么样",
    "如何",
    "概况",
    "基本面",
)


def message_requests_data_ingest(text: str) -> bool:
    q = str(text or "")
    return any(h in q for h in _INGEST_HINTS)


def stock_data_missing(stock_code: str) -> bool:
    from ..datastore.db import get_annual_report, get_latest_snapshot

    code = str(stock_code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return True
    return get_latest_snapshot(code) is None and get_annual_report(code) is None


def _bootstrap_done_for_code(boot: dict[str, Any], code: str) -> bool:
    stocks = boot.get("stocks")
    if isinstance(stocks, dict) and code in stocks:
        return stocks[code].get("status") in {"completed", "skipped"}
    if boot.get("stock_code") == code and boot.get("status") == "completed":
        return True
    return False


def query_implies_financial_data(query: str, session: ChatSession | None = None) -> bool:
    from .intent import classify_query_intent

    return classify_query_intent(query, session).want_data_api


def should_run_chat_bootstrap(
    session: ChatSession,
    stock_codes: list[str] | str | None,
    query: str,
) -> bool:
    """识别到股票且本条像在问财务/估值时，自动后台入库（无需用户说「入库」或先填侧栏）。"""
    codes = normalize_stock_codes_list(
        stock_codes if isinstance(stock_codes, list) else None,
        single=stock_codes if isinstance(stock_codes, str) else None,
    )
    if not codes or not chat_bootstrap_enabled():
        return False

    boot = session.data_bootstrap if isinstance(session.data_bootstrap, dict) else {}
    if boot.get("status") == "running":
        return False

    pending = [c for c in codes if not _bootstrap_done_for_code(boot, c)]
    if not pending:
        return False

    if message_requests_data_ingest(query):
        return True
    if parse_stock_codes_text(query):
        return True
    if query_implies_financial_data(query, session):
        return True
    return False


def bind_stocks_from_chat(
    session: ChatSession,
    message: str,
    *,
    sidebar_code: str | None = None,
    sidebar_stocks: str | None = None,
) -> list[str]:
    """从本条消息、侧栏、会话历史与巨潮简称解析股票并写入 session（无需用户先填侧栏）。"""
    from .data_tools import resolve_stocks_for_chat, sec_name_for_code

    codes = resolve_stocks_for_chat(
        message,
        session,
        sidebar_code=sidebar_code,
        sidebar_stocks=sidebar_stocks,
    )
    if not codes:
        return list(session.stock_codes or [])
    previous = list(session.stock_codes or [])
    merged = merge_session_stock_codes(session, codes)
    if previous and set(previous) != set(merged):
        session.binding_warnings.append(
            f"会话股票已从 {stocks_display_label(previous)} 更新为 {stocks_display_label(merged)}"
        )
    if session.title in {"", "新对话"} and len(merged) == 1:
        name = sec_name_for_code(merged[0])
        session.title = f"{merged[0]} {name}".strip() if name else merged[0]
    elif session.title in {"", "新对话"} and len(merged) > 1:
        session.title = f"多股对比 {stocks_display_label(merged)}"
    return merged


def bind_stock_from_chat(
    session: ChatSession,
    message: str,
    *,
    sidebar_code: str | None = None,
    sidebar_stocks: str | None = None,
) -> str | None:
    codes = bind_stocks_from_chat(
        session, message, sidebar_code=sidebar_code, sidebar_stocks=sidebar_stocks
    )
    return codes[0] if codes else None
