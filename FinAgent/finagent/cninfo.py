"""巨潮资讯网数据获取模块（遗留/备用）。

已由 sina_finance.py 替代为主要数据源。此模块保留仅作为回退使用。
"""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from .stock_utils import (
    EXCLUDE_PATTERN,
    AnnualReport,
    classify_stock,
    default_as_of,
    normalize_stock_code,
    parse_report_year,
)

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
DOWNLOAD_BASE = "http://static.cninfo.com.cn/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "X-Requested-With": "XMLHttpRequest",
}
STOCK_LIST_URLS = (
    "http://www.cninfo.com.cn/new/data/szse_stock.json",
    "http://www.cninfo.com.cn/new/data/sse_stock.json",
)
_ORG_ID_CACHE: dict[str, str] | None = None
_STOCK_NAME_CACHE: dict[str, str] | None = None


def _fallback_org_id(stock_code: str, column: str) -> str:
    code = normalize_stock_code(stock_code)
    if column == "sse":
        if code.startswith("688"):
            return f"gshk0{code}"
        return f"gssh0{code}"
    return f"gssz0{code}"


def _load_org_id_map(session: requests.Session | None = None) -> dict[str, str]:
    global _ORG_ID_CACHE
    if _ORG_ID_CACHE is not None:
        return _ORG_ID_CACHE
    http = session or requests.Session()
    mapping: dict[str, str] = {}
    for url in STOCK_LIST_URLS:
        try:
            response = http.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for item in data.get("stockList") or []:
            code = str(item.get("code") or "").strip()
            org_id = str(item.get("orgId") or "").strip()
            if code and org_id:
                mapping[code] = org_id
    _ORG_ID_CACHE = mapping
    return mapping


def _load_stock_name_map(session: requests.Session | None = None) -> dict[str, str]:
    """简称/全称 → 6 位股票代码。"""
    global _STOCK_NAME_CACHE
    if _STOCK_NAME_CACHE is not None:
        return _STOCK_NAME_CACHE
    http = session or requests.Session()
    mapping: dict[str, str] = {}
    for url in STOCK_LIST_URLS:
        try:
            response = http.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for item in data.get("stockList") or []:
            code = str(item.get("code") or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            for key in ("zwjc", "secName", "name", "abbr"):
                name = str(item.get(key) or "").strip()
                if len(name) >= 2:
                    mapping[name] = code
    _STOCK_NAME_CACHE = mapping
    return mapping


def lookup_stock_code_by_name(text: str, session: requests.Session | None = None) -> str | None:
    q = str(text or "").strip()
    if len(q) < 2:
        return None
    names = _load_stock_name_map(session)
    for name in sorted(names.keys(), key=len, reverse=True):
        if name in q:
            return names[name]
    return None


def org_id_for(stock_code: str, column: str | None = None, session: requests.Session | None = None) -> str:
    code = normalize_stock_code(stock_code)
    org_id = _load_org_id_map(session).get(code)
    if org_id:
        return org_id
    col = column or classify_stock(code)[0]
    return _fallback_org_id(code, col)


def _stock_param(stock_code: str, column: str, session: requests.Session | None = None) -> str:
    code = normalize_stock_code(stock_code)
    return f"{code},{org_id_for(code, column, session)}"


def fetch_annual_reports(
    stock_code: str,
    start_date: str,
    end_date: str,
    page_size: int = 30,
    session: requests.Session | None = None,
) -> list[AnnualReport]:
    code = normalize_stock_code(stock_code)
    column, plate, _ = classify_stock(code)
    http = session or requests.Session()
    params = {
        "stock": _stock_param(code, column, http),
        "tabName": "fulltext",
        "pageNum": "1",
        "pageSize": str(page_size),
        "column": column,
        "plate": plate,
        "category": "category_ndbg_szsh;",
        "seDate": f"{start_date}~{end_date}",
        "isHLtitle": "true",
    }
    response = http.post(QUERY_URL, data=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    announcements = response.json().get("announcements") or []
    reports: list[AnnualReport] = []
    for ann in announcements:
        title = ann.get("announcementTitle", "")
        if "年度报告" not in title or EXCLUDE_PATTERN.search(title):
            continue
        adjunct_url = ann.get("adjunctUrl", "")
        reports.append(
            AnnualReport(
                stock_code=ann.get("secCode", code),
                sec_name=ann.get("secName", ""),
                title=title,
                announcement_time=int(ann.get("announcementTime", 0)),
                adjunct_url=adjunct_url,
                pdf_url=DOWNLOAD_BASE + adjunct_url,
                report_year=parse_report_year(title),
            )
        )
    return sorted(reports, key=lambda item: item.announcement_time, reverse=True)


def latest_annual_report(stock_code: str, as_of: date) -> AnnualReport:
    from .progress import info

    end = as_of.strftime("%Y-%m-%d")
    start = f"{as_of.year - 5}-01-01"
    info(f"查询区间: {start} ~ {end}")
    reports = fetch_annual_reports(stock_code, start, end)
    if not reports:
        raise RuntimeError(
            f"未在巨潮资讯找到 {stock_code} 截至 {end} 的正式年报。"
            "可能原因：该时段尚未披露年报、查询截止日期过早，或巨潮接口暂时不可用。"
            "请尝试将「截止日期」设为最新披露日之后，或稍后重试。"
        )
    info(f"共找到 {len(reports)} 份年报，选用最新一份")
    return reports[0]


def download_report(report: AnnualReport, output_dir: Path, use_cache: bool = True) -> Path:
    from .progress import info, ok

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", f"{report.stock_code}_{report.sec_name}_{report.title}.pdf")
    target = output_dir / safe_name
    if use_cache and target.exists() and target.stat().st_size > 0:
        info(f"使用缓存: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        return target
    last_error: Exception | None = None
    info(f"开始下载: {report.pdf_url}")
    for attempt in range(3):
        try:
            with requests.get(report.pdf_url, headers=HEADERS, timeout=120, stream=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with target.open("wb") as handle:
                    for chunk in resp.iter_content(8192):
                        if chunk:
                            handle.write(chunk)
                            downloaded += len(chunk)
                if total:
                    ok(f"下载完成: {downloaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB")
                else:
                    ok(f"下载完成: {downloaded / 1024 / 1024:.1f} MB")
            return target
        except Exception as exc:  # pragma: no cover - network timing dependent
            last_error = exc
            info(f"第 {attempt + 1} 次重试...")
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"下载年报失败: {report.pdf_url}") from last_error
