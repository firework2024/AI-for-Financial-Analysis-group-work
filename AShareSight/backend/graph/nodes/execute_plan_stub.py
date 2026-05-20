# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.graph.adapters import (
    build_agent_invokers as _build_agent_invokers,
    build_tool_invokers as _build_tool_invokers,
)
from backend.graph.executor import execute_plan
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.json_utils import json_dumps_safe
from backend.graph.memory_scope import current_thread_focus, user_profile_memory
from backend.graph.request_task_contract import build_tool_diagnostic, output_is_error_like
from backend.graph.state import GraphState
def build_tool_invokers(allowed_tools: list[str]) -> dict[str, Any]:
    return _build_tool_invokers(allowed_tools=allowed_tools or [])


def build_agent_invokers(allowed_agents: list[str], state: GraphState) -> dict[str, Any]:
    # Backward-compatible wrapper for tests that monkeypatch this symbol.
    return _build_agent_invokers(allowed_agents=allowed_agents or [], state=state)


_EXECUTION_OWNED_ARTIFACT_KEYS = {
    "agent_diagnostics",
    "brief_data",
    "draft_markdown",
    "errors",
    "evidence_by_task",
    "evidence_pool",
    "rag_context",
    "rag_stats",
    "render_vars",
    "response",
    "signals",
    "step_results",
    "task_results",
    "tool_diagnostics",
    "verifier_result",
}


def _merge_prior_artifacts(prior: Any, current: Any) -> dict[str, Any]:
    if not isinstance(prior, dict):
        prior = {}
    if not isinstance(current, dict):
        current = {}
    preserved = {key: value for key, value in prior.items() if key not in _EXECUTION_OWNED_ARTIFACT_KEYS}
    return {**preserved, **current}


def _env_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10_000) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(str(raw).strip())
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _ttl_hours_for_evidence(*, subject_type: str, evidence_type: str, source: str, confidence: float = 0.0, source_reliability: float = 0.0) -> int:
    """
    RAG v2 TTL policy:
    - filing/research_doc: persistent (no TTL)
    - DeepSearch high-quality (confidence >= 0.7 AND source_reliability >= 0.75): persistent
    - news/selection/search-derived: short-term TTL
    - others: session-ephemeral TTL
    """
    if subject_type in ("filing", "research_doc"):
        return 0

    # E4: DeepSearch high-quality results 鈫?persistent
    if confidence >= 0.7 and source_reliability >= 0.75:
        return 0

    news_ttl = _env_int("RAG_V2_NEWS_TTL_HOURS", 24 * 7, min_value=1, max_value=24 * 180)
    ephemeral_ttl = _env_int("RAG_V2_EPHEMERAL_TTL_HOURS", 12, min_value=1, max_value=24 * 30)

    source_norm = (source or "").strip().lower()
    evidence_type_norm = (evidence_type or "").strip().lower()
    if evidence_type_norm in ("news", "selection"):
        return news_ttl
    if source_norm in ("news", "selection", "search", "tavily", "exa", "google_news"):
        return news_ttl
    return ephemeral_ttl


# E4: High-reliability source domains (strict whitelist from deep_search_agent)
_HIGH_RELIABILITY_SOURCE_HINTS = frozenset({
    "sec.gov", "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
})


def _estimate_source_reliability(url: str) -> float:
    """Estimate source reliability from URL domain (0.0 - 1.0)."""
    if not url:
        return 0.5
    url_lower = url.lower()
    # Check high-reliability domains
    for domain in _HIGH_RELIABILITY_SOURCE_HINTS:
        if domain in url_lower:
            return 0.9
    # Investor relations pages
    if "investor" in url_lower:
        return 0.85
    # Known finance sources
    finance_hints = ("yahoo.com/finance", "cnbc.com", "marketwatch.com", "seekingalpha.com")
    for hint in finance_hints:
        if hint in url_lower:
            return 0.75
    return 0.6


def _build_rag_doc_id(*, thread_id: str, evidence: dict[str, Any], index: int) -> str:
    explicit = str(evidence.get("id") or "").strip()
    if explicit:
        return explicit
    title = str(evidence.get("title") or "").strip()
    url = str(evidence.get("url") or "").strip()
    snippet = str(evidence.get("snippet") or "").strip()
    material = f"{thread_id}|{index}|{title}|{url}|{snippet}".encode("utf-8")
    return hashlib.sha1(material).hexdigest()[:24]


def _sanitize_collection_segment(value: str) -> str:
    import re

    text = (value or "").strip()
    if not text:
        return "unknown"
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown"


def _collection_from_thread_id(thread_id: str) -> str:
    return build_thread_working_set_collection(thread_id)


def _kb_collection_from_subject(subject: dict[str, Any] | None) -> str | None:
    return build_subject_kb_collection(subject if isinstance(subject, dict) else None)


def _memory_collection_from_thread(*, thread_id: str, user_id: str | None = None) -> str:
    return build_thread_memory_collection(thread_id=thread_id, user_id=user_id)


def _normalize_watchlist_items(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        symbol = str(item or '').strip().upper()
        if not symbol or symbol in result:
            continue
        result.append(symbol)
        if len(result) >= limit:
            break
    return result


def _normalize_memory_focus_list(value: Any, *, limit: int = 3) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            'ticker': str(item.get('ticker') or '').strip().upper(),
            'query': str(item.get('query') or '').strip(),
            'summary': str(item.get('summary') or '').strip(),
            'sentiment': str(item.get('sentiment') or '').strip(),
            'updated_at': str(item.get('updated_at') or '').strip(),
        }
        if not any(normalized.values()):
            continue
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _build_memory_context_specs(*, memory_context: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    if not isinstance(memory_context, dict) or not memory_context:
        return []

    profile = user_profile_memory(memory_context)
    risk_tolerance = str(profile.get("risk_tolerance") or "").strip().lower()
    investment_style = str(profile.get("investment_style") or "").strip().lower()
    watchlist = _normalize_watchlist_items(profile.get("watchlist"))
    last_focus_raw = current_thread_focus(memory_context)
    last_focus_list = _normalize_memory_focus_list([last_focus_raw] if last_focus_raw else [], limit=1)
    last_focus = last_focus_list[0] if last_focus_list else None
    recent_focuses: list[dict[str, Any]] = []

    specs: list[dict[str, Any]] = []
    if watchlist or risk_tolerance not in {"", "medium"} or investment_style not in {"", "balanced"}:
        profile_lines = [
            "memory_kind: profile",
            f"user_id: {user_id}",
            f"risk_tolerance: {risk_tolerance or 'medium'}",
            f"investment_style: {investment_style or 'balanced'}",
        ]
        if watchlist:
            profile_lines.append(f"watchlist: {', '.join(watchlist)}")
        specs.append({
            "source_id": "memdoc:profile",
            "title": "Memory Profile",
            "content": "\n".join(profile_lines),
            "metadata": {
                "memory_kind": "profile",
                "watchlist": watchlist,
            },
        })

    if watchlist:
        specs.append({
            "source_id": "memdoc:watchlist",
            "title": "Memory Watchlist",
            "content": "\n".join([
                "memory_kind: watchlist",
                f"user_id: {user_id}",
                f"watchlist: {', '.join(watchlist)}",
            ]),
            "metadata": {
                "memory_kind": "watchlist",
                "watchlist": watchlist,
            },
        })

    if last_focus:
        ticker = str(last_focus.get("ticker") or "").strip().upper()
        focus_lines = [
            "memory_kind: last_focus",
            f"user_id: {user_id}",
        ]
        if ticker:
            focus_lines.append(f"ticker: {ticker}")
        if last_focus.get("query"):
            focus_lines.append(f"query: {last_focus['query']}")
        if last_focus.get("summary"):
            focus_lines.append(f"summary: {last_focus['summary']}")
        if last_focus.get("sentiment"):
            focus_lines.append(f"sentiment: {last_focus['sentiment']}")
        if last_focus.get("updated_at"):
            focus_lines.append(f"updated_at: {last_focus['updated_at']}")
        specs.append({
            "source_id": "memdoc:last_focus",
            "title": f"Memory Last Focus {ticker or user_id}",
            "content": "\n".join(focus_lines),
            "metadata": {
                "memory_kind": "last_focus",
                "ticker": ticker or None,
                "query": last_focus.get("query") or None,
                "sentiment": last_focus.get("sentiment") or None,
                "updated_at": last_focus.get("updated_at") or None,
            },
        })

    seen_recent_keys: set[tuple[str, str]] = set()
    if last_focus:
        seen_recent_keys.add((str(last_focus.get("ticker") or "").strip().upper(), str(last_focus.get("query") or "").strip()))

    for index, focus in enumerate(recent_focuses, start=1):
        ticker = str(focus.get("ticker") or "").strip().upper()
        query = str(focus.get("query") or "").strip()
        focus_key = (ticker, query)
        if focus_key in seen_recent_keys:
            continue
        seen_recent_keys.add(focus_key)
        recent_lines = [
            "memory_kind: recent_focus",
            f"user_id: {user_id}",
            f"recent_focus_rank: {index}",
        ]
        if ticker:
            recent_lines.append(f"ticker: {ticker}")
        if query:
            recent_lines.append(f"query: {query}")
        if focus.get("summary"):
            recent_lines.append(f"summary: {focus['summary']}")
        if focus.get("sentiment"):
            recent_lines.append(f"sentiment: {focus['sentiment']}")
        if focus.get("updated_at"):
            recent_lines.append(f"updated_at: {focus['updated_at']}")
        specs.append({
            "source_id": f"memdoc:recent_focus:{index}",
            "title": f"Memory Recent Focus {index} {ticker or user_id}",
            "content": "\n".join(recent_lines),
            "metadata": {
                "memory_kind": "recent_focus",
                "memory_rank": index,
                "ticker": ticker or None,
                "query": query or None,
                "sentiment": focus.get("sentiment") or None,
                "updated_at": focus.get("updated_at") or None,
            },
        })

    return [spec for spec in specs if str(spec.get("content") or "").strip()]
    return [spec for spec in specs if str(spec.get("content") or "").strip()]


def _resolve_hit_layer(hit: dict[str, Any]) -> str:
    metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
    collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
    details = collection_details(collection)
    return str(hit.get('layer') or metadata.get('layer') or details.get('layer') or 'unknown').strip().lower() or 'unknown'


def _summarize_layer_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for hit in hits or []:
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
        matched_collections_raw = hit.get('matched_collections') or metadata.get('matched_collections')
        collection_pairs: list[tuple[str, str]] = []
        if isinstance(matched_collections_raw, list):
            for item in matched_collections_raw:
                collection = str(item or '').strip()
                if not collection:
                    continue
                details = collection_details(collection)
                layer = str(details.get('layer') or 'unknown').strip().lower() or 'unknown'
                collection_pairs.append((layer, collection))

        if not collection_pairs:
            collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
            collection_pairs.append((_resolve_hit_layer(hit), collection))

        title = str(hit.get('title') or hit.get('source_id') or '').strip()
        seen_layers_for_hit: set[str] = set()
        for layer, collection in collection_pairs:
            normalized_layer = str(layer or 'unknown').strip().lower() or 'unknown'
            bucket = buckets.setdefault(normalized_layer, {
                'layer': normalized_layer,
                'count': 0,
                'collections': [],
                'sample_titles': [],
            })
            if normalized_layer not in seen_layers_for_hit:
                bucket['count'] += 1
                total_matches += 1
                seen_layers_for_hit.add(normalized_layer)
            if collection and collection not in bucket['collections']:
                bucket['collections'].append(collection)
            if title and title not in bucket['sample_titles'] and len(bucket['sample_titles']) < 3:
                bucket['sample_titles'].append(title)

    total = max(1, total_matches)
    items = []
    for layer, bucket in buckets.items():
        items.append({
            'layer': layer,
            'count': int(bucket['count']),
            'share': float(bucket['count']) / float(total),
            'collections': bucket['collections'],
            'sample_titles': bucket['sample_titles'],
        })
    return sorted(items, key=lambda item: (-int(item['count']), str(item['layer'])))

logger = logging.getLogger(__name__)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    material = "|".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(material).hexdigest()[:length]}"


def _resolve_session_id(state: GraphState) -> str:
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    for candidate in (
        state.get("session_id"),
        ui_context.get("session_id"),
        state.get("thread_id"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    return "unknown"


def _resolve_rag_user_id(state: GraphState, *, session_id: str) -> str:
    candidate = session_id or str(state.get("thread_id") or "").strip()
    try:
        from backend.graph.store import resolve_user_id

        value = str(resolve_user_id(candidate) or "").strip()
        if value:
            return value
    except Exception:
        pass

    parts = candidate.split(":")
    if len(parts) >= 2 and str(parts[1]).strip():
        return str(parts[1]).strip()
    return "anonymous"


def _build_rag_run_id(*, state: GraphState, session_id: str, query_text: str, started_at: datetime) -> str:
    direct = str(state.get("run_id") or "").strip()
    if direct:
        return direct
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    runtime = trace.get("runtime") if isinstance(trace.get("runtime"), dict) else {}
    for candidate in (trace.get("run_id"), runtime.get("run_id")):
        value = str(candidate or "").strip()
        if value:
            return value
    return _stable_id("ragrun", session_id, query_text, started_at.isoformat())


def _build_source_doc_obs_id(*, run_id: str, source_id: str, title: str, url: str, index: int) -> str:
    return _stable_id("srcdoc", run_id, source_id, title, url, index)


def _build_chunk_record_id(*, run_id: str, source_doc_id: str, chunk_index: int, chunk_text: str) -> str:
    return _stable_id("chunk", run_id, source_doc_id, chunk_index, chunk_text)


def _build_vector_source_id(*, collection: str, source_id: str, chunk_index: int, chunk_text: str) -> str:
    return _stable_id("vec", collection, source_id, chunk_index, chunk_text)


def _infer_chunk_doc_type(*, evidence_type: str, source: str, title: str, subject_type: str) -> str:
    evidence_norm = str(evidence_type or "").strip().lower()
    source_norm = str(source or "").strip().lower()
    title_norm = str(title or "").strip().lower()
    subject_norm = str(subject_type or "").strip().lower()

    if any(token in title_norm for token in ("transcript", "earnings call", "conference call")):
        return "transcript"
    if evidence_norm in {"filing", "sec", "10-k", "10-q", "8-k"} or source_norm in {"sec_edgar", "sec"}:
        return "filing"
    if evidence_norm in {"news", "selection"}:
        return "news"
    if subject_norm == "research_doc" or "research" in evidence_norm or "research" in source_norm:
        return "research"
    return "web_page"


def _chunk_profile(doc_type: str) -> dict[str, int]:
    profiles = {
        "filing": {"max_chunk_size": 1000, "overlap": 200},
        "transcript": {"max_chunk_size": 800, "overlap": 100},
        "news": {"max_chunk_size": 2000, "overlap": 0},
        "research": {"max_chunk_size": 1200, "overlap": 200},
        "web_page": {"max_chunk_size": 1200, "overlap": 200},
        "table": {"max_chunk_size": 8000, "overlap": 0},
    }
    return profiles.get(doc_type, profiles["web_page"])


def _infer_chunk_strategy(*, doc_type: str, chunk_count: int, content: str) -> str:
    if doc_type == "table":
        return "preserve_table"
    if chunk_count <= 1 and doc_type in {"news", "web_page"} and len(content) <= 2000:
        return "preserve_short_doc"
    if doc_type == "filing":
        return "recursive_filing"
    if doc_type == "transcript":
        return "qa_recursive"
    if doc_type == "research":
        return "recursive_research"
    return "recursive_generic"


def _build_source_doc_content(evidence: dict[str, Any]) -> str:
    pieces: list[str] = []
    seen: set[str] = set()

    for raw_value in (
        evidence.get("title"),
        evidence.get("content"),
        evidence.get("body"),
        evidence.get("text"),
        evidence.get("transcript"),
        evidence.get("snippet"),
        evidence.get("summary"),
        evidence.get("description"),
    ):
        value = str(raw_value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        pieces.append(value)
    return "\n\n".join(pieces).strip()


def _safe_event_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        try:
            return json.loads(json_dumps_safe(payload, ensure_ascii=False))
        except Exception:
            return {"raw": str(payload)}
    if isinstance(payload, list):
        try:
            return {"items": json.loads(json_dumps_safe(payload, ensure_ascii=False))}
        except Exception:
            return {"items": [str(item) for item in payload[:20]]}
    return {"value": str(payload)}


def _decorate_rag_hit(hit: dict[str, Any]) -> dict[str, Any]:
    result = dict(hit or {})
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    for key in (
        "run_id",
        "source_doc_id",
        "chunk_id",
        "doc_type",
        "chunk_index",
        "total_chunks",
        "chunk_strategy",
        "chunk_size",
        "chunk_overlap",
        "layer",
        "entity_scope",
        "entity_key",
        "ingest_source",
        "promotion_status",
        "doc_fingerprint",
        "parent_collection",
        "parent_run_id",
        "matched_layers",
        "matched_collections",
    ):
        if key in metadata and key not in result:
            result[key] = metadata.get(key)
    if metadata.get("source_id") and "evidence_source_id" not in result:
        result["evidence_source_id"] = metadata.get("source_id")
    if result.get("source_id") and "vector_source_id" not in result:
        result["vector_source_id"] = result.get("source_id")
    return result


async def execute_plan_stub(state: GraphState) -> dict:
    """
    Phase 3 executor scaffold:
    - Runs the step scheduler (parallel_group + cache + optional failures)
    - Default: dry-run (no live tool calls) to keep behavior deterministic
    """
    trace = state.get("trace") or {}

    plan_ir = state.get("plan_ir") or {}

    live_tools = os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false").lower() in ("true", "1", "yes", "on")

    tool_invokers = None
    agent_invokers = None
    if live_tools:
        policy = state.get("policy") or {}
        allowed_tools = policy.get("allowed_tools") if isinstance(policy, dict) else []
        allowed_agents = policy.get("allowed_agents") if isinstance(policy, dict) else []
        tool_invokers = build_tool_invokers(list(allowed_tools or []))
        agent_invokers = build_agent_invokers(list(allowed_agents or []), state)

    artifacts, exec_events = await execute_plan(
        plan_ir,
        tool_invokers=tool_invokers,
        agent_invokers=agent_invokers,
        dry_run=not live_tools,
    )
    artifacts = _merge_prior_artifacts(state.get("artifacts"), artifacts)

    # Phase 4: build a unified evidence_pool from selection (ephemeral, request-scoped).
    subject = state.get("subject") or {}
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    evidence_pool: list[dict[str, Any]] = []
    tool_diagnostics: list[dict[str, Any]] = []
    if isinstance(selection_payload, list) and selection_payload:
        for item in selection_payload:
            if not isinstance(item, dict):
                continue
            evidence_pool.append(
                {
                    "title": item.get("title") or item.get("headline") or "",
                    "url": item.get("url"),
                    "snippet": item.get("snippet") or item.get("summary"),
                    "source": item.get("source") or "selection",
                    "published_date": item.get("ts") or item.get("datetime") or item.get("published_at"),
                    "confidence": item.get("confidence", 0.7),
                    "type": item.get("type") or "selection",
                    "id": item.get("id"),
                }
            )

    # Phase 4.2+: merge tool outputs into evidence_pool (best-effort normalization).
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
    step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

    def _step_task_ids(step: dict[str, Any]) -> list[str]:
        raw = step.get("task_ids")
        values = raw if isinstance(raw, list) else []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            task_id = str(value or "").strip()
            if task_id and task_id not in seen:
                seen.add(task_id)
                result.append(task_id)
        single = str(step.get("task_id") or "").strip()
        if single and single not in seen:
            result.insert(0, single)
        return result

    def _append_tool_evidence(tool_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        # Some tools return JSON text (e.g. get_company_news). Try to parse.
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
                output = parsed
            except Exception:
                pass
        if output_is_error_like(output):
            return

        # Special-case: make technical snapshot readable in evidence list.
        if tool_name == "get_technical_snapshot" and isinstance(output, dict):
            if output.get("error"):
                evidence_pool.append(
                    {
                        "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                        "url": None,
                        "snippet": f"error={output.get('error')} points={output.get('points','N/A')}",
                        "source": tool_name,
                        "published_date": output.get("as_of"),
                        "confidence": 0.7,
                        "type": "tool",
                        "id": output.get("id") or f"{tool_name}:{step_id}",
                    }
                )
                return

            parts = []
            if output.get("close") is not None:
                parts.append(f"close={output.get('close')}")
            if output.get("ma20") is not None:
                parts.append(f"MA20={output.get('ma20')}")
            if output.get("ma50") is not None:
                parts.append(f"MA50={output.get('ma50')}")
            if output.get("rsi14") is not None:
                parts.append(f"RSI14={output.get('rsi14')}({output.get('rsi_state')})")
            if output.get("macd") is not None and output.get("macd_signal") is not None:
                parts.append(f"MACD={output.get('macd')} vs {output.get('macd_signal')}({output.get('momentum')})")
            if output.get("trend"):
                parts.append(f"trend={output.get('trend')}")

            evidence_pool.append(
                {
                    "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                    "url": None,
                    "snippet": " | ".join(parts) if parts else None,
                    "source": output.get("source") or tool_name,
                    "published_date": output.get("as_of"),
                    "confidence": 0.75,
                    "type": "tool",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
                }
            )
            return

        if tool_name in ("get_sec_filings", "get_sec_material_events", "get_sec_risk_factors") and isinstance(output, dict):
            filings = output.get("filings") or output.get("events") or []
            company_name = output.get("company_name") or output.get("ticker") or ""
            for i, filing in enumerate(filings[:10]):
                if not isinstance(filing, dict):
                    continue
                form_type = str(filing.get("form") or "SEC").strip() or "SEC"
                filing_url = str(filing.get("filing_url") or "").strip()
                filing_date = str(filing.get("filing_date") or "").strip() or None
                description = str(filing.get("primary_doc_description") or form_type).strip()
                evidence_pool.append(
                    {
                        "title": f"{company_name} {form_type} ({filing_date or 'N/A'})".strip(),
                        "url": filing_url or None,
                        "snippet": f"SEC EDGAR {form_type} filing. Filed: {filing_date or 'N/A'}. {description}",
                        "source": "sec_edgar",
                        "published_date": filing_date,
                        "confidence": 0.85,
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:{i+1}",
                    }
                )

            risk_excerpt = str(output.get("risk_factors_excerpt") or "").strip()
            if risk_excerpt:
                selected = output.get("selected_filing") if isinstance(output.get("selected_filing"), dict) else {}
                evidence_pool.append(
                    {
                        "title": f"{company_name} Risk Factors (Item 1A)".strip(),
                        "url": str(selected.get("filing_url") or "").strip() or None,
                        "snippet": risk_excerpt[:800],
                        "source": "sec_edgar",
                        "published_date": selected.get("filing_date"),
                        "confidence": 0.9,
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:risk",
                    }
                )
            return

        if tool_name == "get_local_market_filings" and isinstance(output, dict):
            filings = output.get("filings") or []
            ticker = str(output.get("ticker") or "").strip()
            market = str(output.get("market") or "").strip().upper()
            for i, filing in enumerate(filings[:10]):
                if not isinstance(filing, dict):
                    continue
                form_type = str(filing.get("form") or "filing").strip() or "filing"
                filing_url = str(filing.get("filing_url") or filing.get("url") or "").strip()
                filing_date = str(filing.get("filing_date") or filing.get("published_date") or "").strip() or None
                title = str(filing.get("title") or "").strip()
                description = str(
                    filing.get("primary_doc_description") or filing.get("snippet") or title or form_type
                ).strip()
                evidence_pool.append(
                    {
                        "title": title or f"{ticker} {form_type} ({filing_date or 'N/A'})".strip(),
                        "url": filing_url or None,
                        "snippet": f"{market} local disclosure {form_type}. Filed: {filing_date or 'N/A'}. {description}",
                        "source": filing.get("source") or "local_disclosure",
                        "published_date": filing_date,
                        "confidence": filing.get("confidence", 0.8),
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "get_authoritative_media_news" and isinstance(output, dict):
            articles = output.get("articles") or []
            for i, article in enumerate(articles[:10]):
                if not isinstance(article, dict):
                    continue
                title = str(article.get("title") or "").strip()
                url = str(article.get("url") or "").strip()
                snippet = str(article.get("snippet") or title).strip()
                article_text = f"{title} {snippet} {url}".lower()
                if "cpi" in article_text and (
                    "london stock exchange:cpi" in article_text
                    or "lse:cpi" in article_text
                    or "capita" in article_text
                ):
                    continue
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"authoritative media {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": article.get("source") or "authoritative_feed",
                        "published_date": article.get("published_date"),
                        "confidence": article.get("confidence", 0.78),
                        "type": "news",
                        "id": article.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "get_official_macro_releases" and isinstance(output, dict):
            releases = output.get("releases") or []
            for i, release in enumerate(releases[:10]):
                if not isinstance(release, dict):
                    continue
                title = str(release.get("title") or "").strip()
                url = str(release.get("url") or "").strip()
                snippet = str(release.get("snippet") or title).strip()
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"macro release {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": release.get("source") or "macro_official_feeds",
                        "published_date": release.get("published_date"),
                        "confidence": release.get("confidence", 0.82 if release.get("is_official") else 0.65),
                        "type": release.get("type") or "macro_release",
                        "id": release.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "get_earnings_call_transcripts" and isinstance(output, dict):
            transcripts = output.get("transcripts") or output.get("articles") or []
            for i, item in enumerate(transcripts[:10]):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(item.get("snippet") or title).strip()
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"earnings transcript {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": item.get("source") or "earnings_transcript",
                        "published_date": item.get("published_date"),
                        "confidence": item.get("confidence", 0.8),
                        "type": "transcript",
                        "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "fetch_url_content" and isinstance(output, dict):
            title = str(output.get("title") or output.get("url") or "URL content").strip()
            url = str(output.get("final_url") or output.get("url") or "").strip()
            snippet = str(output.get("description") or output.get("content") or output.get("error") or "").strip()
            evidence_pool.append(
                {
                    "title": title,
                    "url": url or None,
                    "snippet": snippet[:1200],
                    "source": output.get("source") or "url",
                    "published_date": None,
                    "confidence": 0.75 if output.get("content") else 0.45,
                    "type": "url",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
                }
            )
            return

        if isinstance(output, list):
            for i, item in enumerate(output[:10]):
                if not isinstance(item, dict):
                    continue
                evidence_pool.append(
                    {
                        "title": item.get("title") or item.get("headline") or f"{tool_name} result {i+1}",
                        "url": item.get("url"),
                        "snippet": item.get("snippet") or item.get("summary") or item.get("content"),
                        "source": item.get("source") or tool_name,
                        "published_date": item.get("published_date") or item.get("published_at") or item.get("datetime"),
                        "confidence": item.get("confidence", 0.6),
                        "type": item.get("type") or "tool",
                        "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        snippet = json_dumps_safe(output, ensure_ascii=False) if isinstance(output, dict) else str(output)
        evidence_pool.append(
            {
                "title": f"{tool_name} output",
                "url": None,
                "snippet": snippet[:800],
                "source": tool_name,
                "published_date": None,
                "confidence": 0.6,
                "type": "tool",
                "id": f"{tool_name}:{step_id}",
                }
            )

    jina_enrich_enabled = str(os.getenv("JINA_ENRICH_EVIDENCE", "true")).strip().lower() in {"1", "true", "yes", "on"}

    def _maybe_enrich_snippet_from_jina(url: str | None, snippet: Any) -> Any:
        if not jina_enrich_enabled:
            return snippet
        target = str(url or "").strip()
        snippet_text = str(snippet or "").strip()
        if not target.startswith(("http://", "https://")):
            return snippet
        if len(snippet_text) >= 80:
            return snippet
        if "news.google.com" in target:
            return snippet
        try:
            from backend.tools.jina_reader import fetch_via_jina
        except Exception:
            return snippet
        try:
            jina_text = fetch_via_jina(target)
            if jina_text and len(jina_text) > len(snippet_text):
                return jina_text[:800]
        except Exception:
            return snippet
        return snippet

    def _append_agent_evidence(agent_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        if isinstance(output, str):
            try:
                output = json.loads(output)
            except Exception:
                output = {"summary": output}

        if not isinstance(output, dict):
            evidence_pool.append(
                {
                    "title": f"{agent_name} output",
                    "url": None,
                    "snippet": str(output)[:800],
                    "source": agent_name,
                    "published_date": None,
                    "confidence": 0.5,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}",
                }
            )
            return

        summary = output.get("summary")
        confidence_base = output.get("confidence", 0.6)
        as_of = output.get("as_of")

        if isinstance(summary, str) and summary.strip():
            evidence_pool.append(
                {
                    "title": f"{agent_name} summary",
                    "url": None,
                    "snippet": summary.strip()[:800],
                    "source": agent_name,
                    "published_date": as_of,
                    "confidence": confidence_base if isinstance(confidence_base, (int, float)) else 0.6,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}:summary",
                }
            )

        evidence = output.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return

        for i, item in enumerate(evidence[:10]):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            snippet = item.get("text") or item.get("snippet") or item.get("summary")
            if not snippet:
                continue
            url = item.get("url")
            snippet = _maybe_enrich_snippet_from_jina(url, snippet)
            source = item.get("source") or agent_name
            evidence_pool.append(
                {
                    "title": item.get("title") or f"{agent_name} evidence {i+1}",
                    "url": url,
                    "snippet": str(snippet).strip()[:800],
                    "source": source,
                    "published_date": item.get("timestamp") or as_of,
                    "confidence": item.get("confidence", confidence_base if isinstance(confidence_base, (int, float)) else 0.6),
                    "type": "agent",
                    "id": item.get("id") or f"{agent_name}:{step_id}:{i+1}",
                }
            )

    if isinstance(step_results, dict) and step_results:
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "tool":
                if step.get("kind") == "agent":
                    agent_name = step.get("name") or ""
                    if agent_name:
                        before_count = len(evidence_pool)
                        _append_agent_evidence(str(agent_name), str(step_id), item.get("output"))
                        for evidence in evidence_pool[before_count:]:
                            if isinstance(evidence, dict):
                                evidence["step_id"] = str(step_id)
                                evidence["task_ids"] = _step_task_ids(step)
                continue
            tool_name = step.get("name") or ""
            if not tool_name:
                continue
            output = item.get("output")
            if output_is_error_like(output):
                tool_diagnostics.append(
                    build_tool_diagnostic(
                        tool_name=str(tool_name),
                        step_id=str(step_id),
                        task_ids=_step_task_ids(step),
                        output=output,
                    )
                )
                continue
            before_count = len(evidence_pool)
            _append_tool_evidence(str(tool_name), str(step_id), output)
            for evidence in evidence_pool[before_count:]:
                if isinstance(evidence, dict):
                    evidence["step_id"] = str(step_id)
                    evidence["task_ids"] = _step_task_ids(step)

    # Dedupe by url or title+source
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in evidence_pool:
        if not isinstance(e, dict):
            continue
        key = e.get("url") or f"{e.get('title')}|{e.get('source')}"
        if not key or key in seen:
            continue
        seen.add(str(key))
        deduped.append(e)
    artifacts["evidence_pool"] = deduped
    evidence_by_task: dict[str, list[dict[str, Any]]] = {}
    for evidence in deduped:
        task_ids = evidence.get("task_ids") if isinstance(evidence, dict) else None
        for task_id in [str(value or "").strip() for value in (task_ids if isinstance(task_ids, list) else [])]:
            if not task_id:
                continue
            evidence_by_task.setdefault(task_id, []).append(evidence)
    artifacts["evidence_by_task"] = evidence_by_task
    if tool_diagnostics:
        artifacts["tool_diagnostics"] = tool_diagnostics

    # Phase P0-3c: collect per-agent fallback diagnostics into artifacts
    # so synthesize/render can surface degradation info to the user.
    agent_diagnostics: dict[str, dict[str, Any]] = {}
    if isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "agent":
                continue
            agent_name = step.get("name") or step_id
            output = item.get("output")
            if not isinstance(output, dict):
                continue
            diag: dict[str, Any] = {
                "status": output.get("status", "unknown"),
                "duration_ms": output.get("duration_ms"),
            }
            fallback_reason = output.get("fallback_reason")
            if fallback_reason:
                diag["fallback_reason"] = fallback_reason
                diag["retryable"] = output.get("retryable", False)
                diag["error_stage"] = output.get("error_stage", "unknown")
            agent_diagnostics[str(agent_name)] = diag
    if agent_diagnostics:
        artifacts["agent_diagnostics"] = agent_diagnostics

    # AShareSight: RAG 已移除
    rag_trace: dict[str, Any] = {"enabled": False, "reason": "rag_removed_asharesight"}

    trace.update(
        {
            "executor": {
                "type": "dry_run" if not live_tools else "live_tools",
                "ran_steps": len((plan_ir.get("steps") or []) if isinstance(plan_ir, dict) else []),
                "error_count": len((artifacts.get("errors") or []) if isinstance(artifacts, dict) else []),
                "failure_strategy_version": FAILURE_STRATEGY_VERSION,
                "events": exec_events,
            }
        }
    )
    trace["rag"] = rag_trace
    return {"artifacts": artifacts, "trace": trace}
