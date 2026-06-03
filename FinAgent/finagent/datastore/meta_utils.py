"""快照 meta 写入规则：空对象/空壳数据不得覆盖已有有效内容。"""

from __future__ import annotations

from typing import Any

from .db import META_KEYS

_META_DICT_KEYS = frozenset({"industry", "industry_l2", "factor", "technical", "benchmark_index"})


def meta_value_is_usable(key: str, value: Any) -> bool:
    """空 dict、无同行的 industry_comparison、None 均视为不可用，不能作为有效更新。"""
    if value is None:
        return False
    if not isinstance(value, dict):
        return True
    if key in _META_DICT_KEYS:
        return bool(value)
    if key == "industry_comparison":
        industry = value.get("industry") if isinstance(value.get("industry"), dict) else {}
        peers = value.get("peers") if isinstance(value.get("peers"), dict) else {}
        has_name = any(
            industry.get(name)
            for name in ("level1_name", "first_industry_name", "selected_industry_name")
        )
        has_peers = int(peers.get("effective_count") or 0) > 0
        has_metrics = bool(value.get("metrics"))
        return has_name or has_peers or has_metrics
    return bool(value)


def merge_snapshot_meta(old_meta: dict[str, Any], new_data: dict[str, Any]) -> dict[str, Any]:
    """仅合并可用 meta；incoming 为空时保留 old，永不以空覆盖非空。"""
    meta = dict(old_meta or {})
    for key in META_KEYS:
        value = new_data.get(key)
        if meta_value_is_usable(key, value):
            meta[key] = value
    return meta


def series_payload_is_empty(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return True
    rows = payload.get("rows")
    if isinstance(rows, list):
        return len(rows) == 0
    return int(payload.get("row_count") or 0) == 0
