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
    tools: dict[str, Any] | None,
    session: ChatSession,
) -> str:
    from ..llm import llm_text

    system = (
        "你是 FinAgent 研究助手，像同事聊天一样回答，口语自然、别写成研报八股。"
        "可以分段，但不要用过多小标题和编号列表；需要数字时引用上下文里的数据，别编造。"
        "payload 中 tools.data_api 是本地 SQLite 原始数据（行情/财务/年报 MD&A）；"
        "tools.live_data 是米筐实时快照；tools.web_search 是网页检索结果。"
        "引用数字时优先 data_api / live_data；新闻政策类可结合 web_search，并注明来源标题。"
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
        "tools": tools,
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

    tools_payload, tool_calls = gather_tool_context(query, session)

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
