from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://money.finance.sina.com.cn",
}
BASE = "https://money.finance.sina.com.cn"
EXCLUDE_PATTERN = re.compile(r"摘要|英文版|更正|修订|补充")


@dataclass
class SinaReport:
    stock_code: str
    title: str
    pub_date: str
    text: str
    pdf_url: str | None
    detail_url: str
    char_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "title": self.title,
            "pub_date": self.pub_date,
            "char_count": self.char_count,
            "pdf_url": self.pdf_url,
            "detail_url": self.detail_url,
        }


def fetch_latest_report_text(stock_code: str, year: int | None = None) -> SinaReport | None:
    """
    从新浪财经获取指定股票的纯文本年报。

    Parameters
    ----------
    stock_code : str
        6位股票代码，如 "600519"
    year : int, optional
        指定年份，如 2025。不指定则取最新年报。

    Returns
    -------
    SinaReport or None
    """
    code = _normalize(stock_code)

    list_url = f"{BASE}/corp/go.php/vCB_Bulletin/stockid/{code}/page_type/ndbg.phtml"
    resp = requests.get(list_url, headers=HEADERS, timeout=30)
    resp.encoding = "gbk"

    pattern = re.compile(
        r"href='/corp/view/vCB_AllBulletinDetail\.php\?stockid=" + code + r"&id=(\d+)'[^>]*>(.*?)</a>"
    )
    matches = pattern.findall(resp.text)

    target_id = None
    target_title = None
    for ann_id, title in matches:
        clean = re.sub(r"<[^>]+>", "", title).strip()
        if EXCLUDE_PATTERN.search(clean) or "年度报告" not in clean:
            continue
        if year and f"{year}年年度报告" not in clean:
            continue
        target_id = ann_id
        target_title = clean
        break

    if not target_id:
        return None

    return _fetch_detail(code, target_id, target_title)


def _fetch_detail(code: str, ann_id: str, title: str) -> SinaReport | None:
    detail_url = f"{BASE}/corp/view/vCB_AllBulletinDetail.php?stockid={code}&id={ann_id}"
    resp2 = requests.get(detail_url, headers=HEADERS, timeout=30)
    resp2.encoding = "gbk"

    soup = BeautifulSoup(resp2.text, "html.parser")

    # 提取 PDF 下载链接
    pdf_url: str | None = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".PDF" in href or ".pdf" in href:
            pdf_url = href if href.startswith("http") else f"{BASE}{href}"
            break

    # 提取公告日期
    date_m = re.search(r"公告日期[：:]\s*(\d{4}-\d{2}-\d{2})", resp2.text)
    pub_date = date_m.group(1) if date_m else ""

    # 提取正文：找最大的 <td>
    best_text = ""
    max_len = 0
    for td in soup.find_all("td"):
        t = td.get_text(separator="\n", strip=True)
        if len(t) > max_len:
            max_len = len(t)
            best_text = t

    # 清理正文：去掉导航栏等头部杂质和尾部免责声明
    lines = best_text.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if "股份有限公司" in line or "年年度报告" in line:
            start_idx = i
            break

    end_idx = len(lines)
    for i in range(len(lines) - 1, max(start_idx, len(lines) - 30), -1):
        if any(k in lines[i] for k in ["免责声明", "版权声明", "返回页首", "新浪简介"]):
            end_idx = i
            break

    cleaned = "\n".join(lines[start_idx:end_idx]).strip()

    return SinaReport(
        stock_code=code,
        title=title,
        pub_date=pub_date,
        text=cleaned,
        pdf_url=pdf_url,
        detail_url=detail_url,
        char_count=len(cleaned),
    )


def _normalize(stock_code: str) -> str:
    code = stock_code.strip().upper().split(".")[0]
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"股票代码应为6位数字: {stock_code}")
    return code


def save_report_text(report: SinaReport, output_dir: Path, use_cache: bool = True) -> Path:
    """保存年报文本到文件（UTF-8），返回文件路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[\\/:*?\"<>|]+", "_", f"{report.stock_code}_{report.title}.txt")
    target = output_dir / safe_name
    if use_cache and target.exists() and target.stat().st_size > 0:
        return target
    target.write_text(report.text, encoding="utf-8")
    return target