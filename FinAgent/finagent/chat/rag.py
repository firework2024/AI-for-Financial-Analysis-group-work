"""轻量 RAG：分块 + 关键词检索（无额外向量库依赖）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class TextChunk:
    id: str
    text: str
    source: str
    meta: dict[str, Any]


def _tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "").lower())
    tokens: set[str] = set()
    for word in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_.]{2,}", cleaned):
        tokens.add(word)
        if len(word) >= 4 and re.search(r"[\u4e00-\u9fff]", word):
            for i in range(len(word) - 1):
                tokens.add(word[i : i + 2])
    return tokens


def chunk_text(
    text: str,
    *,
    source: str,
    chunk_size: int = 700,
    overlap: int = 120,
    meta: dict[str, Any] | None = None,
) -> list[TextChunk]:
    cleaned = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
        if len(paragraph) <= chunk_size:
            buffer = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + chunk_size, len(paragraph))
            chunks.append(paragraph[start:end])
            if end >= len(paragraph):
                break
            start = max(end - overlap, start + 1)
        buffer = ""
    if buffer:
        chunks.append(buffer)

    base_meta = dict(meta or {})
    return [
        TextChunk(id=f"{source}#{index}", text=body, source=source, meta=base_meta | {"index": index})
        for index, body in enumerate(chunks)
        if body.strip()
    ]


_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "总资产": ("资产总计", "资产合计", "资产总额"),
    "营收": ("营业收入", "收入"),
    "净利润": ("归母净利润", "净利"),
    "负债": ("总负债", "资产负债"),
    "现金流": ("经营现金流", "经营活动产生的现金流量"),
    "股价": ("收盘", "最新价"),
    "融资": ("融资余额", "两融"),
}


def expand_query_terms(query: str) -> set[str]:
    tokens = _tokenize(query)
    expanded = set(tokens)
    q = str(query or "")
    for key, synonyms in _QUERY_SYNONYMS.items():
        if key in q:
            expanded.update(_tokenize(key))
            for synonym in synonyms:
                expanded.update(_tokenize(synonym))
    return expanded


def _score_chunk(chunk: TextChunk, q_tokens: set[str], *, stock_code: str | None) -> float:
    c_tokens = _tokenize(chunk.text)
    if not c_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens)
    if overlap == 0 and not any(token in chunk.text for token in q_tokens if len(token) >= 2):
        return 0.0
    score = overlap / (len(q_tokens) ** 0.5)
    if any(token in chunk.text for token in q_tokens if len(token) >= 3):
        score += 0.5
    if stock_code and stock_code in chunk.text:
        score += 0.8
    meta = chunk.meta or {}
    if stock_code and meta.get("stock_code") == stock_code:
        score += 0.6
    if meta.get("kind") in {"summary", "section", "analysis", "mda", "pit_financials"}:
        score += 0.15
    return score


def search_chunks(
    chunks: list[TextChunk],
    query: str,
    *,
    top_k: int = 6,
    stock_code: str | None = None,
) -> list[tuple[TextChunk, float]]:
    q_tokens = expand_query_terms(query)
    if not q_tokens or not chunks:
        return []

    scored: list[tuple[TextChunk, float]] = []
    for chunk in chunks:
        score = _score_chunk(chunk, q_tokens, stock_code=stock_code)
        if score > 0:
            scored.append((chunk, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    hits = scored[:top_k]
    if hits and hits[0][1] >= 0.45:
        return hits

    # 财务类问题：按同义词再扫一遍，避免「总资产」与「资产总计」零重叠
    fallback_tokens = expand_query_terms(query)
    for chunk in chunks:
        if any(token in chunk.text for token in fallback_tokens if len(token) >= 2):
            score = _score_chunk(chunk, fallback_tokens, stock_code=stock_code)
            if score <= 0:
                score = 0.35
            scored.append((chunk, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    deduped: list[tuple[TextChunk, float]] = []
    seen: set[str] = set()
    for chunk, score in scored:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        deduped.append((chunk, score))
        if len(deduped) >= top_k:
            break
    return deduped


def format_hits(hits: list[tuple[TextChunk, float]]) -> list[dict[str, Any]]:
    return [
        {
            "source": chunk.source,
            "score": round(score, 3),
            "text": chunk.text[:900],
            "meta": chunk.meta,
        }
        for chunk, score in hits
    ]
