"""新浪财经年报纯文本获取模块。

替代 cninfo.py 作为 FinAgent 的主要年报数据源。
通过 HTTP GET 请求新浪财经公告页面，解析 HTML 中的纯文本年报内容。
无需 PDF 下载和解析，直接得到可用于 NLP 分析的纯文本。

接口文档见 新浪财经年报批量下载指南.md
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from .stock_utils import (
    EXCLUDE_PATTERN,
    AnnualReport,
    default_as_of,
    normalize_stock_code,
    parse_report_year,
)

BASE_URL = "https://money.finance.sina.com.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://money.finance.sina.com.cn",
}
ANNOUNCEMENT_RE = re.compile(
    r"href='/corp/view/vCB_AllBulletinDetail\.php\?stockid=(\d+)&id=(\d+)'[^>]*>(.*?)</a>",
    re.DOTALL,
)
DATE_RE = re.compile(r"公告日期[：:]\s*(\d{4}-\d{2}-\d{2})")
DETAIL_URL_TPL = BASE_URL + "/corp/view/vCB_AllBulletinDetail.php?stockid={stock_code}&id={ann_id}"


@dataclass
class SinaFetchResult:
    """新浪财经年报获取结果。

    Attributes:
        report:      AnnualReport 元数据（复用 stock_utils 中的 dataclass）
        full_text:   清洗后的年报纯文本正文
        detail_url:  新浪详情页 URL
    """
    report: AnnualReport
    full_text: str
    detail_url: str


# ── 内部工具函数 ──────────────────────────────────────────


def _sec_name_from_title(title: str, stock_code: str) -> str:
    """从公告标题提取公司简称，如 '乾照光电：2025年年度报告' → '乾照光电'。"""
    # 优先级：冒号前的内容
    for sep in ("：", ":", " ", "　"):
        parts = title.split(sep)
        if parts[0] and parts[0] != title:
            return parts[0].strip()
    # 回退：从正文中提取（由调用方处理）
    return stock_code


def _date_to_timestamp(date_str: str) -> int:
    """将 '2026-03-21' 格式的日期转换为 UTC 毫秒级时间戳。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_list_page(stock_code: str) -> str:
    """请求新浪财经年报列表页（ndbg），返回原始 HTML（GBK 解码）。"""
    code = normalize_stock_code(stock_code)
    url = f"{BASE_URL}/corp/go.php/vCB_Bulletin/stockid/{code}/page_type/ndbg.phtml"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.encoding = "gbk"  # ★ 绝对不能省略
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        raise RuntimeError(
            f"新浪财经列表页请求失败: {stock_code} - {exc}"
        ) from exc


def _parse_list_page(html: str, stock_code: str, year: int | None = None) -> tuple[str, str] | None:
    """从列表页 HTML 中解析目标年报的 (id, title)，找不到返回 None。

    按时间倒序（页面默认），返回第一个匹配的正式年报（过滤摘要/英文版/更正等）。
    如果指定 year，只匹配对应年份。
    """
    for m in ANNOUNCEMENT_RE.finditer(html):
        _, ann_id, raw_title = m.groups()
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        if EXCLUDE_PATTERN.search(title) or "年度报告" not in title:
            continue
        if year is not None and f"{year}年年度报告" not in title:
            continue
        return ann_id, title
    return None


def _fetch_detail_page(stock_code: str, ann_id: str) -> str:
    """请求详情页，返回原始 HTML（GBK 解码）。"""
    url = DETAIL_URL_TPL.format(stock_code=stock_code, ann_id=ann_id)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.encoding = "gbk"
    resp.raise_for_status()
    return resp.text


def _extract_pdf_url(soup: BeautifulSoup) -> str:
    """从详情页 HTML 中提取可选的 PDF 下载链接。"""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".PDF" in href or ".pdf" in href:
            if href.startswith("http"):
                return href
            return BASE_URL + href
    return ""


def _extract_date(raw_html: str) -> str:
    """从详情页原始 HTML 中提取公告日期。"""
    m = DATE_RE.search(raw_html)
    return m.group(1) if m else ""


def _extract_text(soup: BeautifulSoup) -> str:
    """核心提取：从详情页中找到最大的 <td>，取其文本内容。"""
    best_text = ""
    max_len = 0
    for td in soup.find_all("td"):
        t = td.get_text(separator="\n", strip=True)
        if len(t) > max_len:
            max_len = len(t)
            best_text = t

    # 备用方案：如果 <td> 策略失效，从 <body> 提取
    if not best_text and soup.find("body"):
        body = soup.find("body")
        if body:
            best_text = body.get_text(separator="\n", strip=True)

    return best_text


def _clean_text(raw_text: str) -> str:
    """清洗文本：去掉导航栏/页首/页脚等非正文杂质。

    正文起点：包含 '股份有限公司' 或 '年年度报告' 的行。
    正文终点：包含 '免责声明'、'版权声明' 等关键词的行（在文件尾部查找）。
    """
    lines = raw_text.split("\n")
    # 找起点
    start = 0
    for i, line in enumerate(lines):
        if "股份有限公司" in line or "年年度报告" in line:
            start = i
            break
    # 找终点（从尾部向上，最多搜索 30 行）
    end = len(lines)
    search_start = max(start, len(lines) - 30)
    for i in range(len(lines) - 1, search_start - 1, -1):
        if any(k in lines[i] for k in ["免责声明", "版权声明", "返回页首", "新浪简介"]):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def _build_annual_report(
    stock_code: str,
    ann_id: str,
    title: str,
    pub_date: str,
    pdf_url: str,
) -> AnnualReport:
    """构造 AnnualReport 元数据对象。"""
    code = normalize_stock_code(stock_code)
    sec_name = _sec_name_from_title(title, code)
    return AnnualReport(
        stock_code=code,
        sec_name=sec_name,
        title=title,
        announcement_time=_date_to_timestamp(pub_date) if pub_date else 0,
        adjunct_url="",
        pdf_url=pdf_url,
        report_year=parse_report_year(title),
    )


# ── 公开 API ──────────────────────────────────────────────


def latest_annual_report(stock_code: str, as_of: datetime.date | None = None) -> SinaFetchResult:
    """获取指定股票最新正式年报的纯文本。

    Parameters
    ----------
    stock_code : str
        6 位 A 股代码，如 '600519', '000858'
    as_of : date, optional
        截止日期，用于确定年份。默认为今天。

    Returns
    -------
    SinaFetchResult
        包含年报元数据和纯文本正文的结果对象。

    Raises
    ------
    RuntimeError
        未找到年报或网络请求失败时抛出。
    """
    from .progress import info

    as_of_date = default_as_of(None) if as_of is None else as_of
    year = as_of_date.year
    code = normalize_stock_code(stock_code)

    info(f"新浪财经查询: {stock_code}, 年份: {year}")

    # 步骤 1：获取年报列表
    list_html = _fetch_list_page(code)
    parsed = _parse_list_page(list_html, code, year=year)
    if not parsed:
        # 尝试不指定年份，找最新一份
        parsed = _parse_list_page(list_html, code, year=None)
    if not parsed:
        raise RuntimeError(
            f"无法从新浪财经获取 {stock_code} 的 {year} 年年报。"
            "可能原因：新浪财经接口暂时不可用、股票代码无效、或该年份尚未披露年报。"
        )

    ann_id, title = parsed
    info(f"找到年报: {title}")

    # 步骤 2：获取详情页
    time.sleep(1.5)  # 频率控制
    detail_html = _fetch_detail_page(code, ann_id)
    soup = BeautifulSoup(detail_html, "html.parser")

    # 步骤 3：提取附加信息
    pdf_url = _extract_pdf_url(soup)
    pub_date = _extract_date(detail_html)

    # 步骤 4：提取纯文本
    raw_text = _extract_text(soup)
    cleaned_text = _clean_text(raw_text)

    if not cleaned_text:
        info("警告：新浪财经详情页文本提取为空，可能页面结构已变更")
        # 备用：直接从原始 HTML 的 body 提取
        if soup.find("body"):
            cleaned_text = soup.find("body").get_text(separator="\n", strip=True)

    # 构建元数据
    report = _build_annual_report(code, ann_id, title, pub_date, pdf_url)
    detail_url = DETAIL_URL_TPL.format(stock_code=code, ann_id=ann_id)

    return SinaFetchResult(report=report, full_text=cleaned_text, detail_url=detail_url)


def save_report_text(text: str, output_dir: Path, stem: str) -> Path:
    """将年报纯文本保存到本地文件（用于缓存 / 查看）。

    Parameters
    ----------
    text : str
        年报纯文本内容。
    output_dir : Path
        输出目录（如 annual_reports/）。
    stem : str
        文件名前缀（不含扩展名），如 '600519_贵州茅台_2025'。

    Returns
    -------
    Path
        保存的文件路径。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    target = output_dir / f"{safe_stem}.txt"
    target.write_text(text, encoding="utf-8")
    return target
