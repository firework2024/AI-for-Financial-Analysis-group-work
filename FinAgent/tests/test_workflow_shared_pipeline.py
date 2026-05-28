from pathlib import Path

from finagent.fundamental_pipeline import FundamentalPipelineResult
from finagent.workflow import WorkflowOptions, run
import finagent.workflow as workflow


def test_workflow_run_uses_shared_pipeline_and_preserves_output_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "load_dotenv", lambda: None)
    monkeypatch.setattr(workflow, "default_as_of", lambda value: __import__("datetime").date(2026, 5, 28))
    monkeypatch.setattr(
        workflow,
        "run_fundamental_pipeline",
        lambda **kwargs: FundamentalPipelineResult(
            annual_report={"stock_code": "600519", "sec_name": "贵州茅台", "title": "贵州茅台：2025年年度报告", "pub_date": "2026-03-20", "report_year": 2025, "text_path": "", "pdf_url": None, "detail_url": ""},
            mda={"confidence": "high", "start_heading": None, "end_heading": None, "summary": "经营改善"},
            financial_data=[],
            financial_analysis={
                "positive_signals": ["自由现金流保持为正"],
                "negative_signals": ["收入增长放缓"],
                "key_risks": ["成长性风险"],
                "reviewed_signals": [],
                "raw_signals": {"structured_signals": [], "compound_signals": [], "signal_summary": {}},
                "data_notes": [],
                "metrics": [],
            },
            investment_director="总结。",
        ),
    )
    monkeypatch.setattr(workflow, "render_markdown", lambda result: "# mock report\n")
    monkeypatch.setattr(workflow, "write_report", lambda markdown, output_path: Path(output_path).write_text(markdown, encoding="utf-8") or Path(output_path))

    result = run(
        WorkflowOptions(
            stock="600519",
            output=str(tmp_path / "report.md"),
            workdir=str(tmp_path),
        )
    )

    assert set(result) >= {
        "annual_report",
        "mda",
        "financial_data",
        "financial_analysis",
        "investment_director",
        "output_markdown",
        "output_json",
    }
    assert Path(result["output_markdown"]).exists()
    assert Path(result["output_json"]).exists()
