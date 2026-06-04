from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import pandas as pd


INDUSTRY_SOURCE = "citics_2019"
MIN_EFFECTIVE_PEERS = 5
MIN_DBSCAN_ROWS = 8
MIN_DBSCAN_FEATURES = 3

PEER_FACTOR_CANDIDATES = [
    "pe_ratio_ttm",
    "pb_ratio_ttm",
    "ps_ratio_ttm",
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "operating_revenue_growth_ratio_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
    "quick_ratio",
]

CORE_EFFECTIVE_FACTORS = [
    "pe_ratio_ttm",
    "pb_ratio_ttm",
    "ps_ratio_ttm",
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "debt_to_asset_ratio",
    "current_ratio",
]

VALUATION_FACTORS = {"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"}
LOWER_IS_BETTER = {"pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm", "debt_to_asset_ratio"}
HIGHER_IS_BETTER = {
    "gross_profit_margin_ttm",
    "net_profit_margin_ttm",
    "roe_ttm",
    "net_profit_growth_ratio_ttm",
    "net_profit_parent_company_growth_ratio_ttm",
    "operating_profit_growth_ratio_ttm",
    "gross_profit_growth_ratio_ttm",
    "operating_revenue_growth_ratio_ttm",
    "current_ratio",
    "quick_ratio",
}

FACTOR_LABELS = {
    "pe_ratio_ttm": "PE(TTM)",
    "pb_ratio_ttm": "PB(TTM)",
    "ps_ratio_ttm": "PS(TTM)",
    "gross_profit_margin_ttm": "毛利率(TTM)",
    "net_profit_margin_ttm": "净利率(TTM)",
    "roe_ttm": "ROE(TTM)",
    "net_profit_growth_ratio_ttm": "净利润增长率(TTM)",
    "net_profit_parent_company_growth_ratio_ttm": "归母净利润增长率(TTM)",
    "operating_profit_growth_ratio_ttm": "营业利润增长率(TTM)",
    "gross_profit_growth_ratio_ttm": "毛利润增长率(TTM)",
    "operating_revenue_growth_ratio_ttm": "营收增长率(TTM)",
    "debt_to_asset_ratio": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
}


def fetch_industry_comparison(
    rqdatac: Any,
    *,
    order_book_id: str,
    as_of: date,
    available_factors: set[str] | None = None,
) -> dict[str, Any]:
    notes: list[str] = []
    factors = [name for name in PEER_FACTOR_CANDIDATES if available_factors is None or name in available_factors]
    if not factors:
        return _empty_result(order_book_id, "无可用同行因子。")

    industry_row = _target_industry(rqdatac, order_book_id, as_of)
    industry_info = _industry_info(industry_row)
    if not industry_info:
        return _empty_result(order_book_id, "无法获取目标公司中信行业分类。")

    last_attempt: dict[str, Any] | None = None
    for level in (3, 2):
        code = industry_info.get(f"level{level}_code")
        name = industry_info.get(f"level{level}_name")
        if not code and not name:
            notes.append(f"目标公司缺少 {level} 级行业分类。")
            continue

        industry_key = str(code or name)
        members = _industry_members(rqdatac, industry_key, as_of)
        if order_book_id not in members:
            members = [order_book_id, *members]
        members = _dedupe(members)
        factor_frame = _latest_factor_frame(
            rqdatac,
            members,
            factors,
            as_of,
        )
        effective = _effective_peer_frame(factor_frame, order_book_id)
        last_attempt = {
            "level": level,
            "code": code,
            "name": name,
            "candidate_count": len(members),
            "effective_count": len(effective),
            "members": members,
            "factor_frame": factor_frame,
            "effective_frame": effective,
        }
        if len(effective) >= MIN_EFFECTIVE_PEERS:
            return _build_result(
                order_book_id=order_book_id,
                industry_info=industry_info,
                selected=last_attempt,
                notes=notes,
            )
        if level == 3:
            notes.append("三级行业有效同行少于 5 家，已回退二级行业。")

    if last_attempt:
        notes.append("二级行业有效同行仍少于 5 家，按无有效同行处理。")
        return _no_peer_result(order_book_id, industry_info, last_attempt, notes)
    return _empty_result(order_book_id, "无法形成有效同行池。")


def _build_result(
    *,
    order_book_id: str,
    industry_info: dict[str, Any],
    selected: dict[str, Any],
    notes: list[str],
) -> dict[str, Any]:
    frame = selected["effective_frame"]
    metrics = _metric_stats(frame, order_book_id)
    cluster = _dbscan_anomaly(frame, order_book_id)
    result_notes = [*notes]
    if cluster.get("status") != "ok" and cluster.get("reason"):
        result_notes.append(str(cluster["reason"]))
    return {
        "industry": {
            **industry_info,
            "source": INDUSTRY_SOURCE,
            "selected_level": selected["level"],
            "selected_industry_code": selected["code"],
            "selected_industry_name": selected["name"],
        },
        "peers": {
            "selected_level": selected["level"],
            "candidate_count": selected["candidate_count"],
            "effective_count": selected["effective_count"],
            "order_book_ids": [str(idx) for idx in frame.index.tolist()],
            "sample_order_book_ids": [str(idx) for idx in frame.index.tolist()[:20]],
        },
        "metrics": metrics,
        "relative_signals": _relative_signals(metrics),
        "cluster_anomalies": cluster,
        "data_notes": _dedupe(result_notes),
    }


def _no_peer_result(
    order_book_id: str,
    industry_info: dict[str, Any],
    selected: dict[str, Any],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "industry": {
            **industry_info,
            "source": INDUSTRY_SOURCE,
            "selected_level": None,
            "selected_industry_code": None,
            "selected_industry_name": None,
        },
        "peers": {
            "selected_level": selected.get("level"),
            "candidate_count": selected.get("candidate_count", 0),
            "effective_count": selected.get("effective_count", 0),
            "order_book_ids": [],
            "sample_order_book_ids": [],
        },
        "metrics": {},
        "relative_signals": [],
        "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": "无有效同行。"},
        "data_notes": _dedupe(notes),
    }


def _empty_result(order_book_id: str, note: str) -> dict[str, Any]:
    return {
        "industry": {"source": INDUSTRY_SOURCE, "selected_level": None},
        "peers": {"selected_level": None, "candidate_count": 0, "effective_count": 0, "order_book_ids": [], "sample_order_book_ids": []},
        "metrics": {},
        "relative_signals": [],
        "cluster_anomalies": {"method": "DBSCAN", "status": "skipped", "reason": note},
        "data_notes": [note],
    }


def _target_industry(rqdatac: Any, order_book_id: str, as_of: date) -> dict[str, Any]:
    df = rqdatac.get_instrument_industry(order_book_id, source=INDUSTRY_SOURCE, level=0, date=as_of)
    if df is None or getattr(df, "empty", True):
        return {}
    row = df.reset_index().iloc[0].to_dict()
    return {str(k): _json_value(v) for k, v in row.items()}


def _industry_info(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "level1_code": row.get("first_industry_code"),
        "level1_name": row.get("first_industry_name"),
        "level2_code": row.get("second_industry_code"),
        "level2_name": row.get("second_industry_name"),
        "level3_code": row.get("third_industry_code"),
        "level3_name": row.get("third_industry_name"),
    }


def _industry_members(rqdatac: Any, industry: str, as_of: date) -> list[str]:
    try:
        members = rqdatac.get_industry(industry, source=INDUSTRY_SOURCE, date=as_of)
    except Exception:
        members = []
    return [str(item) for item in (members or []) if str(item).strip()]


def _latest_factor_frame(rqdatac: Any, order_book_ids: list[str], factors: list[str], as_of: date) -> pd.DataFrame:
    if not order_book_ids or not factors:
        return pd.DataFrame()
    # 当日因子可能尚未更新；回看若干交易日取各股票最近一条有效截面。
    lookback_start = as_of - timedelta(days=15)
    df = rqdatac.get_factor(order_book_ids, factors, start_date=lookback_start, end_date=as_of)
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(index=order_book_ids, columns=factors)
    frame = df.reset_index()
    if "order_book_id" not in frame.columns:
        first = frame.columns[0]
        frame = frame.rename(columns={first: "order_book_id"})
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values(["order_book_id", "date"])
        core = [name for name in CORE_EFFECTIVE_FACTORS if name in frame.columns]
        if core:
            frame = frame[frame[core].notna().any(axis=1)]
    frame = frame.groupby("order_book_id", as_index=True).tail(1).set_index("order_book_id")
    for order_book_id in order_book_ids:
        if order_book_id not in frame.index:
            frame.loc[order_book_id] = pd.NA
    frame = frame.reindex(order_book_ids)
    for factor in factors:
        if factor not in frame.columns:
            frame[factor] = pd.NA
        frame[factor] = pd.to_numeric(frame[factor], errors="coerce")
    return frame[factors]


def _effective_peer_frame(frame: pd.DataFrame, order_book_id: str) -> pd.DataFrame:
    if frame.empty or order_book_id not in frame.index:
        return pd.DataFrame()
    core = [name for name in CORE_EFFECTIVE_FACTORS if name in frame.columns]
    if not core:
        return pd.DataFrame()
    valid_count = frame[core].notna().sum(axis=1)
    effective = frame.loc[valid_count >= 3].copy()
    if order_book_id not in effective.index:
        return pd.DataFrame()
    return effective


def _metric_stats(frame: pd.DataFrame, order_book_id: str) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    if frame.empty or order_book_id not in frame.index:
        return metrics
    for factor in frame.columns:
        series = pd.to_numeric(frame[factor], errors="coerce").dropna()
        target = _float_or_none(frame.loc[order_book_id, factor])
        if target is None or len(series) < MIN_EFFECTIVE_PEERS:
            continue
        p25 = float(series.quantile(0.25))
        p75 = float(series.quantile(0.75))
        percentile = _percentile(series, target)
        metrics[factor] = {
            "label": FACTOR_LABELS.get(factor, factor),
            "target": target,
            "mean": float(series.mean()),
            "median": float(series.median()),
            "p25": p25,
            "p75": p75,
            "percentile": percentile,
            "valid_count": int(len(series)),
            "direction": _direction(factor),
            "relative_label": _relative_label(factor, percentile),
        }
    return metrics


def _relative_signals(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for factor, item in metrics.items():
        percentile = item.get("percentile")
        if percentile is None:
            continue
        direction = item.get("direction")
        label = item.get("label", factor)
        relative = item.get("relative_label")
        if direction == "lower_better" and percentile >= 0.75:
            signals.append({"metric": factor, "label": label, "polarity": "negative", "severity": "medium", "summary": f"{label}高于行业上四分位，{relative}。"})
        elif direction == "higher_better" and percentile <= 0.25:
            signals.append({"metric": factor, "label": label, "polarity": "negative", "severity": "medium", "summary": f"{label}低于行业下四分位，{relative}。"})
        elif direction == "higher_better" and percentile >= 0.75:
            signals.append({"metric": factor, "label": label, "polarity": "positive", "severity": "medium", "summary": f"{label}高于行业上四分位，{relative}。"})
    return signals[:10]


def _dbscan_anomaly(frame: pd.DataFrame, order_book_id: str) -> dict[str, Any]:
    if len(frame) < MIN_DBSCAN_ROWS:
        return {"method": "DBSCAN", "status": "skipped", "reason": "有效同行少于 8 家，跳过 DBSCAN。"}
    prepared = _prepare_cluster_matrix(frame)
    matrix = prepared["matrix"]
    features = prepared["features"]
    if matrix is None or len(features) < MIN_DBSCAN_FEATURES:
        return {"method": "DBSCAN", "status": "skipped", "reason": "有效聚类特征少于 3 个，跳过 DBSCAN。"}
    if order_book_id not in matrix.index:
        return {"method": "DBSCAN", "status": "skipped", "reason": "目标公司不在有效聚类样本中。"}
    try:
        from sklearn.cluster import DBSCAN
        from sklearn.neighbors import NearestNeighbors
    except Exception as exc:
        return {"method": "DBSCAN", "status": "skipped", "reason": f"scikit-learn 不可用，跳过 DBSCAN：{type(exc).__name__}"}

    n = len(matrix)
    min_samples = max(3, min(6, int(math.floor(math.sqrt(n)))))
    neighbor_count = min(min_samples, n)
    neighbors = NearestNeighbors(n_neighbors=neighbor_count)
    neighbors.fit(matrix.to_numpy())
    distances, _ = neighbors.kneighbors(matrix.to_numpy())
    kth_distances = distances[:, -1]
    eps = float(pd.Series(kth_distances).quantile(0.80))
    if not math.isfinite(eps) or eps <= 0:
        eps = 0.5
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(matrix.to_numpy())
    label_by_id = dict(zip(matrix.index.tolist(), labels.tolist(), strict=False))
    target_label = int(label_by_id[order_book_id])
    target_vector = matrix.loc[order_book_id]
    plot_features = _plot_features(matrix)
    single_metric_anomalies = _single_metric_anomalies(target_vector)
    top_contributors = _top_contributors(target_vector)
    cluster_size = int(sum(1 for label in labels if int(label) == target_label)) if target_label != -1 else 0
    score = float(target_vector.abs().mean())
    return {
        "method": "DBSCAN",
        "status": "ok",
        "features": features,
        "eps": eps,
        "min_samples": min_samples,
        "target_label": target_label,
        "is_noise": target_label == -1,
        "cluster_size": cluster_size,
        "anomaly_score": score,
        "top_contributors": top_contributors,
        "single_metric_anomalies": single_metric_anomalies,
        "plot_features": plot_features,
        "points": _cluster_points(matrix, labels, order_book_id, plot_features),
    }


def _prepare_cluster_matrix(frame: pd.DataFrame) -> dict[str, Any]:
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    keep: list[str] = []
    min_valid = max(MIN_EFFECTIVE_PEERS, int(math.ceil(len(numeric) * 0.60)))
    for col in numeric.columns:
        if numeric[col].notna().sum() >= min_valid:
            keep.append(col)
    if len(keep) < MIN_DBSCAN_FEATURES:
        return {"matrix": None, "features": []}
    clipped = numeric[keep].copy()
    for col in keep:
        series = clipped[col].dropna()
        if series.empty:
            continue
        low = series.quantile(0.05)
        high = series.quantile(0.95)
        clipped[col] = clipped[col].clip(lower=low, upper=high)
        median = clipped[col].median()
        clipped[col] = clipped[col].fillna(median)
    scaled = pd.DataFrame(index=clipped.index)
    for col in keep:
        median = clipped[col].median()
        q1 = clipped[col].quantile(0.25)
        q3 = clipped[col].quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            std = clipped[col].std()
            iqr = std if std and not pd.isna(std) else 1.0
        scaled[col] = (clipped[col] - median) / iqr
    scaled = scaled.replace([float("inf"), float("-inf")], 0).fillna(0)
    return {"matrix": scaled, "features": keep}


def _single_metric_anomalies(target_vector: pd.Series) -> list[dict[str, Any]]:
    items = []
    for factor, value in target_vector.items():
        value = float(value)
        if abs(value) > 2.5:
            items.append({"metric": factor, "label": FACTOR_LABELS.get(factor, factor), "robust_z": value})
    return sorted(items, key=lambda item: abs(item["robust_z"]), reverse=True)[:5]


def _top_contributors(target_vector: pd.Series) -> list[dict[str, Any]]:
    items = [
        {"metric": factor, "label": FACTOR_LABELS.get(factor, factor), "robust_z": float(value)}
        for factor, value in target_vector.items()
    ]
    return sorted(items, key=lambda item: abs(item["robust_z"]), reverse=True)[:3]


def _plot_features(matrix: pd.DataFrame) -> list[str]:
    if matrix.shape[1] <= 2:
        return list(matrix.columns[:2])
    variance = matrix.var(axis=0).sort_values(ascending=False)
    return [str(item) for item in variance.index[:2]]


def _cluster_points(matrix: pd.DataFrame, labels: Any, order_book_id: str, features: list[str]) -> list[dict[str, Any]]:
    if len(features) < 2:
        return []
    x_key, y_key = features[0], features[1]
    points: list[dict[str, Any]] = []
    for order_id, label in zip(matrix.index.tolist(), labels, strict=False):
        points.append(
            {
                "order_book_id": str(order_id),
                "x": float(matrix.loc[order_id, x_key]),
                "y": float(matrix.loc[order_id, y_key]),
                "label": int(label),
                "is_noise": int(label) == -1,
                "is_target": str(order_id) == order_book_id,
            }
        )
    return points


def _percentile(series: pd.Series, target: float) -> float:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return 0.0
    below = int((valid < target).sum())
    equal = int((valid == target).sum())
    return float((below + 0.5 * equal) / len(valid))


def _relative_label(factor: str, percentile: float) -> str:
    if percentile >= 0.75:
        position = "处于行业高位"
    elif percentile <= 0.25:
        position = "处于行业低位"
    else:
        position = "接近行业中位区间"
    direction = _direction(factor)
    if direction == "lower_better" and percentile >= 0.75:
        return f"{position}，相对不利"
    if direction == "higher_better" and percentile >= 0.75:
        return f"{position}，相对占优"
    if direction == "higher_better" and percentile <= 0.25:
        return f"{position}，相对偏弱"
    return position


def _direction(factor: str) -> str:
    if factor in LOWER_IS_BETTER:
        return "lower_better"
    if factor in HIGHER_IS_BETTER:
        return "higher_better"
    return "neutral"


def _dedupe(values: list[Any]) -> list[Any]:
    seen: dict[Any, None] = {}
    for value in values:
        if value not in seen and value not in (None, ""):
            seen[value] = None
    return list(seen)


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result) or not math.isfinite(result):
        return None
    return result


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value
