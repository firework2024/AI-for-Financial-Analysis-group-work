"""探测米筐 RQData 是否可用（init、行情、中信行业）。

用法（在 FinAgent 目录或仓库根目录）:
  python scripts/probe_rqdata.py
  python scripts/probe_rqdata.py 600519
  python scripts/probe_rqdata.py 600519 --verbose
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _finagent_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_cli(argv: list[str]) -> tuple[str, bool]:
    code = "600519"
    verbose = False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("-v", "--verbose"):
            verbose = True
            i += 1
            continue
        if arg.isdigit() and len(arg) == 6:
            code = arg
        i += 1
    return code.strip().split(".")[0], verbose


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _row_from_industry_df(df: Any) -> dict[str, Any]:
    import pandas as pd

    if df is None:
        return {}
    if getattr(df, "empty", True):
        return {}
    if isinstance(df, pd.Series):
        return {str(k): _jsonable(v) for k, v in df.items()}
    frame = df.reset_index() if hasattr(df, "reset_index") else df
    if getattr(frame, "empty", True):
        return {}
    row = frame.iloc[0].to_dict()
    return {str(k): _jsonable(v) for k, v in row.items()}


def _probe_industry(rqdatac: Any, order_book_id: str, as_of: date, *, verbose: bool) -> None:
    for level in (1, 0):
        label = "level={}".format(level)
        try:
            df = rqdatac.get_instrument_industry(
                order_book_id, source="citics_2019", level=level, date=as_of
            )
        except Exception as exc:
            print("  {}: ERROR {}".format(label, type(exc).__name__, exc))
            continue
        empty = df is None or getattr(df, "empty", True)
        row = _row_from_industry_df(df)
        name_keys = (
            "first_industry_name",
            "level1_name",
            "first_industry_code",
            "level1_code",
        )
        names = {k: row.get(k) for k in name_keys if row.get(k) not in (None, "")}
        status = "EMPTY" if empty else "OK"
        print("  {}: {} names/codes={}".format(label, status, names or row))
        if verbose and not empty:
            try:
                print("    columns:", list(getattr(df, "columns", [])))
                print("    index:", getattr(df, "index", None))
            except Exception:
                pass


def main() -> int:
    code, verbose = _parse_cli(sys.argv)
    root = _finagent_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from finagent.env import prepare_rqdata_env
    from finagent.stock_utils import to_order_book_id

    prepare_rqdata_env()
    order_book_id = to_order_book_id(code)
    as_of = date.today()
    prev = as_of - timedelta(days=7)

    print("=== RQData probe ===")
    print("stock_code={} order_book_id={}".format(code, order_book_id))
    print("as_of={} (also try prev week for industry)".format(as_of.isoformat()))
    print("RQ_USER set:", bool(os.getenv("RQ_USER")))
    print("RQ_PASSWORD set:", bool(os.getenv("RQ_PASSWORD")))
    print("RQ_HOST:", os.getenv("RQ_HOST") or "(default)")

    try:
        import rqdatac
        from finagent.rqdata_client import _init_rqdata

        print("\n[1] init")
        _init_rqdata(rqdatac)
        print("  init: OK")
    except Exception as exc:
        print("  init: FAIL {}: {}".format(type(exc).__name__, exc))
        return 1

    print("\n[2] get_price (5d)")
    try:
        start = (as_of - timedelta(days=10)).isoformat()
        df = rqdatac.get_price(order_book_id, start_date=start, end_date=as_of.isoformat(), frequency="1d")
        n = 0 if df is None else len(df)
        print("  get_price: OK rows={}".format(n))
        if verbose and n:
            print("    tail close:", df["close"].iloc[-1] if "close" in df.columns else df.iloc[-1])
    except Exception as exc:
        print("  get_price: FAIL {}: {}".format(type(exc).__name__, exc))

    print("\n[3] get_instrument_industry (citics_2019)")
    _probe_industry(rqdatac, order_book_id, as_of, verbose=verbose)
    print("  --- date={} ---".format(prev.isoformat()))
    _probe_industry(rqdatac, order_book_id, prev, verbose=verbose)

    print("\n[4] get_factor (pe_ratio_ttm)")
    try:
        df = rqdatac.get_factor(order_book_id, factor="pe_ratio_ttm", start_date=prev, end_date=as_of)
        n = 0 if df is None else len(df)
        print("  get_factor: OK rows={}".format(n))
    except Exception as exc:
        print("  get_factor: FAIL {}: {}".format(type(exc).__name__, exc))

    print("\n[5] instruments (sec_name)")
    try:
        inst = rqdatac.instruments(order_book_id)
        name = getattr(inst, "symbol", None) or getattr(inst, "abbrev_symbol", None)
        print("  instruments: OK", name or inst)
    except Exception as exc:
        print("  instruments: FAIL {}: {}".format(type(exc).__name__, exc))

    print("\nDone. If [3] is EMPTY but [1][2] OK, check citics_2019 permission or date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
