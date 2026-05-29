from finagent.cninfo import classify_stock, org_id_for, parse_report_year


def test_classify_stock():
    assert classify_stock("600519") == ("sse", "sh", "XSHG")
    assert classify_stock("688981") == ("sse", "shkcp", "XSHG")
    assert classify_stock("000858") == ("szse", "sz", "XSHE")
    assert classify_stock("300750") == ("szse", "szcy", "XSHE")


def test_parse_report_year():
    assert parse_report_year("贵州茅台2025年年度报告") == 2025
    assert parse_report_year("2024年年度报告摘要") == 2024


def test_org_id_for_uses_cninfo_mapping(monkeypatch):
    monkeypatch.setattr(
        "finagent.cninfo._ORG_ID_CACHE",
        {
            "300750": "GD165627",
            "688981": "gshk0000981",
            "600519": "gssh0600519",
        },
    )
    assert org_id_for("300750") == "GD165627"
    assert org_id_for("688981") == "gshk0000981"
    assert org_id_for("600519") == "gssh0600519"


def test_org_id_for_fallback_when_missing_from_mapping(monkeypatch):
    monkeypatch.setattr("finagent.cninfo._ORG_ID_CACHE", {})
    assert org_id_for("600519") == "gssh0600519"
    assert org_id_for("688981") == "gshk0688981"
    assert org_id_for("300750", "szse") == "gssz0300750"
