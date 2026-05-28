from finagent.env import load_dotenv
from finagent.rqdata_client import _init_rqdata
import rqdatac

load_dotenv()
_init_rqdata(rqdatac)
order_book_id = '600519.XSHG'
start_date = '2025-09-04'
end_date = '2026-05-22'
factors = ['market_cap', 'pe_ratio_ttm', 'pb_ratio_ttm', 'ps_ratio_ttm', 'gross_profit_margin_ttm', 'net_profit_margin_ttm', 'debt_to_asset_ratio', 'current_ratio', 'quick_ratio', 'dividend_yield_ttm', 'net_profit_growth_ratio_ttm', 'net_profit_parent_company_growth_ratio_ttm', 'operating_profit_growth_ratio_ttm', 'gross_profit_growth_ratio_ttm', 'account_receivable_turnover_rate_ttm', 'current_asset_turnover_ttm']

price = rqdatac.get_price(order_book_id, start_date=start_date, end_date=end_date, frequency="1d", fields=["open", "high", "low", "close", "volume", "total_turnover"])
price_change_rate = rqdatac.get_price_change_rate(order_book_id, start_date=start_date, end_date=end_date)
turnover = rqdatac.get_turnover_rate(order_book_id, start_date=start_date, end_date=end_date)
capital_flow = rqdatac.get_capital_flow(order_book_id, start_date=start_date, end_date=end_date)
factor = rqdatac.get_factor(order_book_id, factors, start_date=end_date, end_date=end_date)
factor_history = rqdatac.get_factor(order_book_id, factors, start_date=start_date, end_date=end_date)
securities_margin = rqdatac.get_securities_margin(order_book_id, start_date=start_date, end_date=end_date)
dividend = rqdatac.get_dividend(order_book_id, start_date="2024-01-01", end_date=end_date)
shares = rqdatac.get_shares(order_book_id, start_date="2024-01-01", end_date=end_date)
industry = rqdatac.get_instrument_industry(order_book_id, source="citics_2019", level=1, date=end_date)
interbank_rate = rqdatac.get_interbank_offered_rate(start_date=start_date, end_date=end_date)
yield_curve = rqdatac.get_yield_curve(start_date=start_date, end_date=end_date)

print(price.tail())
print(price_change_rate.tail())
print(turnover.tail())
print(capital_flow.tail())
print(factor.tail())
print(factor_history.tail())
print(securities_margin.tail())
print(dividend.tail())
print(shares.tail())
print(industry)
print(interbank_rate.tail())
print(yield_curve.tail())
