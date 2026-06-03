"""对话回答格式：去掉易空图/不适配短行情的图块。"""

from __future__ import annotations

import re

from ..chart_catalog import CHAT_EXCLUDED_CHART_KEYS, chart_caption

# 与 CHAT_EXCLUDED_CHART_KEYS 对应的中文图题（用于剥离 LLM 仿报告体例的输出）
_CHAT_STRIP_CAPTIONS: tuple[str, ...] = tuple(
    chart_caption(key) for key in CHAT_EXCLUDED_CHART_KEYS
)


def sanitize_chat_answer(text: str) -> str:
    """移除对话中不应出现的图块（如 MA20/MA60 均线图，短 K 线时常为空）。"""
    if not text or not str(text).strip():
        return str(text or "")
    out = str(text)
    for caption in _CHAT_STRIP_CAPTIONS:
        if not caption:
            continue
        # 只删图题 + 可选图片行 + 可选图注，避免误删后续正文段落
        pattern = (
            rf"####\s*图\s*·\s*{re.escape(caption)}"
            rf"(?:\s*\n+!\[[^\]]*\]\([^)]+\))?"
            rf"(?:\s*\n+\*\*图注\*\*[^\n]*)?"
            rf"\s*\n+"
        )
        out = re.sub(pattern, "\n", out, flags=re.IGNORECASE)
    for key in CHAT_EXCLUDED_CHART_KEYS:
        out = re.sub(
            rf"!\[[^\]]*\]\([^)]*{re.escape(key)}[^)]*\)\s*",
            "",
            out,
            flags=re.IGNORECASE,
        )
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
