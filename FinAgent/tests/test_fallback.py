from finagent.fallback import apply_financial_fallbacks


def test_field_level_fallback_and_missing():
    rows = [{"year": 2025, "quarter": "2025q4", "revenue": None}]
    text = "营业总收入 1,234.56\n"
    enriched = apply_financial_fallbacks(rows, text)
    assert enriched[0]["fields"]["revenue"]["source"] == "annual_report"
    assert enriched[0]["fields"]["revenue"]["value"] == 1234.56
    assert enriched[0]["fields"]["goodwill"]["source"] == "missing"


def test_factor_fallback_precedes_annual_report_text():
    rows = [{"year": 2025, "quarter": "2025q4", "revenue": None}]
    enriched = apply_financial_fallbacks(rows, "营业总收入 1,234.56\n", {2025: {"revenue": 999.0}})
    assert enriched[0]["fields"]["revenue"] == {"value": 999.0, "source": "rqdata_factor"}
