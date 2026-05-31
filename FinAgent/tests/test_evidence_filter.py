from finagent.chat.evidence_filter import filter_retrieved_hits, prune_tools_payload, strict_answer_required
from finagent.chat.intent import QueryIntent, classify_query_intent


def test_strict_quote_filters_fundamental_hits():
    intent = classify_query_intent("股价")
    assert strict_answer_required(intent)
    hits = [
        {"source": "datastore:price", "score": 0.9, "text": '{"close": 424}', "meta": {"kind": "price"}},
        {
            "source": "datastore:annual_financials",
            "score": 0.88,
            "text": "归母净利润722亿元，营收4237亿元",
            "meta": {"kind": "annual_financials"},
        },
    ]
    kept = filter_retrieved_hits(hits, intent, query="股价")
    assert len(kept) == 1
    assert kept[0]["meta"]["kind"] == "price"


def test_prune_tools_strips_annual_for_quote():
    intent = classify_query_intent("宁德时代股价")
    payload = {
        "live_data": {
            "quote": {"date": "2026-05-29", "close": 424.0, "change_pct": 2.0},
            "factor": {"pe_ratio_ttm": 25},
            "technical": {"latest_close": 424},
        },
        "data_api": {
            "stored": {
                "annual_report": {"financial_data": [{"revenue": 1}]},
                "technical": {"latest_close": 424},
                "factor": {"pe_ratio_ttm": 25},
            }
        },
        "evidence_summary": {"financial_facts": {"rows": []}, "has_quote": True},
        "answer_guidance": "x",
    }
    out = prune_tools_payload(payload, intent)
    assert out is not None
    assert "factor" not in (out.get("live_data") or {})
    assert "annual_report" not in ((out.get("data_api") or {}).get("stored") or {})
    assert "financial_facts" not in (out.get("evidence_summary") or {})
    assert "【硬性】" in (out.get("answer_guidance") or "")


def test_focused_metric_keeps_matching_financial_hit():
    intent = QueryIntent(focused_metrics=["\u51c0\u5229\u6da6"], fundamentals=True)
    profit_text = "\u5f52\u6bcd\u51c0\u5229\u6da6722\u4ebf\u5143\uff0c\u540c\u6bd4\u589e42%"
    asset_text = "\u603b\u8d44\u4ea75000\u4ebf\u5143"
    hits = [
        {"source": "pit", "score": 0.8, "text": profit_text, "meta": {"kind": "pit_financials"}},
        {"source": "pit", "score": 0.7, "text": asset_text, "meta": {"kind": "pit_financials"}},
    ]
    kept = filter_retrieved_hits(hits, intent, query="\u51c0\u5229\u6da6\u591a\u5c11")
    assert len(kept) == 1
    assert "722" in kept[0]["text"]
