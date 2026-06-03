"""从 data_snapshots.meta_json 移除空 meta 占位（如 industry: {}）。

空对象会干扰合并/补全逻辑，且无法从历史快照恢复行业名。

用法:
  python scripts/clean_empty_snapshot_meta.py --dry-run
  python scripts/clean_empty_snapshot_meta.py
  python scripts/clean_empty_snapshot_meta.py --stock 600519
"""

import argparse
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


def _strip_empty_meta(meta):
    finagent_root = str(Path(__file__).resolve().parents[1])
    if finagent_root not in sys.path:
        sys.path.insert(0, finagent_root)
    from finagent.datastore.db import META_KEYS
    from finagent.datastore.meta_utils import meta_value_is_usable

    cleaned = dict(meta or {})
    removed = []
    for key in META_KEYS:
        if key not in cleaned:
            continue
        value = cleaned[key]
        if not meta_value_is_usable(key, value):
            removed.append(key)
            del cleaned[key]
    return cleaned, removed


def _scan(conn, stock_filter=None):
    if stock_filter:
        rows = conn.execute(
            """
            SELECT id, stock_code, meta_json
            FROM data_snapshots
            WHERE stock_code = ?
            ORDER BY id
            """,
            (stock_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, stock_code, meta_json FROM data_snapshots ORDER BY id"
        ).fetchall()
    return rows


def main():
    parser = argparse.ArgumentParser(description="清理快照 meta 中的空占位字段")
    parser.add_argument("--dry-run", action="store_true", help="仅列出将删除的字段，不写库")
    parser.add_argument(
        "--stock",
        action="append",
        dest="stocks",
        help="仅处理指定 6 位代码（可多次指定）；默认处理全部快照",
    )
    args = parser.parse_args()

    db = _db_path()
    if not Path(db).is_file():
        print("no db:", db)
        raise SystemExit(1)

    print("db={}".format(db))
    conn = sqlite3.connect(db)
    try:
        codes = args.stocks
        if codes:
            codes = [str(c).strip().split(".")[0] for c in codes]
            all_rows = []
            for code in codes:
                all_rows.extend(_scan(conn, code))
        else:
            all_rows = _scan(conn, None)

        touched = 0
        for sid, stock_code, meta_raw in all_rows:
            try:
                meta = json.loads(meta_raw or "{}")
            except (TypeError, ValueError):
                continue
            cleaned, removed = _strip_empty_meta(meta)
            if not removed:
                continue
            touched += 1
            print(
                "snapshot_id={} stock={} remove: {}".format(
                    sid, stock_code, ", ".join(removed)
                )
            )
            if args.dry_run:
                continue
            conn.execute(
                "UPDATE data_snapshots SET meta_json = ? WHERE id = ?",
                (json.dumps(cleaned, ensure_ascii=False), sid),
            )

        if not args.dry_run and touched:
            conn.commit()

        if touched == 0:
            print("未发现需清理的空 meta 字段。")
        elif args.dry_run:
            print("（dry-run，共 {} 条快照含空占位，未写库）".format(touched))
            print("去掉 --dry-run 后执行写库；之后可运行 repair_snapshot_meta.py 补全行业/technical。")
        else:
            print("已清理 {} 条快照的空 meta。".format(touched))
            print("提示: python scripts/repair_snapshot_meta.py <代码> 或完整 rqdata ingest 重新补全。")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
