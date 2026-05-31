"""对话问题意图：供工具编排与 LLM 参考，不做硬性截断回答。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ..datastore.query import extract_report_year, _mentions_annual, _mentions_financials, _select_data_keys

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def want_live_quote(self) -> bool:
        return self.quote_primary or bool(self.matched_data_keys and "price" in self.matched_data_keys)

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
        if self.quote_primary and not (self.fundamentals or self.annual):
            return "用户主要在问行情/收盘价：先给最新价与日期，勿用年报营收/毛利率长文代替股价。"
        if self.annual or self.disclosure:
            return "用户关注披露/年报：可结合 retrieved_chunks 与 annual_report。"
        if self.fundamentals:
            return "用户关注财务指标：可引用 data_api 财务序列与年报字段。"
        return "根据 question 选用最相关证据，避免堆砌无关指标。"


def classify_query_intent(query: str, session: Any | None = None) -> QueryIntent:
    q = str(query or "").strip()
    ql = q.lower()
    keys = _select_data_keys(q)
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
