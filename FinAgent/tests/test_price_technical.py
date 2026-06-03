from finagent.multi_report import _core_metric_table
from finagent.price_technical import ensure_technical_from_price_rows
from finagent.report_format import industry_label


def test_industry_label_prefers_name_over_code():
    industry = {
        "first_industry_code": "36",
        "first_industry_name": "食品饮料",
    }
    assert industry_label(industry) == "食品饮料"


def test_ensure_technical_from_price_rows_fills_missing_meta():
    payload = {
        "price": {
            "rows": [
                {"date": f"2026-01-{day:02d}", "close": 100.0 + day, "volume": 1_000_000}
                for day in range(1, 65)
            ],
        },
        "technical": {},
    }
    ensure_technical_from_price_rows(payload)
    technical = payload["technical"]
    assert technical.get("latest_close") is not None
    assert technical.get("ma20") is not None
    assert technical.get("rsi14") is not None


def test_core_metric_table_uses_computed_technical():
    data = {
        "industry": {"first_industry_code": "36", "first_industry_name": "食品饮料"},
        "price": {
            "rows": [
                {"date": f"2026-01-{day:02d}", "close": 1300.0 + day * 0.5, "volume": 5_000_000}
                for day in range(1, 65)
            ],
        },
        "factor": {
            "pe_ratio_ttm": 20.0,
            "pb_ratio_ttm": 6.5,
            "market_cap": 1.65e12,
            "dividend_yield_ttm": 0.039,
        },
        "securities_margin": {
            "rows": [{"margin_balance": 2.0e10, "buy_on_margin_value": 1.0e9}],
        },
    }
    ensure_technical_from_price_rows(data)
    table = "\n".join(_core_metric_table(data))
    assert "食品饮料" in table
    assert "数据缺失" not in table.split("最新收盘价")[1].split("PE")[0]
    assert "1326" not in table or "1300" in table or "1332" in table
