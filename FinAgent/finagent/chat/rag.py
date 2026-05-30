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


def search_chunks(chunks: list[TextChunk], query: str, *, top_k: int = 6) -> list[tuple[TextChunk, float]]:
    q_tokens = _tokenize(query)
    if not q_tokens or not chunks:
        return []
    scored: list[tuple[TextChunk, float]] = []
    for chunk in chunks:
        c_tokens = _tokenize(chunk.text)
        if not c_tokens:
            continue
        overlap = len(q_tokens & c_tokens)
        if overlap == 0 and query[:8] not in chunk.text:
            continue
        score = overlap / (len(q_tokens) ** 0.5)
        if any(token in chunk.text for token in q_tokens if len(token) >= 3):
            score += 0.5
        scored.append((chunk, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


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
