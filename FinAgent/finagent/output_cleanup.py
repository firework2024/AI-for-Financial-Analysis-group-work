"""清理 outputs 中不需要的图表文件，并可选剥离报告正文里的图/表块。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .chart_catalog import (
    CHART_CAPTIONS,
    DEFAULT_PURGE_OUTPUT_CHART_KEYS,
    DEFAULT_PURGE_OUTPUT_TABLE_KEYS,
    TABLE_CAPTIONS,
)


def resolve_purge_chart_keys(
    *,
    use_defaults: bool = True,
    extra: set[str] | None = None,
) -> set[str]:
    keys: set[str] = set()
    if use_defaults:
        keys |= set(DEFAULT_PURGE_OUTPUT_CHART_KEYS)
    if extra:
        keys |= {str(item).strip() for item in extra if str(item).strip()}
    return keys


def resolve_purge_table_keys(
    *,
    use_defaults: bool = False,
    extra: set[str] | None = None,
) -> set[str]:
    keys: set[str] = set()
    if use_defaults:
        keys |= set(DEFAULT_PURGE_OUTPUT_TABLE_KEYS)
    if extra:
        keys |= {str(item).strip() for item in extra if str(item).strip()}
    return keys


def discover_report_stems(outputs_dir: Path) -> list[str]:
    stems: set[str] = set()
    for path in outputs_dir.glob("*_multi_agent_report.md"):
        stems.add(path.stem)
    charts_root = outputs_dir / "charts"
    if charts_root.is_dir():
        for child in charts_root.iterdir():
            if child.is_dir():
                stems.add(child.name)
    return sorted(stems)


def chart_file_candidates(outputs_dir: Path, report_stem: str, chart_key: str) -> list[Path]:
    names = {f"{chart_key}.png", f"{chart_key}.jpg", f"{chart_key}.jpeg", f"{chart_key}.webp"}
    found: list[Path] = []
    charts_dir = outputs_dir / "charts" / report_stem
    if charts_dir.is_dir():
        for name in names:
            path = charts_dir / name
            if path.is_file():
                found.append(path)
    for path in outputs_dir.rglob(f"{chart_key}.png"):
        if report_stem in path.as_posix():
            found.append(path)
    return sorted(set(found))


def purge_chart_files(
    outputs_dir: Path,
    chart_keys: set[str],
    *,
    report_stem: str | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """删除 outputs/charts 下指定 chart_key 的 PNG 等文件。"""
    outputs_dir = outputs_dir.resolve()
    stems = [report_stem] if report_stem else discover_report_stems(outputs_dir)
    deleted: list[Path] = []
    for stem in stems:
        for key in sorted(chart_keys):
            for path in chart_file_candidates(outputs_dir, stem, key):
                deleted.append(path)
                if not dry_run:
                    path.unlink(missing_ok=True)
    return deleted


def strip_chart_blocks(text: str, chart_keys: set[str]) -> str:
    if not text or not chart_keys:
        return text
    result = str(text)
    for key in chart_keys:
        pattern = re.compile(
            rf"####\s*图\s*[·•]\s*[^\n]*\n\n!\[[^\]]*\]\([^)]*{re.escape(key)}\.[^)]+\)\n\n"
            rf"(?:\*\*图注\*\*[^\n]*\n)?",
            re.MULTILINE,
        )
        result = pattern.sub("", result)
        loose = re.compile(rf"!\[[^\]]*\]\([^)]*{re.escape(key)}\.[^)]+\)\n?", re.MULTILINE)
        result = loose.sub("", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def strip_table_blocks(text: str, table_keys: set[str]) -> str:
    if not text or not table_keys:
        return text
    result = str(text)
    for key in table_keys:
        caption = TABLE_CAPTIONS.get(key, key.replace("_", " "))
        pattern = re.compile(
            rf"####\s*表\s*[·•]\s*{re.escape(caption)}[^\n]*\n\n(?:\|[^\n]+\n)+",
            re.MULTILINE,
        )
        result = pattern.sub("", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def strip_visual_blocks(
    text: str,
    *,
    chart_keys: set[str] | None = None,
    table_keys: set[str] | None = None,
) -> str:
    result = str(text or "")
    if chart_keys:
        result = strip_chart_blocks(result, chart_keys)
    if table_keys:
        result = strip_table_blocks(result, table_keys)
    return result


def _patch_json_payload(payload: dict[str, Any], chart_keys: set[str], table_keys: set[str]) -> dict[str, Any]:
    out = dict(payload)
    charts = out.get("charts")
    if isinstance(charts, dict):
        out["charts"] = {name: path for name, path in charts.items() if name not in chart_keys}

    sections = out.get("sections")
    if isinstance(sections, dict):
        out["sections"] = {
            name: strip_visual_blocks(content, chart_keys=chart_keys, table_keys=table_keys)
            for name, content in sections.items()
        }

    placement = out.get("chart_placement")
    if isinstance(placement, dict):
        placements = placement.get("placements")
        if isinstance(placements, list):
            new_placements = []
            for item in placements:
                if not isinstance(item, dict):
                    continue
                charts_list = item.get("charts")
                if isinstance(charts_list, list):
                    filtered = [name for name in charts_list if str(name) not in chart_keys]
                    if not filtered:
                        continue
                    item = {**item, "charts": filtered}
                new_placements.append(item)
            placement = {**placement, "placements": new_placements}
        out["chart_placement"] = placement

    visual_meta = out.get("visual_meta")
    if isinstance(visual_meta, list):
        out["visual_meta"] = [
            item
            for item in visual_meta
            if not (isinstance(item, dict) and str(item.get("visual_key") or item.get("chart")) in chart_keys)
        ]
    return out


def clean_report_bundle(
    outputs_dir: Path,
    report_stem: str,
    *,
    chart_keys: set[str],
    table_keys: set[str] | None = None,
    strip_reports: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """清理单个报告：删图文件，并可选更新 md/html/json。"""
    outputs_dir = outputs_dir.resolve()
    table_keys = table_keys or set()
    deleted_files = purge_chart_files(outputs_dir, chart_keys, report_stem=report_stem, dry_run=dry_run)
    updated: list[str] = []

    if not strip_reports:
        return {"report": report_stem, "deleted_files": [str(p) for p in deleted_files], "updated_files": updated}

    md_path = outputs_dir / f"{report_stem}.md"
    html_path = outputs_dir / f"{report_stem}.html"
    json_path = outputs_dir / f"{report_stem}.json"

    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        cleaned = strip_visual_blocks(text, chart_keys=chart_keys, table_keys=table_keys)
        if cleaned != text:
            updated.append(str(md_path))
            if not dry_run:
                md_path.write_text(cleaned, encoding="utf-8")

    if html_path.is_file():
        text = html_path.read_text(encoding="utf-8")
        cleaned = text
        for key in chart_keys:
            cleaned = re.sub(rf"<h3>图\s*[·•]\s*[^<]*</h3>\s*<p><img[^>]*{re.escape(key)}[^>]*></p>", "", cleaned)
            cleaned = re.sub(rf"<img[^>]*{re.escape(key)}[^>]*>", "", cleaned)
        for key in table_keys:
            caption = TABLE_CAPTIONS.get(key, key.replace("_", " "))
            cleaned = re.sub(
                rf"<h3>表\s*[·•]\s*{re.escape(caption)}[^<]*</h3>\s*<table[\s\S]*?</table>",
                "",
                cleaned,
            )
        if cleaned != text:
            updated.append(str(html_path))
            if not dry_run:
                html_path.write_text(cleaned, encoding="utf-8")

    if json_path.is_file():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        patched = _patch_json_payload(payload, chart_keys, table_keys)
        if patched != payload:
            updated.append(str(json_path))
            if not dry_run:
                json_path.write_text(json.dumps(patched, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "report": report_stem,
        "deleted_files": [str(p) for p in deleted_files],
        "updated_files": updated,
        "chart_keys": sorted(chart_keys),
        "table_keys": sorted(table_keys),
    }


def purge_chart_paths(paths: dict[str, str]) -> list[Path]:
    """按 charts 字典里的路径删除磁盘文件（供生成流程 prune 时调用）。"""
    deleted: list[Path] = []
    for path_str in paths.values():
        path = Path(path_str)
        if not path.is_file():
            continue
        deleted.append(path)
        path.unlink(missing_ok=True)
    return deleted


def chart_key_labels(chart_keys: set[str]) -> list[str]:
    return [f"{key} ({CHART_CAPTIONS.get(key, key)})" for key in sorted(chart_keys)]
