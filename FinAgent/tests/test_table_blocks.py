from finagent.table_blocks import format_table_block, table_data_available


def _capital_section_data():
    return {
        "technical": {"avg_volume_20d": 5066895},
        "price": {
            "rows": [
                {"date": "2026-05-27", "total_turnover": 10_587_000_000},
                {"date": "2026-05-28", "total_turnover": 5_113_000_000},
                {"date": "2026-05-29", "total_turnover": 10_037_000_000},
            ]
        },
        "turnover": {
            "rows": [
                {"date": "2026-05-27", "today": 0.0066},
                {"date": "2026-05-28", "today": 0.0031},
                {"date": "2026-05-29", "today": 0.0061},
            ]
        },
        "capital_flow": {"row_count": 0, "rows": []},
        "securities_margin": {
            "rows": [
                {
                    "date": "2026-05-13",
                    "margin_balance": 19_062_000_000,
                    "short_balance": 1_310_000_000,
                    "buy_on_margin_value": 500_000_000,
                },
                {
                    "date": "2026-05-28",
                    "margin_balance": 20_048_000_000,
                    "short_balance": 1_630_000_000,
                    "buy_on_margin_value": 1_466_000_000,
                },
            ]
        },
        "shares": {
            "rows": [
                {
                    "date": "2026-05-20",
                    "total": 1_252_270_215,
                    "circulation_a": 1_252_270_215,
                    "free_circulation": 482_653_595,
                },
                {
                    "date": "2026-05-29",
                    "total": 1_250_081_601,
                    "circulation_a": 1_250_081_601,
                    "free_circulation": 480_464_981,
                },
            ]
        },
        "factor": {"dividend_yield_ttm": 0.0389},
        "interbank_rate": {
            "rows": [{"date": "2026-05-29", "ON": 1.324, "1Y": 1.4655}]
        },
        "yield_curve": {
            "rows": [{"date": "2026-05-29", "1Y": 0.011578, "10Y": 0.01709}]
        },
    }


def test_trading_activity_table():
    data = _capital_section_data()
    block = format_table_block("trading_activity_table", data)
    assert block is not None
    assert "成交活跃度" in block
    assert "近12日最高成交额" in block
    assert "主力资金流向" in block
    assert "数据缺失" in block


def test_margin_period_and_share_structure_tables():
    data = _capital_section_data()
    margin = format_table_block("margin_period_table", data)
    share = format_table_block("share_structure_table", data)
    assert margin and "两融区间变动" in margin
    assert "变动幅度" in margin
    assert share and "股本结构快照" in share
    assert "自由流通占比" in share


def test_funding_cost_table():
    data = _capital_section_data()
    block = format_table_block("funding_cost_table", data)
    assert block is not None
    assert "股息率(TTM)" in block
    assert "Shibor" in block
    assert "股息率 − 1Y国债" in block


def test_technical_snapshot_table_is_wide():
    data = {
        "technical": {
            "latest_close": 1326,
            "ma20": 1333.39,
            "ma60": 1397.84,
            "return_20d": -0.0536,
            "return_60d": -0.0703,
            "rsi14": 41.04,
            "macd": -12.3,
            "macd_signal": -10.1,
            "volatility_20d": 0.18,
            "latest_drawdown": -0.15,
            "max_drawdown": -0.22,
            "avg_volume_20d": 5066895,
        }
    }
    block = format_table_block("technical_snapshot_table", data)
    assert block is not None
    assert "技术指标快照" in block
    assert "MACD" in block
    assert "| 维度 |" in block
    assert block.count("|") >= 12


def test_valuation_snapshot_table_is_wide():
    data = {
        "factor": {
            "pe_ratio_ttm": 20.04,
            "pb_ratio_ttm": 6.55,
            "ps_ratio_ttm": 9.62,
            "dividend_yield_ttm": 0.0389,
            "market_cap": 1_657_608_000_000,
        }
    }
    block = format_table_block("latest_valuation_snapshot", data)
    assert block is not None
    assert "PE(TTM)" in block
    assert "| 维度 |" in block
    assert "最新" in block


def test_table_data_available_for_new_keys():
    data = _capital_section_data()
    for key in (
        "trading_activity_table",
        "margin_period_table",
        "share_structure_table",
        "funding_cost_table",
    ):
        assert table_data_available(key, data), key
