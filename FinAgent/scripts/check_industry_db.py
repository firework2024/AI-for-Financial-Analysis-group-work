"""检查 data_snapshots.meta_json 中的行业/因子/技术指标。用法: python scripts/check_industry_db.py [股票代码]"""

import json
import os
import sqlite3
import sys
from pathlib import Path


def _db_path():
    override = os.environ.get("FINAGENT_DB_PATH", "").strip()
    if override:
        return str(Path(override).expanduser())
    return str(Path(__file__).resolve().parents[1] / "data_store" / "finagent.db")


def main():
    code = (sys.argv[1] if len(sys.argv) > 1 else "600519").strip().split(".")[0]
    db = _db_path()
    if not Path(db).is_file():
        print("no db:", db)
        raise SystemExit(1)

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """
            SELECT id, stock_code, end_date, meta_json
            FROM data_snapshots
            WHERE stock_code = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (code,),
        ).fetchone()
        if not row:
            print("no snapshot for {}".format(code))
            raise SystemExit(0)
        sid, stock, end, meta_raw = row
        print("db={}".format(db))
        print("snapshot_id={} stock={} end={}".format(sid, stock, end))
        meta = json.loads(meta_raw or "{}")
        for key in ("industry", "industry_l2", "industry_comparison", "factor", "technical"):
            val = meta.get(key)
            if val is None:
                print("  meta.{}: <absent>".format(key))
            elif isinstance(val, dict) and not val:
                print("  meta.{}: {{}} empty".format(key))
            else:
                text = json.dumps(val, ensure_ascii=False)
                suffix = "..." if len(text) > 280 else ""
                print("  meta.{}: {}{}".format(key, text[:280], suffix))
        series = conn.execute(
            "SELECT data_key, row_count FROM data_series WHERE snapshot_id = ? ORDER BY data_key",
            (sid,),
        ).fetchall()
        print("  series:", series)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
