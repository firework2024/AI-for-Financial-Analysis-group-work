from finagent.financial_analysis import (
    _analysis_has_narrative,
    _build_display_signals,
    _build_llm_evidence,
    _finalize_signal_review,
)
from finagent.llm import (
    _build_financial_data_first_prompt,
    financial_llm_mode,
)


def test_financial_llm_mode_defaults_to_data_first(monkeypatch):
    monkeypatch.delenv("FINAGENT_FINANCIAL_LLM_MODE", raising=False)
    assert financial_llm_mode() == "data_first"
    monkeypatch.setenv("FINAGENT_FINANCIAL_LLM_MODE", "signal_review")
    assert financial_llm_mode() == "signal_review"


def test_llm_evidence_includes_metrics_table():
    rows = [{"year": 2024, "quarter": "2024q4", "fields": {}}]
    metrics = [{"year": 2024, "revenue": 100.0, "revenue_growth": 0.1}]
    pack = {"structured_signals": [], "compound_signals": [], "signal_summary": {}}
    evidence = _build_llm_evidence(rows, metrics, pack, {"stock_code": "600519"})
    assert evidence["metrics"] == metrics
    assert "reading_guide" in evidence


def test_data_first_prompt_leads_with_metrics():
    evidence = {"metrics": [{"year": 2024}], "rows": [], "signals": {}, "data_quality": []}
    prompt = _build_financial_data_first_prompt("框架", evidence, {})
    assert "逐年衍生指标 metrics" in prompt
    assert prompt.index("metrics") < prompt.index("规则引擎附录")


def test_finalize_skips_rule_only_dump_when_narrative_present():
    signal_pack = {
        "structured_signals": [
            {
                "id": "s1",
                "category": "growth",
                "category_cn": "成长性",
                "polarity": "positive",
                "severity": "low",
                "title": "收入增长",
                "description": "收入增",
                "evidence": "2024",
                "metric": "revenue_growth",
                "related_metrics": ["revenue_growth"],
                "type": "single",
                "confidence": "high",
            }
        ],
        "compound_signals": [],
    }
    analysis = {
        "interpretation": "营收与利润同步改善。",
        "key_findings": ["2024 年营收同比 +10%"],
        "reviewed_signals": [],
        "positive_signals": [],
        "negative_signals": [],
        "key_risks": [],
        "data_notes": [],
    }
    result = _finalize_signal_review(analysis, signal_pack, [], [])
    assert _analysis_has_narrative(analysis)
    assert result["interpretation"].startswith("营收")
    assert len(result["reviewed_signals"]) == 0
    assert result["display_signals"][0]["type"] == "finding"


def test_display_signals_from_reviewed_when_no_narrative():
    reviewed = [
        {
            "category": "growth",
            "category_cn": "成长性",
            "polarity": "positive",
            "severity": "low",
            "title": "收入增长",
            "explanation": "说明",
            "evidence": "",
            "metrics": [],
            "confidence": "",
            "source_signal_id": "",
            "type": "",
        }
    ]
    display = _build_display_signals({}, reviewed, has_narrative=False)
    assert display
    assert display[0].get("summary") or display[0].get("source_titles")
