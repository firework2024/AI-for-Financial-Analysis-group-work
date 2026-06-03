"""修复快照 meta 中空 industry/technical，并写回 SQLite。用法: python scripts/repair_snapshot_meta.py 600519"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _db_path():
    override = os.environ.get("FINAGENT_DB_PATH", "").strip()
    if override:
        return str(Path(override).expanduser())
    return str(Path(__file__).resolve().parents[1] / "data_store" / "finagent.db")


def _rebuild_payload_from_snapshot(conn, snapshot_id):
    # type: (sqlite3.Connection, int) -> Optional[Dict[str, Any]]
    row = conn.execute(
        "SELECT stock_code, order_book_id, start_date, end_date, meta_json FROM data_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if not row:
        return None
    stock_code, order_book_id, start_date, end_date, meta_raw = row
    meta = json.loads(meta_raw or "{}")
    series_rows = conn.execute(
        "SELECT data_key, columns_json, rows_json, row_count FROM data_series WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    payload = {
        "stock_code": stock_code,
        "order_book_id": order_book_id or "{}.XSHG".format(stock_code),
        "start_date": start_date,
        "end_date": end_date,
    }
    for key in ("factor", "industry", "industry_l2", "industry_comparison", "technical", "benchmark_index"):
        if key in meta:
            payload[key] = meta[key]
    for data_key, columns_json, rows_json, row_count in series_rows:
        rows = json.loads(rows_json or "[]")
        block = {"rows": rows, "row_count": row_count or len(rows)}
        if columns_json:
            block["columns"] = json.loads(columns_json)
        payload[data_key] = block
    return payload


def main():
    code = (sys.argv[1] if len(sys.argv) > 1 else "600519").strip().split(".")[0]
    db = _db_path()
    if not Path(db).is_file():
        print("no db:", db)
        raise SystemExit(1)

    finagent_root = str(Path(__file__).resolve().parents[1])
    if finagent_root not in sys.path:
        sys.path.insert(0, finagent_root)
    from finagent.core_metrics import enrich_core_metrics, industry_has_display_name, restore_industry_from_snapshot_history
    from finagent.datastore.db import META_KEYS
    from finagent.datastore.meta_utils import meta_value_is_usable
    from finagent.price_technical import ensure_technical_from_price_rows

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT id FROM data_snapshots WHERE stock_code = ? ORDER BY id DESC LIMIT 1",
            (code,),
        ).fetchone()
        if not row:
            print("no snapshot for {}".format(code))
            raise SystemExit(0)
        sid = int(row[0])
        payload = _rebuild_payload_from_snapshot(conn, sid)
        if not payload:
            print("rebuild failed")
            raise SystemExit(1)

        restored = restore_industry_from_snapshot_history(conn, code, exclude_snapshot_id=sid)
        if restored:
            payload["industry"] = restored
            print("  restored industry from older snapshot:", json.dumps(restored, ensure_ascii=False)[:120])

        ensure_technical_from_price_rows(payload)
        enrich_core_metrics(payload)

        if not industry_has_display_name(payload.get("industry")):
            em = payload.get("industry") or {}
            print("  warn: industry still empty after enrich; check eastmoney network or re-run full rqdata ingest")

        old_meta = json.loads(
            conn.execute("SELECT meta_json FROM data_snapshots WHERE id = ?", (sid,)).fetchone()[0] or "{}"
        )
        meta = dict(old_meta)
        for key in META_KEYS:
            value = payload.get(key)
            if value is None:
                continue
            if not meta_value_is_usable(key, value):
                continue
            meta[key] = value

        conn.execute(
            "UPDATE data_snapshots SET meta_json = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), sid),
        )
        conn.commit()

        industry = meta.get("industry") or {}
        technical = meta.get("technical") or {}
        print("repaired snapshot_id={}".format(sid))
        print("  industry:", json.dumps(industry, ensure_ascii=False)[:200])
        if isinstance(technical, dict):
            print("  technical keys:", list(technical.keys())[:8])
        else:
            print("  technical:", technical)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
