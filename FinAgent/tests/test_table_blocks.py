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


def test_technical_snapshot_table_is_disabled():
    from finagent.table_blocks import format_table_block, table_data_available

    data = {
        "technical": {
            "latest_close": 1326,
            "ma20": 1333.39,
            "ma60": 1397.84,
            "return_20d": -0.0536,
            "rsi14": 41.04,
        }
    }
    assert format_table_block("technical_snapshot_table", data) is None
    assert table_data_available("technical_snapshot_table", data) is False


def test_valuation_snapshot_table_is_vertical():
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
    assert "| 指标 | 数值 |" in block
    assert "| 维度 |" not in block


def test_table_data_available_for_new_keys():
    data = _capital_section_data()
    for key in (
        "trading_activity_table",
        "margin_period_table",
        "share_structure_table",
        "funding_cost_table",
    ):
        assert table_data_available(key, data), key


def _industry_comparison_data():
    return {
        "industry_comparison": {
            "industry": {
                "selected_level": 3,
                "selected_industry_name": "住宅物业开发",
            },
            "peers": {"effective_count": 68},
            "metrics": {
                "pe_ratio_ttm": {
                    "label": "PE(TTM)",
                    "target": 7.34,
                    "median": -3.22,
                    "mean": 7.77,
                    "percentile": 0.76,
                },
                "pb_ratio_ttm": {
                    "label": "PB(TTM)",
                    "target": 0.67,
                    "median": 0.85,
                    "mean": 0.91,
                    "percentile": 0.35,
                },
                "gross_profit_margin_ttm": {
                    "label": "毛利率(TTM)",
                    "target": 0.2346,
                    "median": 0.1726,
                    "mean": 0.1864,
                    "percentile": 0.67,
                },
                "operating_revenue_growth_ratio_ttm": {
                    "label": "营收增长率(TTM)",
                    "target": 0.075,
                    "median": -0.1286,
                    "mean": -0.0054,
                    "percentile": 0.70,
                },
                "debt_to_asset_ratio": {
                    "label": "资产负债率",
                    "target": 46.88,
                    "median": 65.46,
                    "mean": 62.06,
                    "percentile": 0.26,
                },
                "current_ratio": {
                    "label": "流动比率",
                    "target": 1.12,
                    "median": 1.81,
                    "mean": 2.11,
                    "percentile": 0.14,
                },
                "quick_ratio": {
                    "label": "速动比率",
                    "target": 0.43,
                    "median": 0.61,
                    "mean": 0.86,
                    "percentile": 0.29,
                },
            },
        }
    }


def test_industry_growth_leverage_compare_table():
    data = _industry_comparison_data()
    block = format_table_block("industry_growth_leverage_compare_table", data)
    assert block is not None
    assert "行业成长与杠杆对比" in block
    assert "住宅物业开发" in block
    assert "有效同行 68 家" in block
    assert "营收增长率(TTM)" in block
    assert "速动比率" in block
    assert "7.50%" in block
    assert "46.88%" in block
    assert "0.43x" in block
    assert "70%" in block


def test_industry_operating_peer_compare_table():
    data = _industry_comparison_data()
    data["industry_comparison"]["metrics"]["net_profit_margin_ttm"] = {
        "label": "净利率(TTM)",
        "target": 0.1809,
        "median": 0.0317,
        "mean": 0.05,
        "percentile": 0.97,
        "relative_label": "处于行业高位，相对占优",
    }
    block = format_table_block("industry_operating_peer_compare_table", data)
    assert block is not None
    assert "同行横向坐标" in block
    assert "住宅物业开发" in block
    assert "有效同行 68 家" in block
    assert "毛利率(TTM)" in block
    assert "净利率(TTM)" in block
    assert "速动比率" in block
    assert "23.46%" in block
    assert "18.09%" in block
    assert "97%" in block
    assert "| 解读 |" in block
    assert "PE(TTM)" not in block


def test_industry_peer_compare_table_includes_valuation_and_quality():
    data = _industry_comparison_data()
    block = format_table_block("industry_peer_compare_table", data)
    assert block is not None
    assert "行业横向坐标" in block
    assert "PE(TTM)" in block
    assert "毛利率(TTM)" in block
    assert "7.34x" in block
    assert "| 解读 |" in block
