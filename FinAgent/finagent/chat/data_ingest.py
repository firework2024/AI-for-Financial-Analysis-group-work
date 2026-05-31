"""对话场景：本地数据库缺数据时，按需拉取年报/行情并入库。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..cninfo import default_as_of, download_report, fetch_annual_reports, latest_annual_report, normalize_stock_code
from ..concurrency import env_flag, finagent_max_workers, parallel_map
from ..datastore.snapshot_merge import market_snapshot_is_stale
from ..datastore.query import (
    _OVERVIEW_HINTS,
    _mentions_annual,
    _mentions_financials,
    _select_data_keys,
    extract_report_year,
    query_needs_stored_data,
)
from .data_tools import fetch_market_snapshot, needs_live_data
from .intent import classify_query_intent

# 新对话一键入库：行情 + PIT 可并行，年报（PDF）放最后
BOOTSTRAP_GAPS = ("market_snapshot", "pit_financials", "annual_report")
BOOTSTRAP_PARALLEL_GAPS = frozenset({"market_snapshot", "pit_financials"})
FAST_INGEST_ORDER = ("market_snapshot", "pit_financials", "annual_report")

_GAP_LABELS = {
    "market_snapshot": "行情快照",
    "pit_financials": "财务序列",
    "annual_report": "年报 PDF",
}


def chat_bootstrap_enabled() -> bool:
    from ..env import get_env

    flag = str(get_env("FINAGENT_AUTO_INGEST_ON_NEW_CHAT", "true") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def bootstrap_lookback_days() -> int:
    from ..env import get_env

    raw = str(get_env("FINAGENT_BOOTSTRAP_LOOKBACK_DAYS", "90") or "90").strip()
    try:
        return max(30, min(int(raw), 365))
    except ValueError:
        return 90


def ingest_parallel_enabled() -> bool:
    return env_flag("FINAGENT_INGEST_PARALLEL", default=True)


def bootstrap_stock_data(
    stock_code: str,
    *,
    workdir: Path | None = None,
    report_year: int | None = None,
    lookback_days: int | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """新对话预加载：行情 + PIT + 年报写入 SQLite（已存在步骤会跳过）。"""
    code = normalize_stock_code(stock_code)
    root = workdir or Path(".")
    year = report_year if report_year is not None else default_as_of(None).year - 1
    lb = lookback_days if lookback_days is not None else bootstrap_lookback_days()
    actions = _run_ingest_plan(
        code,
        BOOTSTRAP_GAPS,
        workdir=root,
        report_year=year,
        lookback_days=lb,
        on_progress=on_progress,
        parallel_prefetch=BOOTSTRAP_PARALLEL_GAPS,
    )
    ok_count = sum(1 for item in actions if item.get("ok"))
    sec_name = next((a.get("sec_name") for a in actions if a.get("sec_name")), None)
    return {
        "stock_code": code,
        "report_year": year,
        "requested_gaps": list(BOOTSTRAP_GAPS),
        "actions": actions,
        "ok": ok_count > 0,
        "sec_name": sec_name,
        "message": _bootstrap_message(actions, sec_name=sec_name, code=code),
    }


def get_data_gaps(stock_code: str, query: str) -> list[str]:
    """根据问题判断本地尚缺哪些数据类型。"""
    from ..datastore.db import get_annual_report, get_latest_snapshot, get_pit_financials

    code = normalize_stock_code(stock_code)
    intent = classify_query_intent(query)
    report_year = extract_report_year(query)
    snapshot = get_latest_snapshot(code)
    pit = get_pit_financials(code)
    annual = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)

    wants_market = intent.want_live_quote or bool(_select_data_keys(query)) or needs_live_data(query)
    wants_financial = intent.fundamentals and _mentions_financials(query)
    wants_annual = (intent.annual or intent.disclosure) and (
        _mentions_annual(query) or report_year is not None
    )
    wants_overview = intent.overview

    gaps: list[str] = []
    if wants_market and market_snapshot_is_stale(snapshot):
        gaps.append("market_snapshot")
    if wants_annual and annual_report_needs_update(code, annual, report_year=report_year):
        gaps.append("annual_report")
    if wants_financial and pit is None and "annual_report" not in gaps:
        gaps.append("pit_financials")

    if not snapshot and not pit and not annual and (query_needs_stored_data(query) or needs_live_data(query)):
        if wants_overview:
            for kind in ("market_snapshot", "annual_report"):
                if kind not in gaps:
                    gaps.append(kind)
        elif wants_market and "market_snapshot" not in gaps:
            gaps.append("market_snapshot")
        elif (wants_annual or wants_financial) and "annual_report" not in gaps:
            gaps.append("annual_report")

    return gaps


def ensure_stored_data(stock_code: str, query: str, *, workdir: Path | None = None) -> dict[str, Any] | None:
    """缺数据则拉取并写入 SQLite，返回 ingest 摘要。"""
    code = normalize_stock_code(stock_code)
    gaps = get_data_gaps(code, query)
    if not gaps:
        return None

    root = workdir or Path(".")
    year = extract_report_year(query)
    ordered = [g for g in FAST_INGEST_ORDER if g in gaps]
    actions = _run_ingest_plan(
        code,
        ordered,
        workdir=root,
        report_year=year,
        lookback_days=bootstrap_lookback_days(),
        parallel_prefetch=BOOTSTRAP_PARALLEL_GAPS,
    )
    ok_count = sum(1 for item in actions if item.get("ok"))
    return {
        "stock_code": code,
        "requested_gaps": gaps,
        "actions": actions,
        "ok": ok_count > 0,
        "message": _ingest_message(actions),
    }


def ingest_market_snapshot(stock_code: str, *, lookback_days: int = 180) -> dict[str, Any]:
    from ..datastore.db import get_latest_snapshot

    code = normalize_stock_code(stock_code)
    before = get_latest_snapshot(code)
    live = fetch_market_snapshot(code, lookback_days=lookback_days, incremental=True)
    err = live.get("error")
    if err and not live_quote_has_data(live):
        return {"ok": False, "error": str(err)}
    snap = get_latest_snapshot(code)
    mode = "incremental" if before else "full"
    return {
        "ok": True,
        "mode": mode,
        "snapshot_id": (snap or {}).get("id"),
        "source": live.get("source"),
        "end_date": live.get("end_date"),
        "live": live,
    }


def ingest_pit_financials(stock_code: str, *, report_year: int | None = None) -> dict[str, Any]:
    from ..datastore.db import get_annual_report, get_pit_financials
    from ..rqdata_client import fetch_financials

    code = normalize_stock_code(stock_code)
    if get_pit_financials(code):
        pit = get_pit_financials(code)
        return {"ok": True, "skipped": True, "row_count": len((pit or {}).get("rows") or [])}

    annual = get_annual_report(code)
    year = report_year or (annual or {}).get("report_year") or (default_as_of(None).year - 1)
    fetched = fetch_financials(code, int(year), years=3)
    return {"ok": True, "report_year": int(year), "row_count": len(fetched.rows)}


def ingest_annual_report(
    stock_code: str,
    *,
    report_year: int | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    from ..datastore.db import get_annual_report, save_annual_report_record
    from ..datastore.annual_text import mda_storage_payload
    from ..fallback import apply_financial_fallbacks

    code = normalize_stock_code(stock_code)
    existing = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)
    if existing and not annual_report_needs_update(code, existing, report_year=report_year):
        return {
            "ok": True,
            "skipped": True,
            "report_year": existing.get("report_year"),
            "sec_name": existing.get("sec_name"),
            "skip_reason": _annual_skip_reason(existing),
        }

    as_of = default_as_of(None)
    report = _resolve_annual_report(code, report_year, as_of)
    if report.report_year is None:
        raise RuntimeError(f"无法识别年报年份: {report.title}")

    root = workdir or Path(".")
    parallel = ingest_parallel_enabled()
    if parallel:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            pdf_future = pool.submit(_download_and_parse_pdf, report, root)
            fin_future = pool.submit(_financial_rows_for_annual, code, int(report.report_year))
            pdf_path, full_text, mda = pdf_future.result()
            fin_rows, order_book_id = fin_future.result()
    else:
        pdf_path, full_text, mda = _download_and_parse_pdf(report, root)
        fin_rows, order_book_id = _financial_rows_for_annual(code, int(report.report_year))

    financial_data = apply_financial_fallbacks(fin_rows, full_text)
    mda_payload = mda_storage_payload(mda)
    save_annual_report_record(
        stock_code=report.stock_code,
        report_year=report.report_year,
        order_book_id=order_book_id,
        sec_name=report.sec_name,
        title=report.title,
        pdf_path=str(pdf_path),
        meta=report.to_dict(),
        financial_data=financial_data,
        mda_text=mda_payload["mda_text"],
        mda_meta=mda_payload["mda_meta"],
    )
    return {
        "ok": True,
        "report_year": report.report_year,
        "sec_name": report.sec_name,
        "pdf_path": str(pdf_path),
        "financial_rows": len(financial_data),
    }


def _run_ingest_plan(
    code: str,
    gaps: tuple[str, ...] | list[str],
    *,
    workdir: Path,
    report_year: int | None,
    lookback_days: int,
    on_progress: Any | None = None,
    parallel_prefetch: frozenset[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    gap_list = list(gaps)
    total = len(gap_list)
    actions: list[dict[str, Any]] = []
    prefetch = set(parallel_prefetch or ()) if ingest_parallel_enabled() else set()
    batch = [g for g in gap_list if g in prefetch]
    tail = [g for g in gap_list if g not in prefetch]

    def _emit(gap: str, index: int) -> None:
        if on_progress:
            label = _GAP_LABELS.get(gap, gap)
            on_progress(
                gap=gap,
                index=index,
                total=total,
                message=f"正在入库 {label}（{index}/{total}）…",
            )

    if batch:
        tasks = {
            gap: (lambda g=gap: _ingest_gap(code, g, workdir=workdir, report_year=report_year, lookback_days=lookback_days))
            for gap in batch
        }
        for gap in batch:
            _emit(gap, gap_list.index(gap) + 1)
        results = parallel_map(tasks, max_workers=min(len(batch), finagent_max_workers()))
        for gap in batch:
            actions.append(_action_from_gap_result(gap, results.get(gap)))
    for offset, gap in enumerate(tail):
        _emit(gap, len(batch) + offset + 1)
        actions.append(_action_from_gap_result(gap, _ingest_gap(code, gap, workdir=workdir, report_year=report_year, lookback_days=lookback_days)))
    return actions


def _ingest_gap(
    code: str,
    gap: str,
    *,
    workdir: Path,
    report_year: int | None,
    lookback_days: int,
) -> dict[str, Any]:
    if gap == "annual_report":
        return ingest_annual_report(code, report_year=report_year, workdir=workdir)
    if gap == "pit_financials":
        return ingest_pit_financials(code, report_year=report_year)
    if gap == "market_snapshot":
        return ingest_market_snapshot(code, lookback_days=lookback_days)
    raise ValueError(f"unknown gap: {gap}")


def _action_from_gap_result(gap: str, result: Any) -> dict[str, Any]:
    if isinstance(result, BaseException):
        return {"gap": gap, "ok": False, "error": f"{type(result).__name__}: {result}"}
    if isinstance(result, dict):
        return {"gap": gap, **result}
    return {"gap": gap, "ok": False, "error": "unknown result"}


def _download_and_parse_pdf(report: Any, workdir: Path) -> tuple[Path, str, Any]:
    from ..pdf_text import extract_mda, extract_pdf_text

    pdf_path = download_report(report, workdir / "annual_reports", use_cache=True)
    full_text = extract_pdf_text(pdf_path)
    mda = extract_mda(full_text)
    return pdf_path, full_text, mda


def _financial_rows_for_annual(stock_code: str, report_year: int) -> tuple[list[dict[str, Any]], str]:
    from ..cninfo import to_order_book_id
    from ..datastore.db import get_pit_financials
    from ..rqdata_client import fetch_financials

    code = normalize_stock_code(stock_code)
    pit = get_pit_financials(code)
    rows = (pit or {}).get("rows") if isinstance(pit, dict) else None
    if rows and int((pit or {}).get("report_year") or report_year) == int(report_year):
        obid = str((pit or {}).get("order_book_id") or to_order_book_id(code))
        return list(rows), obid
    fetched = fetch_financials(code, report_year, years=3)
    return fetched.rows, fetched.order_book_id


def _resolve_annual_report(stock_code: str, report_year: int | None, as_of):
    if report_year is not None:
        reports = fetch_annual_reports(stock_code, f"{report_year}-01-01", f"{report_year}-12-31")
        for item in reports:
            if item.report_year == report_year:
                return item
        if reports:
            return reports[0]
    return latest_annual_report(stock_code, as_of)


def target_annual_report_year(as_of: date | None = None) -> int:
    """当前时点应优先使用的最新完整年报年份（A 股多为上一年度）。"""
    ref = as_of or default_as_of(None)
    return ref.year - 1


def annual_report_needs_update(
    stock_code: str,
    existing: dict[str, Any] | None,
    *,
    report_year: int | None = None,
    as_of: date | None = None,
) -> bool:
    if existing is None:
        return True
    ref = as_of or default_as_of(None)
    if report_year is not None:
        stored = existing.get("report_year")
        if stored != report_year:
            return True
        return _annual_fetched_too_old(existing, ref)
    target = target_annual_report_year(ref)
    stored_year = existing.get("report_year")
    if stored_year is None:
        return True
    if int(stored_year) < target:
        return True
    if int(stored_year) > target:
        return False
    return _annual_fetched_too_old(existing, ref)


def _annual_max_age_days() -> int:
    from ..env import get_env

    raw = str(get_env("FINAGENT_ANNUAL_MAX_AGE_DAYS", "120") or "120").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 120


def _annual_fetched_too_old(existing: dict[str, Any], as_of: date) -> bool:
    max_age = _annual_max_age_days()
    if max_age <= 0:
        return False
    text = str(existing.get("fetched_at") or "").strip()
    if not text:
        return True
    try:
        fetched = datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        return True
    return (as_of - fetched).days >= max_age


def _annual_skip_reason(existing: dict[str, Any]) -> str:
    year = existing.get("report_year")
    max_age = _annual_max_age_days()
    if max_age <= 0:
        return f"本地已有 {year} 年报，按年份无需更新"
    return f"本地已有 {year} 年报且在 {max_age} 天内已更新"


def live_quote_has_data(live: dict[str, Any] | None) -> bool:
    from .data_tools import live_quote_available

    return live_quote_available(live)


def fetch_stock_data_full(
    stock_code: str,
    *,
    report_year: int | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """主动拉取行情、年报、PIT 财务并写入 SQLite（对话「获取数据」按钮）。"""
    code = normalize_stock_code(stock_code)
    root = workdir or Path(".")
    year = report_year or extract_report_year("") or (default_as_of(None).year - 1)
    actions = _run_ingest_plan(
        code,
        FAST_INGEST_ORDER,
        workdir=root,
        report_year=year,
        lookback_days=bootstrap_lookback_days(),
        parallel_prefetch=BOOTSTRAP_PARALLEL_GAPS,
    )
    ok_count = sum(1 for item in actions if item.get("ok"))
    return {
        "stock_code": code,
        "requested_gaps": list(FAST_INGEST_ORDER),
        "actions": actions,
        "ok": ok_count > 0,
        "message": _ingest_message(actions),
    }


def _bootstrap_message(actions: list[dict[str, Any]], *, sec_name: str | None, code: str) -> str:
    base = _ingest_message(actions)
    label = sec_name or code
    return f"{label} 数据预加载完成：{base}" if base else f"{label} 数据预加载完成"


def _ingest_message(actions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in actions:
        gap = item.get("gap")
        if not item.get("ok"):
            parts.append(f"{gap} 拉取失败：{item.get('error', '未知错误')}")
            continue
        if item.get("skipped"):
            reason = item.get("skip_reason") or "已存在，跳过"
            parts.append(f"{gap} {reason}")
            continue
        if gap == "annual_report":
            parts.append(f"已下载并入库 {item.get('report_year')} 年报（{item.get('sec_name') or ''}）")
        elif gap == "market_snapshot":
            mode = item.get("mode") or "full"
            label = "增量更新" if mode == "incremental" else "全量拉取"
            parts.append(f"已{label}行情（截至 {item.get('end_date') or '最近交易日'}）")
        elif gap == "pit_financials":
            parts.append(f"已入库财务序列（{item.get('row_count', 0)} 条）")
    return "；".join(parts) if parts else ""
