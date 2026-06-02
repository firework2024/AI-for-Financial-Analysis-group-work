from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .report_writing import FUNDAMENTAL_NARRATIVE_SECTION

DISCLAIMER = "本报告仅供课程研究与信息展示，不构成投资建议。"
MISSING_LABEL = "数据缺失"
TABLE_EMPTY = "—"
_LLM_REVISE_PREAMBLE = re.compile(
    r"^(?:好的[，,].*?(?:重写|修订|验证 Agent|意见|根据).*?(?:\n\n|\n---\n|\n(?=#)))|"
    r"^(?:根据验证 Agent[^\n]*(?:\n|$))+",
    re.DOTALL,
)

_FIELD_NAME = r"[a-z][a-z0-9_]{1,}"
_QUARTER_CODE = r"20\d{2}q[1-4]"
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")


def _split_md_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _join_md_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _drop_table_columns(block: list[str], drop_headers: set[str]) -> list[str]:
    if len(block) < 2 or not _TABLE_SEP_RE.match(block[1].strip()):
        return block
    headers = _split_md_table_row(block[0])
    drop_indices = {i for i, header in enumerate(headers) if header in drop_headers}
    if not drop_indices:
        return block
    kept_headers = [headers[i] for i in range(len(headers)) if i not in drop_indices]
    rows = [
        _join_md_table_row(kept_headers),
        _join_md_table_row(["---"] * len(kept_headers)),
    ]
    for row_line in block[2:]:
        cells = _split_md_table_row(row_line)
        kept = [cells[i] for i in range(len(headers)) if i not in drop_indices]
        if kept:
            rows.append(_join_md_table_row(kept))
    return rows


def _strip_data_source_columns_from_tables(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    drop_headers = {"数据来源", "数据来源说明"}
    while i < len(lines):
        line = lines[i]
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1].strip())
        ):
            block = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j])
                j += 1
            out.extend(_drop_table_columns(block, drop_headers))
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _normalize_tsv_tables(text: str) -> str:
    """把模型输出的制表符表格标准化为 Markdown 表格。"""
    lines = str(text or "").splitlines()
    if not lines:
        return str(text or "")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "\t" not in line:
            out.append(line)
            i += 1
            continue
        block: list[str] = []
        j = i
        while j < len(lines):
            raw = lines[j]
            if not raw.strip():
                break
            if "\t" not in raw:
                break
            cells = [cell.strip() for cell in re.split(r"\t+", raw.strip()) if cell.strip()]
            if len(cells) < 2:
                break
            block.append("| " + " | ".join(cells) + " |")
            j += 1
        if len(block) >= 2:
            col_count = len(_split_md_table_row(block[0]))
            out.append(block[0])
            out.append("| " + " | ".join(["---"] * col_count) + " |")
            out.extend(block[1:])
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


_PIPELINE_ONLY_SECTIONS = ("字段来源概览", "数据说明", "年报来源", "免责声明")


def strip_pipeline_only_sections(text: str) -> str:
    """去掉模型正文末尾误生成的流水线附录（字段来源概览等）。"""
    result = str(text or "").strip()
    if not result:
        return result
    earliest: int | None = None
    for title in _PIPELINE_ONLY_SECTIONS:
        match = re.search(rf"^#{{1,6}}\s*{re.escape(title)}\s*$", result, re.MULTILINE)
        if match is not None and (earliest is None or match.start() < earliest):
            earliest = match.start()
    if earliest is not None:
        result = result[:earliest].rstrip()
        result = re.sub(r"\n---+\s*$", "", result).strip()
    return result


def polish_field_refs(text: str) -> str:
    """去掉冗余的数据源/字段元数据；保留字段名时用反引号供前端统一标签样式。"""
    if not text:
        return text

    result = str(text)
    field = _FIELD_NAME
    quarter = _QUARTER_CODE

    result = re.sub(r"[（(]\s*来源[：:][^）)]+[）)]", "", result)
    result = _strip_data_source_columns_from_tables(result)
    result = re.sub(
        rf"[（(]\s*`?quarter`?\s*为\s*`?({quarter})`?\s*[）)]",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(rf"根据\s*`?({field})`?\s*数据[，,]?\s*", "", result, flags=re.IGNORECASE)
    result = re.sub(rf"基于\s*`?({field})`?\s*数据[，,]?\s*", "", result, flags=re.IGNORECASE)
    result = re.sub(rf"基于\s*`?({field})`?\s*中", "", result, flags=re.IGNORECASE)
    result = re.sub(rf"`?({field})`?\s*字段", "", result, flags=re.IGNORECASE)
    result = re.sub(
        rf"基于米筐数据\s*`?({field})`?\s*字段[，,]?\s*",
        "基于米筐数据，",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(rf"JSON\s*中的\s*`?({field})`?\s*", "", result, flags=re.IGNORECASE)

    def _wrap_token(match: re.Match[str]) -> str:
        token = match.group(1)
        if "_" not in token and not re.fullmatch(quarter, token, re.IGNORECASE):
            return token
        return f"`{token}`"

    result = re.sub(rf"(?<![`/\w])({field}|{quarter})(?![`\w])", _wrap_token, result, flags=re.IGNORECASE)
    result = re.sub(r"[，,]\s*[，,]", "，", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


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

    text = _strip_thinking_blocks(text)

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
    text = _normalize_tsv_tables(text)
    text = _expand_inline_labels(text)
    from .report_writing import normalize_core_conclusion_markdown

    text = normalize_core_conclusion_markdown(text)
    text = _structure_section_readability(text, section_name)
    text = _normalize_body_headings(text)
    if section_name in (FUNDAMENTAL_NARRATIVE_SECTION, "投资总监分析") or "投资总监" in section_name:
        text = strip_pipeline_only_sections(text)
    text = polish_field_refs(text)
    skip_lead = ("执行摘要", "免责声明", "数据与工具", "验证", "投资总监", FUNDAMENTAL_NARRATIVE_SECTION, "经营与财务")
    if not any(skip in section_name for skip in skip_lead):
        from .report_writing import ensure_section_lead_conclusion

        text = ensure_section_lead_conclusion(text, section_name)
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


def _strip_thinking_blocks(text: str) -> str:
    cleaned = re.sub(
        r"<(?:redacted_)?thinking>.*?</(?:redacted_)?thinking>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"<(?:redacted_)?thinking>[\s\S]*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _strip_llm_preamble(text: str) -> str:
    cleaned = _LLM_REVISE_PREAMBLE.sub("", text.strip()).strip()
    lines = cleaned.splitlines()
    while lines:
        line = lines[0].strip()
        if not line:
            lines.pop(0)
            continue
        if line == "---":
            lines.pop(0)
            continue
        if re.match(r"^好的[，,]", line) and re.search(
            r"(?:重写|修订|汇总|验证|根据|遵照|指示|反馈|意见|输入信息|严格基于)",
            line,
        ):
            lines.pop(0)
            continue
        if re.match(r"^根据验证 Agent", line):
            lines.pop(0)
            continue
        break
    cleaned = "\n".join(lines).strip()
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


_TOPIC_MARKER_REWRITES: tuple[tuple[str, str], ...] = (
    ("基本面方面", "**基本面**"),
    ("融资融券方面", "**融资融券**"),
    ("资金流向数据", "**资金流向**"),
    ("宏观利率方面", "**宏观利率**"),
    ("数据局限包括", "**数据局限**"),
)

_RISK_SECTION_NAMES = ("综合风险与数据局限", "综合风险", "数据覆盖与局限")


def _structure_section_readability(text: str, section_name: str) -> str:
    """拆分超长段落、主题小标题与编号式数据局限列表。"""
    if not text.strip():
        return text
    if any(name in section_name for name in _RISK_SECTION_NAMES):
        pass  # 章节级 **核心结论** 由 ensure_section_lead_conclusion 统一处理
    text = _promote_topic_subheadings(text)
    text = _normalize_numbered_limitations(text)
    text = _split_long_paragraphs(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _ensure_risk_opening_subheading(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("**") or stripped.startswith("#"):
        return text
    if re.match(r"截至|近\d+个?交易日|从\d", stripped):
        return f"**价格与波动**\n\n{text}"
    return text


def _promote_topic_subheadings(text: str) -> str:
    result = text
    for marker, heading in _TOPIC_MARKER_REWRITES:
        result = re.sub(
            rf"(?<=[。；;!?！？])\s*{re.escape(marker)}[，,：:]?\s*",
            f"\n\n{heading}\n\n",
            result,
        )
        result = re.sub(
            rf"(?<=\n\n)\s*{re.escape(marker)}[，,：:]?\s*",
            f"{heading}\n\n",
            result,
        )
        if result.startswith(marker):
            result = re.sub(rf"^{re.escape(marker)}[，,：:]?\s*", f"{heading}\n\n", result, count=1)
    # 「宏观利率方面未出现但单独一段以宏观利率开头」
    result = re.sub(
        r"(?<=[。；;])\s*(宏观利率方面[，,]\s*)",
        r"\n\n**宏观利率**\n\n",
        result,
    )
    result = re.sub(
        r"(?<=[。；;])\s*(宏观利率[，,]\s*)",
        r"\n\n**宏观利率**\n\n",
        result,
    )
    return result


def _normalize_numbered_limitations(text: str) -> str:
    patterns = (
        r"数据局限包括[：:]\s*(.+)$",
        r"\*\*数据局限\*\*\s*\n\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            continue
        body = match.group(1).strip()
        if not re.search(r"\d+[）)]", body):
            continue
        items = re.findall(r"\d+[）)]([^；;\n]+)", body)
        if not items:
            continue
        bullets = "\n".join(f"- {item.strip().rstrip('。')}" for item in items if item.strip())
        prefix = text[: match.start()].rstrip()
        if prefix.endswith("**数据局限**"):
            return f"{prefix}\n\n{bullets}".strip()
        return f"{prefix}\n\n**数据局限**\n\n{bullets}".strip()
    return text


def _split_long_paragraphs(text: str, *, max_chars: int = 280) -> str:
    blocks: list[str] = []
    for para in re.split(r"\n\n+", text):
        stripped = para.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("- "):
            blocks.append(stripped)
            continue
        if re.fullmatch(r"\*\*.+\*\*", stripped):
            blocks.append(stripped)
            continue
        if len(stripped) <= max_chars:
            blocks.append(stripped)
            continue
        sentences = [part for part in re.split(r"(?<=[。！？!?；;])", stripped) if part.strip()]
        if len(sentences) <= 1:
            if len(stripped) > max_chars:
                blocks.extend(_hard_split_text(stripped, max_chars=max_chars))
            else:
                blocks.append(stripped)
            continue
        chunk = ""
        for sentence in sentences:
            if chunk and len(chunk) + len(sentence) > max_chars:
                blocks.append(chunk.strip())
                chunk = sentence
            else:
                chunk += sentence
        if chunk.strip():
            blocks.append(chunk.strip())
    return "\n\n".join(blocks)


def _hard_split_text(text: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            pivot = max(window.rfind("，"), window.rfind(","), window.rfind(" "))
            if pivot > max_chars // 3:
                end = start + pivot + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


def section_writing_style_hint(section_name: str) -> str:
    from .report_writing import section_writing_guide

    return section_writing_guide(section_name)


_CHART_PATH_PATTERN = r"(?:charts|outputs)[\\/][\w./-]+\.(?:png|jpe?g|gif|webp)"


def normalize_chart_ref_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").lstrip("./")
    for prefix in ("FinAgent/outputs/", "outputs/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def section_anchor(title: str, used: set[str] | None = None) -> str:
    used = used if used is not None else set()
    base = re.sub(r"\s+", "-", str(title).strip())
    base = re.sub(r"[^\w\u4e00-\u9fff-]", "", base).lower() or "section"
    anchor = base
    index = 2
    while anchor in used:
        anchor = f"{base}-{index}"
        index += 1
    used.add(anchor)
    return anchor


def build_report_toc(section_titles: list[str]) -> list[dict[str, str]]:
    used: set[str] = set()
    entries: list[dict[str, str]] = []
    for title in section_titles:
        text = str(title or "").strip()
        if not text:
            continue
        entries.append({"title": text, "id": section_anchor(text, used)})
    return entries


def toc_id_map(entries: list[dict[str, str]]) -> dict[str, str]:
    return {str(item["title"]): str(item["id"]) for item in entries if item.get("title") and item.get("id")}


def render_toc_markdown(entries: list[dict[str, str]]) -> list[str]:
    if not entries:
        return []
    lines = ["## 目录", ""]
    lines.extend(f"- [{item['title']}](#{item['id']})" for item in entries)
    lines.append("")
    return lines


def render_toc_html(entries: list[dict[str, str]]) -> str:
    if not entries:
        return ""
    items = "".join(
        f'<li><a href="#{html.escape(item["id"])}">{html.escape(item["title"])}</a></li>'
        for item in entries
    )
    return (
        f'<nav class="report-toc">'
        f'<details class="report-toc-details">'
        f'<summary>目录 <span class="report-toc-count">{len(entries)} 节</span></summary>'
        f"<ul>{items}</ul>"
        f"</details></nav>"
    )


def markdown_section(title: str, anchor: str, body: str) -> list[str]:
    return [f'<a id="{anchor}"></a>', "", f"## {title}", body.strip(), ""]


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
