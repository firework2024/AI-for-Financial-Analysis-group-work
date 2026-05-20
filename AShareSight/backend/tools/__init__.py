"""AShareSight tools — A-share data via rqdatac + Eastmoney fallback."""

from .env import TAVILY_API_KEY, EXA_API_KEY
from .search import DDGS_AVAILABLE, TAVILY_AVAILABLE, EXA_AVAILABLE, WIKIPEDIA_AVAILABLE, search
from .news import (
    format_news_items,
    get_company_news,
    get_event_calendar,
    get_news_sentiment,
    get_market_news_headlines,
    score_news_source_reliability,
)
from .rqdata_price import (
    get_stock_price,
    get_stock_historical_data,
    get_performance_comparison,
    analyze_historical_drawdowns,
    get_factor_exposure,
    run_portfolio_stress_test,
    get_limit_board_info,
    get_suspension_info,
    get_st_status,
    _fetch_rqdatac_price,
    _search_for_price,
)
from .rqdata_financial import (
    get_financial_statements,
    get_financial_statements_summary,
    get_company_info,
    get_earnings_estimates,
    get_eps_revisions,
    resolve_company_ticker,
)
from .macro import get_market_sentiment, get_economic_events, get_fred_data, get_china_macro_snapshot
from .macro_official import search_official_macro_releases, get_official_macro_releases
from .utils import get_current_datetime
from .web import fetch_url_content, fetch_url_document
from .authoritative_feeds import search_authoritative_feeds, get_authoritative_media_news
from .local_disclosure import get_local_market_filings
from .cn_hk_market import (
    detect_market as detect_cn_hk_market,
    fetch_cn_hk_quote_metrics,
    fetch_cn_hk_kline,
    fetch_cn_hk_financial_statements,
)
from .screener import screen_stocks
from .cn_market_flow import fetch_fund_flow, fetch_northbound
from .cn_market_board import fetch_limit_board, fetch_lhb
from .concept_map import fetch_concept_map
from .wayback import resolve_wayback_snapshot, fetch_via_wayback

__all__ = [
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "DDGS_AVAILABLE",
    "TAVILY_AVAILABLE",
    "EXA_AVAILABLE",
    "WIKIPEDIA_AVAILABLE",
    "search",
    "format_news_items",
    "get_company_news",
    "get_event_calendar",
    "get_news_sentiment",
    "get_market_news_headlines",
    "score_news_source_reliability",
    "get_stock_price",
    "get_stock_historical_data",
    "get_performance_comparison",
    "analyze_historical_drawdowns",
    "get_factor_exposure",
    "run_portfolio_stress_test",
    "get_limit_board_info",
    "get_suspension_info",
    "get_st_status",
    "_fetch_rqdatac_price",
    "_search_for_price",
    "get_financial_statements",
    "get_financial_statements_summary",
    "get_company_info",
    "get_earnings_estimates",
    "get_eps_revisions",
    "resolve_company_ticker",
    "get_market_sentiment",
    "get_economic_events",
    "get_fred_data",
    "get_china_macro_snapshot",
    "search_official_macro_releases",
    "get_official_macro_releases",
    "get_current_datetime",
    "fetch_url_content",
    "fetch_url_document",
    "search_authoritative_feeds",
    "get_authoritative_media_news",
    "get_local_market_filings",
    "detect_cn_hk_market",
    "fetch_cn_hk_quote_metrics",
    "fetch_cn_hk_kline",
    "fetch_cn_hk_financial_statements",
    "screen_stocks",
    "fetch_fund_flow",
    "fetch_northbound",
    "fetch_limit_board",
    "fetch_lhb",
    "fetch_concept_map",
    "resolve_wayback_snapshot",
    "fetch_via_wayback",
]
