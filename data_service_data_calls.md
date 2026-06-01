# data_service.py data call map

This file lists all places in `AShareSight/backend/dashboard/data_service.py` that trigger data retrieval (external APIs, market data providers, or shared data helpers that fetch remote data).

## Data Call Verification Todo

| # | Function / Call | Status | Notes / Issues Found |
|---|-----------------|--------|---------------------|
| 1 | `_load_ohlcv_frame` -> `rqdatac.get_price` | OK | Parameters correct; fallback to `fetch_cn_hk_kline` works |
| 2 | `_load_ohlcv_frame` -> `fetch_cn_hk_kline` | OK | Eastmoney kline fallback operational |
| 3 | `fetch_snapshot` -> `rqdatac.get_price` | OK | Uses 60-day window for last close calc |
| 4 | `fetch_snapshot` -> `rqdatac.get_factor` | OK | Validates factor names via `get_all_factor_names()` |
| 5 | `fetch_snapshot` -> `_fallback_snapshot` | OK | Falls back to `fetch_cn_hk_quote_metrics` |
| 6 | `fetch_market_chart` -> `_load_ohlcv_frame` | OK | Indirect call, same as #1 |
| 7 | `fetch_macro_snapshot` -> `rqdatac.econ.get_money_supply` | OK | Parameters correct |
| 8 | `fetch_macro_snapshot` -> `rqdatac.index_indicator` | WARNING | `fields=["pe_ttm", "pb"]` - "pb" may not exist; API returns `pb_ttm` or `pb_lf` |
| 9 | `fetch_valuation` -> `rqdatac.get_factor` | OK | Validates factor names before call |
| 10 | `fetch_valuation` -> `rqdatac.get_price` | OK | 52-week high/low calculation |
| 11 | `fetch_valuation` -> `rqdatac.get_style_factor_exposure` | BUG | Function does not exist! Should be `rqdatac.get_factor_exposure()` |
| 12 | `fetch_valuation` -> `_fallback_valuation` | OK | Falls back to `fetch_cn_hk_quote_metrics` |
| 13 | `fetch_financial_statements` -> `rqdatac.get_pit_financials_ex` | REVIEW | Quarter format `2024q1` needs verification; field names need validation against supported list |
| 14 | `fetch_financial_statements` -> `_fallback_financials` | OK | Falls back to `fetch_cn_hk_financial_statements` |
| 15 | `fetch_revenue_trend` -> `fetch_financial_statements` | OK | Indirect call |
| 16 | `fetch_segment_mix` -> `fetch_cn_hk_financial_statements` | OK | Eastmoney-only path |
| 17 | `fetch_technical_indicators` -> `_load_ohlcv_frame` | OK | Indirect call |
| 18 | `fetch_indicator_series` -> `_load_ohlcv_frame` | OK | Indirect call |
| 19 | `fetch_earnings_history` -> `fetch_financial_statements` | OK | Indirect call |
| 20 | `fetch_analyst_targets` -> `rqdatac.get_factor` | OK | Validates `forecast_eps`, `forecast_net_profit`, `rating_score` |
| 21 | `fetch_recommendations` -> `fetch_analyst_targets` | OK | Indirect call |
| 22 | `fetch_news` -> `get_stock_news` + `score_news_article` | OK | Eastmoney primary, rqdatac secondary, search fallback |
| 23 | `fetch_sector_weights` -> `rqdatac.get_instrument_industry` | BUG | Returns `first_industry_name` column, but code reads `industry_name` |
| 24 | `fetch_top_constituents` -> `rqdatac.index_components` | WARNING | Return type handling incomplete: when `start_date`/`end_date` passed, returns dict; code only handles list/DataFrame |
| 25 | `fetch_holdings` -> `fetch_top_constituents` | OK | Indirect call |

## Critical Issues Summary

1. **`fetch_valuation` (line 262)**: Uses `rqdatac.get_style_factor_exposure()` which does not exist in rqdatac API. Should be `rqdatac.get_factor_exposure()`.
2. **`fetch_sector_weights` (line 614)**: `get_instrument_industry()` returns column `first_industry_name` (default level=1), but code accesses `industry_name`. This will always return empty/None.
3. **`fetch_macro_snapshot` (line 557-562)**: `index_indicator` fields include `"pb"`, but API returns `pb_ttm`, `pb_lf`, or `pb_lyr`. The `"pb"` key may cause KeyError (caught by try-except but data is lost).
4. **`fetch_financial_statements` (line 330)**: `get_pit_financials_ex` quarter format `2024q1` needs runtime validation. Some field names in the fields list may not be supported by the API.
5. **`fetch_top_constituents` (lines 629-633)**: `index_components` with only `date` arg returns a list, but if `start_date`/`end_date` were used it returns a dict. Current code doesn't handle dict return type.

## Shared data access helpers

| Helper | Data source / call | Notes |
| --- | --- | --- |
| `_load_ohlcv_frame(symbol, period, interval)` | `backend.tools.rqdata_price.get_stock_historical_data` | Primary for CN via rqdatac price pipeline. |
|  | `backend.tools.cn_hk_market.fetch_cn_hk_kline` | CN/HK fallback; converts ticker via `backend.utils.ticker_rq`. |
|  | `yfinance.Ticker(symbol).history(...)` | Global fallback for OHLCV. |
|  | `backend.tools.rqdata_price.get_stock_historical_data` | Late fallback when yfinance fails; reads `rows` / `kline_data`. |
| `_finnhub_request(path, params)` | `backend.tools.http._http_get` to `https://finnhub.io/api/v1/...` | Uses `backend.tools.env.FINNHUB_API_KEY`. |

## Macro / snapshot / charting

| Function | Data source / call | Notes |
| --- | --- | --- |
| `fetch_macro_snapshot()` | `backend.tools.macro.get_market_sentiment()` | CNN Fear & Greed text. |
|  | `backend.tools.macro.get_fred_data()` | FRED macro series (rates, CPI, etc.). |
| `fetch_market_chart(symbol, period, interval)` | `_load_ohlcv_frame(...)` | Uses shared OHLCV helper (rqdatac / CN-HK / yfinance). |
| `fetch_snapshot(symbol, asset_type)` | `backend.tools.rqdata_price.get_stock_price()` | CN equity path (rqdatac). |
|  | `backend.tools.rqdata_financial.get_company_info()` | CN equity path (rqdatac). |
|  | `yfinance.Ticker(symbol).info` | Non-CN path (and fallback). |
|  | `yfinance.Ticker(symbol).history(...)` | Used to compute last close. |
| `fetch_revenue_trend(symbol)` | `yfinance.Ticker(symbol).quarterly_income_stmt` | Uses quarterly income; falls back to `quarterly_financials`. |
| `fetch_segment_mix(symbol)` | `backend.tools.fmp.get_revenue_product_segmentation()` | FMP revenue segmentation. |

## News

| Function | Data source / call | Notes |
| --- | --- | --- |
| `fetch_news(symbol, limit)` | `backend.tools.news.get_company_news()` | Company news. |
|  | `backend.tools.news.get_market_news_headlines()` | Market headlines. |

## ETF / index / portfolio holdings

| Function | Data source / call | Notes |
| --- | --- | --- |
| `fetch_sector_weights(symbol, asset_type)` | `backend.tools.fmp.get_etf_sector_weights()` | ETF / index sector weights. |
| `fetch_top_constituents(symbol, asset_type, limit)` | `backend.tools.fmp.get_index_constituents()` | Index constituents. |
| `fetch_holdings(symbol, asset_type, limit)` | `backend.tools.fmp.get_etf_holdings()` | ETF / portfolio holdings. |

## Valuation

| Function | Data source / call | Notes |
| --- | --- | --- |
| `_fetch_valuation_from_finnhub(symbol)` | `_finnhub_request("stock/profile2")` | Finnhub profile. |
|  | `_finnhub_request("stock/metric")` | Finnhub metrics. |
| `_fetch_valuation_from_cn_hk_market(symbol)` | `backend.tools.cn_hk_market.fetch_cn_hk_quote_metrics()` | CN/HK quote metrics. |
| `fetch_valuation(symbol)` | `yfinance.Ticker(symbol).info` | Primary valuation source for non-CN/HK. |
|  | `_fetch_valuation_from_finnhub(symbol)` | Fallback. |
|  | `_fetch_valuation_from_cn_hk_market(symbol)` | CN/HK fallback (primary if CN/HK). |

## Financial statements

| Function | Data source / call | Notes |
| --- | --- | --- |
| `_fetch_financial_statements_from_sec_companyfacts(symbol, periods)` | `backend.tools.sec.get_sec_company_facts_quarterly()` | SEC Company Facts fallback. |
| `_fetch_financial_statements_from_cn_hk_market(symbol, periods)` | `backend.tools.cn_hk_market.fetch_cn_hk_financial_statements()` | CN/HK financials fallback. |
| `_fetch_financial_statements_from_finnhub(symbol, periods)` | `_finnhub_request("stock/financials-reported")` | Finnhub reports fallback. |
| `fetch_financial_statements(symbol, periods)` | `yfinance.Ticker(symbol).quarterly_income_stmt` | Primary; also uses `quarterly_financials`, `quarterly_balance_sheet`, `quarterly_cashflow`. |
|  | `_fetch_financial_statements_from_sec_companyfacts(...)` | Fallback. |
|  | `_fetch_financial_statements_from_finnhub(...)` | Fallback. |
|  | `_fetch_financial_statements_from_cn_hk_market(...)` | Primary for CN/HK. |

## Technicals / indicators / analyst data

| Function | Data source / call | Notes |
| --- | --- | --- |
| `fetch_technical_indicators(symbol)` | `_load_ohlcv_frame(...)` | OHLCV fetch via shared helper. |
| `fetch_indicator_series(symbol, n_days)` | `_load_ohlcv_frame(...)` | OHLCV fetch via shared helper. |
| `fetch_earnings_history(symbol)` | `yfinance.Ticker(symbol).earnings_history` | EPS estimate vs actual history. |
| `fetch_analyst_targets(symbol)` | `yfinance.Ticker(symbol).analyst_price_targets` | Analyst price targets. |
| `fetch_recommendations(symbol)` | `yfinance.Ticker(symbol).recommendations_summary` | Analyst recommendation summary. |

## Cache wrapper methods (call the above fetchers)

| Method | Fetcher called | Notes |
| --- | --- | --- |
| `DashboardDataService.get_market_chart` | `fetch_market_chart` | Cache wrapper. |
| `DashboardDataService.get_snapshot` | `fetch_snapshot` | Cache wrapper. |
| `DashboardDataService.get_revenue_trend` | `fetch_revenue_trend` | Cache wrapper. |
| `DashboardDataService.get_segment_mix` | `fetch_segment_mix` | Cache wrapper. |
| `DashboardDataService.get_news` | `fetch_news` | Cache wrapper. |
| `DashboardDataService.get_macro_snapshot` | `fetch_macro_snapshot` | Cache wrapper. |
| `DashboardDataService.get_sector_weights` | `fetch_sector_weights` | Cache wrapper. |
| `DashboardDataService.get_top_constituents` | `fetch_top_constituents` | Cache wrapper. |
| `DashboardDataService.get_holdings` | `fetch_holdings` | Cache wrapper. |
| `DashboardDataService.get_valuation` | `fetch_valuation` | Cache wrapper. |
| `DashboardDataService.get_financial_statements` | `fetch_financial_statements` | Cache wrapper. |
| `DashboardDataService.get_technical_indicators` | `fetch_technical_indicators` | Cache wrapper. |
| `DashboardDataService.get_indicator_series` | `fetch_indicator_series` | Cache wrapper. |
| `DashboardDataService.get_earnings_history` | `fetch_earnings_history` | Cache wrapper. |
| `DashboardDataService.get_analyst_targets` | `fetch_analyst_targets` | Cache wrapper. |
| `DashboardDataService.get_recommendations` | `fetch_recommendations` | Cache wrapper. |
