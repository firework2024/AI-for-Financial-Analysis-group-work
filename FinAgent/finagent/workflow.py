from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .env import load_dotenv
from .fallback import apply_financial_fallbacks
from .financial_analysis import analyze_financials
from .llm import fundamental_narrative_analysis, mda_summary_agent
from .mda_analysis import enrich_financial_analysis_with_mda
from .pdf_text import extract_mda
from .report import build_annual_json_payload, render_markdown
from .report_format import write_report
from .rqdata_client import fetch_factor_fallbacks, fetch_financials, fetch_metric_factor_fallbacks
from .sina_finance import latest_annual_report, save_report_text
from .stock_utils import default_as_of


@dataclass
class WorkflowOptions:
    stock: str
    as_of: str | None = None
    years: int = 3
    output: str | None = None
    no_download_cache: bool = False
    workdir: str = "."


def run(options: WorkflowOptions) -> dict[str, Any]:
    from .progress import step, info, ok, warn, section, sub_section

    load_dotenv()
    root = Path(options.workdir)
    as_of_date = default_as_of(options.as_of)

    # ── 第 1 步：获取新浪财经年报 ──
    section("步骤 1/7：获取新浪财经年报")
    step("获取年报", f"股票: {options.stock}, 截止日: {as_of_date}")
    fetch_result = latest_annual_report(options.stock, as_of_date)
    report = fetch_result.report
    full_text = fetch_result.full_text
    if report.report_year is None:
        raise RuntimeError(f"无法从年报标题识别报告年份: {report.title}")
    info(f"找到年报: {report.title}")
    info(f"公司: {report.sec_name} ({report.stock_code})")
    info(f"报告年份: {report.report_year}")
    info(f"正文长度: {len(full_text):,} 字符")

    # ── 第 2 步：保存年报文本 ──
    section("步骤 2/7：保存年报文本")
    step("保存纯文本", f"{report.title}")
    text_stem = f"{report.stock_code}_{report.sec_name}_{report.report_year}年年度报告"
    text_path = save_report_text(full_text, root / "annual_reports", text_stem)
    text_size_kb = Path(text_path).stat().st_size / 1024
    ok(f"文本已保存 ({text_size_kb:.0f} KB): {text_path.name}")

    # ── 第 3 步：提取 MD&A ──
    section("步骤 3/7：提取 MD&A（管理层讨论与分析）")
    step("提取 MD&A")
    mda = extract_mda(full_text)
    info(f"MD&A 置信度: {mda.confidence}")
    info(f"MD&A 起始标题: {mda.start_heading}")
    info(f"MD&A 原始文本预览: {mda.raw_preview[:120]}...")

    # ── 第 4 步：获取财务数据 ──
    section("步骤 4/7：拉取财务数据（米筐 RQData）")
    step("获取 PIT 财务数据", f"回溯 {options.years} 年")
    fetched = fetch_financials(options.stock, report.report_year, options.years)
    info(f"米筐合约代码: {fetched.order_book_id}")
    info(f"获取季度数: {len(fetched.quarters)} ({', '.join(fetched.quarters)})")
    sub_section("字段级因子回补")
    factor_values = fetch_factor_fallbacks(fetched.order_book_id, report.report_year, options.years, as_of_date)
    info(f"因子回补涉及 {len(factor_values)} 个年份")
    metric_factor_values = fetch_metric_factor_fallbacks(fetched.order_book_id, report.report_year, options.years, as_of_date)
    info(f"指标因子回补涉及 {len(metric_factor_values)} 个年份")
    sub_section("执行字段级回退（年报文本 ↔ 米筐因子）")
    financial_data = apply_financial_fallbacks(fetched.rows, full_text, factor_values)
    info(f"财务数据行数: {len(financial_data)}")
    company_context = {
        "stock_code": report.stock_code,
        "sec_name": report.sec_name,
        "report_year": report.report_year,
        "order_book_id": fetched.order_book_id,
        "quarters": fetched.quarters,
    }

    # ── 第 5 步：财务分析 ──
    section("步骤 5/7：执行财务分析")
    step("规则引擎 + LLM 信号检测")
    financial_analysis = analyze_financials(financial_data, metric_factor_values, company_context)
    signals = financial_analysis.get("display_signals", [])
    positive = financial_analysis.get("positive_signals", [])
    negative = financial_analysis.get("negative_signals", [])
    risks = financial_analysis.get("key_risks", [])
    info(f"检测到 {len(signals)} 条展示信号")
    info(f"积极信号: {len(positive)} 条")
    info(f"消极信号: {len(negative)} 条")
    if risks:
        info(f"关键风险: {'; '.join(risks[:5])}")
    step("融合 MD&A 到财务分析")
    financial_analysis = enrich_financial_analysis_with_mda(financial_analysis, mda.mda_text)
    info("MD&A 交叉验证完成")

    # ── 第 6 步：经营与财务叙事 ──
    section("步骤 6/7：经营与财务叙事")
    step("MD&A 摘要生成")
    mda_brief = mda_summary_agent(mda.mda_text, company_context)
    info(f"MD&A 摘要: {mda_brief[:120]}...")
    step("基本面叙事合成", "整合 MD&A + 财务分析 + 公司上下文")
    narrative = fundamental_narrative_analysis(mda.mda_text, financial_analysis, company_context)
    info("经营与财务叙事完成")

    # ── 第 7 步：生成报告 ──
    section("步骤 7/7：生成输出报告")
    result = {
        "annual_report": report.to_dict() | {"local_text": str(text_path)},
        "mda": {
            "confidence": mda.confidence,
            "start_heading": mda.start_heading,
            "end_heading": mda.end_heading,
            "summary": mda_brief,
            "raw_preview": mda.raw_preview,
        },
        "financial_data": financial_data,
        "financial_analysis": financial_analysis,
        "fundamental_narrative": narrative,
    }

    output_path = Path(options.output) if options.output else root / "outputs" / f"{report.stock_code}_{report.report_year}_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    step("渲染 Markdown 报告", str(output_path))
    write_report(render_markdown(result, order_book_id=fetched.order_book_id), output_path)
    ok(f"Markdown 已写入 ({output_path.stat().st_size} 字节)")

    json_path = output_path.with_suffix(".json")
    step("序列化 JSON 数据", str(json_path))
    payload = build_annual_json_payload(
        result=result,
        order_book_id=fetched.order_book_id,
        output_markdown=str(output_path),
        output_json=str(json_path),
    )
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"JSON 已写入 ({json_path.stat().st_size} 字节)")

    result["output_markdown"] = str(output_path)
    result["output_json"] = str(json_path)

    try:
        from .datastore import save_annual_report_record
        from .datastore.annual_text import mda_storage_payload, merge_mda_meta

        step("持久化到本地 SQLite")
        mda_payload = mda_storage_payload(mda)
        save_annual_report_record(
            stock_code=report.stock_code,
            report_year=report.report_year,
            order_book_id=fetched.order_book_id,
            sec_name=report.sec_name,
            title=report.title,
            pdf_path=str(text_path),
            meta=report.to_dict(),
            financial_data=financial_data,
            mda_text=mda_payload["mda_text"],
            mda_meta=merge_mda_meta(
                mda_payload["mda_meta"],
                {"summary": mda_brief},
            ),
        )
        ok("SQLite 持久化完成")
    except Exception as e:
        warn(f"SQLite 持久化跳过: {e}")
    return result
