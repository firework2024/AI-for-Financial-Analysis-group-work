from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_dotenv() -> None:
    path = project_root() / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        # 跳过空值，避免 RQDATAC2_CONF= 覆盖本机 rqsdk license / systemd 注入的配置。
        if key and value and key not in os.environ:
            os.environ[key] = value


def get_env(name: str, default: str | None = None) -> str | None:
    load_dotenv()
    return os.getenv(name, default)


def prepare_rqdata_env() -> None:
    """Normalize RQData env for CLI, Web server, and background tasks."""
    load_dotenv()
    conf_file = os.getenv("RQDATAC2_CONF_FILE")
    if conf_file and not _non_empty(os.getenv("RQDATAC2_CONF")):
        path = Path(conf_file).expanduser()
        if path.is_file():
            conf = path.read_text(encoding="utf-8").strip()
            if conf:
                os.environ["RQDATAC2_CONF"] = conf
    for name in ("RQDATAC2_CONF", "RQDATAC_CONF"):
        if os.getenv(name) == "":
            os.environ.pop(name, None)


def rqdata_configured() -> bool:
    """Whether RQData credentials are likely available (does not call rqdatac.init)."""
    prepare_rqdata_env()
    if _non_empty(os.getenv("RQ_USER")) and _non_empty(os.getenv("RQ_PASSWORD")) and _non_empty(os.getenv("RQ_HOST")):
        return True
    if _non_empty(os.getenv("RQDATAC2_CONF")) or _non_empty(os.getenv("RQDATAC_CONF")):
        return True
    if _non_empty(os.getenv("RQDATA_USERNAME")) and _non_empty(os.getenv("RQDATA_PASSWORD")):
        return True
    return (Path.home() / ".rqdata" / "credentials").is_file()


def project_root() -> Path:
    env_root = os.getenv("FINAGENT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    here = Path(__file__).resolve().parent.parent
    if (here / "pyproject.toml").exists():
        return here
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd
    return here


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _non_empty(value: str | None) -> bool:
    return bool(value and value.strip())
