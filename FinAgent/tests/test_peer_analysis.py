from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from finagent.peer_analysis import PEER_FACTOR_CANDIDATES, _latest_factor_frame, fetch_industry_comparison


TARGET = "000001.XSHE"


class FakeRQData:
    def __init__(self, *, third_members: list[str], second_members: list[str], values: dict[str, dict[str, float | None]]):
        self.third_members = third_members
        self.second_members = second_members
        self.values = values

    def get_instrument_industry(self, order_book_id, source="citics_2019", level=0, date=None):
        return pd.DataFrame(
            [
                {
                    "first_industry_code": "40",
                    "first_industry_name": "银行",
                    "second_industry_code": "4020",
                    "second_industry_name": "全国性银行",
                    "third_industry_code": "402010",
                    "third_industry_name": "股份制银行",
                }
            ],
            index=pd.Index([order_book_id], name="order_book_id"),
        )

    def get_industry(self, industry, source="citics_2019", date=None):
        if str(industry) == "402010":
            return self.third_members
        if str(industry) == "4020":
            return self.second_members
        return []

    def get_factor(self, order_book_ids, factors, start_date=None, end_date=None):
        rows = []
        for order_book_id in order_book_ids:
            row = {"order_book_id": order_book_id}
            values = self.values.get(order_book_id, {})
            for factor in factors:
                row[factor] = values.get(factor)
            rows.append(row)
        return pd.DataFrame(rows).set_index("order_book_id")


def _values(order_book_ids: list[str]) -> dict[str, dict[str, float]]:
    result = {}
    for idx, order_book_id in enumerate(order_book_ids):
        result[order_book_id] = {
            "pe_ratio_ttm": 10.0 + idx,
            "pb_ratio_ttm": 1.0 + idx * 0.1,
            "ps_ratio_ttm": 2.0 + idx * 0.1,
            "gross_profit_margin_ttm": 0.30 + idx * 0.01,
            "net_profit_margin_ttm": 0.10 + idx * 0.01,
            "roe_ttm": 0.08 + idx * 0.01,
            "debt_to_asset_ratio": 50.0 + idx,
            "current_ratio": 1.0 + idx * 0.05,
            "operating_revenue_growth_ratio_ttm": 0.05 + idx * 0.01,
            "net_profit_parent_company_growth_ratio_ttm": 0.04 + idx * 0.01,
        }
    return result


def test_uses_third_level_industry_by_default():
    members = [TARGET, "000002.XSHE", "000003.XSHE", "000004.XSHE", "000005.XSHE"]
    rq = FakeRQData(third_members=members, second_members=[], values=_values(members))

    result = fetch_industry_comparison(rq, order_book_id=TARGET, as_of=date(2026, 6, 1), available_factors=set(PEER_FACTOR_CANDIDATES))

    assert result["industry"]["selected_level"] == 3
    assert result["peers"]["effective_count"] == 5
    assert "pe_ratio_ttm" in result["metrics"]


def test_falls_back_to_second_level_when_third_level_has_too_few_effective_peers():
    third = [TARGET, "000002.XSHE", "000003.XSHE", "000004.XSHE"]
    second = [*third, "000005.XSHE", "000006.XSHE"]
    rq = FakeRQData(third_members=third, second_members=second, values=_values(second))

    result = fetch_industry_comparison(rq, order_book_id=TARGET, as_of=date(2026, 6, 1), available_factors=set(PEER_FACTOR_CANDIDATES))

    assert result["industry"]["selected_level"] == 2
    assert result["peers"]["effective_count"] == 6
    assert any("三级行业有效同行少于 5 家" in note for note in result["data_notes"])


def test_returns_no_peer_when_second_level_is_still_too_small():
    members = [TARGET, "000002.XSHE", "000003.XSHE", "000004.XSHE"]
    rq = FakeRQData(third_members=members[:3], second_members=members, values=_values(members))

    result = fetch_industry_comparison(rq, order_book_id=TARGET, as_of=date(2026, 6, 1), available_factors=set(PEER_FACTOR_CANDIDATES))

    assert result["industry"]["selected_level"] is None
    assert result["metrics"] == {}
    assert result["cluster_anomalies"]["status"] == "skipped"
    assert any("二级行业有效同行仍少于 5 家" in note for note in result["data_notes"])


def test_missing_values_negative_pe_and_small_samples_do_not_break_stats_or_skip_reason():
    members = [TARGET, "000002.XSHE", "000003.XSHE", "000004.XSHE", "000005.XSHE"]
    values = _values(members)
    values["000003.XSHE"]["pe_ratio_ttm"] = -12.0
    values["000004.XSHE"]["current_ratio"] = None
    rq = FakeRQData(third_members=members, second_members=[], values=values)

    result = fetch_industry_comparison(rq, order_book_id=TARGET, as_of=date(2026, 6, 1), available_factors=set(PEER_FACTOR_CANDIDATES))

    assert result["industry"]["selected_level"] == 3
    assert result["metrics"]["pe_ratio_ttm"]["valid_count"] == 5
    assert result["cluster_anomalies"]["status"] == "skipped"
    assert "少于 8 家" in result["cluster_anomalies"]["reason"]


def test_dbscan_outputs_noise_or_single_metric_anomaly_when_target_is_extreme():
    pytest.importorskip("sklearn")
    members = [TARGET, *[f"00000{i}.XSHE" for i in range(2, 12)]]
    values = _values(members)
    values[TARGET]["pe_ratio_ttm"] = 500.0
    values[TARGET]["pb_ratio_ttm"] = 20.0
    values[TARGET]["net_profit_margin_ttm"] = -0.30
    rq = FakeRQData(third_members=members, second_members=[], values=values)

    result = fetch_industry_comparison(rq, order_book_id=TARGET, as_of=date(2026, 6, 1), available_factors=set(PEER_FACTOR_CANDIDATES))
    cluster = result["cluster_anomalies"]

    assert cluster["status"] == "ok"
    assert cluster["points"]
    assert cluster["is_noise"] or cluster["single_metric_anomalies"]


def test_latest_factor_frame_uses_recent_history_when_as_of_is_empty():
    members = [TARGET, "000002.XSHE"]
    factors = ["pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"]

    class StaleTodayRQData(FakeRQData):
        def get_factor(self, order_book_ids, factors, start_date=None, end_date=None):
            rows = []
            for order_book_id in order_book_ids:
                rows.append(
                    {
                        "order_book_id": order_book_id,
                        "date": date(2026, 6, 3),
                        "pe_ratio_ttm": 10.0,
                        "pb_ratio_ttm": 1.0,
                        "ps_ratio_ttm": 2.0,
                    }
                )
                rows.append(
                    {
                        "order_book_id": order_book_id,
                        "date": date(2026, 6, 4),
                        "pe_ratio_ttm": None,
                        "pb_ratio_ttm": None,
                        "ps_ratio_ttm": None,
                    }
                )
            frame = pd.DataFrame(rows)
            return frame.set_index(["order_book_id", "date"])

    rq = StaleTodayRQData(third_members=members, second_members=[], values=_values(members))
    frame = _latest_factor_frame(rq, members, factors, date(2026, 6, 4))

    assert frame.loc[TARGET, "pe_ratio_ttm"] == pytest.approx(10.0)
    assert frame.loc[TARGET, "pb_ratio_ttm"] == pytest.approx(1.0)
