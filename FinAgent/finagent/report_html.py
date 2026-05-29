from __future__ import annotations

import html
import re
from pathlib import Path

REPORT_STYLES = """
:root {
  color-scheme: light;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --bg-soft: #f9fafb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 16px;
  line-height: 1.65;
  color: var(--text);
  background: #fff;
}
.page {
  max-width: 980px;
  margin: 0 auto;
  padding: 2rem 1.5rem 3rem;
  font-size: 1rem;
}
h1 {
  margin: 0 0 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 3px solid var(--accent);
  font-size: 1.75rem;
  font-weight: 700;
}
h2 {
  margin: 2.25rem 0 1rem;
  color: #1e40af;
  font-size: 1.35rem;
  font-weight: 700;
}
h3 {
  margin: 1.35rem 0 0.65rem;
  color: #111827;
  font-size: 1.12rem;
  font-weight: 600;
}
h4 {
  margin: 1.1rem 0 0.55rem;
  color: #111827;
  font-size: 1.02rem;
  font-weight: 600;
}
h5, h6 {
  margin: 1rem 0 0.5rem;
  color: #111827;
  font-size: 1rem;
  font-weight: 600;
}
.section-body {
  font-size: 1rem;
}
.section-body h3, .section-body h4, .section-body h5, .section-body h6 {
  font-size: 1.05rem;
  font-weight: 600;
}
h3.chart-group {
  margin-top: 1.5rem;
  font-size: 1.08rem;
  color: #374151;
}
.draft-banner {
  margin: 0 0 1.25rem;
  padding: 0.85rem 1rem;
  border-left: 4px solid #f59e0b;
  background: #fffbeb;
  color: #92400e;
  border-radius: 6px;
  font-size: 0.95rem;
}
.draft-banner p { margin: 0; }
ul, ol { margin: 0.75rem 0; padding-left: 1.4rem; font-size: 1rem; }
li { margin: 0.35rem 0; }
hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: 0.95rem;
}
th, td {
  border: 1px solid var(--border);
  padding: 0.55rem 0.75rem;
  vertical-align: top;
}
th { background: var(--bg-soft); text-align: left; }
.metrics td:last-child { text-align: right; white-space: nowrap; }
.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem;
  margin: 1rem 0 1.5rem;
}
.chart-figure {
  margin: 0;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-soft);
  text-align: center;
}
.chart-figure img {
  display: block;
  width: 100%;
  height: auto;
  margin: 0 auto;
  border-radius: 6px;
  background: #fff;
}
.chart-figure figcaption {
  margin-bottom: 0.65rem;
  font-weight: 600;
  color: #111827;
}
.section-body img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0.5rem auto 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.report-figure {
  margin: 0.75rem 0 0.25rem;
  text-align: center;
}
.report-figure img {
  margin: 0 auto;
}
.figure-note {
  margin: 0 0 1.75rem;
  padding: 0.7rem 0.9rem;
  border-left: 3px solid var(--accent);
  background: var(--bg-soft);
  font-size: 0.94rem;
  color: #374151;
  line-height: 1.6;
}
.figure-note strong { color: #1e40af; }
.meta-list { color: var(--muted); }
.disclaimer {
  margin-top: 2rem;
  padding: 1rem 1.25rem;
  border-radius: 10px;
  background: var(--bg-soft);
  color: var(--muted);
  font-size: 0.95rem;
}
.disclaimer h2 {
  margin: 0 0 0.5rem;
  font-size: 1.05rem;
  color: var(--muted);
}
@media (max-width: 640px) {
  .page { padding: 1.25rem 1rem 2rem; }
  h1 { font-size: 1.45rem; }
}
"""


def write_html_report(content: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def wrap_html_document(*, title: str, body_html: str) -> str:
    safe_title = html.escape(title)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"  <title>{safe_title}</title>\n"
        f"  <style>{REPORT_STYLES}</style>\n"
        "</head>\n"
        "<body>\n"
        f'  <main class="page">{body_html}</main>\n'
        "</body>\n"
        "</html>\n"
    )


def markdown_to_html(text: str, *, in_section: bool = False) -> str:
    if not text or not str(text).strip():
        return ""
    normalized = str(text).replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", normalized)
    parts: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0]
        if first_line.strip().startswith("|"):
            parts.append(_markdown_table_to_html(block.split("\n")))
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", first_line)
        if heading and "\n" not in block:
            level = _html_heading_level(len(heading.group(1)), in_section=in_section)
            parts.append(f"<h{level}>{_inline_markdown(heading.group(2).strip())}</h{level}>")
            continue
        if heading:
            level = _html_heading_level(len(heading.group(1)), in_section=in_section)
            rest = block.split("\n", 1)[1].strip() if "\n" in block else ""
            parts.append(f"<h{level}>{_inline_markdown(heading.group(2).strip())}</h{level}>")
            if rest:
                parts.append(markdown_to_html(rest, in_section=in_section))
            continue
        if block.strip() == "---":
            parts.append("<hr />")
            continue
        if _is_markdown_list_block(block):
            parts.append(_markdown_list_to_html(block))
            continue
        if re.match(r"^\*\*图注\*\*", block.strip()):
            note = re.sub(r"^\*\*图注\*\*\s*", "", block.strip())
            parts.append(f'<p class="figure-note">{_inline_markdown(note)}</p>')
            continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", block.strip()):
            parts.append(_markdown_image_to_figure(block.strip()))
            continue
        parts.append(f"<p>{_inline_markdown(block.replace(chr(10), ' '))}</p>")
    return "\n".join(parts)


def _html_heading_level(hash_count: int, *, in_section: bool) -> int:
    if in_section:
        return 3 if hash_count <= 4 else 4
    return min(max(hash_count, 1), 6)


def chart_grid_html(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    figures = []
    for caption, path in items:
        safe_caption = html.escape(caption)
        safe_path = html.escape(path.replace("\\", "/"), quote=True)
        figures.append(
            "<figure class=\"chart-figure\">"
            f"<figcaption>{safe_caption}</figcaption>"
            f'<img src="{safe_path}" alt="{safe_caption}" loading="lazy" />'
            "</figure>"
        )
    return f'<div class="chart-grid">{"".join(figures)}</div>'


def _inline_markdown(text: str) -> str:
    chunks: list[str] = []
    pos = 0
    for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        if match.start() > pos:
            chunks.append(_inline_markdown_text(text[pos : match.start()]))
        alt = html.escape(match.group(1))
        src = html.escape(match.group(2).replace("\\", "/"), quote=True)
        chunks.append(f'<img src="{src}" alt="{alt}" loading="lazy" />')
        pos = match.end()
    if pos < len(text):
        chunks.append(_inline_markdown_text(text[pos:]))
    return "".join(chunks)


def _inline_markdown_text(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def _markdown_image_to_figure(line: str) -> str:
    match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
    if not match:
        return f"<p>{_inline_markdown(line)}</p>"
    caption = match.group(1) or "图表"
    path = match.group(2).replace("\\", "/")
    safe_caption = html.escape(caption)
    safe_path = html.escape(path, quote=True)
    return (
        '<figure class="report-figure">'
        f'<img src="{safe_path}" alt="{safe_caption}" loading="lazy" />'
        "</figure>"
    )


def _is_markdown_list_block(block: str) -> bool:
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            return True
        return False
    return False


def _markdown_list_to_html(block: str) -> str:
    lines = [line for line in block.split("\n") if line.strip()]
    if not lines:
        return ""
    ordered = bool(re.match(r"^\d+\.\s+", lines[0].strip()))
    tag = "ol" if ordered else "ul"
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if ordered:
            content = re.sub(r"^\d+\.\s+", "", stripped)
        else:
            content = re.sub(r"^[-*+]\s+", "", stripped)
        items.append(f"<li>{_inline_markdown(content)}</li>")
    return f"<{tag}>{''.join(items)}</{tag}>"


def _markdown_table_to_html(lines: list[str]) -> str:
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$", stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    head = rows[0]
    body = rows[1:]
    html_parts = ["<table><thead><tr>"]
    html_parts.extend(f"<th>{_inline_markdown(cell)}</th>" for cell in head)
    html_parts.append("</tr></thead>")
    if body:
        html_parts.append("<tbody>")
        for row in body:
            html_parts.append("<tr>")
            html_parts.extend(f"<td>{_inline_markdown(cell)}</td>" for cell in row)
            html_parts.append("</tr>")
        html_parts.append("</tbody>")
    html_parts.append("</table>")
    return "".join(html_parts)
