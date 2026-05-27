from __future__ import annotations

from typing import Any


CATEGORY_LABELS = {
    "growth": "成长性",
    "profitability": "盈利能力",
    "cash_quality": "现金流质量",
    "solvency": "偿债能力",
    "operating_efficiency": "营运效率",
    "earnings_quality": "利润质量",
}

SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

POLARITY_RANK = {
    "negative": 0,
    "positive": 1,
    "neutral": 2,
}


def detect_structured_signals(
    rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows or not metrics:
        return []

    latest = metrics[-1]
    previous = metrics[-2] if len(metrics) >= 2 else {}
    latest_row = rows[-1]
    positive_growth_streak = _recent_positive_streak(metrics, "revenue_growth")
    negative_growth_streak = _recent_negative_streak(metrics, "revenue_growth")
    negative_profit_streak = _recent_negative_streak(metrics, "net_profit_parent_company_growth")

    signals: list[dict[str, Any]] = []

    revenue_growth = latest.get("revenue_growth")
    if revenue_growth is not None:
        if revenue_growth > 0.10:
            signals.append(
                make_signal(
                    category="growth",
                    metric="revenue_growth",
                    metric_cn="营业总收入增速",
                    polarity="positive",
                    severity="medium",
                    value=revenue_growth,
                    threshold="> 10%",
                    year=latest["year"],
                    title="收入保持较快增长",
                    description="营业总收入保持两位数增长，成长性表现较好。",
                    evidence=f"{latest['year']} 年收入同比增长 {revenue_growth:.1%}。",
                    source_fields=["revenue", "operating_revenue"],
                    row=latest_row,
                )
            )
        elif revenue_growth < 0:
            severity = "high" if negative_growth_streak >= 2 else "medium"
            title = "收入连续下滑" if severity == "high" else "收入出现下滑"
            description = "营业总收入连续两年下降，成长承压。" if severity == "high" else "营业总收入同比下滑，成长性转弱。"
            signals.append(
                make_signal(
                    category="growth",
                    metric="revenue_growth",
                    metric_cn="营业总收入增速",
                    polarity="negative",
                    severity=severity,
                    value=revenue_growth,
                    threshold="< 0%",
                    year=latest["year"],
                    title=title,
                    description=description,
                    evidence=f"{latest['year']} 年收入同比变动 {revenue_growth:.1%}。",
                    source_fields=["revenue", "operating_revenue"],
                    row=latest_row,
                )
            )
        elif positive_growth_streak >= 2:
            signals.append(
                make_signal(
                    category="growth",
                    metric="revenue_growth",
                    metric_cn="营业总收入增速",
                    polarity="positive",
                    severity="medium",
                    value=revenue_growth,
                    threshold="连续两年增长",
                    year=latest["year"],
                    title="收入延续增长趋势",
                    description="营业总收入连续两年保持增长，成长趋势稳定。",
                    evidence=f"{latest['year']} 年收入同比增长 {revenue_growth:.1%}，已连续两年为正增长。",
                    source_fields=["revenue", "operating_revenue"],
                    row=latest_row,
                )
            )

    profit_growth = latest.get("net_profit_parent_company_growth")
    if profit_growth is not None:
        if profit_growth < 0:
            severity = "high" if negative_profit_streak >= 2 else "medium"
            title = "归母净利润连续下滑" if severity == "high" else "归母净利润下滑"
            description = "归母净利润连续两年下降，盈利增长承压。" if severity == "high" else "归母净利润同比下降，盈利增长放缓。"
            signals.append(
                make_signal(
                    category="growth",
                    metric="net_profit_parent_company_growth",
                    metric_cn="归母净利润增速",
                    polarity="negative",
                    severity=severity,
                    value=profit_growth,
                    threshold="< 0%",
                    year=latest["year"],
                    title=title,
                    description=description,
                    evidence=f"{latest['year']} 年归母净利润同比变动 {profit_growth:.1%}。",
                    source_fields=["net_profit_parent_company"],
                    row=latest_row,
                )
            )
        elif profit_growth > 0.10:
            signals.append(
                make_signal(
                    category="growth",
                    metric="net_profit_parent_company_growth",
                    metric_cn="归母净利润增速",
                    polarity="positive",
                    severity="medium",
                    value=profit_growth,
                    threshold="> 10%",
                    year=latest["year"],
                    title="归母净利润增长较快",
                    description="归母净利润保持较快增长，利润扩张表现较好。",
                    evidence=f"{latest['year']} 年归母净利润同比增长 {profit_growth:.1%}。",
                    source_fields=["net_profit_parent_company"],
                    row=latest_row,
                )
            )

    ocf_growth = latest.get("cash_flow_from_operating_activities_growth")
    if ocf_growth is not None:
        if ocf_growth > 0.10:
            signals.append(
                make_signal(
                    category="growth",
                    metric="cash_flow_from_operating_activities_growth",
                    metric_cn="经营现金流增速",
                    polarity="positive",
                    severity="medium",
                    value=ocf_growth,
                    threshold="> 10%",
                    year=latest["year"],
                    title="经营现金流增长较好",
                    description="经营现金流同比增长，现金创造能力改善。",
                    evidence=f"{latest['year']} 年经营现金流同比增长 {ocf_growth:.1%}。",
                    source_fields=["cash_flow_from_operating_activities"],
                    row=latest_row,
                )
            )
        elif ocf_growth < 0:
            signals.append(
                make_signal(
                    category="growth",
                    metric="cash_flow_from_operating_activities_growth",
                    metric_cn="经营现金流增速",
                    polarity="negative",
                    severity="medium",
                    value=ocf_growth,
                    threshold="< 0%",
                    year=latest["year"],
                    title="经营现金流下滑",
                    description="经营现金流同比下降，现金创造能力走弱。",
                    evidence=f"{latest['year']} 年经营现金流同比变动 {ocf_growth:.1%}。",
                    source_fields=["cash_flow_from_operating_activities"],
                    row=latest_row,
                )
            )

    gross_margin = latest.get("gross_margin")
    previous_gross_margin = previous.get("gross_margin")
    if gross_margin is not None and previous_gross_margin is not None:
        if gross_margin > previous_gross_margin:
            signals.append(
                make_signal(
                    category="profitability",
                    metric="gross_margin",
                    metric_cn="毛利率",
                    polarity="positive",
                    severity="medium",
                    value=gross_margin,
                    threshold="较上年提升",
                    year=latest["year"],
                    title="毛利率改善",
                    description="毛利率较上年提升，盈利效率有所改善。",
                    evidence=f"{latest['year']} 年毛利率为 {gross_margin:.1%}，高于上年的 {previous_gross_margin:.1%}。",
                    source_fields=["revenue", "operating_revenue", "cost_of_goods_sold"],
                    row=latest_row,
                )
            )
        elif gross_margin < previous_gross_margin:
            signals.append(
                make_signal(
                    category="profitability",
                    metric="gross_margin",
                    metric_cn="毛利率",
                    polarity="negative",
                    severity="medium",
                    value=gross_margin,
                    threshold="较上年下降",
                    year=latest["year"],
                    title="毛利率承压",
                    description="毛利率较上年下降，盈利能力受到挤压。",
                    evidence=f"{latest['year']} 年毛利率为 {gross_margin:.1%}，低于上年的 {previous_gross_margin:.1%}。",
                    source_fields=["revenue", "operating_revenue", "cost_of_goods_sold"],
                    row=latest_row,
                )
            )

    roe = latest.get("roe")
    if roe is not None:
        if roe >= 0.15:
            signals.append(
                make_signal(
                    category="profitability",
                    metric="roe",
                    metric_cn="ROE",
                    polarity="positive",
                    severity="medium",
                    value=roe,
                    threshold=">= 15%",
                    year=latest["year"],
                    title="股东回报水平较好",
                    description="ROE 处于较好水平，股东权益回报表现较优。",
                    evidence=f"{latest['year']} 年 ROE 为 {roe:.1%}。",
                    source_fields=["net_profit_parent_company", "equity_parent_company"],
                    row=latest_row,
                )
            )
        elif roe < 0.08:
            signals.append(
                make_signal(
                    category="profitability",
                    metric="roe",
                    metric_cn="ROE",
                    polarity="negative",
                    severity="medium",
                    value=roe,
                    threshold="< 8%",
                    year=latest["year"],
                    title="股东回报偏弱",
                    description="ROE 偏低，股东权益回报能力较弱。",
                    evidence=f"{latest['year']} 年 ROE 为 {roe:.1%}。",
                    source_fields=["net_profit_parent_company", "equity_parent_company"],
                    row=latest_row,
                )
            )

    cash_to_revenue = latest.get("cash_to_revenue")
    if cash_to_revenue is not None:
        if cash_to_revenue >= 1.0:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_revenue",
                    metric_cn="收现比",
                    polarity="positive",
                    severity="medium",
                    value=cash_to_revenue,
                    threshold=">= 1.0",
                    year=latest["year"],
                    title="收入现金回收较好",
                    description="收现比不低于 1，收入回款表现较好。",
                    evidence=f"{latest['year']} 年收现比为 {cash_to_revenue:.2f}。",
                    source_fields=["cash_received_from_sales_of_goods", "revenue", "operating_revenue"],
                    row=latest_row,
                )
            )
        elif cash_to_revenue < 0.6:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_revenue",
                    metric_cn="收现比",
                    polarity="negative",
                    severity="high",
                    value=cash_to_revenue,
                    threshold="< 0.6",
                    year=latest["year"],
                    title="收入回款偏弱",
                    description="收现比较低，收入回款压力较大。",
                    evidence=f"{latest['year']} 年收现比为 {cash_to_revenue:.2f}，低于 0.6。",
                    source_fields=["cash_received_from_sales_of_goods", "revenue", "operating_revenue"],
                    row=latest_row,
                )
            )
        elif cash_to_revenue < 0.8:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_revenue",
                    metric_cn="收现比",
                    polarity="negative",
                    severity="medium",
                    value=cash_to_revenue,
                    threshold="0.6 - 0.8",
                    year=latest["year"],
                    title="收入回款转弱",
                    description="收现比低于 0.8，收入现金回收效率偏弱。",
                    evidence=f"{latest['year']} 年收现比为 {cash_to_revenue:.2f}。",
                    source_fields=["cash_received_from_sales_of_goods", "revenue", "operating_revenue"],
                    row=latest_row,
                )
            )

    cash_to_profit = latest.get("cash_to_profit")
    if cash_to_profit is not None:
        if cash_to_profit >= 1.0:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_profit",
                    metric_cn="净现比",
                    polarity="positive",
                    severity="high",
                    value=cash_to_profit,
                    threshold=">= 1.0",
                    year=latest["year"],
                    title="利润现金转化良好",
                    description="净现比不低于 1，利润现金含量较好。",
                    evidence=f"{latest['year']} 年净现比为 {cash_to_profit:.2f}。",
                    source_fields=["cash_flow_from_operating_activities", "net_profit"],
                    row=latest_row,
                )
            )
        elif cash_to_profit < 0.5:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_profit",
                    metric_cn="净现比",
                    polarity="negative",
                    severity="high",
                    value=cash_to_profit,
                    threshold="< 0.5",
                    year=latest["year"],
                    title="利润现金含量偏弱",
                    description="净现比较低，利润转化为经营现金流的能力偏弱。",
                    evidence=f"{latest['year']} 年净现比为 {cash_to_profit:.2f}，低于 0.5。",
                    source_fields=["cash_flow_from_operating_activities", "net_profit"],
                    row=latest_row,
                )
            )
        elif cash_to_profit < 0.8:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="cash_to_profit",
                    metric_cn="净现比",
                    polarity="negative",
                    severity="medium",
                    value=cash_to_profit,
                    threshold="0.5 - 0.8",
                    year=latest["year"],
                    title="利润现金转化偏弱",
                    description="净现比偏低，利润转化为现金的效率有待改善。",
                    evidence=f"{latest['year']} 年净现比为 {cash_to_profit:.2f}。",
                    source_fields=["cash_flow_from_operating_activities", "net_profit"],
                    row=latest_row,
                )
            )

    free_cash_flow = latest.get("free_cash_flow")
    if free_cash_flow is not None:
        recent_fcf = [item.get("free_cash_flow") for item in metrics[-2:]]
        if len(recent_fcf) == 2 and all(value is not None and value < 0 for value in recent_fcf):
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="free_cash_flow",
                    metric_cn="自由现金流",
                    polarity="negative",
                    severity="high",
                    value=free_cash_flow,
                    threshold="连续两年为负",
                    year=latest["year"],
                    title="自由现金流持续承压",
                    description="自由现金流连续两年为负，资本开支后现金留存持续承压。",
                    evidence=f"{latest['year']} 年自由现金流为 {free_cash_flow:.2f}，且最近两年持续为负。",
                    source_fields=["cash_flow_from_operating_activities", "cash_paid_for_asset"],
                    row=latest_row,
                )
            )
        elif free_cash_flow < 0:
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="free_cash_flow",
                    metric_cn="自由现金流",
                    polarity="negative",
                    severity="medium",
                    value=free_cash_flow,
                    threshold="最新一年为负",
                    year=latest["year"],
                    title="自由现金流转负",
                    description="自由现金流为负，资本开支对现金留存形成压力。",
                    evidence=f"{latest['year']} 年自由现金流为 {free_cash_flow:.2f}。",
                    source_fields=["cash_flow_from_operating_activities", "cash_paid_for_asset"],
                    row=latest_row,
                )
            )
        elif len(recent_fcf) == 2 and all(value is not None and value > 0 for value in recent_fcf):
            signals.append(
                make_signal(
                    category="cash_quality",
                    metric="free_cash_flow",
                    metric_cn="自由现金流",
                    polarity="positive",
                    severity="medium",
                    value=free_cash_flow,
                    threshold="连续为正",
                    year=latest["year"],
                    title="自由现金流保持为正",
                    description="自由现金流连续为正，资本开支后仍有现金结余。",
                    evidence=f"{latest['year']} 年自由现金流为 {free_cash_flow:.2f}，最近两年均为正。",
                    source_fields=["cash_flow_from_operating_activities", "cash_paid_for_asset"],
                    row=latest_row,
                )
            )

    debt_to_assets = latest.get("debt_to_assets")
    if debt_to_assets is not None:
        if debt_to_assets < 0.4:
            signals.append(
                make_signal(
                    category="solvency",
                    metric="debt_to_assets",
                    metric_cn="资产负债率",
                    polarity="positive",
                    severity="medium",
                    value=debt_to_assets,
                    threshold="< 40%",
                    year=latest["year"],
                    title="杠杆水平较稳健",
                    description="资产负债率处于较低水平，杠杆结构相对稳健。",
                    evidence=f"{latest['year']} 年资产负债率为 {debt_to_assets:.1%}。",
                    source_fields=["total_liabilities", "total_assets"],
                    row=latest_row,
                )
            )
        elif debt_to_assets > 0.75:
            signals.append(
                make_signal(
                    category="solvency",
                    metric="debt_to_assets",
                    metric_cn="资产负债率",
                    polarity="negative",
                    severity="high",
                    value=debt_to_assets,
                    threshold="> 75%",
                    year=latest["year"],
                    title="资产负债率偏高",
                    description="资产负债率处于较高水平，杠杆压力较大。",
                    evidence=f"{latest['year']} 年资产负债率为 {debt_to_assets:.1%}。",
                    source_fields=["total_liabilities", "total_assets"],
                    row=latest_row,
                )
            )
        elif debt_to_assets >= 0.6:
            signals.append(
                make_signal(
                    category="solvency",
                    metric="debt_to_assets",
                    metric_cn="资产负债率",
                    polarity="negative",
                    severity="medium",
                    value=debt_to_assets,
                    threshold="60% - 75%",
                    year=latest["year"],
                    title="杠杆水平上行",
                    description="资产负债率进入偏高区间，偿债安全边际收窄。",
                    evidence=f"{latest['year']} 年资产负债率为 {debt_to_assets:.1%}。",
                    source_fields=["total_liabilities", "total_assets"],
                    row=latest_row,
                )
            )

    current_ratio = latest.get("current_ratio")
    if current_ratio is not None:
        if current_ratio < 1.0:
            signals.append(
                make_signal(
                    category="solvency",
                    metric="current_ratio",
                    metric_cn="流动比率",
                    polarity="negative",
                    severity="high",
                    value=current_ratio,
                    threshold="< 1.0",
                    year=latest["year"],
                    title="短期偿债压力偏大",
                    description="流动比率低于 1，短期偿债能力承压。",
                    evidence=f"{latest['year']} 年流动比率为 {current_ratio:.2f}。",
                    source_fields=["current_assets", "current_liabilities"],
                    row=latest_row,
                )
            )
        elif current_ratio >= 1.5:
            signals.append(
                make_signal(
                    category="solvency",
                    metric="current_ratio",
                    metric_cn="流动比率",
                    polarity="positive",
                    severity="low",
                    value=current_ratio,
                    threshold=">= 1.5",
                    year=latest["year"],
                    title="流动性较充裕",
                    description="流动比率处于较好区间，短期流动性相对充裕。",
                    evidence=f"{latest['year']} 年流动比率为 {current_ratio:.2f}。",
                    source_fields=["current_assets", "current_liabilities"],
                    row=latest_row,
                )
            )

    quick_ratio = latest.get("quick_ratio")
    if quick_ratio is not None and quick_ratio < 0.7:
        signals.append(
            make_signal(
                category="solvency",
                metric="quick_ratio",
                metric_cn="速动比率",
                polarity="negative",
                severity="medium",
                value=quick_ratio,
                threshold="< 0.7",
                year=latest["year"],
                title="速动比率偏低",
                description="速动比率偏低，剔除存货后的流动性支持较弱。",
                evidence=f"{latest['year']} 年速动比率为 {quick_ratio:.2f}。",
                source_fields=["current_assets", "inventory", "current_liabilities"],
                row=latest_row,
            )
        )

    revenue_growth = latest.get("revenue_growth")
    receivable_growth = latest.get("receivable_growth")
    if revenue_growth is not None and receivable_growth is not None:
        gap = receivable_growth - revenue_growth
        if gap > 0.20:
            signals.append(
                make_signal(
                    category="operating_efficiency",
                    metric="receivable_growth_gap",
                    metric_cn="应收增速与收入增速差",
                    polarity="negative",
                    severity="high",
                    value=gap,
                    threshold="> 20pct",
                    year=latest["year"],
                    title="应收账款增长明显快于收入",
                    description="应收账款增速显著快于收入增速，回款压力上升。",
                    evidence=f"{latest['year']} 年应收增速 {receivable_growth:.1%}，收入增速 {revenue_growth:.1%}。",
                    source_fields=["bill_accts_receivable", "bill_receivable", "revenue", "operating_revenue"],
                    row=latest_row,
                    related_metrics=["receivable_growth", "revenue_growth"],
                )
            )
        elif gap > 0:
            signals.append(
                make_signal(
                    category="operating_efficiency",
                    metric="receivable_growth_gap",
                    metric_cn="应收增速与收入增速差",
                    polarity="negative",
                    severity="medium",
                    value=gap,
                    threshold="0 - 20pct",
                    year=latest["year"],
                    title="应收账款增速快于收入",
                    description="应收账款增速高于收入增速，需关注回款节奏。",
                    evidence=f"{latest['year']} 年应收增速 {receivable_growth:.1%}，收入增速 {revenue_growth:.1%}。",
                    source_fields=["bill_accts_receivable", "bill_receivable", "revenue", "operating_revenue"],
                    row=latest_row,
                    related_metrics=["receivable_growth", "revenue_growth"],
                )
            )
        else:
            signals.append(
                make_signal(
                    category="operating_efficiency",
                    metric="receivable_growth_gap",
                    metric_cn="应收增速与收入增速差",
                    polarity="positive",
                    severity="medium",
                    value=gap,
                    threshold="<= 0",
                    year=latest["year"],
                    title="应收增长与收入较匹配",
                    description="应收账款增速未快于收入增速，回款质量相对稳定。",
                    evidence=f"{latest['year']} 年应收增速 {receivable_growth:.1%}，收入增速 {revenue_growth:.1%}。",
                    source_fields=["bill_accts_receivable", "bill_receivable", "revenue", "operating_revenue"],
                    row=latest_row,
                    related_metrics=["receivable_growth", "revenue_growth"],
                )
            )

    inventory_growth = latest.get("inventory_growth")
    if revenue_growth is not None and inventory_growth is not None:
        gap = inventory_growth - revenue_growth
        if gap > 0.20:
            signals.append(
                make_signal(
                    category="operating_efficiency",
                    metric="inventory_growth_gap",
                    metric_cn="存货增速与收入增速差",
                    polarity="negative",
                    severity="high",
                    value=gap,
                    threshold="> 20pct",
                    year=latest["year"],
                    title="存货增长明显快于收入",
                    description="存货增速显著快于收入增速，库存压力上升。",
                    evidence=f"{latest['year']} 年存货增速 {inventory_growth:.1%}，收入增速 {revenue_growth:.1%}。",
                    source_fields=["inventory", "revenue", "operating_revenue"],
                    row=latest_row,
                    related_metrics=["inventory_growth", "revenue_growth"],
                )
            )
        elif gap > 0:
            signals.append(
                make_signal(
                    category="operating_efficiency",
                    metric="inventory_growth_gap",
                    metric_cn="存货增速与收入增速差",
                    polarity="negative",
                    severity="medium",
                    value=gap,
                    threshold="0 - 20pct",
                    year=latest["year"],
                    title="存货增速快于收入",
                    description="存货增速高于收入增速，需关注库存消化。",
                    evidence=f"{latest['year']} 年存货增速 {inventory_growth:.1%}，收入增速 {revenue_growth:.1%}。",
                    source_fields=["inventory", "revenue", "operating_revenue"],
                    row=latest_row,
                    related_metrics=["inventory_growth", "revenue_growth"],
                )
            )

    receivable_turnover = latest.get("receivable_turnover")
    previous_receivable_turnover = previous.get("receivable_turnover")
    if receivable_turnover is not None and previous_receivable_turnover is not None and receivable_turnover < previous_receivable_turnover:
        signals.append(
            make_signal(
                category="operating_efficiency",
                metric="receivable_turnover",
                metric_cn="应收账款周转率",
                polarity="negative",
                severity="medium",
                value=receivable_turnover,
                threshold="较上年下降",
                year=latest["year"],
                title="应收周转放缓",
                description="应收账款周转率下降，回款效率走弱。",
                evidence=f"{latest['year']} 年应收周转率为 {receivable_turnover:.2f}，低于上年的 {previous_receivable_turnover:.2f}。",
                source_fields=["bill_accts_receivable", "bill_receivable", "revenue", "operating_revenue"],
                row=latest_row,
            )
        )

    inventory_turnover = latest.get("inventory_turnover")
    previous_inventory_turnover = previous.get("inventory_turnover")
    if inventory_turnover is not None and previous_inventory_turnover is not None and inventory_turnover < previous_inventory_turnover:
        signals.append(
            make_signal(
                category="operating_efficiency",
                metric="inventory_turnover",
                metric_cn="存货周转率",
                polarity="negative",
                severity="medium",
                value=inventory_turnover,
                threshold="较上年下降",
                year=latest["year"],
                title="存货周转放缓",
                description="存货周转率下降，库存周转效率走弱。",
                evidence=f"{latest['year']} 年存货周转率为 {inventory_turnover:.2f}，低于上年的 {previous_inventory_turnover:.2f}。",
                source_fields=["inventory", "cost_of_goods_sold"],
                row=latest_row,
            )
        )

    deduct_growth = latest.get("net_profit_deduct_non_recurring_pnl_growth")
    if deduct_growth is not None and deduct_growth < 0:
        signals.append(
            make_signal(
                category="earnings_quality",
                metric="net_profit_deduct_non_recurring_pnl_growth",
                metric_cn="扣非净利润增速",
                polarity="negative",
                severity="medium",
                value=deduct_growth,
                threshold="< 0%",
                year=latest["year"],
                title="扣非净利润下滑",
                description="扣非净利润同比下降，核心盈利表现承压。",
                evidence=f"{latest['year']} 年扣非净利润同比变动 {deduct_growth:.1%}。",
                source_fields=["net_profit_deduct_non_recurring_pnl"],
                row=latest_row,
            )
        )

    return _dedupe_and_sort(signals)


def detect_compound_signals(
    rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows or not metrics:
        return []

    latest = metrics[-1]
    previous = metrics[-2] if len(metrics) >= 2 else {}
    latest_row = rows[-1]
    signals: list[dict[str, Any]] = []

    revenue_growth = latest.get("revenue_growth")
    ocf_growth = latest.get("cash_flow_from_operating_activities_growth")
    cash_to_profit = latest.get("cash_to_profit")
    if revenue_growth is not None and revenue_growth > 0.10:
        cash_mismatch = (ocf_growth is not None and ocf_growth < 0) or (cash_to_profit is not None and cash_to_profit < 0.8)
        if cash_mismatch:
            severity = "high" if cash_to_profit is not None and cash_to_profit < 0.5 else "medium"
            evidence_parts = [f"{latest['year']} 年收入增长 {revenue_growth:.1%}"]
            if ocf_growth is not None:
                evidence_parts.append(f"经营现金流增长 {ocf_growth:.1%}")
            if cash_to_profit is not None:
                evidence_parts.append(f"净现比为 {cash_to_profit:.2f}")
            signals.append(
                make_signal(
                    category="earnings_quality",
                    metric="revenue_growth_vs_cash_flow",
                    metric_cn="收入增长与现金流匹配度",
                    polarity="negative",
                    severity=severity,
                    value={
                        "revenue_growth": revenue_growth,
                        "cash_flow_from_operating_activities_growth": ocf_growth,
                        "cash_to_profit": cash_to_profit,
                    },
                    threshold="收入增长但现金流恶化或净现比低于 0.8",
                    year=latest["year"],
                    title="收入增长与现金流不匹配",
                    description="收入增长与现金流表现不匹配，收入增长质量存疑。",
                    evidence="，".join(evidence_parts) + "。",
                    source_fields=["revenue", "operating_revenue", "cash_flow_from_operating_activities", "net_profit"],
                    row=latest_row,
                    signal_type="compound",
                    related_metrics=["revenue_growth", "cash_flow_from_operating_activities_growth", "cash_to_profit"],
                )
            )

    profit_growth = latest.get("net_profit_parent_company_growth")
    if profit_growth is not None and profit_growth > 0 and ocf_growth is not None and ocf_growth < 0:
        signals.append(
            make_signal(
                category="earnings_quality",
                metric="profit_growth_vs_cash_flow",
                metric_cn="利润增长与现金流匹配度",
                polarity="negative",
                severity="high" if ocf_growth < -0.10 else "medium",
                value={
                    "net_profit_parent_company_growth": profit_growth,
                    "cash_flow_from_operating_activities_growth": ocf_growth,
                },
                threshold="归母净利润增长且经营现金流下降",
                year=latest["year"],
                title="利润增长未同步转化为现金",
                description="利润增长未同步转化为经营现金流，利润质量需关注。",
                evidence=f"{latest['year']} 年归母净利润增长 {profit_growth:.1%}，经营现金流变动 {ocf_growth:.1%}。",
                source_fields=["net_profit_parent_company", "cash_flow_from_operating_activities"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["net_profit_parent_company_growth", "cash_flow_from_operating_activities_growth"],
            )
        )

    receivable_growth = latest.get("receivable_growth")
    inventory_growth = latest.get("inventory_growth")
    if (
        revenue_growth is not None
        and receivable_growth is not None
        and inventory_growth is not None
        and receivable_growth > revenue_growth
        and inventory_growth > revenue_growth
    ):
        severity = "high" if receivable_growth - revenue_growth > 0.20 or inventory_growth - revenue_growth > 0.20 else "medium"
        signals.append(
            make_signal(
                category="operating_efficiency",
                metric="working_capital_pressure",
                metric_cn="营运资本压力",
                polarity="negative",
                severity=severity,
                value={
                    "revenue_growth": revenue_growth,
                    "receivable_growth": receivable_growth,
                    "inventory_growth": inventory_growth,
                },
                threshold="应收与存货增速同时高于收入增速",
                year=latest["year"],
                title="营运资本占用加重",
                description="应收账款和存货同时快于收入增长，可能存在回款和库存双重压力。",
                evidence=(
                    f"{latest['year']} 年收入增速 {revenue_growth:.1%}，"
                    f"应收增速 {receivable_growth:.1%}，存货增速 {inventory_growth:.1%}。"
                ),
                source_fields=["bill_accts_receivable", "bill_receivable", "inventory", "revenue", "operating_revenue"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["revenue_growth", "receivable_growth", "inventory_growth"],
            )
        )

    gross_margin = latest.get("gross_margin")
    previous_gross_margin = previous.get("gross_margin")
    expense_pairs = [
        ("selling_expense_ratio", "销售费用率"),
        ("ga_expense_ratio", "管理费用率"),
        ("financing_expense_ratio", "财务费用率"),
    ]
    rising_expenses = [
        label
        for key, label in expense_pairs
        if latest.get(key) is not None and previous.get(key) is not None and latest.get(key) > previous.get(key)
    ]
    if gross_margin is not None and previous_gross_margin is not None and gross_margin < previous_gross_margin and rising_expenses:
        signals.append(
            make_signal(
                category="profitability",
                metric="gross_margin_vs_expense_ratio",
                metric_cn="毛利率与费用率组合",
                polarity="negative",
                severity="high",
                value={
                    "gross_margin": gross_margin,
                    "previous_gross_margin": previous_gross_margin,
                    "rising_expenses": rising_expenses,
                },
                threshold="毛利率下降且费用率上升",
                year=latest["year"],
                title="毛利率与费用率双重挤压",
                description="毛利率下降且费用率上升，盈利能力受到双重挤压。",
                evidence=(
                    f"{latest['year']} 年毛利率由 {previous_gross_margin:.1%} 降至 {gross_margin:.1%}，"
                    f"同时 {', '.join(rising_expenses)} 上升。"
                ),
                source_fields=["revenue", "operating_revenue", "cost_of_goods_sold", "selling_expense", "ga_expense", "financing_expense"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["gross_margin", "selling_expense_ratio", "ga_expense_ratio", "financing_expense_ratio"],
            )
        )

    debt_to_assets = latest.get("debt_to_assets")
    previous_debt_to_assets = previous.get("debt_to_assets")
    if (
        debt_to_assets is not None
        and previous_debt_to_assets is not None
        and debt_to_assets > previous_debt_to_assets
        and ocf_growth is not None
        and ocf_growth < 0
    ):
        signals.append(
            make_signal(
                category="solvency",
                metric="debt_to_assets_vs_cash_flow",
                metric_cn="杠杆与现金流匹配度",
                polarity="negative",
                severity="high",
                value={
                    "debt_to_assets": debt_to_assets,
                    "previous_debt_to_assets": previous_debt_to_assets,
                    "cash_flow_from_operating_activities_growth": ocf_growth,
                },
                threshold="资产负债率上升且经营现金流下降",
                year=latest["year"],
                title="杠杆与现金流压力同步上升",
                description="资产负债率上升且经营现金流下降，偿债安全边际下降。",
                evidence=(
                    f"{latest['year']} 年资产负债率由 {previous_debt_to_assets:.1%} 升至 {debt_to_assets:.1%}，"
                    f"经营现金流同比变动 {ocf_growth:.1%}。"
                ),
                source_fields=["total_liabilities", "total_assets", "cash_flow_from_operating_activities"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["debt_to_assets", "cash_flow_from_operating_activities_growth"],
            )
        )

    deduct_growth = latest.get("net_profit_deduct_non_recurring_pnl_growth")
    if profit_growth is not None and profit_growth > 0 and deduct_growth is not None and deduct_growth < 0:
        signals.append(
            make_signal(
                category="earnings_quality",
                metric="profit_vs_deducted_profit",
                metric_cn="归母净利润与扣非净利润匹配度",
                polarity="negative",
                severity="high",
                value={
                    "net_profit_parent_company_growth": profit_growth,
                    "net_profit_deduct_non_recurring_pnl_growth": deduct_growth,
                },
                threshold="归母净利润增长但扣非净利润下降",
                year=latest["year"],
                title="利润增长可持续性不足",
                description="归母净利润增长但扣非净利润下降，利润增长可能受到非经常性损益影响。",
                evidence=(
                    f"{latest['year']} 年归母净利润增长 {profit_growth:.1%}，"
                    f"扣非净利润变动 {deduct_growth:.1%}。"
                ),
                source_fields=["net_profit_parent_company", "net_profit_deduct_non_recurring_pnl"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["net_profit_parent_company_growth", "net_profit_deduct_non_recurring_pnl_growth"],
            )
        )

    if revenue_growth is not None and revenue_growth < 0 and inventory_growth is not None and inventory_growth > 0:
        signals.append(
            make_signal(
                category="operating_efficiency",
                metric="revenue_decline_vs_inventory",
                metric_cn="收入下滑与存货上升组合",
                polarity="negative",
                severity="high" if inventory_growth > 0.10 else "medium",
                value={
                    "revenue_growth": revenue_growth,
                    "inventory_growth": inventory_growth,
                },
                threshold="收入下降且存货上升",
                year=latest["year"],
                title="收入下滑叠加库存上升",
                description="收入下滑同时存货上升，可能存在需求走弱或库存积压风险。",
                evidence=f"{latest['year']} 年收入变动 {revenue_growth:.1%}，存货增长 {inventory_growth:.1%}。",
                source_fields=["revenue", "operating_revenue", "inventory"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["revenue_growth", "inventory_growth"],
            )
        )

    capex_intensity = latest.get("capex_intensity")
    free_cash_flow = latest.get("free_cash_flow")
    if capex_intensity is not None and capex_intensity >= 0.10 and free_cash_flow is not None and free_cash_flow < 0:
        signals.append(
            make_signal(
                category="cash_quality",
                metric="capex_vs_free_cash_flow",
                metric_cn="资本开支与自由现金流匹配度",
                polarity="negative",
                severity="high" if capex_intensity >= 0.15 else "medium",
                value={
                    "capex_intensity": capex_intensity,
                    "free_cash_flow": free_cash_flow,
                },
                threshold="高资本开支且自由现金流为负",
                year=latest["year"],
                title="资本开支对现金流形成压力",
                description="资本开支强度较高且自由现金流为负，扩张活动可能削弱现金流安全垫。",
                evidence=f"{latest['year']} 年资本开支强度为 {capex_intensity:.1%}，自由现金流为 {free_cash_flow:.2f}。",
                source_fields=["cash_paid_for_asset", "revenue", "operating_revenue", "cash_flow_from_operating_activities"],
                row=latest_row,
                signal_type="compound",
                related_metrics=["capex_intensity", "free_cash_flow"],
            )
        )

    return _dedupe_and_sort(signals)


def summarize_signals(signals: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    polarity_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}

    for signal in signals:
        category = signal["category"]
        item = categories.setdefault(
            category,
            {
                "category": category,
                "category_cn": CATEGORY_LABELS.get(category, category),
                "signal_count": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
            },
        )
        item["signal_count"] += 1
        item[signal["polarity"]] += 1
        polarity_counts[signal["polarity"]] = polarity_counts.get(signal["polarity"], 0) + 1
        severity_counts[signal["severity"]] = severity_counts.get(signal["severity"], 0) + 1

    return {
        "total_signals": len(signals),
        "categories": sorted(categories.values(), key=lambda item: item["signal_count"], reverse=True),
        "polarity_counts": polarity_counts,
        "severity_counts": severity_counts,
    }


def make_signal(
    *,
    category: str,
    metric: str,
    metric_cn: str,
    polarity: str,
    severity: str,
    value: Any,
    threshold: str,
    year: int,
    title: str,
    description: str,
    evidence: str,
    source_fields: list[str] | None = None,
    row: dict[str, Any] | None = None,
    signal_type: str = "single",
    confidence: str | None = None,
    related_metrics: list[str] | None = None,
) -> dict[str, Any]:
    source_fields = source_fields or []
    related_metrics = related_metrics or [metric]
    return {
        "id": f"{signal_type}_{category}_{metric}_{year}_{polarity}",
        "type": signal_type,
        "category": category,
        "category_cn": CATEGORY_LABELS.get(category, category),
        "metric": metric,
        "metric_cn": metric_cn,
        "polarity": polarity,
        "severity": severity,
        "value": value,
        "threshold": threshold,
        "year": year,
        "title": title,
        "description": description,
        "evidence": evidence,
        "confidence": confidence or _confidence_for_fields(row, source_fields),
        "source_fields": source_fields,
        "related_metrics": related_metrics,
    }


def _confidence_for_fields(row: dict[str, Any] | None, source_fields: list[str]) -> str:
    if not row:
        return "high"
    fields = row.get("fields", {})
    saw_fallback = False
    for field in source_fields:
        source = fields.get(field, {}).get("source")
        if source == "missing":
            return "low"
        if source in {"rqdata_factor", "annual_report"}:
            saw_fallback = True
    return "medium" if saw_fallback else "high"


def _recent_positive_streak(metrics: list[dict[str, Any]], key: str) -> int:
    streak = 0
    for item in reversed(metrics):
        value = item.get(key)
        if value is None or value <= 0:
            break
        streak += 1
    return streak


def _recent_negative_streak(metrics: list[dict[str, Any]], key: str) -> int:
    streak = 0
    for item in reversed(metrics):
        value = item.get(key)
        if value is None or value >= 0:
            break
        streak += 1
    return streak


def _dedupe_and_sort(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = {signal["id"]: signal for signal in signals}
    return sorted(
        deduped.values(),
        key=lambda item: (
            SEVERITY_RANK.get(item["severity"], 99),
            POLARITY_RANK.get(item["polarity"], 99),
            0 if item["type"] == "compound" else 1,
            item["category"],
            item["title"],
        ),
    )
