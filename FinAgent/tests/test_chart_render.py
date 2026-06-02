from pathlib import Path

import pandas as pd

from finagent.chart_dynamic import execute_parametric_chart, local_chart_need
from finagent.chart_plots import _extract_annual_metric, chart_agent
from finagent.chart_catalog import CHART_CAPTIONS, MARKET_TECH_SECTION


def _sample_data():
    dates = pd.date_range("2025-01-02", periods=80, freq="B")
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
            "current_ratio": 1.5 - i * 0.01,
            "quick_ratio": 1.2 - i * 0.008,
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


def test_dividend_spread_chart(tmp_path: Path):
    data = _sample_data()
    data["factor"] = {"dividend_yield_ttm": 0.0389}
    data["yield_curve"] = {
        "rows": [{"date": "2026-05-29", "1Y": 0.011578, "10Y": 0.01709}],
        "row_count": 1,
    }
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"dividend_spread"})
    assert "dividend_spread" in charts
    assert Path(charts["dividend_spread"]).exists()
    assert Path(charts["dividend_spread"]).stat().st_size > 500


def test_gov_yield_trend_chart(tmp_path: Path):
    data = _sample_data()
    rows = [
        {"date": d.strftime("%Y-%m-%d"), "1Y": 0.011 + i * 0.0001, "10Y": 0.017 + i * 0.00005}
        for i, d in enumerate(pd.date_range("2026-05-20", periods=8, freq="B"))
    ]
    data["yield_curve"] = {"rows": rows, "row_count": len(rows)}
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"gov_yield_trend"})
    assert "gov_yield_trend" in charts
    assert Path(charts["gov_yield_trend"]).exists()


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


def test_technical_indicator_plot_skips_warmup():
    import pandas as pd

    from finagent.chart_style import compute_rsi
    from finagent.technical import enrich_price_frame, technical_indicator_plot_frame, technical_indicator_warmup_bars

    dates = pd.date_range("2025-01-02", periods=80, freq="B")
    frame = pd.DataFrame({"date": dates, "close": 100 + pd.Series(range(80), dtype=float)})
    enriched = enrich_price_frame(frame)
    warmup = technical_indicator_warmup_bars()
    assert warmup == 34
    assert pd.isna(enriched["rsi14"].iloc[0])
    assert pd.isna(compute_rsi(frame["close"]).iloc[0])

    plot = technical_indicator_plot_frame(enriched)
    assert len(plot) == len(enriched) - warmup
    assert plot["rsi14"].notna().iloc[0]
    assert plot["macd"].notna().iloc[0]
    assert plot["macd_signal"].notna().iloc[0]


def test_moving_average_and_volatility_plot_skip_warmup():
    import pandas as pd

    from finagent.technical import (
        MA_SLOW,
        VOL_WINDOW,
        enrich_price_frame,
        moving_average_plot_frame,
        rolling_volatility_plot_frame,
    )

    dates = pd.date_range("2025-01-02", periods=100, freq="B")
    frame = pd.DataFrame({"date": dates, "close": 100 + pd.Series(range(100), dtype=float)})
    enriched = enrich_price_frame(frame)
    ma = moving_average_plot_frame(enriched)
    vol = rolling_volatility_plot_frame(enriched)
    assert len(ma) == len(enriched) - (MA_SLOW - 1)
    assert len(vol) == len(enriched) - VOL_WINDOW
    assert ma["ma20"].notna().iloc[0]
    assert ma["ma60"].notna().iloc[0]
    assert vol["vol20"].notna().iloc[0]


def test_technical_indicators_chart_uses_trimmed_window(tmp_path: Path):
    data = _sample_data()
    dates = pd.date_range("2025-01-02", periods=80, freq="B")
    data["price"]["rows"] = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "close": 100 + i * 0.8,
            "volume": 1_000_000 + i * 10_000,
            "total_turnover": 50_000_000 + i * 100_000,
        }
        for i, d in enumerate(dates)
    ]
    data["price"]["row_count"] = len(data["price"]["rows"])
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"technical_indicators"})
    assert "technical_indicators" in charts
    assert Path(charts["technical_indicators"]).stat().st_size > 500


def test_extract_annual_metric_handles_alias_and_sorts_year():
    financial_data = [
        {"year": 2024, "fields": {"operating_revenue": {"value": 200.0}, "net_profit": {"value": 20.0}}},
        {"year": 2022, "fields": {"operating_revenue": {"value": 120.0}, "net_profit": {"value": 8.0}}},
        {"year": 2023, "fields": {"operating_revenue": {"value": 150.0}, "net_profit": {"value": 12.0}}},
    ]
    years, revenue = _extract_annual_metric(financial_data, "revenue", aliases=("operating_revenue",))
    _, profit = _extract_annual_metric(financial_data, "net_profit_parent_company", aliases=("net_profit",))

    assert years == [2022, 2023, 2024]
    assert revenue == [120.0, 150.0, 200.0]
    assert profit == [8.0, 12.0, 20.0]


def test_profitability_factors_accepts_roe_alias(tmp_path: Path):
    data = _sample_data()
    for row in data["factor_history"]["rows"]:
        row["roe"] = 0.12
        row.pop("roe_ttm", None)
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"profitability_factors"})
    assert "profitability_factors" in charts
    assert Path(charts["profitability_factors"]).exists()


def test_margin_roe_trend_accepts_roe_ttm_alias(tmp_path: Path):
    data = _sample_data()
    data["annual_analysis"] = {
        "financial_data": [
            {
                "year": 2023,
                "fields": {
                    "gross_profit_margin_ttm": {"value": 0.20},
                    "roe_ttm": {"value": 0.10},
                },
            },
            {
                "year": 2024,
                "fields": {
                    "gross_profit_margin_ttm": {"value": 0.22},
                    "roe_ttm": {"value": 0.11},
                },
            },
            {
                "year": 2025,
                "fields": {
                    "gross_profit_margin_ttm": {"value": 0.24},
                    "roe_ttm": {"value": 0.12},
                },
            },
        ]
    }
    charts = chart_agent(data=data, output_dir=tmp_path, only_keys={"margin_roe_trend"})
    assert "margin_roe_trend" in charts
    assert Path(charts["margin_roe_trend"]).exists()
