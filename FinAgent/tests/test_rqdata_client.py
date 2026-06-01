from finagent.rqdata_client import _format_rqdata_error


class QuotaExceeded(Exception):
    pass


def test_format_rqdata_quota_error():
    message = _format_rqdata_error("获取年报口径财务数据", QuotaExceeded("Quota exceeded"))
    assert "额度已用尽" in message
    assert "Quota exceeded" in message


def test_format_rqdata_generic_error():
    message = _format_rqdata_error("获取字段级回补因子", ValueError("bad request"))
    assert message == "获取字段级回补因子失败：ValueError: bad request"
