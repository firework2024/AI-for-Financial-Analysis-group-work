#!/usr/bin/env python3
"""删除 pit_financials_cache 中仅含 year/quarter 的占位记录。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finagent.datastore.db import (  # noqa: E402
    _locked_connect,
    delete_pit_financials_cache,
    get_db_path,
    get_pit_financials,
    init_db,
    pit_cache_is_usable,
)


def list_codes() -> list[str]:
    with _locked_connect() as conn:
        rows = conn.execute("SELECT stock_code FROM pit_financials_cache ORDER BY stock_code").fetchall()
    return [str(r[0]) for r in rows]


def polluted_codes(codes: list[str] | None = None) -> list[str]:
    codes = codes or list_codes()
    out: list[str] = []
    for code in codes:
        pit = get_pit_financials(code)
        if pit and not pit_cache_is_usable(pit):
            out.append(code)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 PIT 占位污染缓存")
    parser.add_argument(
        "--stock",
        action="append",
        dest="stocks",
        help="仅清理指定 6 位代码（可多次指定），默认扫描全部",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出，不删除")
    args = parser.parse_args()

    db = get_db_path()
    print(f"数据库: {db}")
    if not db.is_file():
        print("数据库文件不存在，无需清理。")
        return 0

    init_db(db)
    scope = args.stocks or list_codes()
    if args.stocks:
        missing = [c for c in args.stocks if c not in list_codes()]
        if missing:
            print(f"未在库中找到 PIT 缓存: {', '.join(missing)}")

    bad = polluted_codes(scope)
    if not bad:
        print("未发现占位污染的 PIT 缓存。")
        return 0

    print("占位污染标的:", ", ".join(bad))
    if args.dry_run:
        print("（dry-run，未删除）")
        return 0

    total = 0
    for code in bad:
        n = delete_pit_financials_cache(code)
        total += n
        print(f"  已删除 {code}: {n} 条")
    print(f"合计删除: {total} 条")
    print("提示: 连接 VPN 后在对话中问「历年净利率」或执行 ingest，以重新拉取有效 PIT。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
