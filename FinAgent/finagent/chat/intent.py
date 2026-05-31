"""对话问题意图：供工具编排与 LLM 参考，不做硬性截断回答。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ..datastore.query import extract_report_year, _mentions_annual, _mentions_financials, _select_data_keys
from .metrics import is_valuation_focus, narrow_answer_requested, resolve_focused_metrics

if False:  # TYPE_CHECKING
    from .store import ChatSession

_QUOTE_HINTS = (
    "股价",
    "收盘",
    "开盘价",
    "开盘",
    "现价",
    "行情",
    "k线",
    "涨跌",
    "涨幅",
    "跌停",
    "涨停",
    "市值",
    "换手率",
    "量价",
    "多少钱",
    "什么价",
)
_FUNDAMENTAL_HINTS = (
    "营收",
    "收入",
    "利润",
    "净利",
    "净利润",
    "毛利率",
    "净利率",
    "roe",
    "负债",
    "资产",
    "现金流",
    "三表",
    "分红",
    "派息",
    "财报",
    "财务",
    "估值",
    "pe",
    "pb",
    "ps",
    "行业",
    "分部",
    "境外",
    "海外",
)
_OVERVIEW_HINTS = ("概况", "总结", "怎么样", "概览", "整体", "介绍", "基本面", "综合分析")


@dataclass
class QueryIntent:
    """用户本轮问题的粗粒度意图（供编排与提示，不替代模型判断）。"""

    quote_primary: bool = False
    fundamentals: bool = False
    annual: bool = False
    overview: bool = False
    disclosure: bool = False
    matched_data_keys: list[str] | None = None
    focused_metrics: list[str] | None = None
    narrow_answer: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def valuation_focus(self) -> bool:
        return is_valuation_focus(self.focused_metrics)

    @property
    def want_live_quote(self) -> bool:
        return (
            self.quote_primary
            or self.valuation_focus
            or bool(self.matched_data_keys and "price" in (self.matched_data_keys or []))
        )

    @property
    def want_data_api(self) -> bool:
        return bool(
            self.quote_primary
            or self.fundamentals
            or self.annual
            or self.overview
            or self.disclosure
            or self.matched_data_keys
        )

    @property
    def data_scope(self) -> str:
        if self.quote_primary and not (self.fundamentals or self.annual):
            return "quote"
        if self.annual or self.disclosure:
            return "annual"
        if self.fundamentals:
            return "fundamentals"
        if self.overview:
            return "overview"
        return "auto"

    @property
    def want_background_ingest(self) -> bool:
        """仅补缺库；股价类不为此强行全量下载年报。"""
        if self.quote_primary and not (self.fundamentals or self.annual):
            return False
        return self.fundamentals or self.annual or self.overview or self.disclosure

    def answer_guidance(self) -> str:
        """软提示：供模型参考，不强制裁剪回答结构与篇幅。"""
        if self.quote_primary and not (self.fundamentals or self.annual):
            return "倾向：股价/收盘价问题可先看 quote；若用户同时要基本面，可再补年报。"
        if self.valuation_focus and self.focused_metrics:
            names = "、".join(self.focused_metrics)
            return (
                f"倾向：估值相关（{names}）可看 evidence_summary.valuation_facts / factor；"
                f"多只股票时逐只对比；用户若追问原因可简要解释。"
            )
        if self.narrow_answer and self.focused_metrics:
            names = "、".join(self.focused_metrics)
            return (
                f"倾向：用户明确收窄到「{names}」，可先给核心数字；"
                f"若对理解有帮助，可一两句补充口径或同比。"
            )
        if self.focused_metrics:
            names = "、".join(self.focused_metrics)
            return f"倾向：与 {names} 相关的证据优先；其它内容按用户兴趣决定是否展开。"
        if self.annual or self.disclosure:
            return "倾向：披露/年报可看 annual_report 与 retrieved_chunks。"
        if self.fundamentals:
            return "倾向：财务问题可结合 data_api 与年报字段。"
        return "按 question 自选最相关证据；详略与是否对比由你根据对话判断。"


def _metric_context_from_session(session: Any | None, query: str) -> str:
    if session is None or len(str(query or "").strip()) > 20:
        return ""
    q = str(query or "").strip()
    parts: list[str] = []
    for message in getattr(session, "messages", [])[-8:]:
        if getattr(message, "role", None) not in {"user", "assistant"}:
            continue
        text = str(getattr(message, "content", "") or "").strip()
        if text and text != q:
            parts.append(text[:400])
    return " ".join(parts[-3:])


def classify_query_intent(query: str, session: Any | None = None) -> QueryIntent:
    q = str(query or "").strip()
    ql = q.lower()
    ctx = _metric_context_from_session(session, q)
    focused = resolve_focused_metrics(q, context="" if resolve_focused_metrics(q) else ctx)
    keys = _select_data_keys(f"{ctx} {q}".strip() if ctx else q)
    narrow = narrow_answer_requested(q)
    has_quote = any(h in ql for h in _QUOTE_HINTS) or (
        "最近" in q and any(h in q for h in ("价", "股价", "行情", "收盘"))
    )
    has_fund = any(h in ql for h in _FUNDAMENTAL_HINTS)
    annual = _mentions_annual(q) or extract_report_year(q) is not None
    disclosure = any(h in q for h in ("公告", "披露", "巨潮", "合规"))
    overview = any(h in ql for h in _OVERVIEW_HINTS)
    fundamentals = has_fund or _mentions_financials(q) or "pit_financials" in keys

    quote_primary = has_quote and not (fundamentals or annual or overview)
    if not quote_primary and has_quote and len(q) <= 12 and not fundamentals:
        quote_primary = True

    return QueryIntent(
        quote_primary=quote_primary,
        fundamentals=fundamentals,
        annual=annual,
        overview=overview,
        disclosure=disclosure,
        matched_data_keys=keys or None,
        focused_metrics=focused or None,
        narrow_answer=narrow,
    )


def is_fundamental_narrative_hit(text: str) -> bool:
    blob = str(text or "")
    if len(blob) < 18:
        return False
    hits = sum(
        1
        for h in ("营收", "净利润", "利润", "毛利率", "归母", "亿元", "同比", "净利率", "分行业")
        if h in blob
    )
    return hits >= 2
