"""Tests for finagent.cninfo — cninfo.com.cn specific functionality (org_id mapping)."""

from finagent.cninfo import org_id_for


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
