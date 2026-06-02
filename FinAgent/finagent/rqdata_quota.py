"""米筐 RQData 额度耗尽检测：一旦 QuotaExceeded，本会话内不再调用 rqdatac，改走备用数据源。"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_quota_exhausted = False
_logged_switch = False


def is_rqdata_quota_error(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    if exc.__class__.__name__ == "QuotaExceeded":
        return True
    message = str(exc).strip().lower()
    return "quota exceeded" in message or "quotaexceeded" in message


def rqdata_quota_exhausted() -> bool:
    with _lock:
        return _quota_exhausted


def mark_rqdata_quota_exceeded(exc: BaseException | None = None, *, where: str = "") -> None:
    """标记额度用尽；仅首次打印切换提示，避免重复刷屏。"""
    global _quota_exhausted, _logged_switch
    should_log = False
    with _lock:
        _quota_exhausted = True
        if not _logged_switch:
            _logged_switch = True
            should_log = True
    if should_log:
        ctx = f"（触发点: {where}）" if where else ""
        detail = str(exc).strip() if exc else ""
        suffix = f" 详情: {detail}" if detail else ""
        print(
            f"[rqdatac] 米筐额度已用尽{ctx}；"
            f"本会话将改用东方财富 K 线 / 本地 SQLite，不再重复请求米筐。{suffix}"
        )


def reset_rqdata_quota_state() -> None:
    """测试或新进程前重置（同进程内多标的任务共享状态）。"""
    global _quota_exhausted, _logged_switch
    with _lock:
        _quota_exhausted = False
        _logged_switch = False

