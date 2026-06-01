from finagent.chat.agent import _chunks_for_retrieval, _merge_retrieved_hits, _purge_stale_chunks, index_report
from finagent.chat.rag import chunk_text, search_chunks
from finagent.chat.store import ChatSession


def _sample_report(stock: str, summary: str) -> dict:
    return {
        "meta": {"order_book_id": f"{stock}.XSHE" if stock.startswith("3") else f"{stock}.XSHG"},
        "executive_summary": summary,
        "sections": {"基本面与估值": f"{stock} 总资产9748.28亿元，营收稳步增长。"},
    }


def test_index_report_replaces_stale_summary_chunks():
    session = ChatSession(id="s1", title="000001 报告问答", created_at="", updated_at="", stock_code="000001")
    index_report(session, _sample_report("000001", "平安银行摘要"), report_id="000001_old.json")
    assert any("平安银行" in item["text"] for item in session.chunks)

    index_report(session, _sample_report("300750", "宁德时代摘要"), report_id="300750_multi_agent_report.json")
    texts = " ".join(item["text"] for item in session.chunks)
    assert "平安银行" not in texts
    assert "宁德时代" in texts
    assert session.stock_code == "300750"
    assert all(item.get("meta", {}).get("report_id") == "300750_multi_agent_report.json" for item in session.chunks if item.get("meta", {}).get("kind") == "summary")
    assert session.title == "300750 报告问答"


def test_purge_drops_mismatched_pdf_chunks():
    session = ChatSession(id="s1", title="t", created_at="", updated_at="", stock_code="000001")
    session.chunks = [
        {
            "id": "pdf:000001#0",
            "text": "平安银行 MD&A",
            "source": "pdf:000001.pdf",
            "meta": {"kind": "pdf", "stock_code": "000001"},
        }
    ]
    warnings = _purge_stale_chunks(session, report_id="300750_multi_agent_report.json", stock_code="300750")
    assert session.chunks == []
    assert warnings


def test_chunks_for_retrieval_filters_other_report():
    session = ChatSession(
        id="s1",
        title="t",
        created_at="",
        updated_at="",
        stock_code="300750",
        report_id="300750_multi_agent_report.json",
    )
    session.chunks = [
        {
            "id": "summary#0",
            "text": "宁德时代总资产9748.28亿元",
            "source": "summary",
            "meta": {"kind": "summary", "report_id": "300750_multi_agent_report.json", "stock_code": "300750"},
        },
        {
            "id": "summary#0",
            "text": "平安银行摘要",
            "source": "summary",
            "meta": {"kind": "summary", "report_id": "000001_old.json", "stock_code": "000001"},
        },
    ]
    chunks = _chunks_for_retrieval(session)
    assert len(chunks) == 1
    assert "宁德时代" in chunks[0].text


def test_search_finds_total_assets_with_synonym():
    chunks = chunk_text("宁德时代总资产9748.28亿元，资产负债率稳定。", source="section:基本面", meta={"stock_code": "300750"})
    hits = search_chunks(chunks, "300750 资产总计多少", stock_code="300750")
    assert hits
    assert "9748" in hits[0][0].text


def test_merge_retrieved_hits_prefers_local_db():
    rag = [{"source": "summary", "score": 0.4, "text": "报告片段", "meta": {}}]
    data = [{"source": "datastore:pit_financials", "score": 0.92, "text": "pit row", "meta": {"priority": "local_db"}}]
    merged = _merge_retrieved_hits(rag, data, max_total=2)
    assert merged[0]["source"] == "datastore:pit_financials"
