"""轻量知识图谱：从报告/PDF 抽取实体与关系，供对话检索。"""

from __future__ import annotations

import re
from typing import Any


METRIC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"归母净利润|净利润", "净利润"),
    (r"营业收入|营收", "营收"),
    (r"经营(?:活动)?现金流", "经营现金流"),
    (r"资产负债率", "资产负债率"),
    (r"毛利率", "毛利率"),
    (r"ROE|净资产收益率", "ROE"),
    (r"PE\s*\(?TTM\)?|市盈率", "PE"),
    (r"PB\s*\(?TTM\)?|市净率", "PB"),
    (r"融资余额", "融资余额"),
    (r"RSI|MACD|均线|MA20|MA60", "技术指标"),
    (r"Shibor|收益率曲线|国债", "宏观利率"),
)


def _node_id(kind: str, label: str) -> str:
    return f"{kind}:{label}"


def build_graph_from_report(report: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def add_node(kind: str, label: str, **extra: Any) -> str:
        nid = _node_id(kind, label)
        nodes[nid] = {"id": nid, "kind": kind, "label": label, **extra}
        return nid

    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    stock = str(meta.get("order_book_id") or report.get("annual_report", {}).get("stock_code") or "标的")
    company = add_node("company", stock, stock_code=stock.split(".")[0] if "." in stock else stock)

    summary = str(report.get("executive_summary") or report.get("summary") or "")
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    body = summary + "\n" + "\n".join(str(v) for v in sections.values())
    data_summary = report.get("data_summary") if isinstance(report.get("data_summary"), dict) else {}

    for key, value in (data_summary.get("technical") or {}).items():
        metric = add_node("metric", str(key), value=value)
        edges.append({"from": company, "to": metric, "rel": "has_technical"})
    for key, value in (data_summary.get("factor") or {}).items():
        metric = add_node("metric", str(key), value=value)
        edges.append({"from": company, "to": metric, "rel": "has_factor"})

    for pattern, label in METRIC_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            topic = add_node("topic", label)
            edges.append({"from": company, "to": topic, "rel": "discusses"})

    for name, content in sections.items():
        section = add_node("section", str(name))
        edges.append({"from": company, "to": section, "rel": "has_section"})
        for pattern, label in METRIC_PATTERNS:
            if re.search(pattern, str(content), re.IGNORECASE):
                topic = add_node("topic", label)
                edges.append({"from": section, "to": topic, "rel": "mentions"})

    return {"nodes": list(nodes.values()), "edges": edges}


def build_graph_from_text(text: str, *, source: str = "pdf") -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    company = _node_id("source", source)
    nodes[company] = {"id": company, "kind": "source", "label": source}

    for pattern, label in METRIC_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 80)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            topic_id = _node_id("topic", label)
            if topic_id not in nodes:
                nodes[topic_id] = {"id": topic_id, "kind": "topic", "label": label}
            fact_id = _node_id("fact", f"{label}:{match.start()}")
            nodes[fact_id] = {"id": fact_id, "kind": "fact", "label": label, "snippet": snippet[:200]}
            edges.append({"from": company, "to": topic_id, "rel": "mentions"})
            edges.append({"from": topic_id, "to": fact_id, "rel": "evidence"})
    return {"nodes": list(nodes.values()), "edges": edges}


def query_graph(graph: dict[str, Any], query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    q = str(query or "").lower()
    hits: list[tuple[float, dict[str, Any]]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        label = str(node.get("label") or "")
        snippet = str(node.get("snippet") or "")
        value = str(node.get("value") or "")
        haystack = " ".join([label, snippet, value]).lower()
        score = 0.0
        for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_.]{2,}", q):
            if token in haystack:
                score += 1.0
        if score > 0:
            hits.append((score, node))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [node for _, node in hits[:limit]]
