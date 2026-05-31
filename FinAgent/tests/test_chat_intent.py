from finagent.chat.intent import classify_query_intent, is_fundamental_narrative_hit


def test_quote_primary_recent_price():
    intent = classify_query_intent("最近股价")
    assert intent.quote_primary is True
    assert intent.fundamentals is False
    assert intent.want_live_quote is True
    assert intent.data_scope == "quote"


def test_fundamentals_not_quote_primary():
    intent = classify_query_intent("比亚迪2024年营收和净利润")
    assert intent.quote_primary is False
    assert intent.fundamentals is True
    assert "净利润" in (intent.focused_metrics or [])
    assert "营业收入" in (intent.focused_metrics or [])


def test_fundamental_narrative_detector():
    text = "\u6bd4\u4e9a\u8fea2024\u5e74\u8425\u65367771\u4ebf\uff0c\u540c\u6bd4\u589e\u957f29%\uff1b\u5f52\u6bcd\u51c0\u5229\u6da6402.5\u4ebf"
    assert is_fundamental_narrative_hit(text) is True
