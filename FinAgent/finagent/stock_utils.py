"""A 股通用工具函数（代码校验、分类、年份解析等）。

本模块包含从 cninfo.py 提取的非 cninfo 专属工具函数，
供 sina_finance.py / workflow.py 等模块复用。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

EXCLUDE_PATTERN = re.compile(r"摘要|英文版|更正|修订|补充|取消")


@dataclass
class AnnualReport:
    stock_code: str
    sec_name: str
    title: str
    announcement_time: int
    adjunct_url: str
    pdf_url: str
    report_year: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_stock(stock_code: str) -> tuple[str, str, str]:
    code = normalize_stock_code(stock_code)
    if code.startswith(("600", "601", "603", "605")):
        return "sse", "sh", "XSHG"
    if code.startswith("688"):
        return "sse", "shkcp", "XSHG"
    if code.startswith(("000", "001", "002", "003")):
        return "szse", "sz", "XSHE"
    if code.startswith(("300", "301")):
        return "szse", "szcy", "XSHE"
    raise ValueError(f"暂不支持或无法识别的 A 股代码: {stock_code}")


def normalize_stock_code(stock_code: str) -> str:
    code = stock_code.strip().upper().split(".")[0]
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"股票代码应为 6 位数字: {stock_code}")
    return code


def to_order_book_id(stock_code: str) -> str:
    code = normalize_stock_code(stock_code)
    _, _, suffix = classify_stock(code)
    return f"{code}.{suffix}"


def parse_report_year(title: str) -> int | None:
    match = re.search(r"(20\d{2}|19\d{2})\s*年\s*年度报告", title)
    return int(match.group(1)) if match else None


def default_as_of(value: str | None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()
