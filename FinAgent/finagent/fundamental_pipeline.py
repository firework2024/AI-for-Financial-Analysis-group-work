from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .fallback import apply_financial_fallbacks
from .financial_analysis import analyze_financials
from .financial_statements import extract_financial_fields
from .llm import investment_director_analysis
from .pdf_text import extract_mda
from .rqdata_client import fetch_factor_fallbacks, fetch_financials, fetch_metric_factor_fallbacks
from .sina import fetch_latest_report_text, save_report_text


@dataclass
class FundamentalPipelineResult:
    annual_report: dict[str, Any]
    mda: dict[str, Any]
    financial_data: list[dict[str, Any]]
    financial_analysis: dict[str, Any]
    investment_director: str

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "annual_report": self.annual_report,
            "mda": self.mda,
            "financial_data": self.financial_data,
            "financial_analysis": self.financial_analysis,
            "investment_director": self.investment_director,
        }


def run_fundamental_pipeline(
    *,
    stock: str,
    as_of: date,
    years: int,
    workdir: str | Path = ".",
    no_download_cache: bool = False,
    use_sina_text: bool = True,
) -> FundamentalPipelineResult:
    root = Path(workdir)
    sina_report = fetch_latest_report_text(stock)
    if not sina_report:
        raise RuntimeError(f"未从新浪财经找到 {stock} 的年报。")

    report_year = _parse_year(sina_report.title)
    if report_year is None:
        raise RuntimeError(f"无法从年报标题识别报告年份: {sina_report.title}")
    sec_name = _extract_sec_name(sina_report.title)

    text_path: Path | None = None
    if use_sina_text:
        text_path = save_report_text(sina_report, root / "annual_reports", use_cache=not no_download_cache)
        mda = extract_mda(sina_report.text)
        fallback_text = sina_report.text
    else:
        from .cninfo import download_report, latest_annual_report
        from .pdf_text import extract_pdf_text

        cn_report = latest_annual_report(stock, as_of)
        if cn_report.report_year is None:
            raise RuntimeError(f"无法从年报标题识别报告年份: {cn_report.title}")
        pdf_path = download_report(cn_report, root / "annual_reports", use_cache=not no_download_cache)
        full_text = extract_pdf_text(pdf_path)
        mda = extract_mda(full_text)
        fallback_text = ""

    fetched = fetch_financials(stock, report_year, years)
    factor_values = fetch_factor_fallbacks(fetched.order_book_id, report_year, years, as_of)
    metric_factor_values = fetch_metric_factor_fallbacks(fetched.order_book_id, report_year, years, as_of)

    annual_report_fields: dict[int, dict[str, float]] = {}
    if use_sina_text and sina_report.text:
        annual_report_fields = extract_financial_fields(sina_report.text, report_year)

    financial_data = apply_financial_fallbacks(
        fetched.rows,
        fallback_text,
        factor_values,
        annual_report_fields=annual_report_fields,
    )
    company_context = {
        "stock_code": stock,
        "sec_name": sec_name,
        "report_year": report_year,
        "order_book_id": fetched.order_book_id,
        "quarters": fetched.quarters,
    }
    financial_analysis = analyze_financials(financial_data, metric_factor_values, company_context)
    director = investment_director_analysis(mda.mda_text, financial_analysis, company_context)

    return FundamentalPipelineResult(
        annual_report={
            "stock_code": stock,
            "sec_name": sec_name,
            "title": sina_report.title,
            "pub_date": sina_report.pub_date,
            "report_year": report_year,
            "text_path": str(text_path) if text_path else "",
            "pdf_url": sina_report.pdf_url,
            "detail_url": sina_report.detail_url,
        },
        mda={
            "confidence": mda.confidence,
            "start_heading": mda.start_heading,
            "end_heading": mda.end_heading,
            "summary": mda.summary,
        },
        financial_data=financial_data,
        financial_analysis=financial_analysis,
        investment_director=director,
    )


def _parse_year(title: str) -> int | None:
    match = re.search(r"(20\d{2}|19\d{2})\s*年\s*年度报告", title)
    return int(match.group(1)) if match else None


def _extract_sec_name(title: str) -> str:
    if "：" in title:
        return title.split("：")[0].strip()
    if ":" in title:
        return title.split(":")[0].strip()
    return ""
