"""年报 MD&A 文本规范化与检索（与 chat/rag 分块策略一致）。"""

from __future__ import annotations

import re
from typing import Any

from ..pdf_text import MdaExtraction


def normalize_mda_text(text: str) -> str:
    """入库前规范化：统一换行、压缩空行，保留段落结构。"""
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\x00", "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def mda_storage_payload(mda: MdaExtraction) -> dict[str, Any]:
    """从 PDF 解析结果生成统一入库结构。"""
    text = normalize_mda_text(mda.mda_text)
    return {
        "mda_text": text,
        "mda_meta": {
            "confidence": mda.confidence,
            "start_heading": mda.start_heading,
            "end_heading": mda.end_heading,
            "char_count": len(text),
            "raw_preview": normalize_mda_text(mda.raw_preview)[:3000],
        },
    }


def search_mda_hits(mda_text: str, query: str, *, top_k: int = 4) -> list[dict[str, Any]]:
    """在已存 MD&A 全文中按段落分块检索，保留原文格式。"""
    # 延迟导入以打断 datastore <-> chat 的模块初始化循环依赖。
    from ..chat.rag import chunk_text, format_hits, search_chunks

    text = normalize_mda_text(mda_text)
    if not text:
        return []
    chunks = chunk_text(text, source="annual_report:mda", meta={"kind": "mda"})
    hits = search_chunks(chunks, query, top_k=top_k)
    return format_hits(hits)


def merge_mda_meta(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if value is not None:
            merged[key] = value
    return merged
