"""对话 Agent 循环：多轮思考 + 按需工具调用，再生成最终回答。"""

from __future__ import annotations

import json
import re
from typing import Any

from ..env import get_env
from ..llm import llm_json, llm_text
from ..llm_settings import has_llm_api_key
from .agent import (
    _chunks_for_retrieval,
    _hits_from_tools_payload,
    _hits_from_web_search,
    _local_answer,
    _merge_retrieved_hits,
    _now,
)
from .intent import classify_query_intent
from .rag import format_hits, search_chunks
from .store import ChatMessage, ChatSession
from .tools import gather_tool_context

_TOOL_CATALOG = """
可用工具（name 必须与下列一致，args 为 JSON 对象）：
- resolve_stocks：args {text?}；从公司名/代码/简称解析股票并绑定会话（巨潮+别名），无需用户填侧栏。
- get_session：无参数；返回本会话已绑定的 stock_codes、report_id。
- fetch_factor：args {stock_code}；PE/PB/市值等因子（优先本地库）。
- fetch_market：args {stock_code}；行情快照（价量、技术指标）。
- query_database：args {stock_code, query?}；SQLite 年报/PIT/序列。
- search_documents：args {query?}；检索本会话已绑定 PDF/报告片段。
- web_search：args {query, stock_code?}；联网搜索（需显式需要时使用）。
- ensure_data：args {stock_code, query?}；缺库时补拉行情/年报（较慢，慎用）。
"""


def chat_agent_mode(override: str | None = None) -> str:
    if override:
        mode = str(override).strip().lower()
        if mode in {"loop", "single"}:
            return mode
    mode = (get_env("FINAGENT_CHAT_AGENT_MODE") or "loop").strip().lower()
    return mode if mode in {"loop", "single"} else "loop"


def chat_agent_max_steps(override: int | None = None) -> int:
    if override is not None:
        try:
            return max(1, min(8, int(override)))
        except (TypeError, ValueError):
            pass
    try:
        return max(1, min(8, int(get_env("FINAGENT_CHAT_MAX_STEPS", "4"))))
    except ValueError:
        return 4


def _truncate(obj: Any, limit: int = 3500) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "…(truncated)"


def _execute_tool(name: str, args: dict[str, Any], session: ChatSession, user_query: str) -> dict[str, Any]:
    from .data_tools import fetch_market_snapshot, fetch_valuation_snapshot
    from .data_ingest import ensure_stored_data
    from .tools import query_data_api
    from .web_search import search_web
    from ..env import project_root

    tool = str(name or "").strip()
    params = args if isinstance(args, dict) else {}

    if tool == "resolve_stocks":
        from .stock_bind import bind_stocks_from_chat

        text = str(params.get("text") or user_query).strip()
        codes = bind_stocks_from_chat(session, text)
        return {
            "stock_codes": codes,
            "stock_code": codes[0] if codes else None,
            "text": text,
            "message": "已绑定" if codes else "未能从文本识别股票，可换公司全称或 6 位代码",
        }

    if tool == "get_session":
        codes = list(session.stock_codes or []) or ([session.stock_code] if session.stock_code else [])
        return {
            "stock_codes": codes,
            "stock_code": session.stock_code,
            "report_id": session.report_id,
            "pdf_name": session.pdf_name,
        }

    if tool == "fetch_factor":
        code = str(params.get("stock_code") or session.stock_code or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            return {"error": "需要 6 位 stock_code"}
        live = fetch_valuation_snapshot(code)
        factor = (live or {}).get("factor") or {}
        return {
            "stock_code": code,
            "sec_name": live.get("sec_name"),
            "as_of": live.get("end_date") or live.get("as_of"),
            "source": live.get("source"),
            "factor": factor,
        }

    if tool == "fetch_market":
        code = str(params.get("stock_code") or session.stock_code or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            return {"error": "需要 6 位 stock_code"}
        live = fetch_market_snapshot(code, lookback_days=60, incremental=True)
        return {
            "stock_code": code,
            "quote": (live or {}).get("quote"),
            "technical": (live or {}).get("technical"),
            "factor": (live or {}).get("factor"),
            "source": (live or {}).get("source"),
        }

    if tool == "query_database":
        code = str(params.get("stock_code") or session.stock_code or "").strip()
        q = str(params.get("query") or user_query)
        if not re.fullmatch(r"\d{6}", code):
            return {"error": "需要 6 位 stock_code"}
        intent = classify_query_intent(q, session)
        data = query_data_api(code, q, intent=intent)
        stored = (data or {}).get("stored")
        if not stored:
            return {"stock_code": code, "hint": (data or {}).get("hint") or "无匹配存储数据"}
        return {"stock_code": code, "scope": (data or {}).get("scope"), "stored": stored}

    if tool == "search_documents":
        q = str(params.get("query") or user_query)
        chunks = _chunks_for_retrieval(session)
        watch = list(session.stock_codes or []) or ([session.stock_code] if session.stock_code else [])
        hits = format_hits(
            search_chunks(chunks, q, top_k=6, stock_code=session.stock_code, stock_codes=watch),
        )
        return {"query": q, "hits": hits[:6]}

    if tool == "web_search":
        q = str(params.get("query") or user_query)
        code = str(params.get("stock_code") or session.stock_code or "").strip() or None
        if code and not re.fullmatch(r"\d{6}", code):
            code = None
        web = search_web(q, stock_code=code, max_results=5)
        return {
            "provider": web.get("provider"),
            "error": web.get("error"),
            "results": (web.get("results") or [])[:5],
        }

    if tool == "ensure_data":
        code = str(params.get("stock_code") or session.stock_code or "").strip()
        q = str(params.get("query") or user_query)
        if not re.fullmatch(r"\d{6}", code):
            return {"error": "需要 6 位 stock_code"}
        return ensure_stored_data(code, q, workdir=project_root()) or {"ok": False, "message": "未执行"}

    return {"error": f"未知工具: {tool}", "available": list(_TOOL_NAMES)}


_TOOL_NAMES = (
    "get_session",
    "fetch_factor",
    "fetch_market",
    "query_database",
    "search_documents",
    "web_search",
    "ensure_data",
    "resolve_stocks",
)


def _plan_next_step(
    *,
    user_query: str,
    session: ChatSession,
    observations: list[dict[str, Any]],
    step: int,
    max_steps: int,
) -> dict[str, Any]:
    system = (
        "你是 FinAgent 对话调度器（ReAct）。根据用户问题与已收集的 observations，决定下一步。"
        "输出 JSON："
        '{"thought":"简短推理（中文）","actions":[{"tool":"工具名","args":{}}],"done":false}'
        "规则："
        "- 每轮最多 3 个 actions；已有足够证据时 actions=[] 且 done=true。"
        "- thought 说明本步打算做什么，勿写最终给用户的长答案。"
        "- 用户提到公司名但 session 无代码时，先 resolve_stocks（勿让用户去填侧栏）。"
        "- 库无数据时用 ensure_data；多只股票时先 get_session，再逐只拉数。"
        "- 估值/PE 优先 fetch_factor；纯股价用 fetch_market；年报财务用 query_database。"
        f"{_TOOL_CATALOG}"
    )
    payload = {
        "step": step,
        "max_steps": max_steps,
        "question": user_query,
        "session": {
            "stock_codes": list(session.stock_codes or []),
            "stock_code": session.stock_code,
            "report_id": session.report_id,
        },
        "observations": observations[-8:],
        "recent_messages": [
            {"role": m.role, "content": m.content[:500]}
            for m in session.messages[-6:]
        ],
    }
    return llm_json(system, json.dumps(payload, ensure_ascii=False))


def _prefetch_observation(session: ChatSession, query: str) -> dict[str, Any]:
    """首轮轻量预取：自动解析股票 + 意图，供规划器参考。"""
    from .stock_bind import bind_stocks_from_chat, should_run_chat_bootstrap

    codes = bind_stocks_from_chat(session, query)
    intent = classify_query_intent(query, session)
    boot_hint = None
    if codes and should_run_chat_bootstrap(session, codes, query):
        boot_hint = "后台将自动下载/更新本地数据（无需用户手动入库）"
    return {
        "prefetch": True,
        "stock_codes": codes,
        "auto_ingest": boot_hint,
        "intent": intent.to_dict(),
        "answer_guidance": intent.answer_guidance(),
    }


def _synthesize_answer(
    *,
    user_query: str,
    session: ChatSession,
    observations: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    graph_hits: list[dict[str, Any]],
    tools_payload: dict[str, Any] | None,
) -> str:
    system = (
        "你是 FinAgent 研究助手。用户已看到调度过程；请根据 observations 与证据给出最终回答。"
        "可简可详，由你判断；tools.intent / answer_guidance 仅为倾向。"
        "observations 里已有 stock_codes 或 resolve_stocks 结果时，直接作答，勿让用户去侧栏填代码。"
        "auto_ingest 表示后台正在入库，可先说明进度并回答已有数据。"
        "数字来自 observations，勿编造；quote.close 为最近交易日收盘，prev_close 为昨收。"
        "不要输出 JSON，不要套话，不要给买卖建议。"
    )
    payload = {
        "question": user_query,
        "observations": observations,
        "retrieved_chunks": hits[:12],
        "graph_hits": graph_hits[:8],
        "tools": tools_payload,
        "session": {
            "stock_codes": list(session.stock_codes or []),
            "stock_code": session.stock_code,
            "report_id": session.report_id,
        },
        "recent_messages": [{"role": m.role, "content": m.content} for m in session.messages[-8:]],
    }
    return llm_text(system, json.dumps(payload, ensure_ascii=False)[:20000])


def chat_turn_loop(
    session: ChatSession,
    message: str,
    *,
    max_steps: int | None = None,
) -> ChatMessage:
    """多轮思考 + 工具调用后作答。"""
    query = str(message or "").strip()
    if not query:
        raise ValueError("消息不能为空")

    from .stock_bind import bind_stocks_from_chat

    bind_stocks_from_chat(session, query)

    user = ChatMessage(role="user", content=query, created_at=_now())
    session.messages.append(user)

    tool_trace: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = [_prefetch_observation(session, query)]
    max_steps = chat_agent_max_steps(max_steps)

    if has_llm_api_key():
        for step in range(1, max_steps + 1):
            try:
                plan = _plan_next_step(
                    user_query=query,
                    session=session,
                    observations=observations,
                    step=step,
                    max_steps=max_steps,
                )
            except Exception as exc:
                observations.append({"step": step, "plan_error": str(exc)})
                break

            thought = str(plan.get("thought") or "").strip()
            if thought:
                tool_trace.append({"tool": "think", "step": step, "thought": thought[:400]})

            actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
            done = bool(plan.get("done")) or not actions

            for index, action in enumerate(actions[:3]):
                if not isinstance(action, dict):
                    continue
                name = str(action.get("tool") or action.get("name") or "").strip()
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                result = _execute_tool(name, args, session, query)
                observations.append(
                    {"step": step, "tool": name, "args": args, "result": result},
                )
                tool_trace.append(
                    {
                        "tool": name,
                        "step": step,
                        "args": args,
                        "ok": "error" not in result or not result.get("error"),
                    }
                )

            if done:
                break
    else:
        tool_trace.append({"tool": "think", "thought": "无 LLM Key，跳过规划循环"})

    intent = classify_query_intent(query, session)
    tools_payload, bulk_calls = gather_tool_context(query, session)
    tool_trace.extend(bulk_calls)

    from .knowledge_graph import query_graph

    chunks = _chunks_for_retrieval(session)
    watch_codes = list(session.stock_codes or []) or ([session.stock_code] if session.stock_code else [])
    rag_hits = format_hits(
        search_chunks(chunks, query, top_k=6, stock_code=session.stock_code, stock_codes=watch_codes),
    )
    graph_hits = query_graph(session.knowledge_graph, query, limit=8)
    data_hits = _hits_from_tools_payload(tools_payload, query, intent=intent)
    web_hits = _hits_from_web_search(tools_payload.get("web_search"))
    max_hits = 16 if len(tools_payload.get("stock_codes") or []) > 1 else 10
    hits = _merge_retrieved_hits(
        rag_hits,
        [*data_hits, *web_hits],
        max_total=max_hits,
        quote_primary=intent.quote_primary,
    )

    try:
        if has_llm_api_key():
            answer = _synthesize_answer(
                user_query=query,
                session=session,
                observations=observations,
                hits=hits,
                graph_hits=graph_hits,
                tools_payload=tools_payload,
            )
        else:
            answer = _local_answer(query, hits, graph_hits, tools_payload)
    except Exception as exc:
        answer = _local_answer(query, hits, graph_hits, tools_payload)
        answer += f"\n\n（合成回答失败：{exc}）"

    assistant = ChatMessage(
        role="assistant",
        content=answer.strip(),
        created_at=_now(),
        sources=hits[:4],
        tool_calls=tool_trace,
    )
    session.messages.append(assistant)
    return assistant
