"""复刻工作流：新浪财经年报文本获取 + MD&A 提取

用法（在 FinAgent 目录下运行）：
    python tests/test_sina_mda_extraction.py

或在项目根目录运行：
    PYTHONPATH=FinAgent python FinAgent/tests/test_sina_mda_extraction.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    _finagent_root = Path(__file__).parent.parent.resolve()
    if str(_finagent_root) not in sys.path:
        sys.path.insert(0, str(_finagent_root))

from finagent.sina import fetch_latest_report_text
from finagent.pdf_text import extract_mda


def main() -> None:
    stock_code: str = "600519"
    year: int | None = 2025

    report = fetch_latest_report_text(stock_code, year=year)
    if not report:
        print(f"未找到 {stock_code} {year} 年的年报")
        return

    mda = extract_mda(report.text)
    print(mda.mda_text)


if __name__ == "__main__":
    main()