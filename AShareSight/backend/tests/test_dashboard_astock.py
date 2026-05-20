from __future__ import annotations

from backend.dashboard import peer_service
from backend.utils.ticker_rq import to_rqdatac_id


def test_to_rqdatac_id_normalizes_short_codes():
    assert to_rqdatac_id("600519") == "600519.XSHG"
    assert to_rqdatac_id("000001.SZ") == "000001.XSHE"


def test_resolve_peers_returns_astock_defaults():
    peers = peer_service.resolve_peers("600519.XSHG", limit=4)
    assert len(peers) >= 1
    assert all(".XSHG" in p or ".XSHE" in p for p in peers)
    assert "600519.XSHG" not in peers


def test_fetch_peer_comparison_structure(monkeypatch):
    monkeypatch.setattr(
        peer_service,
        "_fetch_single_peer_metrics",
        lambda sym: {
            "symbol": to_rqdatac_id(sym) or sym,
            "name": sym,
            "trailing_pe": 25.0,
            "market_cap": 1e12,
            "currency": "CNY",
        },
    )
    result = peer_service.fetch_peer_comparison("600519.XSHG", peers=["300750.XSHE", "600036.XSHG"])
    assert result.get("currency") == "CNY"
    assert isinstance(result.get("peers"), list)
    assert len(result["peers"]) >= 1
