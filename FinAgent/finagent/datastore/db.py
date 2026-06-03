"""SQLite 原始数据存储。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..env import get_env, project_root
from .annual_text import normalize_mda_text

if TYPE_CHECKING:
    from ..rqdata_client import FinancialFetchResult

_LOCK = threading.Lock()

# data_executor 返回 dict 中需要落库的序列键
SERIES_KEYS = (
    "price",
    "price_change_rate",
    "turnover",
    "capital_flow",
    "securities_margin",
    "dividend",
    "shares",
    "suspended",
    "st_stock",
    "index_benchmark",
    "block_trade",
    "interbank_rate",
    "yield_curve",
    "factor_history",
    "pit_financials",
)

META_KEYS = ("factor", "industry", "industry_l2", "industry_comparison", "technical", "benchmark_index")


def get_db_path() -> Path:
    override = get_env("FINAGENT_DB_PATH")
    if override:
        return Path(override).expanduser()
    return project_root() / "data_store" / "finagent.db"


def init_db(path: Path | None = None) -> Path:
    db_path = path or get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS data_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_book_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                as_of TEXT NOT NULL,
                lookback_days INTEGER,
                start_date TEXT,
                end_date TEXT,
                source TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS data_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                data_key TEXT NOT NULL,
                columns_json TEXT,
                rows_json TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(id)
            );

            CREATE TABLE IF NOT EXISTS pit_financials_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_book_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                report_year INTEGER NOT NULL,
                years INTEGER NOT NULL,
                quarters_json TEXT,
                rows_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                UNIQUE(order_book_id, report_year, years)
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_stock
                ON data_snapshots(stock_code, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_series_snapshot
                ON data_series(snapshot_id, data_key);
            CREATE INDEX IF NOT EXISTS idx_pit_stock
                ON pit_financials_cache(stock_code, fetched_at DESC);

            CREATE TABLE IF NOT EXISTS annual_report_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                report_year INTEGER NOT NULL,
                order_book_id TEXT,
                sec_name TEXT,
                title TEXT,
                pdf_path TEXT,
                meta_json TEXT,
                financial_data_json TEXT NOT NULL,
                mda_text TEXT,
                mda_meta_json TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE(stock_code, report_year)
            );

            CREATE INDEX IF NOT EXISTS idx_annual_stock
                ON annual_report_records(stock_code, fetched_at DESC);
            """
        )
        _migrate_schema(conn)
    return db_path


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(annual_report_records)").fetchall()}
    if "financial_analysis_json" not in cols:
        conn.execute("ALTER TABLE annual_report_records ADD COLUMN financial_analysis_json TEXT")
    if "financial_analysis_fingerprint" not in cols:
        conn.execute("ALTER TABLE annual_report_records ADD COLUMN financial_analysis_fingerprint TEXT")


def save_data_snapshot(
    data: dict[str, Any],
    *,
    stock_code: str,
    source: str = "data_executor",
    lookback_days: int | None = None,
) -> int:
    """保存 data_executor_agent 返回的完整数据快照，返回 snapshot id。"""
    order_book_id = str(data.get("order_book_id") or "")
    end_date = str(data.get("end_date") or "")
    start_date = str(data.get("start_date") or "")
    as_of = end_date or datetime.now().date().isoformat()
    created_at = datetime.now().isoformat(timespec="seconds")

    meta: dict[str, Any] = {}
    for key in META_KEYS:
        value = data.get(key)
        if value is not None:
            meta[key] = value

    with _locked_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO data_snapshots
                (order_book_id, stock_code, as_of, lookback_days, start_date, end_date, source, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_book_id,
                stock_code,
                as_of,
                lookback_days,
                start_date,
                end_date,
                source,
                json.dumps(meta, ensure_ascii=False, default=_json_default),
                created_at,
            ),
        )
        snapshot_id = int(cursor.lastrowid)

        for key in SERIES_KEYS:
            payload = data.get(key)
            if not isinstance(payload, dict):
                continue
            rows = payload.get("rows")
            if not isinstance(rows, list):
                continue
            columns = payload.get("columns")
            conn.execute(
                """
                INSERT INTO data_series (snapshot_id, data_key, columns_json, rows_json, row_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    key,
                    json.dumps(columns, ensure_ascii=False) if columns is not None else None,
                    json.dumps(rows, ensure_ascii=False, default=_json_default),
                    len(rows),
                ),
            )
        return snapshot_id


def persist_market_snapshot(
    data: dict[str, Any],
    *,
    lookback_days: int | None = None,
    source: str = "data_executor",
    incremental: bool = True,
) -> int | None:
    """将 data_executor 返回的 dict 写入 SQLite；默认在最新快照上增量合并。"""
    stock_code = str(data.get("stock_code") or "").strip()
    if not stock_code:
        order_book_id = str(data.get("order_book_id") or "").strip()
        if order_book_id:
            stock_code = order_book_id.split(".")[0]
    if not stock_code:
        return None
    try:
        if incremental:
            from .snapshot_merge import upsert_market_snapshot

            return upsert_market_snapshot(data, lookback_days=lookback_days, source=source)
        return save_data_snapshot(data, stock_code=stock_code, lookback_days=lookback_days, source=source)
    except Exception as exc:
        print(f"[persist_market_snapshot] failed: {type(exc).__name__}: {exc}")
        return None


def save_pit_financials(
    result: FinancialFetchResult | Any,
    *,
    stock_code: str,
    report_year: int,
    years: int = 3,
) -> None:
    """缓存 PIT 三表原始行（workflow / rqdata_client 共用）。"""
    fetched_at = datetime.now().isoformat(timespec="seconds")
    with _locked_connect() as conn:
        conn.execute(
            """
            INSERT INTO pit_financials_cache
                (order_book_id, stock_code, report_year, years, quarters_json, rows_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_book_id, report_year, years) DO UPDATE SET
                stock_code = excluded.stock_code,
                quarters_json = excluded.quarters_json,
                rows_json = excluded.rows_json,
                fetched_at = excluded.fetched_at
            """,
            (
                result.order_book_id,
                stock_code,
                report_year,
                years,
                json.dumps(result.quarters, ensure_ascii=False),
                json.dumps(result.rows, ensure_ascii=False, default=_json_default),
                fetched_at,
            ),
        )


def save_annual_report_record(
    *,
    stock_code: str,
    report_year: int,
    order_book_id: str | None = None,
    sec_name: str | None = None,
    title: str | None = None,
    pdf_path: str | None = None,
    meta: dict[str, Any] | None = None,
    financial_data: list[dict[str, Any]],
    mda_text: str | None = None,
    mda_meta: dict[str, Any] | None = None,
) -> None:
    """保存年报 PDF 解析结果：含 MD&A 全文与带来源标注的财务字段。"""
    fetched_at = datetime.now().isoformat(timespec="seconds")
    stored_mda = normalize_mda_text(mda_text or "")
    with _locked_connect() as conn:
        conn.execute(
            """
            INSERT INTO annual_report_records
                (stock_code, report_year, order_book_id, sec_name, title, pdf_path,
                 meta_json, financial_data_json, mda_text, mda_meta_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, report_year) DO UPDATE SET
                order_book_id = excluded.order_book_id,
                sec_name = excluded.sec_name,
                title = excluded.title,
                pdf_path = excluded.pdf_path,
                meta_json = excluded.meta_json,
                financial_data_json = excluded.financial_data_json,
                mda_text = excluded.mda_text,
                mda_meta_json = excluded.mda_meta_json,
                fetched_at = excluded.fetched_at
            """,
            (
                stock_code,
                report_year,
                order_book_id,
                sec_name,
                title,
                pdf_path,
                json.dumps(meta or {}, ensure_ascii=False, default=_json_default),
                json.dumps(financial_data, ensure_ascii=False, default=_json_default),
                stored_mda or None,
                json.dumps(mda_meta or {}, ensure_ascii=False, default=_json_default),
                fetched_at,
            ),
        )


def get_annual_report(stock_code: str, *, report_year: int | None = None) -> dict[str, Any] | None:
    with _locked_connect() as conn:
        if report_year is not None:
            row = conn.execute(
                """
                SELECT stock_code, report_year, order_book_id, sec_name, title, pdf_path,
                       meta_json, financial_data_json, mda_text, mda_meta_json, fetched_at,
                       financial_analysis_json, financial_analysis_fingerprint
                FROM annual_report_records
                WHERE stock_code = ? AND report_year = ?
                """,
                (stock_code, report_year),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT stock_code, report_year, order_book_id, sec_name, title, pdf_path,
                       meta_json, financial_data_json, mda_text, mda_meta_json, fetched_at,
                       financial_analysis_json, financial_analysis_fingerprint
                FROM annual_report_records
                WHERE stock_code = ?
                ORDER BY report_year DESC, fetched_at DESC
                LIMIT 1
                """,
                (stock_code,),
            ).fetchone()
    if row is None:
        return None
    item = dict(row)
    return {
        "stock_code": item["stock_code"],
        "report_year": item["report_year"],
        "order_book_id": item["order_book_id"],
        "sec_name": item["sec_name"],
        "title": item["title"],
        "pdf_path": item["pdf_path"],
        "meta": json.loads(item["meta_json"] or "{}"),
        "financial_data": json.loads(item["financial_data_json"] or "[]"),
        "mda_text": item["mda_text"] or "",
        "mda_meta": json.loads(item["mda_meta_json"] or "{}"),
        "fetched_at": item["fetched_at"],
        "financial_analysis": json.loads(item["financial_analysis_json"] or "null")
        if item.get("financial_analysis_json")
        else None,
        "financial_analysis_fingerprint": item.get("financial_analysis_fingerprint"),
    }


def update_annual_financial_analysis(
    stock_code: str,
    report_year: int,
    *,
    analysis: dict[str, Any],
    fingerprint: str,
) -> None:
    with _locked_connect() as conn:
        conn.execute(
            """
            UPDATE annual_report_records
            SET financial_analysis_json = ?, financial_analysis_fingerprint = ?
            WHERE stock_code = ? AND report_year = ?
            """,
            (
                json.dumps(analysis, ensure_ascii=False, default=_json_default),
                fingerprint,
                stock_code,
                report_year,
            ),
        )


def list_snapshots(stock_code: str, *, limit: int = 5) -> list[dict[str, Any]]:
    with _locked_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, order_book_id, stock_code, as_of, lookback_days, start_date, end_date, source, created_at
            FROM data_snapshots
            WHERE stock_code = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (stock_code, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_snapshot(stock_code: str) -> dict[str, Any] | None:
    with _locked_connect() as conn:
        row = conn.execute(
            """
            SELECT id, order_book_id, stock_code, as_of, lookback_days, start_date, end_date, source, meta_json, created_at
            FROM data_snapshots
            WHERE stock_code = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (stock_code,),
        ).fetchone()
        if row is None:
            return None
        snapshot = dict(row)
        if snapshot.get("meta_json"):
            snapshot["meta"] = json.loads(snapshot["meta_json"])
        else:
            snapshot["meta"] = {}
        snapshot.pop("meta_json", None)
        return snapshot


def load_series(snapshot_id: int, data_keys: list[str] | None = None, *, tail: int | None = None) -> dict[str, Any]:
    with _locked_connect() as conn:
        if data_keys:
            placeholders = ",".join("?" for _ in data_keys)
            rows = conn.execute(
                f"""
                SELECT data_key, columns_json, rows_json, row_count
                FROM data_series
                WHERE snapshot_id = ? AND data_key IN ({placeholders})
                """,
                (snapshot_id, *data_keys),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT data_key, columns_json, rows_json, row_count
                FROM data_series
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchall()

    result: dict[str, Any] = {}
    for row in rows:
        item = dict(row)
        series_rows = json.loads(item["rows_json"])
        if tail is not None and tail > 0:
            series_rows = series_rows[-tail:]
        columns = json.loads(item["columns_json"]) if item.get("columns_json") else None
        result[item["data_key"]] = {
            "rows": series_rows,
            "row_count": item["row_count"],
            "columns": columns,
        }
    return result


# PIT 行是否含实质财务数字（用于区分米筐失败时的 year/quarter 占位行）
PIT_CORE_VALUE_FIELDS: tuple[str, ...] = (
    "revenue",
    "operating_revenue",
    "net_profit",
    "net_profit_parent_company",
    "total_assets",
    "total_liabilities",
    "cash_flow_from_operating_activities",
    "gross_profit",
    "cost_of_goods_sold",
    "profit_from_operation",
    "equity_parent_company",
    "current_assets",
    "current_liabilities",
)


def _pit_field_value(row: dict[str, Any], field: str) -> Any:
    if field in row and row[field] is not None:
        return row[field]
    nested = row.get("fields")
    if isinstance(nested, dict) and field in nested:
        item = nested[field]
        if isinstance(item, dict):
            return item.get("value")
        return item
    metric = row.get("metric_snapshot")
    if isinstance(metric, dict) and field in metric:
        return metric[field]
    return None


def _value_is_numeric(value: Any) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return bool(str(value).strip())
    return number == number


def pit_row_has_financial_values(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    return any(_value_is_numeric(_pit_field_value(row, field)) for field in PIT_CORE_VALUE_FIELDS)


def pit_rows_have_financial_values(rows: list[Any] | None) -> bool:
    if not rows:
        return False
    return any(pit_row_has_financial_values(row) for row in rows if isinstance(row, dict))


def pit_cache_is_usable(pit: dict[str, Any] | None, *, min_rows_with_values: int = 1) -> bool:
    if not pit:
        return False
    rows = pit.get("rows") or []
    valuable = sum(1 for row in rows if isinstance(row, dict) and pit_row_has_financial_values(row))
    return valuable >= min_rows_with_values


def count_pit_rows_with_values(rows: list[Any] | None) -> int:
    if not rows:
        return 0
    return sum(1 for row in rows if isinstance(row, dict) and pit_row_has_financial_values(row))


def delete_pit_financials_cache(stock_code: str) -> int:
    with _locked_connect() as conn:
        cursor = conn.execute("DELETE FROM pit_financials_cache WHERE stock_code = ?", (stock_code,))
        return int(cursor.rowcount or 0)


def get_pit_financials(stock_code: str) -> dict[str, Any] | None:
    with _locked_connect() as conn:
        row = conn.execute(
            """
            SELECT order_book_id, report_year, years, quarters_json, rows_json, fetched_at
            FROM pit_financials_cache
            WHERE stock_code = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (stock_code,),
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    return {
        "order_book_id": item["order_book_id"],
        "report_year": item["report_year"],
        "years": item["years"],
        "quarters": json.loads(item["quarters_json"] or "[]"),
        "rows": json.loads(item["rows_json"] or "[]"),
        "fetched_at": item["fetched_at"],
    }


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _locked_connect() -> sqlite3.Connection:
    init_db()
    conn = _connect(get_db_path())
    return _LockedConnection(conn)


class _LockedConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        _LOCK.acquire()
        return self._conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        _LOCK.release()


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)
