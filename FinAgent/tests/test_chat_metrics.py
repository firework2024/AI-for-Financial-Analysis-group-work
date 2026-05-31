from finagent.chat.intent import classify_query_intent
from finagent.chat.metrics import extract_financial_facts, filter_financial_rows, resolve_focused_metrics


def test_resolve_total_assets():
    assert resolve_focused_metrics("总资产？") == ["总资产"]


def test_resolve_net_profit_only():
    assert resolve_focused_metrics("我只要净利润") == ["净利润"]


def test_filter_financial_rows():
    rows = [
        {"year": 2025, "revenue": 100, "net_profit": 10, "total_assets": 500},
        {"year": 2024, "revenue": 90, "net_profit": 9, "total_assets": 480},
    ]
    slim = filter_financial_rows(rows, ["净利润"])
    assert slim[0] == {"year": 2025, "net_profit": 10}
    assert "revenue" not in slim[0]


def test_narrow_intent_for_total_assets():
    intent = classify_query_intent("总资产")
    assert intent.focused_metrics == ["总资产"]
    assert intent.narrow_answer is True


def test_extract_financial_facts():
    stored = {
        "stock_code": "000001",
        "annual_report": {
            "sec_name": "平安银行",
            "report_year": 2025,
            "financial_data": [
                {"year": 2025, "net_profit": 426.33, "total_assets": 59300},
                {"year": 2024, "net_profit": 445.08, "total_assets": 57700},
            ],
        },
    }
    facts = extract_financial_facts(stored, ["总资产"])
    assert facts
    assert facts["by_source"]["annual"][0]["total_assets"] == 59300
