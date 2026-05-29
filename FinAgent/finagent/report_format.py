from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

DISCLAIMER = "本报告仅供课程研究与信息展示，不构成投资建议。"
MISSING_LABEL = "数据缺失"
TABLE_EMPTY = "—"
_LLM_REVISE_PREAMBLE = re.compile(
    r"^(?:好的[，,].*?(?:重写|修订|验证 Agent|意见|根据).*?(?:\n\n|\n---\n|\n(?=#)))|"
    r"^(?:根据验证 Agent[^\n]*(?:\n|$))+",
    re.DOTALL,
)


def disclaimer_lines() -> list[str]:
    return ["## 免责声明", DISCLAIMER, ""]


def format_generated_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def format_generated_at_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_report(markdown: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def normalize_section_text(content: Any, section_name: str) -> str:
    """把章节内容统一成 Markdown 正文，兼容模型返回的 JSON 包裹。"""
    text = str(content or "").strip()
    if not text:
        return "_本节暂无可用内容。_"

    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*?)\n```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    if text.startswith("{"):
        extracted = _extract_section_body_from_json(text)
        if extracted is not None:
            text = extracted.strip()

    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        head = re.match(r"^#{1,6}\s*(.+?)\s*$", lines[0])
        if head:
            title = head.group(1).strip()
            if title == section_name or section_name in title or title in section_name:
                lines.pop(0)
    text = "\n".join(lines).strip()
    text = _strip_llm_preamble(text)
    text = _expand_inline_labels(text)
    text = _normalize_body_headings(text)
    return text or "_本节暂无可用内容。_"


def normalize_sections(sections: dict[str, str]) -> dict[str, str]:
    return {name: normalize_section_text(content, name) for name, content in sections.items()}


def dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def fmt_money(value: Any, *, missing: str = TABLE_EMPTY) -> str:
    if value is None:
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    return f"{number / 100000000:.2f} 亿"


def fmt_num(value: Any, *, missing: str = MISSING_LABEL) -> str:
    if value is None:
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f} 亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.2f} 万"
    return f"{number:.4f}".rstrip("0").rstrip(".")


def fmt_pct(
    value: Any,
    *,
    missing: str = MISSING_LABEL,
    style: str = "auto",
) -> str:
    """style=auto: |x|<=1 视为小数；style=ratio: 直接按 Python 比例格式化（0.05 -> 5.0%）。"""
    if value is None:
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    if style == "ratio":
        return f"{number:.1%}"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.2f}%"


def fmt_table_num(value: Any) -> str:
    if value is None:
        return TABLE_EMPTY
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return TABLE_EMPTY


def _extract_section_body_from_json(text: str) -> str | None:
    keys = ("revised_section", "content", "markdown", "section", "body", "text")
    try:
        obj = json.loads(text)
    except Exception:
        match = re.search(
            r'"(?:revised_section|content|markdown|section|body|text)"\s*:\s*"(.*)"\s*}?\s*$',
            text,
            re.DOTALL,
        )
        if not match:
            return None
        raw = match.group(1)
        try:
            return json.loads('"' + raw + '"')
        except Exception:
            return raw.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value
        strings = [str(v) for v in obj.values() if isinstance(v, str) and v.strip()]
        if strings:
            return "\n\n".join(strings)
    return None


def _strip_llm_preamble(text: str) -> str:
    cleaned = _LLM_REVISE_PREAMBLE.sub("", text.strip()).strip()
    cleaned = re.sub(r"^\s*---\s*\n+", "", cleaned)
    return cleaned.strip()


_INLINE_SECTION_LABELS = ("图表解读", "数据局限", "图表参考", "风险提示")
_INLINE_LABEL_PATTERN = re.compile(
    r"(?<![#\n])\*\*(" + "|".join(re.escape(label) for label in _INLINE_SECTION_LABELS) + r")\*\*[：:]"
)


def _expand_inline_labels(text: str) -> str:
    """把段内的 **图表解读**： / **数据局限**： 拆成独立 #### 小节。"""
    expanded = _INLINE_LABEL_PATTERN.sub(r"\n\n#### \1\n\n", text)
    expanded = re.sub(r"\n{3,}", "\n\n", expanded)
    return expanded.strip()


def _normalize_body_headings(markdown: str) -> str:
    """章节正文标题统一为 ### / ####，避免 ##### 在预览里小于正文字号。"""
    out: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})(\s+.*)$", line)
        if not match:
            out.append(line)
            continue
        level = len(match.group(1))
        new_level = 3 if level <= 3 else 4
        out.append("#" * new_level + match.group(2))
    return "\n".join(out)


_CHART_PATH_PATTERN = r"(?:charts|outputs)[\\/][\w./-]+\.(?:png|jpe?g|gif|webp)"


def normalize_chart_ref_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").lstrip("./")
    for prefix in ("FinAgent/outputs/", "outputs/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def clean_chart_prose(text: str) -> str:
    """清理正文中的图表路径/占位引用；图表由编排阶段以「图+图注」独立块插入。"""
    if not text:
        return text

    result = str(text)
    result = re.sub(r"!\[[^\]]*\]\((?:charts|outputs)[\\/][^)]+\)", "", result, flags=re.IGNORECASE)
    result = re.sub(rf"`({_CHART_PATH_PATTERN})`", "", result, flags=re.IGNORECASE)
    result = re.sub(
        r"[a-zA-Z0-9_]+\s*图表\s*[（(]\s*`?(?:charts|outputs)[\\/][^`)`\s]+\.(?:png|jpe?g|gif|webp)`?\s*[）)]",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        rf"(?:请参考|参考)\s*(?:`?({_CHART_PATH_PATTERN})`?\s*)?(?:图表|上述图表|如下图表)[，,；;：:]?",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(r"`([a-zA-Z0-9_]+\.(?:png|jpe?g|gif|webp))`", "", result, flags=re.IGNORECASE)
    result = re.sub(
        r"\*\*图表解读\*\*[：:]\s*[^\n]*(?:charts|outputs)[\\/][^\n。]*。?",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(r"\*\*图表参考\*\*[：:][^\n]*\n?", "", result)
    result = re.sub(r"该图(?:表)?(?:直观)?(?:展示|验证|反映)[^。]*。", "", result)
    result = re.sub(r"图中(?:可|能)[^。]*。", "", result)
    result = re.sub(r"[，,]\s*[，,]", "，", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
