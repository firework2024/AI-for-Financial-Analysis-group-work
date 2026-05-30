from finagent.chat.knowledge_graph import build_graph_from_text, query_graph
from finagent.chat.rag import chunk_text, search_chunks


def test_rag_finds_relevant_chunk():
    chunks = chunk_text("宁德时代 2025 年营收增长 27%，融资余额持续上升。", source="demo")
    hits = search_chunks(chunks, "融资余额怎么样")
    assert hits
    assert "融资" in hits[0][0].text


def test_graph_query_finds_metric_topic():
    graph = build_graph_from_text("公司 PE 估值偏高，ROE 保持稳定，Shibor 短端上行。")
    hits = query_graph(graph, "PE ROE")
    labels = {node.get("label") for node in hits}
    assert "PE" in labels or "ROE" in labels
