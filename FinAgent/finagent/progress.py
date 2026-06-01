"""进度跟踪工具：在关键步骤打印丰富的时间戳中间信息。

兼容 Windows GBK 编码，避免 UnicodeEncodeError。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

_start_time: float | None = None


def _safe_print(text: str) -> None:
    """编码安全的打印函数，自动替换不可编码字符。"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 回退方案：使用 GBK 能处理的近似字符
        safe = text.encode(sys.stdout.encoding or "gbk", errors="replace").decode(
            sys.stdout.encoding or "gbk", errors="replace"
        )
        print(safe)


def _local_now() -> str:
    """返回本地时间字符串，格式 14:30:45"""
    try:
        import time as _time
        local_offset = -_time.timezone if _time.timezone != 0 else 0
        tz = timezone(timedelta(seconds=local_offset))
        return datetime.now(tz).strftime("%H:%M:%S")
    except Exception:
        return datetime.now().strftime("%H:%M:%S")


def start() -> None:
    """标记工作流开始。"""
    global _start_time
    _start_time = time.time()
    _safe_print("=" * 70)
    _safe_print(f"  FinAgent 工作流启动 -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _safe_print("=" * 70)


def step(phase: str, detail: str = "") -> None:
    """打印一个阶段步骤。"""
    elapsed = ""
    if _start_time is not None:
        elapsed = f" [+{time.time() - _start_time:.0f}s]"
    if detail:
        _safe_print(f"  -> [{_local_now()}{elapsed}] {phase} -- {detail}")
    else:
        _safe_print(f"  -> [{_local_now()}{elapsed}] {phase}")


def info(msg: str) -> None:
    """打印普通信息。"""
    _safe_print(f"     {msg}")


def ok(msg: str) -> None:
    """打印成功信息。"""
    _safe_print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    """打印警告。"""
    _safe_print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    """打印错误。"""
    _safe_print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    """打印分节标题。"""
    elapsed = ""
    if _start_time is not None:
        elapsed = f" [+{time.time() - _start_time:.0f}s]"
    _safe_print("")
    _safe_print(f"  === {title} ===")
    _safe_print(f"  [{_local_now()}{elapsed}]")


def sub_section(title: str) -> None:
    """打印子节标题。"""
    _safe_print(f"  --- {title}")


def end() -> None:
    """标记工作流结束并打印耗时。"""
    if _start_time is not None:
        total = time.time() - _start_time
        elapsed = f"  总耗时: {total:.0f} 秒 ({total / 60:.1f} 分钟)"
    else:
        elapsed = ""
    _safe_print("")
    _safe_print("=" * 70)
    _safe_print(f"  FinAgent 工作流完成 -- {elapsed}")
    _safe_print("=" * 70)


def data_table(headers: list[str], rows: list[list[str]]) -> None:
    """打印简单的对齐表格。"""
    if not rows:
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = "  | " + " | ".join(f"{{:<{w}}}" for w in col_widths) + " |"
    sep = "  +" + "-+-".join("-" * w for w in col_widths) + "-+"
    _safe_print(fmt.format(*headers))
    _safe_print(sep)
    for row in rows:
        _safe_print(fmt.format(*[str(c)[:w] for c, w in zip(row, col_widths)]))
