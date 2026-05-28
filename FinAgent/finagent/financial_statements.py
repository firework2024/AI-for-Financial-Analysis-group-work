"""从年报第八节财务报表提取财务字段值。

用法:
    from finagent.financial_statements import extract_financial_fields
    fields = extract_financial_fields(annual_report_text, report_year=2025)
    # fields[2025]["revenue"] -> 172054171890.91
    # fields[2024]["revenue"] -> 174144069958.25
"""

from __future__ import annotations

import re
from typing import Any

from .fields import FIELD_DEFS

# ---------------------------------------------------------------------------
# 字段名柔性匹配
# ---------------------------------------------------------------------------
_FIELD_LABELS: dict[str, str] = {}
for fd in FIELD_DEFS:
    _FIELD_LABELS[fd.cn] = fd.field
    for alias in fd.aliases:
        _FIELD_LABELS[alias] = fd.field


def _flex_match(label: str) -> str | None:
    """对财务报表行标签做最长子串匹配，返回 FIELD_DEFS 字段名。"""
    # 1) 精确匹配
    if label in _FIELD_LABELS:
        return _FIELD_LABELS[label]

    # 2) 去掉编号前缀 / 其中前缀 再精确匹配
    cleaned = re.sub(r"^[一二三四五六七八九十]+[、.]", "", label)
    cleaned = re.sub(r"^其中[：:]", "", cleaned)
    if cleaned in _FIELD_LABELS:
        return _FIELD_LABELS[cleaned]
    for alias, fname in _FIELD_LABELS.items():
        if cleaned == alias:
            return fname

    # 3) 已知的难以通过通用规则匹配的变体（优先于一般子串匹配）
    KNOWN_MISMATCHES: dict[str, str] = {
        "归属于母公司所有者权益": "equity_parent_company",
        "归属于母公司股东的净利润": "net_profit_parent_company",
        "扣除非经常性损益后的净利润": "net_profit_deduct_non_recurring_pnl",
        "资产减值损失": "adjust_asset_impairment",
    }
    for key, fname in KNOWN_MISMATCHES.items():
        if key in label:
            return fname

    # 4) 子串匹配——取最长，排除长度过短造成误匹配
    MIN_SUBSTR_LEN = 3
    candidates: list[tuple[int, str]] = []
    for fd in FIELD_DEFS:
        if fd.cn in label:
            candidates.append((len(fd.cn), fd.field))
            continue
        for alias in fd.aliases:
            if alias in label:
                candidates.append((len(alias), fd.field))
        # 截掉"合计""净额"后缀后尝试
        trimmed = fd.cn
        for suffix in ("合计", "净额", "净额合计"):
            if trimmed.endswith(suffix):
                base = trimmed[: -len(suffix)]
                if len(base) >= MIN_SUBSTR_LEN and base in label:
                    candidates.append((len(base), fd.field))
                    break
    if candidates:
        candidates.sort(key=lambda x: (-x[0], x[1] if x[0] > 0 else 0))
        best_len, best_field = candidates[0]
        # 如果最佳匹配长度 > 2，优于已知变体的则返回
        # 否则让步给已知变体继续往上走
        return best_field

    return None


# ---------------------------------------------------------------------------
# 基础判别函数
# ---------------------------------------------------------------------------
def _is_num(s: str) -> bool:
    s = s.strip().replace(",", "")
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_num(s: str) -> float | None:
    try:
        return float(s.strip().replace(",", ""))
    except ValueError:
        return None


def _is_ref(s: str) -> bool:
    """是否为附注编号（小整数、/、-）。"""
    s = s.strip()
    if s in ("/", "-", ""):
        return True
    try:
        return int(s) < 1000
    except ValueError:
        return False


def _is_strong_ref(s: str) -> bool:
    """更强力的附注编号判断——排除了同时是财务数值的可能。"""
    s = s.strip()
    if s in ("/", "-"):
        return True
    try:
        n = int(s)
        # 附注编号通常 < 100 且没有小数
        return n < 100 and "." not in s
    except ValueError:
        return False


def _is_label(s: str) -> bool:
    """是否为一个中文标签行。"""
    if not s:
        return False
    if not any("一" <= c <= "鿿" for c in s):
        return False
    digit_ratio = sum(1 for c in s if c.isdigit()) / max(len(s), 1)
    return digit_ratio < 0.5


# ---------------------------------------------------------------------------
# 单表解析
# ---------------------------------------------------------------------------
def _parse_section(lines: list[str], start: int, end: int) -> list[dict[str, Any]]:
    """解析一张财务报表（资产负债表/利润表/现金流量表）。

    返回 [{field, val(本年), prev(上年)}, ...]
    """
    # 跳过表头行（项目、附注、单位等）
    i = start
    while i < end and lines[i] in ("项目", "附注", "单位：元币种：人民币"):
        i += 1

    items: list[dict[str, Any]] = []
    while i < end:
        line = lines[i]

        # 跳过公司负责人签名行
        if "公司负责人" in line:
            i += 1
            continue

        if not _is_label(line):
            i += 1
            continue

        # 收集本行标签之后连续的 编号/数值 行
        values: list[str] = []
        j = i + 1
        while j < end:
            nxt = lines[j]
            if _is_label(nxt):
                break
            if _is_num(nxt) or _is_ref(nxt):
                values.append(nxt)
            j += 1

        n = len(values)
        v_cy: float | None = None
        v_py: float | None = None

        if n >= 3 and _is_ref(values[0]) and _is_num(values[1]):
            # ref + val[0] + val[1]  ...
            v_cy = _parse_num(values[1])
            if _is_num(values[2]):
                v_py = _parse_num(values[2])
            i += 1 + 3
        elif n >= 2 and _is_strong_ref(values[0]) and _is_num(values[1]):
            # strong-ref + val（附注编号 + 唯一数值，另一列空）
            v_cy = _parse_num(values[1])
            i += 1 + 2
        elif n >= 2 and _is_num(values[0]) and _is_num(values[1]):
            # val[0] + val[1]（小计/合计行无附注编号）
            v_cy = _parse_num(values[0])
            v_py = _parse_num(values[1])
            i += 1 + 2
        elif n >= 2 and _is_ref(values[0]) and _is_num(values[1]):
            # ref + val（宽匹配，兜底）
            v_cy = _parse_num(values[1])
            i += 1 + 2
        elif n == 1 and _is_num(values[0]):
            # 只有单个数值
            v_cy = _parse_num(values[0])
            i += 2
        else:
            # 无有效数值，当作空行
            i += 1
            continue

        fname = _flex_match(line)
        if fname and v_cy is not None:
            items.append({"field": fname, "val": v_cy, "prev": v_py})

    return items


# ---------------------------------------------------------------------------
# 找报表段边界
# ---------------------------------------------------------------------------
def _find_consolidated_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    """定位合并资产负债表/利润表/现金流量表的起止行号（排除母公司报表）。"""
    keywords = {
        "bs": "合并资产负债表",
        "is": "合并利润表",
        "cf": "合并现金流量表",
    }
    positions: dict[str, int] = {}
    for k, kw in keywords.items():
        for idx, line in enumerate(lines):
            if kw in line:
                positions[k] = idx
                break

    if not positions:
        return {}

    length = len(lines)

    # 所有母公司报表标题都作为截断标记
    parent_markers = (
        "母公司资产负债表", "母公司利润表", "母公司现金流量表",
        "合并所有者权益变动表",
    )

    def _end_after(begin: int) -> int:
        for i in range(begin + 1, length):
            if any(m in lines[i] for m in parent_markers):
                return i
        return length

    return {
        "bs": (positions.get("bs", 0), min(positions.get("is", length), _end_after(positions.get("bs", 0)))),
        "is": (positions.get("is", 0), min(positions.get("cf", length), _end_after(positions.get("is", 0)))),
        "cf": (positions.get("cf", 0), _end_after(positions.get("cf", 0))),
    }


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------
def extract_financial_fields(
    text: str,
    report_year: int | None = None,
) -> dict[int, dict[str, float]]:
    """从年报全文提取合并财务报表中的财务字段值。

    Parameters
    ----------
    text : str
        年报全文（新浪财经纯文本）。
    report_year : int | None
        报告所属年份（从年报标题中提取的年份）。
        为 None 时只返回 ``{"current": {…}, "prior": {…}}``。

    Returns
    -------
    dict[int, dict[str, float]]
        ``{report_year: {field: value}, report_year-1: {field: value}}``
        或 ``{"current": {…}, "prior": {…}}`` （report_year 为 None 时）。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    ranges = _find_consolidated_ranges(lines)

    if not ranges:
        return {} if report_year else {"current": {}, "prior": {}}

    # 逐表解析——只保留首次出现的值（合并口径），
    # 用首次命中而非 > 0 比较，避免负值被跳过。
    all_items: dict[str, dict[str, float]] = {}
    for sec_name, (sec_start, sec_end) in ranges.items():
        if sec_start >= sec_end:
            continue
        for item in _parse_section(lines, sec_start, sec_end):
            fname = item["field"]
            if fname not in all_items:
                all_items[fname] = {"current": item["val"] or 0.0, "prior": item["prev"] or 0.0}

    if report_year is not None:
        return {
            report_year: {f: v["current"] for f, v in all_items.items() if v["current"]},
            report_year - 1: {f: v["prior"] for f, v in all_items.items() if v["prior"]},
        }

    return {  # type: ignore[return-value]
        "current": {f: v["current"] for f, v in all_items.items() if v["current"]},
        "prior": {f: v["prior"] for f, v in all_items.items() if v["prior"]},
    }
