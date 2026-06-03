from finagent.core_metrics import derive_dividend_yield_ttm, enrich_core_metrics, resolve_industry_dict
from finagent.report_format import industry_label


def test_resolve_industry_from_comparison():
    data = {
        "industry": {},
        "industry_comparison": {
            "industry": {"level1_name": "食品饮料", "selected_level": 1},
        },
    }
    resolved = resolve_industry_dict(data)
    assert industry_label(resolved) == "食品饮料"


def test_derive_dividend_yield_from_dividend_rows():
    data = {
        "technical": {"latest_close": 100.0},
        "end_date": "2026-05-29",
        "factor": {},
        "dividend": {
            "rows": [
                {
                    "ex_dividend_date": "2025-12-19",
                    "dividend_cash_before_tax": 10.0,
                    "round_lot": 10,
                },
                {
                    "ex_dividend_date": "2025-06-26",
                    "dividend_cash_before_tax": 20.0,
                    "round_lot": 10,
                },
            ]
        },
    }
    yield_ratio = derive_dividend_yield_ttm(data)
    assert yield_ratio is not None
    assert 0.002 < yield_ratio < 0.05


def test_industry_from_citics_code_map():
    from finagent.core_metrics import _industry_from_citics_code

    out = _industry_from_citics_code({"first_industry_code": "36"})
    assert out.get("first_industry_name") == "食品饮料"


def test_enrich_core_metrics_updates_factor_and_industry():
    data = {
        "industry": {},
        "industry_comparison": {"industry": {"level1_name": "银行"}},
        "technical": {"latest_close": 50.0},
        "factor": {"pe_ratio_ttm": 6.0},
        "dividend": {
            "rows": [
                {"ex_dividend_date": "2026-01-15", "dividend_cash_before_tax": 2.5, "round_lot": 1},
            ]
        },
        "end_date": "2026-06-01",
    }
    enrich_core_metrics(data)
    assert industry_label(data["industry"]) == "银行"
    assert data["factor"]["dividend_yield_ttm"] is not None
