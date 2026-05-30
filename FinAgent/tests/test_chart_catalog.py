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
