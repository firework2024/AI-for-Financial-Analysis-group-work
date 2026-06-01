from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDef:
    field: str
    cn: str
    statement: str
    aliases: tuple[str, ...] = ()


FIELD_DEFS: list[FieldDef] = [
    FieldDef("total_assets", "资产总计", "balance_sheet", ("总资产",)),
    FieldDef("current_assets", "流动资产合计", "balance_sheet", ("流动资产",)),
    FieldDef("cash_equivalent", "货币资金", "balance_sheet", ("现金及存放中央银行款项",)),
    FieldDef("bill_accts_receivable", "应收账款", "balance_sheet", ("应收票据及应收账款",)),
    FieldDef("bill_receivable", "应收票据", "balance_sheet"),
    FieldDef("inventory", "存货", "balance_sheet"),
    FieldDef("net_fixed_assets", "固定资产", "balance_sheet", ("固定资产净额",)),
    FieldDef("construction_in_progress", "在建工程", "balance_sheet"),
    FieldDef("goodwill", "商誉", "balance_sheet"),
    FieldDef("current_liabilities", "流动负债合计", "balance_sheet", ("流动负债",)),
    FieldDef("total_liabilities", "负债合计", "balance_sheet", ("总负债",)),
    FieldDef("short_term_loans", "短期借款", "balance_sheet"),
    FieldDef("non_current_liability_due_one_year", "一年内到期的非流动负债", "balance_sheet"),
    FieldDef("long_term_loans", "长期借款", "balance_sheet"),
    FieldDef("bond_payable", "应付债券", "balance_sheet"),
    FieldDef("lease_liabilities", "租赁负债", "balance_sheet"),
    FieldDef("accts_payable", "应付账款", "balance_sheet", ("应付票据及应付账款",)),
    FieldDef("contract_liabilities", "合同负债", "balance_sheet"),
    FieldDef("equity_parent_company", "归属于母公司所有者权益合计", "balance_sheet", ("归属母公司所有者权益",)),
    FieldDef("undistributed_profit", "未分配利润", "balance_sheet"),
    FieldDef("revenue", "营业总收入", "income_statement"),
    FieldDef("operating_revenue", "营业收入", "income_statement"),
    FieldDef("cost_of_goods_sold", "营业成本", "income_statement"),
    FieldDef("profit_from_operation", "营业利润", "income_statement"),
    FieldDef("net_profit", "净利润", "income_statement"),
    FieldDef("net_profit_parent_company", "归属于母公司所有者的净利润", "income_statement", ("归母净利润",)),
    FieldDef("net_profit_deduct_non_recurring_pnl", "扣除非经常性损益后的净利润", "income_statement", ("扣非归母净利润",)),
    FieldDef("selling_expense", "销售费用", "income_statement"),
    FieldDef("ga_expense", "管理费用", "income_statement"),
    FieldDef("r_n_d", "研发费用", "income_statement"),
    FieldDef("financing_expense", "财务费用", "income_statement"),
    FieldDef("adjust_asset_impairment", "资产减值损失", "income_statement"),
    FieldDef("adjust_credit_asset_impairment", "信用减值损失", "income_statement"),
    FieldDef("cash_flow_from_operating_activities", "经营活动产生的现金流量净额", "cash_flow"),
    FieldDef("cash_received_from_sales_of_goods", "销售商品、提供劳务收到的现金", "cash_flow"),
    FieldDef("cash_paid_for_asset", "购建固定资产、无形资产和其他长期资产支付的现金", "cash_flow"),
    FieldDef("cash_flow_from_investing_activities", "投资活动产生的现金流量净额", "cash_flow"),
    FieldDef("cash_flow_from_financing_activities", "筹资活动产生的现金流量净额", "cash_flow"),
]

FIELD_NAMES = [item.field for item in FIELD_DEFS]
FIELD_MAP = {item.field: item for item in FIELD_DEFS}
