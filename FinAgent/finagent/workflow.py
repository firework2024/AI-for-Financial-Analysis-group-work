from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .cninfo import default_as_of, download_report, latest_annual_report
from .env import load_dotenv
from .fallback import apply_financial_fallbacks
from .financial_analysis import analyze_financials
from .llm import investment_director_analysis
from .pdf_text import extract_mda, extract_pdf_text
from .report import render_markdown, write_report
from .rqdata_client import fetch_factor_fallbacks, fetch_financials, fetch_metric_factor_fallbacks


@dataclass
class WorkflowOptions:
    stock: str
    as_of: str | None = None
    years: int = 3
    output: str | None = None
    no_download_cache: bool = False
    workdir: str = "."


def run(options: WorkflowOptions) -> dict[str, Any]:
    load_dotenv()
    root = Path(options.workdir)
    as_of_date = default_as_of(options.as_of)
    report = latest_annual_report(options.stock, as_of_date)
    if report.report_year is None:
        raise RuntimeError(f"无法从年报标题识别报告年份: {report.title}")

    pdf_path = download_report(report, root / "annual_reports", use_cache=not options.no_download_cache)
    full_text = extract_pdf_text(pdf_path)
    mda = extract_mda(full_text)
    fetched = fetch_financials(options.stock, report.report_year, options.years)
    factor_values = fetch_factor_fallbacks(fetched.order_book_id, report.report_year, options.years, as_of_date)
    metric_factor_values = fetch_metric_factor_fallbacks(fetched.order_book_id, report.report_year, options.years, as_of_date)
    financial_data = apply_financial_fallbacks(fetched.rows, full_text, factor_values)
    company_context = {
        "stock_code": report.stock_code,
        "sec_name": report.sec_name,
        "report_year": report.report_year,
        "order_book_id": fetched.order_book_id,
        "quarters": fetched.quarters,
    }
    financial_analysis = analyze_financials(financial_data, metric_factor_values, company_context)
    director = investment_director_analysis(mda.mda_text, financial_analysis, company_context)

    result = {
        "annual_report": report.to_dict() | {"local_pdf": str(pdf_path)},
        "mda": {
            "confidence": mda.confidence,
            "start_heading": mda.start_heading,
            "end_heading": mda.end_heading,
            "summary": mda.summary,
        },
        "financial_data": financial_data,
        "financial_analysis": financial_analysis,
        "investment_director": director,
    }
    output_path = Path(options.output) if options.output else root / "outputs" / f"{report.stock_code}_{report.report_year}_report.md"
    write_report(render_markdown(result), output_path)
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps(_json_ready(result), ensure_ascii=False, indent=2), encoding="utf-8")
    result["output_markdown"] = str(output_path)
    result["output_json"] = str(json_path)
    return result


def _json_ready(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "__dict__"):
        return asdict(value)
    return value
