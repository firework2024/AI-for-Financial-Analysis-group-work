from finagent.chart_catalog import (
    CHART_CAPTIONS,
    DEFAULT_SECTION_CHART_CANDIDATES,
    fallback_chart_note,
)
from finagent.data_registry import CHART_DATA_SOURCE


def test_all_fixed_charts_have_data_source():
    for key in CHART_DATA_SOURCE:
        assert key in CHART_CAPTIONS


def test_fallback_chart_note_describes_pattern():
    note = fallback_chart_note(
        "price_volume",
        {
            "order_book_id": "600519.XSHG",
            "price": {
                "rows": [
                    {"date": "2025-01-02", "close": 100, "volume": 1_000_000},
                    {"date": "2025-01-03", "close": 102, "volume": 1_100_000},
                    {"date": "2025-01-06", "close": 104, "volume": 1_200_000},
                ],
                "row_count": 3,
            },
        },
    )
    assert "1326" not in note
    assert note.endswith("。")


def test_section_candidates_only_use_known_charts():
    for charts in DEFAULT_SECTION_CHART_CANDIDATES.values():
        for name in charts:
            assert name in CHART_CAPTIONS


def test_industry_tables_are_prioritized_for_operating_quality_section():
    from finagent.chart_catalog import DEFAULT_SECTION_TABLE_CANDIDATES

    tables = DEFAULT_SECTION_TABLE_CANDIDATES["经营质量分析"]
    candidates = DEFAULT_SECTION_CHART_CANDIDATES["经营质量分析"]

    assert tables[:2] == (
        "industry_profitability_compare_table",
        "industry_growth_leverage_compare_table",
    )
    assert CHART_CAPTIONS["industry_dbscan_anomaly"] == "DBSCAN 同行异常识别"
    assert "industry_profitability_compare" not in candidates
    assert "industry_growth_leverage_compare" not in candidates
    assert "industry_dbscan_anomaly" in candidates
    assert "industry_valuation_compare" not in candidates
    assert "valuation_percentile" not in candidates
    assert "valuation_factors" not in candidates
    assert "latest_valuation_snapshot" not in candidates
