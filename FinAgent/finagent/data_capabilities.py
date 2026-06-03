from __future__ import annotations

import re
from typing import Any

from .data_registry import COLLECTED_SERIES, tool_for_data_key
COMPUTED_METRICS: dict[str, tuple[str, ...]] = {
    "MACD": ("macd", "macd_signal", "technical_indicators"),
    "回撤": ("max_drawdown", "latest_drawdown", "drawdown"),
    "RSI": ("rsi14",),
    "均线": ("ma20", "ma60"),
    "波动率": ("volatility_20d", "rolling_volatility"),
}

DESIGN_LIMITATIONS: dict[str, str] = {
    "季度环比": "pit_financials 仅采集年报 q4 口径，不含单季环比序列。",
    "季度": "pit_financials 仅采集年报 q4 口径，不含单季环比序列。",
    "中间期限": "yield_curve 快照图仅使用 1Y/3Y/5Y/10Y/30Y 等可用期限列。",
    "4Y": "yield_curve 快照图仅使用米筐返回的期限列。",
    "Wind": "系统未接入 Wind。",
    "券商预测": "系统未接入券商盈利预测。",
    "新闻": "系统未接入新闻舆情。",
}


def build_data_capability_inventory(
    data: dict[str, Any],
    charts: dict[str, str] | None = None,
) -> dict[str, Any]:
    charts = charts or {}
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    collected: dict[str, dict[str, Any]] = {}
    for key, label in COLLECTED_SERIES.items():
        value = data.get(key)
        if key == "pit_financials" and isinstance(value, dict):
            from .datastore.db import pit_cache_is_usable

            rows = value.get("rows") or []
            row_count = len(rows) if rows else int(value.get("row_count") or 0)
            available = pit_cache_is_usable(value)
        elif isinstance(value, dict):
            row_count = int(value.get("row_count") or 0)
            available = row_count > 0
        else:
            row_count = 0
            available = False
        collected[key] = {
            "label": label,
            "row_count": row_count,
            "available": available,
            "tool": tool_for_data_key(key),
        }

    computed: dict[str, dict[str, Any]] = {}
    for name, fields in COMPUTED_METRICS.items():
        values = {field: technical.get(field) for field in fields if field in technical}
        chart_keys = [k for k in fields if k in charts]
        available = bool(values) or bool(chart_keys)
        computed[name] = {
            "available": available,
            "technical_fields": list(values.keys()),
            "chart_keys": chart_keys,
        }

    empty_collectable = [key for key, item in collected.items() if not item["available"] and key in {"capital_flow"}]
    return {
        "collected": collected,
        "computed": computed,
        "charts": sorted(charts.keys()),
        "empty_collectable": empty_collectable,
        "design_limits": list(DESIGN_LIMITATIONS.values()),
    }


def build_data_gap_review(
    data: dict[str, Any],
    charts: dict[str, str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """将缺口描述分类：空数据源 / 误报（其实已采集或已计算）/ 设计不包含。"""
    inventory = build_data_capability_inventory(data, charts)
    gaps: list[dict[str, Any]] = []
    notes = notes or []

    for key in inventory["empty_collectable"]:
        gaps.append(
            {
                "id": key,
                "label": COLLECTED_SERIES.get(key, key),
                "status": "empty_at_source",
                "refresh_data": True,
                "note": f"{COLLECTED_SERIES.get(key, key)}：米筐返回 row_count=0，可尝试 refresh_data 重拉一次。",
            }
        )

    for note in notes:
        classified = _classify_gap_note(note, inventory)
        if classified:
            gaps.append(classified)

    deduped = _dedupe_gaps(gaps)
    refresh_keys = [g["id"] for g in deduped if g.get("refresh_data")]
    false_alarms = [g for g in deduped if g.get("status") == "false_alarm"]
    return {
        "gaps": deduped,
        "refresh_data_recommended": bool(refresh_keys),
        "refresh_keys": refresh_keys,
        "false_alarm_count": len(false_alarms),
        "inventory_summary": {
            "computed_available": [k for k, v in inventory["computed"].items() if v.get("available")],
            "empty_collectable": inventory["empty_collectable"],
        },
    }


def filter_gap_notes(
    notes: list[str],
    data: dict[str, Any],
    charts: dict[str, str] | None = None,
) -> list[str]:
    """去掉「MACD/回撤未采集」等误报，保留真实缺口。"""
    inventory = build_data_capability_inventory(data, charts)
    filtered: list[str] = []
    for note in notes:
        text = str(note).strip()
        if not text:
            continue
        classified = _classify_gap_note(text, inventory)
        if classified and classified.get("status") == "false_alarm":
            continue
        if classified and classified.get("status") == "design_limit":
            replacement = classified.get("note")
            if replacement and replacement not in filtered:
                filtered.append(replacement)
            continue
        filtered.append(text)
    return _dedupe_note_strings(filtered)


def reconcile_validation_gaps(
    validation: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """用能力清单清洗 validation 中的 missing_data / action_items。"""
    result = dict(validation)
    all_notes: list[str] = []
    all_notes.extend(_as_string_list(result.get("missing_data_notes")))
    all_notes.extend(_as_string_list(result.get("action_items")))
    review = build_data_gap_review(data, charts, all_notes)
    result["data_gap_review"] = review
    result["missing_data_notes"] = filter_gap_notes(_as_string_list(result.get("missing_data_notes")), data, charts)
    result["action_items"] = filter_gap_notes(_as_string_list(result.get("action_items")), data, charts)
    if review.get("refresh_data_recommended"):
        requests = dict(result.get("refinement_requests") or {})
        requests["refresh_data"] = True
        requests["reason"] = requests.get("reason") or "存在可重试的空数据源：" + ", ".join(review.get("refresh_keys") or [])
        result["refinement_requests"] = requests
        rerun = dict(result.get("agent_rerun_requests") or {})
        rerun["refresh_data"] = True
        rerun.setdefault("reason", requests["reason"])
        result["agent_rerun_requests"] = rerun
    return result


def normalize_executive_summary_gaps(text: str) -> str:
    """执行摘要「数据缺口」：去掉每条重复的详见，末尾统一一行指向专章。"""
    cleaned = re.sub(r"[（(]\s*详见《数据覆盖与局限》\s*[）)]", "", str(text or ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if "### 数据缺口" not in cleaned:
        return cleaned
    head, _, tail = cleaned.partition("### 数据缺口")
    bullets: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item and item not in {"详见《数据覆盖与局限》。", "详情见《数据覆盖与局限》。"}:
                bullets.append(item)
    head = head.rstrip()
    if not bullets:
        return f"{head}\n\n### 数据缺口\n\n详情见《数据覆盖与局限》。".strip()
    block = "\n".join(f"- {item}" for item in bullets[:3])
    return f"{head}\n\n### 数据缺口\n\n{block}\n\n详情见《数据覆盖与局限》。".strip()


def _classify_gap_note(note: str, inventory: dict[str, Any]) -> dict[str, Any] | None:
    text = note.strip()
    lower = text.lower()
    computed = inventory.get("computed") if isinstance(inventory.get("computed"), dict) else {}

    if any(token in text for token in ("MACD", "macd")):
        if computed.get("MACD", {}).get("available"):
            return {"id": "macd", "status": "false_alarm", "note": text, "reason": "MACD 已由行情派生，见 technical 与 technical_indicators 图。"}
    if "回撤" in text or "drawdown" in lower:
        if computed.get("回撤", {}).get("available"):
            return {"id": "drawdown", "status": "false_alarm", "note": text, "reason": "回撤已由行情派生，见 technical 与 drawdown 图。"}
    if "RSI" in text and computed.get("RSI", {}).get("available"):
        return {"id": "rsi", "status": "false_alarm", "note": text}

    for token, explanation in DESIGN_LIMITATIONS.items():
        if token in text:
            return {"id": token, "status": "design_limit", "note": explanation}

    if "capital_flow" in lower or "资金流向" in text:
        item = inventory.get("collected", {}).get("capital_flow", {})
        if not item.get("available"):
            return {
                "id": "capital_flow",
                "status": "empty_at_source",
                "refresh_data": True,
                "note": "资金流向：米筐 get_capital_flow 未返回有效行。",
            }
    return None


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for gap in gaps:
        gap_id = str(gap.get("id") or gap.get("note") or "")
        if gap_id in seen:
            continue
        seen.add(gap_id)
        out.append(gap)
    return out


def _dedupe_note_strings(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for note in notes:
        key = note.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
