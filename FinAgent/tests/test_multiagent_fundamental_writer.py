from pathlib import Path

from finagent.fundamental_pipeline import FundamentalPipelineResult
import finagent.multiagent as multiagent


def test_write_fundamental_section_renders_fixed_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        multiagent,
        "run_fundamental_pipeline",
        lambda **kwargs: FundamentalPipelineResult(
            annual_report={
                "stock_code": "600519",
                "sec_name": "贵州茅台",
                "title": "贵州茅台：2025年年度报告",
                "pub_date": "2026-03-20",
                "report_year": 2025,
                "text_path": "",
                "pdf_url": None,
                "detail_url": "",
            },
            mda={"confidence": "high", "start_heading": "管理层讨论与分析", "end_heading": "第四节 公司治理", "summary": "经营改善"},
            financial_data=[],
            financial_analysis={
                "positive_signals": ["自由现金流保持为正"],
                "negative_signals": ["收入增长放缓"],
                "key_risks": ["成长性风险"],
                "reviewed_signals": [
                    {
                        "severity": "high",
                        "category_cn": "成长性",
                        "title": "收入增长放缓",
                        "explanation": "收入同比回落",
                        "evidence": "2025 年收入增速低于上年",
                    }
                ],
                "data_notes": ["2025 年有 1 个字段使用年报文本回退。"],
            },
            investment_director="贵州茅台（600519）经营表现整体稳健，但成长性有所放缓。",
        ),
    )

    content = multiagent._write_fundamental_section(
        section_name="基本面与估值",
        data={
            "order_book_id": "600519.XSHG",
            "end_date": "2026-05-28",
            "python_script": str(tmp_path / "outputs" / "600519_XSHG_data_agent.py"),
            "factor": {
                "pe_ratio_ttm": 20.5,
                "pb_ratio_ttm": 7.1,
                "dividend_yield_ttm": 0.031,
                "market_cap": 2100000000000.0,
            },
            "capital_flow": {"rows": []},
            "price": {"rows": []},
            "price_change_rate": {"rows": []},
            "turnover": {"rows": []},
            "securities_margin": {"rows": []},
            "dividend": {"rows": []},
            "shares": {"rows": []},
            "interbank_rate": {"rows": []},
            "yield_curve": {"rows": []},
            "suspended": {"rows": []},
            "st_stock": {"rows": []},
        },
        charts={},
    )

    assert "### 财务信号概览" in content
    assert "### 经营解读" in content
    assert "### 数据说明" in content
    assert "### 估值观察" in content
    assert "贵州茅台（600519）2025 年度报告的基本面与估值章节" in content
    assert "自由现金流保持为正" in content


def test_write_fundamental_section_skips_valuation_when_factors_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        multiagent,
        "run_fundamental_pipeline",
        lambda **kwargs: FundamentalPipelineResult(
            annual_report={"stock_code": "600519", "sec_name": "贵州茅台", "title": "贵州茅台：2025年年度报告", "pub_date": "2026-03-20", "report_year": 2025, "text_path": "", "pdf_url": None, "detail_url": ""},
            mda={"confidence": "high", "start_heading": None, "end_heading": None, "summary": "经营改善"},
            financial_data=[],
            financial_analysis={"positive_signals": [], "negative_signals": [], "key_risks": [], "reviewed_signals": [], "data_notes": []},
            investment_director="总结。",
        ),
    )

    content = multiagent._write_fundamental_section(
        section_name="基本面与估值",
        data={
            "order_book_id": "600519.XSHG",
            "end_date": "2026-05-28",
            "python_script": str(tmp_path / "outputs" / "600519_XSHG_data_agent.py"),
            "factor": {},
            "capital_flow": {"rows": []},
            "price": {"rows": []},
            "price_change_rate": {"rows": []},
            "turnover": {"rows": []},
            "securities_margin": {"rows": []},
            "dividend": {"rows": []},
            "shares": {"rows": []},
            "interbank_rate": {"rows": []},
            "yield_curve": {"rows": []},
            "suspended": {"rows": []},
            "st_stock": {"rows": []},
        },
        charts={},
    )

    assert "### 估值观察" not in content


def test_section_writer_agents_fallbacks_for_fundamental_writer_only(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_write_section(*, agent, section_name, data):
        calls.append(agent)
        fallback_reason = data.get("fallback_reason", "")
        return f"{agent}:{section_name}:{fallback_reason}"

    monkeypatch.setattr(multiagent, "run_fundamental_pipeline", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(multiagent, "_write_section", fake_write_section)

    sections = multiagent.section_writer_agents(
        plan={
            "sections": [
                {"name": "基本面与估值", "agent": "fundamental_writer"},
                {"name": "技术因素", "agent": "technical_writer"},
            ]
        },
        data={
            "order_book_id": "600519.XSHG",
            "end_date": "2026-05-28",
            "python_script": str(tmp_path / "outputs" / "600519_XSHG_data_agent.py"),
            "factor": {},
            "capital_flow": {"rows": []},
            "price": {"rows": []},
            "price_change_rate": {"rows": []},
            "turnover": {"rows": []},
            "securities_margin": {"rows": []},
            "dividend": {"rows": []},
            "shares": {"rows": []},
            "interbank_rate": {"rows": []},
            "yield_curve": {"rows": []},
            "suspended": {"rows": []},
            "st_stock": {"rows": []},
            "technical": {},
            "industry": {},
        },
        charts={},
    )

    assert "fundamental pipeline failed" in sections["基本面与估值"]
    assert sections["技术因素"] == "technical_writer:技术因素:"
    assert calls == ["fundamental_writer", "technical_writer"]
