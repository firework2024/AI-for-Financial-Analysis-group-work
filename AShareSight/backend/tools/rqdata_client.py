"""Lazy rqdatac initialization for AShareSight."""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False
_init_error: str | None = None


def ensure_rqdatac() -> bool:
    """Initialize rqdatac once. Returns True if ready."""
    global _initialized, _init_error
    if _initialized:
        return _init_error is None
    with _init_lock:
        if _initialized:
            return _init_error is None
        try:
            import rqdatac

            user = os.getenv("RQDATA_USERNAME", "").strip()
            password = os.getenv("RQDATA_PASSWORD", "").strip()
            uri = os.getenv("RQDATAC_URI", "").strip()
            if uri:
                rqdatac.init(uri=uri)
            elif user and password:
                rqdatac.init(user, password)
            else:
                rqdatac.init()
            _initialized = True
            _init_error = None
            logger.info("[RQData] initialized")
            return True
        except Exception as exc:
            _initialized = True
            _init_error = str(exc)
            logger.warning("[RQData] init failed: %s", exc)
            return False


def rqdatac_module():
    if not ensure_rqdatac():
        return None
    try:
        import rqdatac

        return rqdatac
    except Exception:
        return None
