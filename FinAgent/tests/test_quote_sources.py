from datetime import date

from finagent.chat.quote_sources import (
    _normalize_spot,
    _parse_kline_row,
    eastmoney_secid,
    extract_trade_date_from_query,
    fetch_eastmoney_quote,
    format_quote_text,
    supplement_live_with_web_quote,
)


def test_eastmoney_secid_sz():
    assert eastmoney_secid("300274") == "0.300274"


def test_extract_trade_date_from_query():
    assert extract_trade_date_from_query("5月29日收盘价", default_year=2026) == date(2026, 5, 29)


def test_normalize_spot():
    raw = {
        "f43": 177.99,
        "f44": 190.63,
        "f45": 176.0,
        "f46": 190.14,
        "f57": "300274",
        "f58": "阳光电源",
        "f60": 190.09,
        "f86": "20260529150000",
        "f116": 369000000000,
        "f162": 40.26,
        "f167": 7.81,
        "f168": 5.54,
        "f169": -12.1,
        "f170": -6.37,
    }
    quote = _normalize_spot(raw)
    assert quote["close"] == 177.99
    assert quote["prev_close"] == 190.09
    assert quote["change_pct"] == -6.37
    assert quote["date"] == "2026-05-29"


def test_parse_kline_row():
    row = _parse_kline_row("2026-05-29,190.14,177.99,190.63,176.00,881400,16010000000,3.2,-6.37,-12.10,5.54")
    assert row["close"] == 177.99
    assert row["open"] == 190.14


def test_format_quote_text():
    text = format_quote_text({"name": "阳光电源", "date": "2026-05-29", "close": 177.99, "change_pct": -6.37})
    assert "177.99" in text
    assert "阳光电源" in text


def test_supplement_live_with_web_quote(monkeypatch):
    monkeypatch.setattr(
        "finagent.chat.quote_sources.fetch_eastmoney_quote",
        lambda code, trade_date=None: {
            "stock_code": code,
            "name": "阳光电源",
            "date": "2026-05-29",
            "close": 177.99,
            "prev_close": 190.09,
            "change": -12.1,
            "change_pct": -6.37,
            "source": "eastmoney_spot",
        },
    )
    live = supplement_live_with_web_quote({"error": "Timeout"}, "300274", "5月29日收盘")
    assert live["quote"]["close"] == 177.99
    assert "error" not in live


def test_close_prev_close_distinct():
    from finagent.chat.quote_sources import _normalize_spot

    spot = _normalize_spot(
        {
            "f43": 177.99,
            "f60": 190.09,
            "f57": "300274",
            "f58": "阳光电源",
            "f169": -12.1,
            "f170": -6.37,
            "f86": 1780040043,
        }
    )
    assert spot["close"] == 177.99
    assert spot["prev_close"] == 190.09
    assert spot["close"] != spot["prev_close"]


def test_fetch_eastmoney_quote_spot(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"f43": 177.99, "f58": "阳光电源", "f57": "300274", "f60": 190.09, "f86": "20260529150000"}}

    monkeypatch.setattr("finagent.chat.quote_sources.requests.get", lambda *a, **k: FakeResp())
    out = fetch_eastmoney_quote("300274")
    assert out["close"] == 177.99
