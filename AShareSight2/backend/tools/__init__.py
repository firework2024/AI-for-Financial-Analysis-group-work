"""AShareSight tools — A-share market data tools powered by rqdatac."""

from .env import (
    CN_DATA_PRIMARY,
    CN_DATA_FALLBACK,
    TAVILY_API_KEY,
)

from .search import (
    TAVILY_AVAILABLE,
    search,
)

from .news import (
    get_stock_news,
    get_top_news_for_ticker,
    score_news_article,
)
from .rqdata_price import (
    get_stock_price,
    get_stock_historical_data,
    get_performance_comparison,
    get_factor_exposure,
    get_turnover_rate,
    get_suspension_info,
    is_st_stock,
)

from .rqdata_financial import (
    get_financial_statements,
    get_company_info,
    get_earnings_estimates,
    resolve_company_ticker,
)

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
from .web import fetch_url_content, fetch_url_document

# Backward-compatible aliases for existing code
get_company_news = get_stock_news
get_financial_statements_summary = get_financial_statements

__all__ = [
    "CN_DATA_PRIMARY",
    "CN_DATA_FALLBACK",
    "TAVILY_API_KEY",
    "TAVILY_AVAILABLE",
    "search",
    "get_stock_news",
    "get_top_news_for_ticker",
    "score_news_article",
    "get_stock_price",
    "get_stock_historical_data",
    "get_performance_comparison",
    "get_factor_exposure",
    "get_turnover_rate",
    "get_suspension_info",
    "is_st_stock",
    "get_financial_statements",
    "get_company_info",
    "get_earnings_estimates",
    "resolve_company_ticker",
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
    "fetch_url_content",
    "fetch_url_document",
    "get_company_news",
    "get_financial_statements_summary",
]
