from __future__ import annotations

from pathlib import Path
from typing import Any

from .fields import FIELD_MAP


def render_markdown(result: dict[str, Any]) -> str:
    report = result["annual_report"]
    analysis = result["financial_analysis"]
    lines = [
        f"# {report.get('sec_name') or report['stock_code']} 年报智能体分析",
        "",
        "## 年报来源",
        f"- 股票代码：{report['stock_code']}",
        f"- 年报标题：{report['title']}",
        f"- PDF：{report['pdf_url']}",
        f"- MD&A 提取置信度：{result['mda']['confidence']}",
        "",
        "## 财务数据分析智能体",
        "### 积极信号",
        *[f"- {item}" for item in analysis["positive_signals"]],
        "",
        "### 消极信号",
        *[f"- {item}" for item in analysis["negative_signals"]],
        "",
        "### 数据说明",
        *[f"- {item}" for item in analysis["data_notes"]],
        "",
        "## 核心指标",
        "| 年份 | 营收 | 归母净利润 | 经营现金流 | 毛利率 | 收现比 | 净现比 | 资产负债率 | ROE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in analysis["metrics"]:
        lines.append(
            "| {year} | {revenue} | {np} | {ocf} | {gm} | {cr} | {cp} | {da} | {roe} |".format(
                year=metric["year"],
                revenue=_money(metric.get("revenue")),
                np=_money(metric.get("net_profit_parent_company")),
                ocf=_money(metric.get("cash_flow_from_operating_activities")),
                gm=_pct(metric.get("gross_margin")),
                cr=_num(metric.get("cash_to_revenue")),
                cp=_num(metric.get("cash_to_profit")),
                da=_pct(metric.get("debt_to_assets")),
                roe=_pct(metric.get("roe")),
            )
        )
    lines.extend(
        [
            "",
            "## 投资总监总结",
            result["investment_director"],
            "",
            "## 字段来源概览",
        ]
    )
    for row in result["financial_data"]:
        factor = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "rqdata_factor"]
        annual = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "annual_report"]
        missing = [FIELD_MAP[field].cn for field, item in row["fields"].items() if item["source"] == "missing"]
        lines.append(f"- {row['year']} 年：米筐因子回补 {len(factor)} 项，年报回退 {len(annual)} 项，缺失 {len(missing)} 项。")
    return "\n".join(lines) + "\n"


def write_report(markdown: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _money(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 100000000:.2f} 亿"


def _pct(value: float | None) -> str:
    return "" if value is None else f"{value:.1%}"


def _num(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
