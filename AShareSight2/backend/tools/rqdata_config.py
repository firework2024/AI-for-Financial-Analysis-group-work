"""RQData connection initialization and configuration."""

import logging
import os

logger = logging.getLogger(__name__)

_rqdata_initialized = False


def init_rqdata() -> bool:
    """Initialize RQData connection from .env credentials.

    Supports three methods:
      1. URI proxy:  rqdatac.init(user, pass, 'tcp://host:port')
      2. Direct auth: rqdatac.init(user, pass)
      3. License key: rqdatac.init() (via RQDATAC2_CONF env var)

    Returns True if connected successfully, False otherwise.
    """
    global _rqdata_initialized
    if _rqdata_initialized:
        return True

    try:
        import rqdatac
    except ImportError:
        logger.warning("rqdatac not installed. Install with: pip install rqdatac")
        return False

    username = os.getenv("RQDATA_USERNAME", "").strip()
    password = os.getenv("RQDATA_PASSWORD", "").strip()
    uri = os.getenv("RQDATA_URI", "").strip()        # e.g. 222.29.71.3:16010
    license_conf = os.getenv("RQDATAC2_CONF", "").strip()

    try:
        if uri and username and password:
            url = f"tcp://{uri}" if "://" not in uri else uri
            rqdatac.init(username, password, url)
            logger.info("RQData initialized via username/password/URI proxy")
        elif username and password:
            rqdatac.init(username, password)
            logger.info("RQData initialized via username/password")
        elif license_conf:
            rqdatac.init()
            logger.info("RQData initialized via license key")
        else:
            logger.warning(
                "RQData credentials not found. "
                "Set RQDATA_USERNAME/PASSWORD/RQDATA_URI or RQDATAC2_CONF in .env"
            )
            return False
        _rqdata_initialized = True
        return True
    except Exception as exc:
        logger.error("RQData init failed: %s", exc)
        return False


def get_rqdata_status() -> dict:
    """Return RQData connection status (for health check)."""
    return {
        "initialized": _rqdata_initialized,
    }
