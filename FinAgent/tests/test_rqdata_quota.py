import pandas as pd

from finagent.rqdata_quota import (
    is_rqdata_quota_error,
    mark_rqdata_quota_exceeded,
    reset_rqdata_quota_state,
    rqdata_quota_exhausted,
)


class QuotaExceeded(Exception):
    pass


def setup_function():
    reset_rqdata_quota_state()


def test_is_rqdata_quota_error():
    assert is_rqdata_quota_error(QuotaExceeded("Quota exceeded"))
    assert is_rqdata_quota_error(Exception("Quota exceeded"))
    assert not is_rqdata_quota_error(ValueError("bad"))


def test_mark_sets_session_flag():
    assert not rqdata_quota_exhausted()
    mark_rqdata_quota_exceeded(QuotaExceeded("Quota exceeded"), where="instruments")
    assert rqdata_quota_exhausted()


def test_safe_rq_call_skips_after_quota(monkeypatch):
    from finagent import multiagent

    reset_rqdata_quota_state()
    mark_rqdata_quota_exceeded(QuotaExceeded("Quota exceeded"), where="test")

    called = {"n": 0}

    def boom():
        called["n"] += 1
        return pd.DataFrame({"x": [1]})

    out = multiagent._safe_rq_call("instruments", boom)
    assert called["n"] == 0
    assert out.empty
