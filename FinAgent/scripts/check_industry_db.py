"""检查 data_snapshots.meta_json 中的行业/因子/技术指标。用法: python FinAgent/scripts/check_industry_db.py [股票代码]"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


def _db_path() -> str:
    override = os.environ.get("FINAGENT_DB_PATH", "").strip()
    if override:
        return str(Path(override).expanduser())
    return str(Path(__file__).resolve().parents[1] / "data_store" / "finagent.db")


def main() -> None:
    code = (sys.argv[1] if len(sys.argv) > 1 else "600519").strip().split(".")[0]
    db = _db_path()
    if not Path(db).is_file():
        print("no db:", db)
        raise SystemExit(1)

    with sqlite3.connect(db) as conn:
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
            print(f"no snapshot for {code}")
            raise SystemExit(0)
        sid, stock, end, meta_raw = row
        print(f"db={db}")
        print(f"snapshot_id={sid} stock={stock} end={end}")
        meta = json.loads(meta_raw or "{}")
        for key in ("industry", "industry_l2", "industry_comparison", "factor", "technical"):
            val = meta.get(key)
            if val is None:
                print(f"  meta.{key}: <absent>")
            elif isinstance(val, dict) and not val:
                print(f"  meta.{key}: {{}} empty")
            else:
                text = json.dumps(val, ensure_ascii=False)
                print(f"  meta.{key}: {text[:280]}{'...' if len(text) > 280 else ''}")
        series = conn.execute(
            "SELECT data_key, row_count FROM data_series WHERE snapshot_id = ? ORDER BY data_key",
            (sid,),
        ).fetchall()
        print("  series:", series)


if __name__ == "__main__":
    main()
