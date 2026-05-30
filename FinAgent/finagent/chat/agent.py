"""对话 Agent：RAG + 知识图谱 + 按需取数。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..env import get_env
from ..pdf_text import extract_mda, extract_pdf_text
from .data_tools import extract_stock_code, fetch_market_snapshot, needs_live_data
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


def _append_chunks(session: ChatSession, new_chunks: list[TextChunk]) -> None:
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


def index_report(session: ChatSession, report: dict[str, Any], *, report_id: str) -> None:
    session.report_id = report_id
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    stock = str(meta.get("order_book_id") or "").split(".")[0]
    if stock:
        session.stock_code = stock

    pieces: list[tuple[str, str, dict[str, Any]]] = []
    summary = str(report.get("executive_summary") or report.get("summary") or "")
    if summary:
        pieces.append(("summary", summary, {"kind": "summary"}))
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    for name, content in sections.items():
        pieces.append((f"section:{name}", str(content), {"kind": "section", "name": name}))
    analysis = report.get("financial_analysis") if isinstance(report.get("financial_analysis"), dict) else {}
    if analysis:
        pieces.append(("financial_analysis", json.dumps(analysis, ensure_ascii=False)[:12000], {"kind": "analysis"}))

    new_chunks: list[TextChunk] = []
    for source, text, meta in pieces:
        new_chunks.extend(chunk_text(text, source=source, meta=meta))
    _append_chunks(session, new_chunks)
    session.knowledge_graph = _merge_graph(session.knowledge_graph, build_graph_from_report(report))
    if not session.title or session.title == "新对话":
        session.title = f"{session.stock_code or report_id.split('_')[0]} 报告问答"


def index_pdf(session: ChatSession, pdf_path: Path, *, display_name: str | None = None) -> dict[str, Any]:
    text = extract_pdf_text(pdf_path)
    mda = extract_mda(text)
    session.pdf_name = display_name or pdf_path.name
    stock = extract_stock_code(pdf_path.name) or extract_stock_code(text[:4000])
    if stock:
        session.stock_code = stock

    new_chunks = chunk_text(mda.mda_text or text[:80000], source=f"pdf:{session.pdf_name}", meta={"kind": "pdf"})
    if len(new_chunks) < 3:
        new_chunks = chunk_text(text[:120000], source=f"pdf:{session.pdf_name}", meta={"kind": "pdf_full"})
    _append_chunks(session, new_chunks)
    session.knowledge_graph = _merge_graph(
        session.knowledge_graph,
        build_graph_from_text(mda.mda_text or text[:50000], source=session.pdf_name or "pdf"),
    )
    if session.title == "新对话":
        session.title = f"{session.stock_code or 'PDF'} 文档问答"
    return {"chars": len(text), "mda_confidence": mda.confidence, "stock_code": session.stock_code}


def _local_answer(query: str, hits: list[dict[str, Any]], graph_hits: list[dict[str, Any]], live: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if live and not live.get("error"):
        tech = live.get("technical") or {}
        factor = live.get("factor") or {}
        if tech or factor:
            parts.append("我先看了下最新数据快照：")
            if tech.get("latest_close") is not None:
                parts.append(f"最新收盘大概 {tech.get('latest_close')}，20 日涨跌 {tech.get('return_20d')}。")
            if factor.get("pe_ratio_ttm") is not None:
                parts.append(f"PE(TTM) 约 {factor.get('pe_ratio_ttm')}，PB 约 {factor.get('pb_ratio_ttm')}。")
    if hits:
        parts.append("结合你上传/绑定的材料，相关片段是：")
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
    live: dict[str, Any] | None,
    session: ChatSession,
) -> str:
    from ..llm import llm_text

    system = (
        "你是 FinAgent 研究助手，像同事聊天一样回答，口语自然、别写成研报八股。"
        "可以分段，但不要用过多小标题和编号列表；需要数字时引用上下文里的数据，别编造。"
        "如果材料里没有，就直说不知道；可以给下一步怎么查的建议。"
        "不要输出 JSON，不要写「作为 AI」之类套话，不要给买卖建议。"
    )
    payload = {
        "session": {
            "stock_code": session.stock_code,
            "report_id": session.report_id,
            "pdf_name": session.pdf_name,
        },
        "retrieved_chunks": hits,
        "graph_hits": graph_hits,
        "live_data": live,
        "recent_messages": [{"role": m.role, "content": m.content} for m in history[-8:]],
        "question": query,
    }
    return llm_text(system, json.dumps(payload, ensure_ascii=False)[:18000])


def chat_turn(session: ChatSession, message: str) -> ChatMessage:
    query = str(message or "").strip()
    if not query:
        raise ValueError("消息不能为空")

    user = ChatMessage(role="user", content=query, created_at=_now())
    session.messages.append(user)

    chunks = _chunks_from_session(session)
    hits = format_hits(search_chunks(chunks, query, top_k=6))
    graph_hits = query_graph(session.knowledge_graph, query, limit=8)

    live: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = []
    stock = session.stock_code or extract_stock_code(query)
    if stock and needs_live_data(query):
        live = fetch_market_snapshot(stock)
        tool_calls.append({"tool": "fetch_market_snapshot", "stock_code": stock, "ok": "error" not in (live or {})})

    try:
        if get_env("OPENAI_API_KEY"):
            answer = _llm_answer(
                query=query,
                history=session.messages,
                hits=hits,
                graph_hits=graph_hits,
                live=live,
                session=session,
            )
        else:
            answer = _local_answer(query, hits, graph_hits, live)
    except Exception as exc:
        answer = _local_answer(query, hits, graph_hits, live)
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
