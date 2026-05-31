"""按本轮意图裁剪证据与 tools 载荷，避免模型看到无关数字后答偏。"""

from __future__ import annotations

import copy
from typing import Any

from .intent import QueryIntent, is_fundamental_narrative_hit
from .metrics import filter_financial_rows, is_valuation_focus, slim_factor_block

_QUOTE_HIT_KINDS = frozenset({"price", "technical"})
_FINANCIAL_HIT_KINDS = frozenset({"annual_financials", "pit_financials", "mda"})

_METRIC_HINTS: dict[str, tuple[str, ...]] = {
    "总资产": ("总资产", "资产总计", "资产合计", "资产规模"),
    "净利润": ("净利润", "归母", "净利"),
    "营业收入": ("营收", "营业收入", "收入"),
    "经营现金流": ("现金流", "经营现金流"),
    "市盈率": ("市盈率", "pe_ratio", "pe("),
    "市净率": ("市净率", "pb"),
    "市销率": ("市销率", "ps"),
    "总市值": ("市值", "market_cap"),
    "ROE": ("roe", "净资产收益率"),
    "毛利率": ("毛利率", "毛利"),
}


def strict_answer_required(intent: QueryIntent) -> bool:
    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        return True
    if intent.narrow_answer and intent.focused_metrics:
        return True
    if intent.focused_metrics and not intent.overview:
        return True
    return False


def _hit_kind(hit: dict[str, Any]) -> str:
    meta = hit.get("meta") if isinstance(hit.get("meta"), dict) else {}
    return str(meta.get("kind") or "")


def _blob_matches_focused_metrics(blob: str, labels: list[str]) -> bool:
    if not labels:
        return True
    text = str(blob or "").lower()
    for label in labels:
        hints = _METRIC_HINTS.get(label, (label,))
        if any(h.lower() in text for h in hints):
            return True
    return False


def _query_mentions_price(query: str) -> bool:
    q = str(query or "").lower()
    return any(h in q for h in ("股价", "行情", "收盘", "现价", "涨跌", "k线", "多少钱", "价格", "开盘"))


def filter_retrieved_hits(
    hits: list[dict[str, Any]],
    intent: QueryIntent,
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    if not hits or not strict_answer_required(intent):
        return hits

    labels = list(intent.focused_metrics or [])
    kept: list[dict[str, Any]] = []

    for hit in hits:
        kind = _hit_kind(hit)
        text = str(hit.get("text") or "")

        if intent.quote_primary and not (intent.fundamentals or intent.annual):
            if kind in _FINANCIAL_HIT_KINDS or is_fundamental_narrative_hit(text):
                continue
            if kind and kind not in _QUOTE_HIT_KINDS and kind != "web_search":
                continue
            if kind == "factor":
                continue
            if not kind and is_fundamental_narrative_hit(text):
                continue
            kept.append(hit)
            continue

        if labels and not intent.overview:
            if kind in _FINANCIAL_HIT_KINDS or is_fundamental_narrative_hit(text):
                if not _blob_matches_focused_metrics(text, labels):
                    continue
            if kind == "factor" and not is_valuation_focus(labels):
                continue
            if kind in {"technical", "price"} and not _query_mentions_price(query):
                continue
            if not kind and is_fundamental_narrative_hit(text) and not _blob_matches_focused_metrics(text, labels):
                continue
            kept.append(hit)
            continue

        if intent.narrow_answer and is_fundamental_narrative_hit(text) and labels:
            if not _blob_matches_focused_metrics(text, labels):
                continue
        kept.append(hit)

    cap = 4 if intent.quote_primary or intent.narrow_answer else 6
    return kept[:cap]


def _slim_live_block(live: dict[str, Any] | None, intent: QueryIntent) -> dict[str, Any] | None:
    if not isinstance(live, dict) or not live:
        return live
    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        slim: dict[str, Any] = {}
        for key in ("stock_code", "sec_name", "end_date", "as_of", "source", "market_context"):
            if key in live:
                slim[key] = live[key]
        quote = live.get("quote")
        if isinstance(quote, dict):
            slim["quote"] = {
                k: quote[k]
                for k in ("date", "close", "prev_close", "change_pct", "open", "high", "low", "volume")
                if quote.get(k) is not None
            }
        return slim
    labels = list(intent.focused_metrics or [])
    if labels and is_valuation_focus(labels):
        slim_factor = slim_factor_block(live.get("factor"), labels)
        base = {k: live[k] for k in ("stock_code", "sec_name", "end_date", "as_of", "source") if k in live}
        if slim_factor:
            base["factor"] = slim_factor
        return base
    return live


def _slim_stored_block(stored: dict[str, Any] | None, intent: QueryIntent) -> dict[str, Any] | None:
    if not isinstance(stored, dict) or not stored:
        return stored
    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        out: dict[str, Any] = {
            "stock_code": stored.get("stock_code"),
            "matched_keys": [k for k in (stored.get("matched_keys") or []) if k in {"price", "price_change_rate"}],
            "scope": stored.get("scope") or "quote",
        }
        series = stored.get("series") or {}
        if series.get("price"):
            out["series"] = {"price": series["price"]}
        tech = stored.get("technical")
        if isinstance(tech, dict):
            out["technical"] = {
                k: tech[k]
                for k in ("latest_close", "return_20d", "return_60d", "rsi_14")
                if tech.get(k) is not None
            }
        return out
    labels = list(intent.focused_metrics or [])
    if labels and not intent.overview:
        out: dict[str, Any] = {
            "stock_code": stored.get("stock_code"),
            "matched_keys": stored.get("matched_keys"),
            "scope": stored.get("scope"),
        }
        annual = stored.get("annual_report") or {}
        fin = annual.get("financial_data") or []
        if fin:
            out["annual_report"] = {
                "report_year": annual.get("report_year"),
                "financial_data": filter_financial_rows(fin, labels)[-4:],
            }
        pit = stored.get("pit_financials_cache") or {}
        rows = pit.get("rows") or []
        if rows:
            out["pit_financials_cache"] = {**pit, "rows": filter_financial_rows(rows, labels)[-4:]}
        if is_valuation_focus(labels):
            factor = slim_factor_block(stored.get("factor"), labels)
            if factor:
                out["factor"] = factor
        return out
    return stored


def prune_tools_payload(payload: dict[str, Any] | None, intent: QueryIntent) -> dict[str, Any] | None:
    if not payload or not strict_answer_required(intent):
        return payload

    out = copy.deepcopy(payload)
    out["answer_guidance"] = (
        f"{out.get('answer_guidance') or ''} "
        "【硬性】只回答 question 直接问到的内容；禁止附带用户未提及的指标、章节或背景数据。"
    ).strip()

    out["live_data"] = _slim_live_block(out.get("live_data"), intent)
    by_stock = out.get("live_by_stock") or {}
    if isinstance(by_stock, dict):
        out["live_by_stock"] = {code: _slim_live_block(block, intent) for code, block in by_stock.items()}

    block = out.get("data_api")
    if isinstance(block, dict) and isinstance(block.get("stored"), dict):
        block["stored"] = _slim_stored_block(block["stored"], intent)

    data_by = out.get("data_by_stock") or {}
    if isinstance(data_by, dict):
        for code, item in data_by.items():
            if isinstance(item, dict) and isinstance(item.get("stored"), dict):
                item["stored"] = _slim_stored_block(item["stored"], intent)

    summary = out.get("evidence_summary") or {}
    if isinstance(summary, dict):
        if intent.quote_primary and not (intent.fundamentals or intent.annual):
            summary.pop("financial_facts", None)
        labels = list(intent.focused_metrics or [])
        if labels and not is_valuation_focus(labels):
            summary.pop("valuation_facts", None)
        elif labels:
            summary.pop("financial_facts", None)
        out["evidence_summary"] = summary

    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        if (out.get("live_data") or {}).get("quote", {}).get("close") is not None:
            out["web_search"] = None

    return out


def filter_graph_hits(graph_hits: list[dict[str, Any]], intent: QueryIntent) -> list[dict[str, Any]]:
    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        return []
    return graph_hits


def rag_top_k_for_intent(intent: QueryIntent, default: int = 6) -> int:
    if intent.quote_primary and not (intent.fundamentals or intent.annual):
        return 2
    if intent.narrow_answer or (intent.focused_metrics and not intent.overview):
        return 4
    return default
