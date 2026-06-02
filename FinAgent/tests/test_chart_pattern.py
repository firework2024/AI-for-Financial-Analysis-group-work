import pandas as pd

from finagent.chart_pattern import build_chart_pattern, chart_pattern_note


def _price_data(*, rising: bool = True):
    dates = pd.date_range("2025-01-02", periods=30, freq="B")
    rows = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "close": 100 + i * (0.8 if rising else -0.5),
            "volume": 1_000_000 + i * 10_000,
            "total_turnover": 50_000_000 + i * 100_000,
        }
        for i, d in enumerate(dates)
    ]
    return {"order_book_id": "600519.XSHG", "price": {"rows": rows, "row_count": len(rows)}}


def test_price_volume_note_describes_shape_not_numbers():
    note = chart_pattern_note("price_volume", _price_data(rising=True))
    assert "600519" not in note
    assert any(word in note for word in ("同步", "上行", "走强", "量价"))


def test_margin_balances_detects_uptrend():
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    rows = [
        {"date": d.strftime("%Y-%m-%d"), "margin_balance": 100 + i * 5}
        for i, d in enumerate(dates)
    ]
    data = {
        "order_book_id": "300750.XSHE",
        "securities_margin": {"rows": rows, "row_count": len(rows)},
    }
    pattern = build_chart_pattern("margin_balances", data)
    assert "上行" in pattern["shape"]
    note = chart_pattern_note("margin_balances", data)
    assert "上行" in note


def test_moving_averages_note_is_morphology():
    note = chart_pattern_note("moving_averages", _price_data(rising=True))
    assert any(word in note for word in ("均线", "趋势", "震荡", "缠绕", "之上", "之下"))
    assert "方向尚不明朗" not in note
