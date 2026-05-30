from pathlib import Path

import pandas as pd

from finagent.chart_dynamic import execute_parametric_chart, local_chart_need
from finagent.chart_plots import chart_agent
from finagent.chart_catalog import CHART_CAPTIONS, MARKET_TECH_SECTION


def _sample_data():
    dates = pd.date_range("2025-01-02", periods=30, freq="B")
    rows = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "close": 100 + i * 0.8,
            "volume": 1_000_000 + i * 10_000,
            "total_turnover": 50_000_000 + i * 100_000,
        }
        for i, d in enumerate(dates)
    ]
    change_rows = [
        {"date": d.strftime("%Y-%m-%d"), "600519.XSHG": 0.01 if i % 2 == 0 else -0.008}
        for i, d in enumerate(dates)
    ]
    index_rows = [
        {"date": d.strftime("%Y-%m-%d"), "close": 4000 + i * 5}
        for i, d in enumerate(dates)
    ]
    factor_history_rows = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "market_cap": 2_000_000_000_000 + i * 1e9,
            "pe_ratio_ttm": 25 + i * 0.1,
            "gross_profit_margin_ttm": 0.9 - i * 0.001,
            "net_profit_growth_ratio_ttm": 0.12 - i * 0.002,
            "debt_to_asset_ratio": 0.2 + i * 0.001,
        }
        for i, d in enumerate(dates)
    ]
    return {
        "order_book_id": "600519.XSHG",
        "benchmark_index": {"id": "000300.XSHG", "label": "沪深300"},
        "price": {"rows": rows, "row_count": len(rows)},
        "price_change_rate": {"rows": change_rows, "row_count": len(change_rows)},
        "index_benchmark": {"rows": index_rows, "row_count": len(index_rows)},
        "factor_history": {"rows": factor_history_rows, "row_count": len(factor_history_rows)},
        "factor": {"market_cap": 2.1e12, "net_profit_growth_ratio_ttm": 0.1},
        "turnover": {"rows": [], "row_count": 0},
        "capital_flow": {"rows": [], "row_count": 0},
        "block_trade": {"rows": [], "row_count": 0},
    }


def test_fixed_chart_agent_subset(tmp_path: Path):
    data = _sample_data()
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"price_volume", "moving_averages"})
    assert "price_volume" in charts
    assert "moving_averages" in charts
    assert Path(charts["price_volume"]).exists()
    assert Path(charts["price_volume"]).stat().st_size > 500


def test_new_fixed_chart_templates(tmp_path: Path):
    data = _sample_data()
    keys = {
        "daily_return",
        "rolling_volatility",
        "relative_return",
        "turnover_amount",
        "market_cap_trend",
        "growth_factors",
        "profitability_factors",
        "liquidity_factors",
        "debt_ratio_trend",
    }
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys=keys)
    for key in keys:
        assert key in charts, key
        assert Path(charts[key]).exists()


def test_chart_catalog_covers_fixed_templates():
    assert "relative_return" in CHART_CAPTIONS
    assert "latest_growth_snapshot" in CHART_CAPTIONS


def test_local_chart_need_recognizes_new_templates():
    data = _sample_data()
    sections = {MARKET_TECH_SECTION: "近期相对沪深300基准表现与波动率变化。"}
    need = local_chart_need(data=data, sections=sections, plan={})
    picked = {item["chart_key"] for item in need.get("charts") or []}
    assert "relative_return" in picked or "rolling_volatility" in picked


def test_parametric_line_chart(tmp_path: Path):
    data = _sample_data()
    spec = {
        "chart_key": "custom_close_trend",
        "chart_type": "line",
        "data_keys": ["price"],
        "y_fields": ["close"],
        "transform": "none",
        "title": "收盘价走势",
    }
    path = execute_parametric_chart(spec, data=data, output_dir=tmp_path)
    assert path is not None
    assert Path(path).exists()
