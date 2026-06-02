"""对话场景：本地数据库缺数据时，按需拉取年报/行情并入库。

统一链路（各入口最终汇聚于此）：
- 新对话 bootstrap → bootstrap_stock_data
- 对话按需补拉 → ensure_stored_data / fetch_stock_data_full
- 多智能体基本面 → ensure_annual_report_in_store + data_executor_agent
- Web/CLI 手动入库 → run_data_ingest(mode=...)
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

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

# 对话：先增量刷新到最近交易日(quote_refresh)，再按需拉报告级长历史(market_history)
BOOTSTRAP_GAPS_LIGHT = ("market_history", "pit_financials")
BOOTSTRAP_GAPS_FULL = ("market_history", "pit_financials", "annual_report")
BOOTSTRAP_GAPS = BOOTSTRAP_GAPS_FULL
REPORT_INGEST_GAPS = ("quote_refresh", "market_history", "pit_financials", "annual_report")
BOOTSTRAP_PARALLEL_GAPS = frozenset({"pit_financials"})
CHAT_INGEST_ORDER = ("quote_refresh", "market_history", "pit_financials", "annual_report")
FAST_INGEST_ORDER = CHAT_INGEST_ORDER

_GAP_LABELS = {
    "quote_refresh": "行情增量（至最近交易日）",
    "market_history": "报告级量价历史",
    "market_snapshot": "报告级量价历史",
    "pit_financials": "财务序列",
    "annual_report": "年报 PDF",
}


class AnnualCacheError(RuntimeError):
    """本地年报/财务数据不可用且禁止外网拉取时抛出。"""


IngestMode = Literal[
    "bootstrap_light",
    "bootstrap_full",
    "query_driven",
    "manual_full",
    "force_all",
    "report_prep",
]


def gaps_for_mode(mode: IngestMode) -> tuple[str, ...]:
    if mode == "report_prep":
        return REPORT_INGEST_GAPS
    if mode in {"bootstrap_full", "manual_full", "force_all"}:
        return BOOTSTRAP_GAPS_FULL
    if mode == "bootstrap_light":
        return BOOTSTRAP_GAPS_LIGHT
    return CHAT_INGEST_ORDER


def quote_refresh_lookback_days() -> int:
    from ..env import get_env

    raw = str(get_env("FINAGENT_QUOTE_REFRESH_LOOKBACK_DAYS", "60") or "60").strip()
    try:
        return max(20, min(int(raw), 120))
    except ValueError:
        return 60


def report_market_lookback_days() -> int:
    from ..env import get_env

    raw = str(get_env("FINAGENT_REPORT_MARKET_LOOKBACK_DAYS", "260") or "260").strip()
    try:
        return max(60, min(int(raw), 520))
    except ValueError:
        return 260


def _needs_report_level_market(query: str, intent: Any) -> bool:
    if getattr(intent, "overview", False):
        return True
    if getattr(intent, "want_background_ingest", False):
        return True
    keys = set(_select_data_keys(query))
    deep = {
        "turnover",
        "capital_flow",
        "securities_margin",
        "factor_history",
        "dividend",
        "shares",
        "index_benchmark",
        "block_trade",
        "interbank_rate",
        "yield_curve",
    }
    return bool(keys & deep)


def _annual_has_usable_content(annual: dict[str, Any] | None) -> bool:
    if not annual:
        return False
    fin = annual.get("financial_data")
    if isinstance(fin, list) and fin:
        return True
    return bool(str(annual.get("mda_text") or "").strip())


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


def bootstrap_include_annual_report() -> bool:
    return env_flag("FINAGENT_BOOTSTRAP_INCLUDE_ANNUAL_REPORT", default=False)


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
    gaps = BOOTSTRAP_GAPS_FULL if bootstrap_include_annual_report() else BOOTSTRAP_GAPS_LIGHT
    actions = _run_ingest_plan(
        code,
        gaps,
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
        "requested_gaps": list(gaps),
        "actions": actions,
        "ok": ok_count > 0,
        "sec_name": sec_name,
        "message": _bootstrap_message(actions, sec_name=sec_name, code=code),
    }


def get_data_gaps(stock_code: str, query: str) -> list[str]:
    """对话按需入库：1) 有无本地数据 2) 是否最新交易日 3) 过时则先增量再拉报告级行情/年报。"""
    from ..datastore.db import get_annual_report, get_latest_snapshot, get_pit_financials
    from ..datastore.market_cache import local_price_volume_available, market_is_current
    from ..stock_utils import calendar_trading_as_of

    code = normalize_stock_code(stock_code)
    intent = classify_query_intent(query)
    report_year = extract_report_year(query)
    ref = calendar_trading_as_of(default_as_of(None))
    snapshot = get_latest_snapshot(code)
    pit = get_pit_financials(code)
    annual = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)

    wants_market = intent.want_live_quote or bool(_select_data_keys(query)) or needs_live_data(query)
    wants_financial = intent.fundamentals and _mentions_financials(query)
    wants_annual = (intent.annual or intent.disclosure) and (
        _mentions_annual(query) or report_year is not None
    )
    wants_overview = intent.overview
    wants_report_market = _needs_report_level_market(query, intent)

    has_market = local_price_volume_available(code)
    market_current = market_is_current(code, as_of=ref) if has_market else False

    gaps: list[str] = []
    if wants_market:
        if not has_market:
            gaps.append("market_history")
        elif not market_current:
            gaps.append("quote_refresh")
            if wants_report_market or wants_overview:
                gaps.append("market_history")

    if wants_annual and annual_report_needs_update(code, annual, report_year=report_year):
        gaps.append("annual_report")
    if wants_financial and pit is None and "annual_report" not in gaps:
        gaps.append("pit_financials")

    if not has_market and not pit and not annual and (query_needs_stored_data(query) or needs_live_data(query)):
        if wants_overview:
            for kind in ("market_history", "annual_report"):
                if kind not in gaps:
                    gaps.append(kind)
        elif wants_market and "market_history" not in gaps and "quote_refresh" not in gaps:
            gaps.append("market_history")
        elif (wants_annual or wants_financial) and "annual_report" not in gaps:
            gaps.append("annual_report")

    return _dedupe_gaps(gaps)


def _dedupe_gaps(gaps: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for gap in gaps:
        if gap in seen:
            continue
        seen.add(gap)
        out.append(gap)
    return out


def ensure_stored_data(stock_code: str, query: str, *, workdir: Path | None = None) -> dict[str, Any] | None:
    """缺数据则拉取并写入 SQLite，返回 ingest 摘要。"""
    result = run_data_ingest(
        stock_code,
        mode="query_driven",
        query=query,
        workdir=workdir or Path("."),
    )
    if result.get("skipped"):
        return None
    return result


def ingest_quote_refresh(stock_code: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """增量拉取至最近交易日（对话第 3 步之「快照」）。"""
    from ..datastore.db import get_latest_snapshot
    from ..datastore.market_cache import market_is_current
    from ..stock_utils import calendar_trading_as_of

    code = normalize_stock_code(stock_code)
    before = get_latest_snapshot(code)
    ref = calendar_trading_as_of(default_as_of(None))
    if not force_refresh and market_is_current(code, as_of=ref):
        return {
            "ok": True,
            "skipped": True,
            "mode": "quote_ok",
            "snapshot_id": (before or {}).get("id"),
            "end_date": (before or {}).get("end_date"),
            "skip_reason": "本地量价已覆盖最近交易日，跳过增量刷新",
        }
    lb = quote_refresh_lookback_days()
    live = fetch_market_snapshot(code, lookback_days=lb, incremental=True, force_refresh=force_refresh)
    err = live.get("error")
    if err and not live_quote_has_data(live):
        return {"ok": False, "error": str(err), "gap": "quote_refresh"}
    snap = get_latest_snapshot(code)
    return {
        "ok": True,
        "mode": "incremental" if before else "full",
        "snapshot_id": (snap or {}).get("id"),
        "source": live.get("source"),
        "end_date": live.get("end_date"),
        "live": live,
        "lookback_days": lb,
    }


def ingest_market_history(
    stock_code: str,
    *,
    lookback_days: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """报告级量价长历史（多智能体/深度对话用，不做「仅快照元数据」校验）。"""
    from ..datastore.db import get_latest_snapshot
    from ..datastore.market_cache import snapshot_usable_for_executor
    from ..stock_utils import calendar_trading_as_of

    code = normalize_stock_code(stock_code)
    lb = int(lookback_days or report_market_lookback_days())
    before = get_latest_snapshot(code)
    ref = calendar_trading_as_of(default_as_of(None))
    if not force_refresh and before and snapshot_usable_for_executor(before, as_of=ref, lookback_days=lb):
        return {
            "ok": True,
            "skipped": True,
            "mode": "history_ok",
            "snapshot_id": before.get("id"),
            "source": "local_db_cache",
            "end_date": before.get("end_date"),
            "skip_reason": f"本地报告级量价已就绪（回看 {lb} 天），跳过米筐拉取",
        }
    live = fetch_market_snapshot(code, lookback_days=lb, incremental=True, force_refresh=force_refresh)
    err = live.get("error")
    if err and not live_quote_has_data(live):
        return {"ok": False, "error": str(err), "gap": "market_history"}
    snap = get_latest_snapshot(code)
    return {
        "ok": True,
        "mode": "incremental" if before else "full",
        "snapshot_id": (snap or {}).get("id"),
        "source": live.get("source"),
        "end_date": live.get("end_date"),
        "live": live,
        "lookback_days": lb,
    }


def ingest_market_snapshot(
    stock_code: str,
    *,
    lookback_days: int = 180,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """兼容旧名：等同 ingest_market_history。"""
    return ingest_market_history(stock_code, lookback_days=lookback_days, force_refresh=force_refresh)


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
    force_refresh: bool = False,
) -> dict[str, Any]:
    from ..datastore.db import get_annual_report, save_annual_report_record
    from ..datastore.annual_text import mda_storage_payload
    from ..fallback import apply_financial_fallbacks

    code = normalize_stock_code(stock_code)
    existing = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)
    if existing and not force_refresh and not annual_report_needs_update(code, existing, report_year=report_year):
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
    force_refresh: bool = False,
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
            gap: (
                lambda g=gap: _ingest_gap(
                    code, g, workdir=workdir, report_year=report_year, lookback_days=lookback_days, force_refresh=force_refresh
                )
            )
            for gap in batch
        }
        for gap in batch:
            _emit(gap, gap_list.index(gap) + 1)
        results = parallel_map(tasks, max_workers=min(len(batch), finagent_max_workers()))
        for gap in batch:
            actions.append(_action_from_gap_result(gap, results.get(gap)))
    for offset, gap in enumerate(tail):
        _emit(gap, len(batch) + offset + 1)
        actions.append(_action_from_gap_result(gap, _ingest_gap(code, gap, workdir=workdir, report_year=report_year, lookback_days=lookback_days, force_refresh=force_refresh)))
    return actions


def _ingest_gap(
    code: str,
    gap: str,
    *,
    workdir: Path,
    report_year: int | None,
    lookback_days: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if gap == "annual_report":
        return ingest_annual_report(code, report_year=report_year, workdir=workdir, force_refresh=force_refresh)
    if gap == "pit_financials":
        return ingest_pit_financials(code, report_year=report_year)
    if gap == "quote_refresh":
        return ingest_quote_refresh(code, force_refresh=force_refresh)
    if gap in ("market_snapshot", "market_history"):
        lb = lookback_days if gap == "market_history" else report_market_lookback_days()
        return ingest_market_history(code, lookback_days=lb, force_refresh=force_refresh)
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
    force_refresh: bool = False,
) -> dict[str, Any]:
    """主动拉取行情、年报、PIT 财务并写入 SQLite（对话「同步数据」按钮）。"""
    return run_data_ingest(
        stock_code,
        mode="force_all" if force_refresh else "manual_full",
        report_year=report_year,
        workdir=workdir,
        force_refresh=force_refresh,
    )


def run_data_ingest(
    stock_code: str,
    *,
    mode: IngestMode = "manual_full",
    query: str | None = None,
    report_year: int | None = None,
    lookback_days: int | None = None,
    workdir: Path | None = None,
    force_refresh: bool = False,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """统一入库入口：按场景选择缺口集合并执行 _run_ingest_plan。"""
    code = normalize_stock_code(stock_code)
    root = workdir or Path(".")
    lb = lookback_days if lookback_days is not None else bootstrap_lookback_days()
    year = report_year if report_year is not None else (
        extract_report_year(query or "") or (default_as_of(None).year - 1)
    )

    if mode == "query_driven":
        if not query:
            raise ValueError("query_driven 模式需要 query 参数")
        gaps = get_data_gaps(code, query)
        if not gaps:
            coverage = get_data_coverage(code, lookback_days=lb)
            return {
                "stock_code": code,
                "mode": mode,
                "requested_gaps": [],
                "actions": [],
                "ok": True,
                "skipped": True,
                "coverage": coverage,
                "message": "本地数据已满足当前问题，无需补拉",
            }
        ordered = [g for g in FAST_INGEST_ORDER if g in gaps]
    else:
        ordered = list(gaps_for_mode(mode))

    refresh = force_refresh or mode == "force_all"
    actions = _run_ingest_plan(
        code,
        ordered,
        workdir=root,
        report_year=year,
        lookback_days=lb,
        on_progress=on_progress,
        parallel_prefetch=BOOTSTRAP_PARALLEL_GAPS,
        force_refresh=refresh,
    )
    if mode == "report_prep":
        ordered, actions = _merge_quote_refresh_into_market_history(ordered, actions)
    ok_count = sum(1 for item in actions if item.get("ok"))
    return {
        "stock_code": code,
        "mode": mode,
        "report_year": year,
        "requested_gaps": ordered,
        "actions": actions,
        "ok": ok_count > 0,
        "coverage": get_data_coverage(code, lookback_days=lb),
        "message": _ingest_message(actions),
    }


def ensure_annual_report_in_store(
    stock_code: str,
    *,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
    report_year: int | None = None,
) -> dict[str, Any] | None:
    """多智能体/报告生成前确保 SQLite 中有可用年报（巨潮 PDF 路径）。"""
    from ..datastore.db import get_annual_report

    code = normalize_stock_code(stock_code)
    existing = get_annual_report(code, report_year=report_year) if report_year else get_annual_report(code)

    if use_cached_only:
        if not _annual_has_usable_content(existing):
            raise AnnualCacheError(
                "本地没有已保存的年报数据（三表或 MD&A）。"
                "请先在对话中完成年报/PDF 入库，或取消「仅用本地数据」。"
            )
        return {
            "ok": True,
            "skipped": True,
            "report_year": existing.get("report_year"),
            "source": "local_cache",
        }

    needs = force_refresh or annual_report_needs_update(code, existing, report_year=report_year)
    if existing and not needs:
        return {
            "ok": True,
            "skipped": True,
            "report_year": existing.get("report_year"),
            "skip_reason": _annual_skip_reason(existing),
        }
    return ingest_annual_report(code, report_year=report_year, workdir=workdir)


def get_data_coverage(
    stock_code: str,
    *,
    lookback_days: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """检查 SQLite 中行情/PIT/年报覆盖与新鲜度（供 API 与前端状态条）。"""
    from ..datastore.db import get_annual_report, get_latest_snapshot, get_pit_financials
    from ..datastore.market_cache import (
        local_price_volume_available,
        market_is_current,
        snapshot_usable_for_executor,
    )

    code = normalize_stock_code(stock_code)
    lb = lookback_days if lookback_days is not None else bootstrap_lookback_days()
    ref = as_of or default_as_of(None)

    snapshot = get_latest_snapshot(code)
    pit = get_pit_financials(code)
    annual = get_annual_report(code)

    market_local = local_price_volume_available(code)
    market_current = market_is_current(code, as_of=ref) if market_local else False
    market_fresh = bool(snapshot and snapshot_usable_for_executor(snapshot, as_of=ref, lookback_days=lb))
    market_stale = market_snapshot_is_stale(snapshot) if snapshot else True
    pit_rows = (pit or {}).get("rows") or []
    pit_ok = bool(pit_rows)
    annual_ok = bool(annual and not annual_report_needs_update(code, annual, as_of=ref))

    gaps: list[str] = []
    if not market_local:
        gaps.append("market_history")
    elif not market_current:
        gaps.append("quote_refresh")
        gaps.append("market_history")
    elif not market_fresh:
        gaps.append("market_history")
    if not pit_ok:
        gaps.append("pit_financials")
    if not annual_ok:
        gaps.append("annual_report")

    gaps = _dedupe_gaps(gaps)

    return {
        "stock_code": code,
        "lookback_days": lb,
        "market_snapshot": {
            "present": market_local,
            "current": market_current,
            "fresh": market_fresh,
            "stale": market_stale,
            "end_date": (snapshot or {}).get("end_date"),
            "snapshot_id": (snapshot or {}).get("id"),
        },
        "pit_financials": {
            "present": pit_ok,
            "row_count": len(pit_rows),
            "report_year": (pit or {}).get("report_year"),
        },
        "annual_report": {
            "present": bool(annual),
            "fresh": annual_ok,
            "report_year": (annual or {}).get("report_year"),
            "sec_name": (annual or {}).get("sec_name"),
        },
        "gaps": gaps,
        "ready_for_chat": market_local and pit_ok,
        "ready_for_multi_agent": market_fresh and pit_ok and annual_ok,
    }


def ensure_report_data_for_generation(
    stock_code: str,
    *,
    lookback_days: int | None = None,
    workdir: Path | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """多智能体生成前：先行情增量刷新，再入库报告级量价历史 + 年报 + PIT。"""
    lb = lookback_days if lookback_days is not None else report_market_lookback_days()
    if use_cached_only:
        cov = get_data_coverage(stock_code, lookback_days=lb)
        missing = list(cov.get("gaps") or [])
        if missing:
            raise AnnualCacheError(
                f"本地数据不足：{', '.join(_GAP_LABELS.get(g, g) for g in missing)}。"
                "请取消「仅用本地数据」或先在对话中完成入库。"
            )
        return {"stock_code": normalize_stock_code(stock_code), "skipped": True, "coverage": cov}
    return run_data_ingest(
        stock_code,
        mode="report_prep",
        lookback_days=lb,
        workdir=workdir,
        force_refresh=force_refresh,
    )


def _merge_quote_refresh_into_market_history(
    requested_gaps: list[str],
    actions: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """报告生成场景下，将 quote_refresh 执行结果并入 market_history，避免独立动作暴露。"""
    quote_idx = next((idx for idx, item in enumerate(actions) if item.get("gap") == "quote_refresh"), None)
    if quote_idx is None:
        return requested_gaps, actions
    market_idx = next((idx for idx, item in enumerate(actions) if item.get("gap") in {"market_history", "market_snapshot"}), None)
    if market_idx is None:
        return requested_gaps, actions

    quote_action = actions[quote_idx]
    market_action = dict(actions[market_idx])
    market_action["quote_refresh"] = {
        "ok": bool(quote_action.get("ok")),
        "skipped": bool(quote_action.get("skipped")),
        "mode": quote_action.get("mode"),
        "end_date": quote_action.get("end_date"),
        "snapshot_id": quote_action.get("snapshot_id"),
        "source": quote_action.get("source"),
        "skip_reason": quote_action.get("skip_reason"),
        "error": quote_action.get("error"),
    }
    if not market_action.get("end_date") and quote_action.get("end_date"):
        market_action["end_date"] = quote_action.get("end_date")
    if not market_action.get("snapshot_id") and quote_action.get("snapshot_id"):
        market_action["snapshot_id"] = quote_action.get("snapshot_id")
    actions[market_idx] = market_action

    merged_actions = [item for idx, item in enumerate(actions) if idx != quote_idx]
    merged_gaps = [gap for gap in requested_gaps if gap != "quote_refresh"]
    return merged_gaps, merged_actions


def _bootstrap_message(actions: list[dict[str, Any]], *, sec_name: str | None, code: str) -> str:
    label = sec_name or code
    ok = sum(1 for item in actions if item.get("ok"))
    if ok:
        return f"{label} 数据已就绪"
    return f"{label} 入库部分失败"


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
        elif gap == "quote_refresh":
            parts.append(f"已刷新至最近交易日（截至 {item.get('end_date') or '—'}）")
        elif gap in ("market_snapshot", "market_history"):
            mode = item.get("mode") or "full"
            label = "增量更新" if mode == "incremental" else "全量拉取"
            lb = item.get("lookback_days")
            suffix = f"，回看 {lb} 天" if lb else ""
            parts.append(f"已{label}报告级量价{suffix}（截至 {item.get('end_date') or '最近交易日'}）")
        elif gap == "pit_financials":
            parts.append(f"已入库财务序列（{item.get('row_count', 0)} 条）")
    return "；".join(parts) if parts else ""
