from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cninfo import default_as_of, download_report, latest_annual_report
from .env import load_dotenv
from .fallback import apply_financial_fallbacks
from .financial_analysis import analyze_financials
from .mda_analysis import enrich_financial_analysis_with_mda
from .llm import investment_director_analysis, mda_summary_agent
from .pdf_text import extract_mda, extract_pdf_text
from .report import build_annual_json_payload, render_markdown
from .report_format import write_report
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
    financial_analysis = enrich_financial_analysis_with_mda(financial_analysis, mda.mda_text)
    mda_brief = mda_summary_agent(mda.mda_text, company_context)
    director = investment_director_analysis(mda.mda_text, financial_analysis, company_context)

    result = {
        "annual_report": report.to_dict() | {"local_pdf": str(pdf_path)},
        "mda": {
            "confidence": mda.confidence,
            "start_heading": mda.start_heading,
            "end_heading": mda.end_heading,
            "summary": mda_brief,
            "raw_preview": mda.raw_preview,
        },
        "financial_data": financial_data,
        "financial_analysis": financial_analysis,
        "investment_director": director,
    }
    output_path = Path(options.output) if options.output else root / "outputs" / f"{report.stock_code}_{report.report_year}_report.md"
    write_report(render_markdown(result, order_book_id=fetched.order_book_id), output_path)
    json_path = output_path.with_suffix(".json")
    payload = build_annual_json_payload(
        result=result,
        order_book_id=fetched.order_book_id,
        output_markdown=str(output_path),
        output_json=str(json_path),
    )
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result["output_markdown"] = str(output_path)
    result["output_json"] = str(json_path)
    try:
        from .datastore import save_annual_report_record
        from .datastore.annual_text import mda_storage_payload, merge_mda_meta

        mda_payload = mda_storage_payload(mda)
        save_annual_report_record(
            stock_code=report.stock_code,
            report_year=report.report_year,
            order_book_id=fetched.order_book_id,
            sec_name=report.sec_name,
            title=report.title,
            pdf_path=str(pdf_path),
            meta=report.to_dict(),
            financial_data=financial_data,
            mda_text=mda_payload["mda_text"],
            mda_meta=merge_mda_meta(
                mda_payload["mda_meta"],
                {"summary": mda_brief},
            ),
        )
    except Exception:
        pass
    return result
