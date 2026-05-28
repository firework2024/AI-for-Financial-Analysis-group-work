from pathlib import Path
from types import SimpleNamespace

from finagent.pdf_text import MdaExtraction
from finagent.rqdata_client import FinancialFetchResult
import finagent.fundamental_pipeline as fp


def test_run_fundamental_pipeline_builds_shared_result(tmp_path, monkeypatch):
    saved_paths: list[Path] = []
    fallback_inputs: dict[str, object] = {}

    monkeypatch.setattr(
        fp,
        "fetch_latest_report_text",
        lambda stock: SimpleNamespace(
            stock_code=stock,
            title="示例股份：2025年年度报告",
            pub_date="2026-03-20",
            text="管理层讨论与分析\n经营持续改善\n第四节 公司治理",
            pdf_url="https://example.com/report.pdf",
            detail_url="https://example.com/detail",
            char_count=24,
        ),
    )
    monkeypatch.setattr(
        fp,
        "save_report_text",
        lambda report, output_dir, use_cache: saved_paths.append(output_dir / "report.txt") or (output_dir / "report.txt"),
    )
    monkeypatch.setattr(
        fp,
        "extract_mda",
        lambda text: MdaExtraction(
            full_text=text,
            mda_text="经营持续改善",
            confidence="high",
            start_heading="管理层讨论与分析",
            end_heading="第四节 公司治理",
        ),
    )
    monkeypatch.setattr(
        fp,
        "fetch_financials",
        lambda stock, report_year, years: FinancialFetchResult(
            rows=[{"year": 2025, "quarter": "2025q4", "revenue": 100.0}],
            order_book_id=f"{stock}.XSHG",
            quarters=["2025q4"],
        ),
    )
    monkeypatch.setattr(fp, "fetch_factor_fallbacks", lambda *args, **kwargs: {2025: {"inventory": 1.0}})
    monkeypatch.setattr(fp, "fetch_metric_factor_fallbacks", lambda *args, **kwargs: {2025: {"gross_margin": 0.5}})
    monkeypatch.setattr(fp, "extract_financial_fields", lambda text, report_year: {2025: {"revenue": 100.0}})

    def fake_apply_financial_fallbacks(rows, annual_report_text, factor_values, *, annual_report_fields=None):
        fallback_inputs["annual_report_text"] = annual_report_text
        fallback_inputs["annual_report_fields"] = annual_report_fields
        return [{"year": 2025, "quarter": "2025q4", "fields": {"revenue": {"value": 100.0, "source": "rqdata"}}}]

    monkeypatch.setattr(fp, "apply_financial_fallbacks", fake_apply_financial_fallbacks)
    monkeypatch.setattr(
        fp,
        "analyze_financials",
        lambda financial_data, metric_factor_values, company_context: {
            "positive_signals": ["现金流稳定"],
            "negative_signals": ["收入增长放缓"],
            "key_risks": ["成长性风险"],
            "reviewed_signals": [{"severity": "high", "category_cn": "成长性", "title": "收入增长放缓", "explanation": "增速回落", "evidence": "2025 年收入增速回落"}],
            "raw_signals": {"structured_signals": [], "compound_signals": [], "signal_summary": {}},
            "data_notes": ["2025 年有 1 个字段使用年报文本回退。"],
            "metrics": [],
        },
    )
    monkeypatch.setattr(fp, "investment_director_analysis", lambda mda_text, financial_analysis, company_context: f"总结：{mda_text}")

    result = fp.run_fundamental_pipeline(
        stock="600519",
        as_of=__import__("datetime").date(2026, 5, 28),
        years=3,
        workdir=tmp_path,
        no_download_cache=False,
        use_sina_text=True,
    )

    assert result.annual_report["stock_code"] == "600519"
    assert result.annual_report["sec_name"] == "示例股份"
    assert result.annual_report["report_year"] == 2025
    assert result.mda["confidence"] == "high"
    assert result.financial_analysis["positive_signals"] == ["现金流稳定"]
    assert result.investment_director == "总结：经营持续改善"
    assert fallback_inputs["annual_report_text"] == "管理层讨论与分析\n经营持续改善\n第四节 公司治理"
    assert fallback_inputs["annual_report_fields"] == {2025: {"revenue": 100.0}}
    assert saved_paths and saved_paths[0].parent == tmp_path / "annual_reports"
