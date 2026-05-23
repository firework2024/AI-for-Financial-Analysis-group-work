from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_financial_framework_text() -> str:
    path = Path(__file__).resolve().parent.parent / "财务分析智能体_知识框架提炼.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_financial_framework_excerpt() -> str:
    text = load_financial_framework_text()
    # 直接用完整框架做提示，避免在首版里因摘要过度裁剪遗漏规则。
    return text
