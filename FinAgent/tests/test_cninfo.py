from finagent.cninfo import classify_stock, parse_report_year


def test_classify_stock():
    assert classify_stock("600519") == ("sse", "sh", "XSHG")
    assert classify_stock("688981") == ("sse", "shkcp", "XSHG")
    assert classify_stock("000858") == ("szse", "sz", "XSHE")
    assert classify_stock("300750") == ("szse", "szcy", "XSHE")


def test_parse_report_year():
    assert parse_report_year("贵州茅台2025年年度报告") == 2025
    assert parse_report_year("2024年年度报告摘要") == 2024
