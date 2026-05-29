from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class MdaExtraction:
    full_text: str
    mda_text: str
    confidence: str
    start_heading: str | None
    end_heading: str | None

    @property
    def raw_preview(self) -> str:
        """PDF 原文截取，仅供调试；报告展示请使用 mda_summary_agent 提炼结果。"""
        text = re.sub(r"\s+", " ", self.mda_text).strip()
        return text[:3000]


START_PATTERNS = [
    r"管理层讨论与分析",
    r"经营情况讨论与分析",
    r"董事会报告",
]
END_PATTERNS = [
    r"\n\s*第四节",
    r"\n\s*第[四五六七八九十]+节\s*(公司治理|重要事项|股份变动|环境和社会责任|财务报告)",
]


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))
    doc.close()
    return "\n".join(parts)


def extract_mda(text: str) -> MdaExtraction:
    normalized = text.replace("\r\n", "\n")
    start_match = _first_match(normalized, START_PATTERNS, skip_toc=True)
    if not start_match:
        return MdaExtraction(normalized, normalized[:30000], "low", None, None)

    end_match = _first_match(normalized[start_match.end() :], END_PATTERNS)
    start = start_match.start()
    if end_match:
        end = start_match.end() + end_match.start()
        confidence = "high"
        end_heading = end_match.group(0)
    else:
        end = min(start + 50000, len(normalized))
        confidence = "medium"
        end_heading = None
    return MdaExtraction(
        full_text=normalized,
        mda_text=normalized[start:end].strip(),
        confidence=confidence,
        start_heading=start_match.group(0),
        end_heading=end_heading,
    )


def _first_match(text: str, patterns: list[str], skip_toc: bool = False) -> re.Match[str] | None:
    matches: list[re.Match[str]] = []
    for pattern in patterns:
        matches.extend(re.finditer(pattern, text, re.IGNORECASE))
    if skip_toc:
        body_matches = [match for match in matches if not _looks_like_toc_hit(text, match)]
        if body_matches:
            matches = body_matches
    return min(matches, key=lambda match: match.start()) if matches else None


def _looks_like_toc_hit(text: str, match: re.Match[str]) -> bool:
    window = text[max(0, match.start() - 120) : match.end() + 120]
    if match.start() < 3000 and ("..." in window or "……" in window):
        return True
    return window.count(".") > 20 or window.count("…") > 10
