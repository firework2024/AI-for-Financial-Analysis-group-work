"""对话 Agent：RAG + 知识图谱 + 按需取数。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..llm_settings import has_llm_api_key
from ..pdf_text import extract_mda, extract_pdf_text
from .data_tools import extract_stock_code
from .tools import gather_tool_context
from .knowledge_graph import build_graph_from_report, build_graph_from_text, query_graph
from .rag import TextChunk, chunk_text, format_hits, search_chunks
from .store import ChatMessage, ChatSession


def _merge_graph(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in (base.get("nodes") or []) if isinstance(node, dict) and node.get("id")}
    for node in extra.get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            nodes[node["id"]] = node
    edges = list(base.get("edges") or [])
    seen = {(edge.get("from"), edge.get("to"), edge.get("rel")) for edge in edges if isinstance(edge, dict)}
    for edge in extra.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        key = (edge.get("from"), edge.get("to"), edge.get("rel"))
        if key in seen:
            continue
        edges.append(edge)
        seen.add(key)
    return {"nodes": list(nodes.values()), "edges": edges}


_REPORT_CHUNK_KINDS = frozenset({"summary", "section", "analysis"})
_PDF_CHUNK_KINDS = frozenset({"pdf", "pdf_full"})


def _report_stock_code(report: dict[str, Any], report_id: str) -> str | None:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    stock = str(meta.get("order_book_id") or "").split(".")[0]
    if stock and re.fullmatch(r"\d{6}", stock):
        return stock
    annual = report.get("annual_report") if isinstance(report.get("annual_report"), dict) else {}
    code = str(annual.get("stock_code") or "").strip()
    if code:
        return code
    prefix = str(report_id or "").split("_")[0]
    return prefix if re.fullmatch(r"\d{6}", prefix) else None


def _chunk_stock_code(item: dict[str, Any]) -> str | None:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    stock = meta.get("stock_code")
    if stock and re.fullmatch(r"\d{6}", str(stock)):
        return str(stock)
    source = str(item.get("source") or "")
    match = re.search(r"\b([036]\d{5})\b", source)
    return match.group(1) if match else extract_stock_code(str(item.get("text") or "")[:400])


def _purge_stale_chunks(session: ChatSession, *, report_id: str, stock_code: str | None) -> list[str]:
    """重绑报告时移除旧报告片段，并忽略与其它股票不符的 PDF 片段。"""
    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    for item in session.chunks:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        kind = meta.get("kind")
        chunk_report = meta.get("report_id")
        chunk_stock = _chunk_stock_code(item)

        if kind in _REPORT_CHUNK_KINDS:
            if chunk_report and chunk_report != report_id:
                continue
            if not chunk_report:
                continue
        elif kind in _PDF_CHUNK_KINDS and stock_code and chunk_stock and chunk_stock != stock_code:
            warnings.append(f"已忽略与其它股票不符的 PDF 片段：{item.get('source') or session.pdf_name or 'pdf'}")
            continue

        kept.append(item)
    session.chunks = kept
    return warnings


def _chunks_for_retrieval(session: ChatSession) -> list[TextChunk]:
    chunks = _chunks_from_session(session)
    stock = session.stock_code
    report_id = session.report_id
    if not stock and not report_id:
        return chunks

    filtered: list[TextChunk] = []
    for chunk in chunks:
        meta = chunk.meta or {}
        kind = meta.get("kind")
        if kind in _REPORT_CHUNK_KINDS:
            if report_id and meta.get("report_id") and meta.get("report_id") != report_id:
                continue
            if stock and meta.get("stock_code") and meta.get("stock_code") != stock:
                continue
        elif kind in _PDF_CHUNK_KINDS and stock and meta.get("stock_code") and meta.get("stock_code") != stock:
            continue
        filtered.append(chunk)
    return filtered or chunks


def _chunks_from_session(session: ChatSession) -> list[TextChunk]:
    return [
        TextChunk(
            id=str(item.get("id") or f"chunk#{index}"),
            text=str(item.get("text") or ""),
            source=str(item.get("source") or "unknown"),
            meta=item.get("meta") if isinstance(item.get("meta"), dict) else {},
        )
        for index, item in enumerate(session.chunks)
        if isinstance(item, dict)
    ]


def _append_chunks(session: ChatSession, new_chunks: list[TextChunk], *, replace_ids: bool = False) -> None:
    if replace_ids:
        replace = {chunk.id for chunk in new_chunks}
        session.chunks = [item for item in session.chunks if not (isinstance(item, dict) and item.get("id") in replace)]
    existing = {item.get("id") for item in session.chunks if isinstance(item, dict)}
    for chunk in new_chunks:
        if chunk.id in existing:
            continue
        session.chunks.append(
            {
                "id": chunk.id,
                "text": chunk.text,
                "source": chunk.source,
                "meta": chunk.meta,
            }
        )


def index_report(session: ChatSession, report: dict[str, Any], *, report_id: str) -> dict[str, Any]:
    previous_report_id = session.report_id
    previous_stock = session.stock_code
    stock = _report_stock_code(report, report_id)
    warnings = _purge_stale_chunks(session, report_id=report_id, stock_code=stock)
    switched_report = bool(previous_report_id and previous_report_id != report_id)
    if switched_report:
        warnings.append(f"已切换报告：{previous_report_id} -> {report_id}")
    if session.stock_code and stock and session.stock_code != stock:
        warnings.append(f"会话原股票 {session.stock_code} 已切换为 {stock}（报告 {report_id}）")
    session.report_id = report_id
    if stock:
        session.stock_code = stock

    base_meta = {"report_id": report_id, "stock_code": stock}
    pieces: list[tuple[str, str, dict[str, Any]]] = []
    summary = str(report.get("executive_summary") or report.get("summary") or "")
    if summary:
        pieces.append(("summary", summary, {"kind": "summary", **base_meta}))
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    for name, content in sections.items():
        pieces.append((f"section:{name}", str(content), {"kind": "section", "name": name, **base_meta}))
    analysis = report.get("financial_analysis") if isinstance(report.get("financial_analysis"), dict) else {}
    if analysis:
        pieces.append(
            (
                "financial_analysis",
                json.dumps(analysis, ensure_ascii=False)[:12000],
                {"kind": "analysis", **base_meta},
            )
        )

    new_chunks: list[TextChunk] = []
    for source, text, meta in pieces:
        new_chunks.extend(chunk_text(text, source=source, meta=meta))
    _append_chunks(session, new_chunks, replace_ids=True)
    session.knowledge_graph = build_graph_from_report(report)
    session.binding_warnings = warnings
    legacy_titles = {
        "新对话",
        f"{previous_stock} 报告问答" if previous_stock else "",
        f"{(previous_report_id or '').split('_')[0]} 报告问答" if previous_report_id else "",
    }
    if not session.title or session.title in legacy_titles or switched_report:
        session.title = f"{session.stock_code or report_id.split('_')[0]} 报告问答"
    return {"stock_code": stock, "chunk_count": len(new_chunks), "warnings": warnings}


def index_pdf(session: ChatSession, pdf_path: Path, *, display_name: str | None = None) -> dict[str, Any]:
    text = extract_pdf_text(pdf_path)
    mda = extract_mda(text)
    session.pdf_name = display_name or pdf_path.name
    stock = extract_stock_code(pdf_path.name) or extract_stock_code(text[:4000])
    pdf_meta = {"kind": "pdf", "stock_code": stock}
    if stock:
        session.stock_code = stock

    new_chunks = chunk_text(mda.mda_text or text[:80000], source=f"pdf:{session.pdf_name}", meta=pdf_meta)
    if len(new_chunks) < 3:
        new_chunks = chunk_text(text[:120000], source=f"pdf:{session.pdf_name}", meta={**pdf_meta, "kind": "pdf_full"})
    _append_chunks(session, new_chunks)
    session.knowledge_graph = _merge_graph(
        session.knowledge_graph,
        build_graph_from_text(mda.mda_text or text[:50000], source=session.pdf_name or "pdf"),
    )
    if session.title == "新对话":
        session.title = f"{session.stock_code or 'PDF'} 文档问答"
    _persist_pdf_to_datastore(session, pdf_path, mda, text)
    return {"chars": len(text), "mda_confidence": mda.confidence, "stock_code": session.stock_code}


def _persist_pdf_to_datastore(session: ChatSession, pdf_path: Path, mda: Any, full_text: str) -> None:
    stock = session.stock_code
    if not stock:
        return
    report_year = _guess_report_year(pdf_path.name, full_text)
    if report_year is None:
        return
    try:
        from ..datastore import save_annual_report_record
        from ..datastore.annual_text import mda_storage_payload

        mda_payload = mda_storage_payload(mda)
        save_annual_report_record(
            stock_code=stock,
            report_year=report_year,
            title=session.pdf_name or pdf_path.name,
            pdf_path=str(pdf_path),
            meta={"source": "chat_upload", "pdf_name": session.pdf_name},
            financial_data=[],
            mda_text=mda_payload["mda_text"],
            mda_meta=mda_payload["mda_meta"],
        )
    except Exception:
        pass


def _guess_report_year(filename: str, text: str) -> int | None:
    for source in (filename, text[:8000]):
        match = re.search(r"(20\d{2})\s*年?\s*度?\s*报告", source)
        if match:
            return int(match.group(1))
    match = re.search(r"(20\d{2})", filename)
    return int(match.group(1)) if match else None


def _hits_from_data_api(data_api: dict[str, Any] | None, query: str = "") -> list[dict[str, Any]]:
    if not data_api or data_api.get("error"):
        return []
    stored = data_api.get("stored") or {}
    if not stored:
        return []
    stock = data_api.get("stock_code")
    matched_keys = list(stored.get("matched_keys") or [])
    hits: list[dict[str, Any]] = []

    annual = stored.get("annual_report") or {}
    for index, item in enumerate(annual.get("mda_hits") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("snippet") or "").strip()
        if not text:
            continue
        hits.append(
            {
                "source": "datastore:annual_mda",
                "score": 0.78 - index * 0.02,
                "text": text[:900],
                "meta": {"kind": "mda", "stock_code": stock, "priority": "local_db"},
            }
        )

    if "pit_financials" in matched_keys or _query_mentions_financials(query):
        pit = stored.get("pit_financials_cache") or {}
        for index, row in enumerate((pit.get("rows") or [])[-2:]):
            hits.append(
                {
                    "source": "datastore:pit_financials",
                    "score": 0.72 - index * 0.02,
                    "text": json.dumps(row, ensure_ascii=False)[:900],
                    "meta": {"kind": "pit_financials", "stock_code": stock, "priority": "local_db"},
                }
            )

    meta_scores = {
        "technical": 0.68,
        "factor": 0.66,
        "industry": 0.6,
        "benchmark_index": 0.58,
    }
    for key, base_score in meta_scores.items():
        block = stored.get(key)
        if not isinstance(block, dict) or not block:
            continue
        if matched_keys and not _meta_key_relevant(key, matched_keys):
            continue
        hits.append(
            {
                "source": f"datastore:{key}",
                "score": base_score,
                "text": json.dumps(block, ensure_ascii=False)[:900],
                "meta": {"kind": key, "stock_code": stock, "priority": "local_db"},
            }
        )

    return hits


def _query_mentions_financials(query: str) -> bool:
    q = str(query or "").lower()
    hints = (
        "营收", "利润", "净利", "资产", "负债", "现金流", "财务", "三表", "毛利率", "roe",
        "pe", "pb", "估值", "融资", "股价", "收盘", "涨跌", "换手",
    )
    return any(h in q for h in hints)


def _meta_key_relevant(meta_key: str, matched_keys: list[str]) -> bool:
    mapping = {
        "technical": {"price", "price_change_rate", "turnover", "capital_flow"},
        "factor": {"factor", "factor_history"},
        "industry": {"industry"},
        "benchmark_index": {"index_benchmark"},
    }
    return bool(mapping.get(meta_key, set()) & set(matched_keys))


def _merge_retrieved_hits(
    rag_hits: list[dict[str, Any]],
    data_hits: list[dict[str, Any]],
    *,
    max_total: int = 8,
) -> list[dict[str, Any]]:
    merged = sorted([*data_hits, *rag_hits], key=lambda item: float(item.get("score") or 0), reverse=True)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in merged:
        fingerprint = re.sub(r"\s+", " ", str(item.get("text") or ""))[:120]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(item)
        if len(unique) >= max_total:
            break
    return unique


def _local_answer(
    query: str,
    hits: list[dict[str, Any]],
    graph_hits: list[dict[str, Any]],
    tools: dict[str, Any] | None,
) -> str:
    parts: list[str] = []
    data_api = (tools or {}).get("data_api") or {}
    stored = data_api.get("stored") or {}
    live = (tools or {}).get("live_data") or {}
    web = (tools or {}).get("web_search") or {}

    tech = live.get("technical") or stored.get("technical") or {}
    factor = live.get("factor") or stored.get("factor") or {}
    if (live and not live.get("error")) or stored:
        if tech or factor:
            parts.append("我先看了下数据库/最新数据快照：")
            if tech.get("latest_close") is not None:
                parts.append(f"最新收盘大概 {tech.get('latest_close')}，20 日涨跌 {tech.get('return_20d')}。")
            if factor.get("pe_ratio_ttm") is not None:
                parts.append(f"PE(TTM) 约 {factor.get('pe_ratio_ttm')}，PB 约 {factor.get('pb_ratio_ttm')}。")
        if stored.get("series"):
            keys = ", ".join(stored.get("matched_keys") or [])
            parts.append(f"库里还命中这些序列：{keys}。")
    if data_api.get("hint"):
        parts.append(str(data_api["hint"]))
    if web.get("results"):
        parts.append("网上搜到这些：")
        for item in web["results"][:3]:
            parts.append(f"- {item.get('title')}: {str(item.get('snippet') or '')[:160]}")
    if hits:
        parts.append("结合你上传/绑定的材料（含本地数据库），相关片段是：")
        for hit in hits[:3]:
            snippet = re.sub(r"\s+", " ", str(hit.get("text") or ""))[:220]
            parts.append(f"- {snippet}")
    elif graph_hits:
        parts.append("图谱里找到这些相关点：")
        for node in graph_hits[:4]:
            label = node.get("label")
            snippet = node.get("snippet") or node.get("value")
            if snippet:
                parts.append(f"- {label}: {snippet}")
            else:
                parts.append(f"- {label}")
    if not parts:
        return "我这边还没有足够上下文。你可以拖一份 PDF 进来，或者从左侧选一份报告再接着问。"
    parts.append("如果你想更细，可以直接追问某个指标或章节。")
    return "\n".join(parts)


def _llm_answer(
    *,
    query: str,
    history: list[ChatMessage],
    hits: list[dict[str, Any]],
    graph_hits: list[dict[str, Any]],
    tools: dict[str, Any] | None,
    session: ChatSession,
) -> str:
    from ..llm import llm_text

    system = (
        "你是 FinAgent 研究助手，像同事聊天一样回答，口语自然、别写成研报八股。"
        "必须直接回答 question 本身；不要每次重复同一套行情/估值/财务摘要。"
        "可以分段，但不要用过多小标题和编号列表；需要数字时引用上下文里的数据，别编造。"
        "回答优先级（必须遵守）："
        "1) 先理解 question 意图，再选用最相关的来源；"
        "2) retrieved_chunks 绑定报告/PDF 片段（解读报告、风险、业务问题时优先）；"
        "3) tools.data_api 本地 SQLite（仅在与问题相关的 matched_keys / mda_hits 出现时引用）；"
        "4) tools.live_data 米筐实时快照（用户问最新行情/估值时）；"
        "5) tools.web_search 网页检索（已按 authority_score 排序）。"
        "若 question 与财务指标无关，不要机械罗列 PE/PB/收盘价；若与报告解读有关，优先用 retrieved_chunks。"
        "只有上述来源都确实没有该字段时，才说明缺失并建议下一步。"
        "引用新闻时优先 source_tier 为 official / financial_data 的结果，并注明标题；社区来源仅作参考。"
        "session.binding_warnings 若有内容，说明上下文曾切换股票/报告，勿混用其它公司数据。"
        "不要输出 JSON，不要写「作为 AI」之类套话，不要给买卖建议。"
    )
    payload = {
        "session": {
            "stock_code": session.stock_code,
            "report_id": session.report_id,
            "pdf_name": session.pdf_name,
            "binding_warnings": session.binding_warnings,
        },
        "retrieved_chunks": hits,
        "graph_hits": graph_hits,
        "tools": tools,
        "recent_messages": [{"role": m.role, "content": m.content} for m in history[-8:]],
        "question": query,
    }
    return llm_text(system, json.dumps(payload, ensure_ascii=False)[:18000])


def sync_session_stock(session: ChatSession, stock_code: str | None) -> None:
    code = str(stock_code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return
    if session.stock_code == code:
        return
    if session.stock_code and session.stock_code != code:
        session.binding_warnings.append(f"会话股票已从 {session.stock_code} 更新为 {code}")
    session.stock_code = code


def chat_turn(session: ChatSession, message: str) -> ChatMessage:
    query = str(message or "").strip()
    if not query:
        raise ValueError("消息不能为空")

    user = ChatMessage(role="user", content=query, created_at=_now())
    session.messages.append(user)

    chunks = _chunks_for_retrieval(session)
    rag_hits = format_hits(search_chunks(chunks, query, top_k=6, stock_code=session.stock_code))
    graph_hits = query_graph(session.knowledge_graph, query, limit=8)

    tools_payload, tool_calls = gather_tool_context(query, session)
    data_hits = _hits_from_data_api(tools_payload.get("data_api"), query)
    hits = _merge_retrieved_hits(rag_hits, data_hits, max_total=8)

    try:
        if has_llm_api_key():
            answer = _llm_answer(
                query=query,
                history=session.messages,
                hits=hits,
                graph_hits=graph_hits,
                tools=tools_payload,
                session=session,
            )
        else:
            answer = _local_answer(query, hits, graph_hits, tools_payload)
    except Exception as exc:
        answer = _local_answer(query, hits, graph_hits, tools_payload)
        answer += f"\n\n（LLM 暂不可用：{exc}）"

    assistant = ChatMessage(
        role="assistant",
        content=answer.strip(),
        created_at=_now(),
        sources=hits[:4],
        tool_calls=tool_calls,
    )
    session.messages.append(assistant)
    return assistant


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
