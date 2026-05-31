"""研报具体分析写作规范与结构化证据包（供年报 / 多智能体章节共用）。"""

from __future__ import annotations

import re
from typing import Any

_ANALYTICAL_CORE = (
    "写作范式：章节必须以 **核心结论** 开头，其下单独 1 句（≤80 字）概括本节判断（含具体数字与日期），"
    "空一行后再写小标题、表格与细节；全报告级执行摘要另由系统生成。"
    "每个判断必须可追溯至 JSON 字段；禁止空泛形容词替代数据；"
    "涉及两个及以上时点/年份时必须用 Markdown 表格对比；"
    "解释「为什么」而不只描述「是什么」；不给买卖建议；"
    "禁止输出思考过程或 <thinking> 标签。"
)

_SECTION_LEAD_SKIP = ("执行摘要", "免责声明", "数据与工具", "验证 Agent", "投资总监分析")

_CONCLUSION_JUDGMENT = re.compile(
    r"(显示|表明|反映|面临|呈现|承压|偏弱|偏强|不足|矛盾|风险|改善|下行|上行|弱|强|倒挂|背离|放大|收缩|跌破|突破|转|缺|缺失|局限|下滑|暴增|持续)"
)

_PIT_SUMMARY_FIELDS = (
    ("revenue", "营收"),
    ("net_profit_parent_company", "归母净利润"),
    ("cash_flow_from_operating_activities", "经营现金流"),
    ("profit_from_operation", "营业利润"),
    ("total_liabilities", "负债合计"),
    ("inventory", "存货"),
)


def analytical_writing_core() -> str:
    return _ANALYTICAL_CORE


def annual_director_system_prompt() -> str:
    return (
        "你是投资总监。请基于 MD&A 与财务数据分析智能体输出，"
        "撰写克制、可追溯、具体量化的年度经营分析报告，不给买卖建议。"
        + _ANALYTICAL_CORE
    )


def annual_director_structure_guide() -> str:
    return (
        "必须按以下结构输出 Markdown 正文（可根据公司实际情况增删子节，但须保持「结论先行 + 分维拆解 + 表格对比」）：\n"
        "1. **核心经营表现概述** — 1 段，点明年度核心矛盾（如增收不增利、利润与现金流背离），附关键同比数字。\n"
        "2. **业务/收入结构变化** — 若 MD&A 或财务数据有分板块信息，用表格列营收、同比、毛利率变动；说明结构迁移含义。\n"
        "3. **利润与费用驱动** — 拆解亏损/利润变化；结合 MD&A 对原因的管理层表述，与报表数字对照（一致/矛盾/未披露）。\n"
        "4. **现金流质量** — 多年对比表（经营现金流、收现比、净现比、自由现金流）；解释与净利润背离，引用 MD&A 中现金流/回款说明。\n"
        "5. **营运资本与偿债** — 存货/应收 vs 收入增速、负债率、有息负债、流动/速动比率；与 MD&A 中库存/债务/流动性表述对照。\n"
        "6. **核心矛盾汇总** — Markdown 表格，仅列「矛盾维度」「具体表现」两列；"
        "禁止写「数据来源」列，正文亦勿用「（来源：…）」标注字段或信号名。\n"
        "7. **关注事项与数据局限** — bullet 列表；MD&A 未解释的关键勾稽项写入此处。\n"
        "8. **总结** — 1 段综合判断，不重复堆砌前文数字。\n"
        "禁止单独增设「MD&A与报表勾稽」章节；勾稽信息必须融入上述对应段落。"
    )


def section_writing_guide(section_name: str) -> str:
    """多智能体各章节写作指引（对齐年报深度分析范式）。"""
    common = _ANALYTICAL_CORE + " 用 **加粗短语** 作小标题；数据局限用 `-` 列表。"
    hints: dict[str, str] = {
        "量价与技术面": (
            "**趋势概览**（MA20/MA60、20/60 日收益、RSI，附具体日期与价位）；"
            "**近期异动**（列明具体交易日、涨跌幅、成交量/换手率 vs 均量）；"
            "**量价关系**（放量/缩量与价格方向的对应）；"
            "至少 1 个 Markdown 小表对比近 5–10 个关键交易日。"
        ),
        "基本面与估值": (
            "**盈利与成长**（TTM 因子 + 多年财报表；若有 mda_crosswalk 则在叙述中对照 MD&A 表述，不写独立勾稽章节）；"
            "**现金流与勾稽**（收现比/净现比/利润-现金流背离，结合 MD&A 解释）；"
            "**估值水平**（PE/PB/PS/股息率）；"
            "有 pit 或年报数据时必须输出多年对比表。"
        ),
        "资金与交易结构": (
            "**成交与活跃度**；**融资融券**（余额起止、峰值买入日、融券变化，附日期）；"
            "**股东与股本**；**分红与资金成本**；"
            "两融/成交须给出区间起止日期与具体金额。"
        ),
        "宏观利率背景": (
            "先 1 句结论；**短端利率**（Shibor 最新 vs 20 日前）；"
            "**收益率曲线**（1Y/10Y/30Y 最新值及期限利差）；"
            "须说明与目标股估值/股息率的逻辑联系，无联系则写数据局限。"
        ),
        "综合风险与数据局限": (
            "分块：**价格与波动**、**基本面与估值**、**杠杆与流动性**、**宏观与利率**、**数据局限**；"
            "每块 2–4 句带数字；只做汇总，禁止复制前文整段；数据局限用 bullet。"
        ),
    }
    extra = next((value for key, value in hints.items() if key in section_name), "")
    return f"{common} {extra}".strip()


def section_writing_style_hint(section_name: str) -> str:
    """兼容 report_format 旧入口。"""
    return section_writing_guide(section_name)


def section_opening_conclusion_rule() -> str:
    return (
        "章节第一行必须是 **核心结论**，下一行单独 1 句结论（≤80 字，含数字）；"
        "结论句直接写内容，行前不要加冒号（勿写「：2025年…」）；"
        "然后再空一行写 **趋势概览** 等小标题与表格。"
    )


def normalize_core_conclusion_markdown(text: str) -> str:
    """统一 **核心结论** 排版：标题一行、结论一句，去掉行首多余冒号。"""
    if not text or "**核心结论**" not in text:
        return text
    result = str(text)
    result = re.sub(r"\*\*核心结论\*\*[：:]\s*", "**核心结论**\n\n", result)
    result = re.sub(r"(\*\*核心结论\*\*\s*\n+)\s*[：:]+\s*", r"\1", result)
    result = re.sub(
        r"(\*\*核心结论\*\*\s*\n+)([^\n#|!\-].+)",
        lambda m: m.group(1) + _strip_leading_colon(m.group(2)),
        result,
    )
    return result


def _strip_leading_colon(line: str) -> str:
    return re.sub(r"^[：:\s]+", "", str(line or "").strip())


def multi_executive_summary_prompt() -> str:
    return (
        "写 1 段执行摘要 Markdown 正文（80–150 字），不要章节标题。"
        "第一句点明目标股当前核心矛盾（可用「但/然而/同时」连接两面）；"
        "全文至少 3 个具体数字（价格、收益率、估值、两融等，须来自 JSON）；"
        "不给买卖建议；禁止思考过程标签。"
    )


def ensure_section_lead_conclusion(text: str, section_name: str) -> str:
    """强制分析章节以 **核心结论** + 独立结论句开头。"""
    stripped = str(text or "").strip()
    if not stripped or stripped.startswith("_"):
        return text
    if any(skip in section_name for skip in _SECTION_LEAD_SKIP):
        return text
    if stripped.startswith("**核心结论**"):
        return _normalize_lead_conclusion_block(stripped)

    lead = _extract_lead_conclusion_sentence(stripped)
    if not lead:
        return text
    body = _remove_duplicate_lead(stripped, lead)
    return f"**核心结论**\n\n{_strip_leading_colon(lead)}\n\n{body}".strip()


def _normalize_lead_conclusion_block(text: str) -> str:
    match = re.match(r"^\*\*核心结论\*\*\s*\n+(.+?)(?:\n\n|\Z)", text, re.DOTALL)
    if not match:
        return text
    lead = _strip_leading_colon(match.group(1).strip())
    if "\n" in lead:
        first = _strip_leading_colon(lead.splitlines()[0].strip())
        rest_block = "\n".join(lead.splitlines()[1:]).strip()
        body = text[match.end() :].lstrip("\n")
        parts = [f"**核心结论**\n\n{first}"]
        if rest_block:
            parts.append(rest_block)
        if body:
            parts.append(body)
        return "\n\n".join(parts).strip()
    if _is_standalone_conclusion_line(lead):
        body = text[match.end() :].lstrip("\n")
        if body:
            return f"**核心结论**\n\n{lead}\n\n{body}".strip()
        return f"**核心结论**\n\n{lead}".strip()
    extracted = _strip_leading_colon(_extract_lead_conclusion_sentence(lead) or lead)
    body = text[match.end() :].lstrip("\n")
    return f"**核心结论**\n\n{extracted}\n\n{body}".strip()


def _extract_lead_conclusion_sentence(text: str) -> str | None:
    blocks = [part.strip() for part in re.split(r"\n\n+", text) if part.strip()]
    for block in blocks:
        if block.startswith("#") or block.startswith("|") or block.startswith("!["):
            continue
        if re.fullmatch(r"\*\*.+\*\*", block):
            continue
        if block.startswith("**") and "**" in block[2:]:
            inner = re.sub(r"^\*\*[^*]+\*\*\s*", "", block).strip()
            if inner:
                block = inner
        for sentence in _split_sentences(block):
            if _is_standalone_conclusion_line(sentence):
                return sentence.rstrip("。") + "。"
    return None


def _split_sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[。！？!?])", text) if part.strip()]


def _is_standalone_conclusion_line(line: str) -> bool:
    candidate = line.strip()
    if not candidate or candidate.startswith(("#", "|", "-", "*", "!", "`")):
        return False
    if re.fullmatch(r"\*\*.+\*\*", candidate):
        return False
    if not re.search(r"\d", candidate):
        return False
    if len(candidate) < 16 or len(candidate) > 220:
        return False
    return bool(_CONCLUSION_JUDGMENT.search(candidate))


def _remove_duplicate_lead(text: str, lead: str) -> str:
    normalized_lead = re.sub(r"\s+", "", lead.rstrip("。！？!?"))
    blocks = [part.strip() for part in re.split(r"\n\n+", text) if part.strip()]
    if not blocks:
        return text
    first = blocks[0]
    if re.fullmatch(r"\*\*.+\*\*", first) and len(blocks) > 1:
        first = blocks[1]
        blocks = blocks[1:]
    if re.sub(r"\s+", "", first.rstrip("。！？!?")) == normalized_lead:
        return "\n\n".join(blocks[1:]).strip() if len(blocks) > 1 else ""
    cleaned_first = first.replace(lead, "", 1).strip()
    if cleaned_first and cleaned_first != first:
        blocks[0] = cleaned_first
        return "\n\n".join(blocks).strip()
    return text


def local_multi_executive_summary(data: dict[str, Any], sections: dict[str, str]) -> str:
    """无 LLM 时的执行摘要占位。"""
    code = data.get("stock_code") or str(data.get("order_book_id", "")).split(".")[0]
    name = data.get("sec_name") or code
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    close = technical.get("latest_close")
    ret20 = technical.get("return_20d")
    pe = factor.get("pe_ratio_ttm")
    parts = [f"{name}（{code}）"]
    if close is not None and ret20 is not None:
        parts.append(f"最新收盘 {close} 元、近 20 日收益 {float(ret20):.1%}")
    if pe is not None:
        parts.append(f"PE(TTM) {float(pe):.2f} 倍")
    section_hint = "；".join(name for name in sections if sections.get(name))[:80]
    tail = f"详见 {section_hint} 等章节。" if section_hint else "详见各分析章节。"
    return (
        f"{'，'.join(parts)}。"
        f"短期量价与中期趋势、估值与资金结构存在分化，{tail}"
    )


def build_analytical_evidence(data: dict[str, Any], section_name: str) -> dict[str, Any]:
    """为章节 LLM 预打包结构化证据，减少遗漏时点/数值。"""
    evidence: dict[str, Any] = {
        "stock_code": data.get("stock_code"),
        "order_book_id": data.get("order_book_id"),
        "sec_name": data.get("sec_name"),
        "date_range": [data.get("start_date"), data.get("end_date")],
    }
    technical = data.get("technical") if isinstance(data.get("technical"), dict) else {}
    if technical:
        latest = technical.get("latest_close")
        ma20 = technical.get("ma20")
        ma60 = technical.get("ma60")
        evidence["price_snapshot"] = {
            **technical,
            "vs_ma20_pct": _pct_diff(latest, ma20),
            "vs_ma60_pct": _pct_diff(latest, ma60),
        }

    price_rows = _rows(data, "price")
    if price_rows:
        evidence["price_windows"] = {
            "last_5d": _window_stats(price_rows, 5, value_keys=("close", "volume", "total_turnover")),
            "last_20d": _window_stats(price_rows, 20, value_keys=("close", "volume")),
            "period_extremes": _period_extremes(price_rows, "close"),
            "recent_daily": price_rows[-10:],
        }

    margin_rows = _rows(data, "securities_margin")
    if margin_rows:
        evidence["margin_trajectory"] = _margin_trajectory(margin_rows)

    factor = data.get("factor") if isinstance(data.get("factor"), dict) else {}
    if factor:
        evidence["factor_snapshot"] = factor

    factor_hist = _rows(data, "factor_history")
    if factor_hist:
        evidence["factor_trend"] = {
            "first": factor_hist[0],
            "latest": factor_hist[-1],
            "sample_size": len(factor_hist),
        }

    pit = data.get("pit_financials") if isinstance(data.get("pit_financials"), dict) else {}
    pit_rows = pit.get("rows") if isinstance(pit.get("rows"), list) else []
    if pit_rows:
        evidence["pit_financials_table"] = summarize_pit_rows(pit_rows)

    annual_ctx = data.get("annual_report_context")
    if isinstance(annual_ctx, dict) and annual_ctx:
        evidence["annual_report_context"] = {
            key: annual_ctx.get(key)
            for key in (
                "report_year",
                "sec_name",
                "financial_years",
                "articulation_checks",
                "mda_crosswalk",
                "mda_summary",
                "reviewed_signals",
            )
            if annual_ctx.get(key) is not None
        }
        crosswalk = annual_ctx.get("mda_crosswalk")
        if isinstance(crosswalk, list) and crosswalk:
            evidence["mda_crosswalk_preview"] = crosswalk[:6]

    macro = {
        "interbank_latest": (_rows(data, "interbank_rate") or [None])[-1],
        "interbank_20d_ago": (_rows(data, "interbank_rate") or [None])[max(0, len(_rows(data, "interbank_rate") or []) - 21)],
        "yield_curve_latest": (_rows(data, "yield_curve") or [None])[-1],
    }
    if any(macro.values()):
        evidence["macro_snapshots"] = macro

    if "资金" in section_name or "风险" in section_name:
        evidence["capital_flow_summary"] = {
            k: v
            for k, v in (data.get("capital_flow") or {}).items()
            if k != "rows"
        }
        if _rows(data, "capital_flow"):
            evidence["capital_flow_recent"] = _rows(data, "capital_flow")[-8:]

    return evidence


def summarize_pit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year = row.get("year") or (str(row.get("quarter", ""))[:4] if row.get("quarter") else None)
        item: dict[str, Any] = {"year": year, "quarter": row.get("quarter")}
        for field, label in _PIT_SUMMARY_FIELDS:
            value = row.get(field)
            if value is not None:
                item[field] = value
                item[f"{field}_label"] = label
        if len(item) > 2:
            table.append(item)
    return table


def summarize_annual_financial_data(financial_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从年报 workflow 的 financial_data 提取逐年核心指标。"""
    rows: list[dict[str, Any]] = []
    for entry in financial_data:
        if not isinstance(entry, dict):
            continue
        year = entry.get("year")
        fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
        row: dict[str, Any] = {"year": year}
        for key in (
            "revenue",
            "net_profit_parent_company",
            "cash_flow_from_operating_activities",
            "gross_margin",
            "cash_to_revenue",
            "cash_to_profit",
            "debt_to_assets",
            "roe",
            "free_cash_flow",
        ):
            payload = fields.get(key)
            if isinstance(payload, dict) and payload.get("value") is not None:
                row[key] = payload.get("value")
            elif payload is not None:
                row[key] = payload
        if len(row) > 1:
            rows.append(row)
    return rows


def _rows(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if isinstance(value, dict):
        rows = value.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _pct_diff(latest: Any, base: Any) -> float | None:
    try:
        a = float(latest)
        b = float(base)
        if b == 0:
            return None
        return (a - b) / b
    except (TypeError, ValueError):
        return None


def _window_stats(rows: list[dict[str, Any]], window: int, *, value_keys: tuple[str, ...]) -> dict[str, Any]:
    segment = rows[-window:] if len(rows) >= window else rows
    if not segment:
        return {}
    first, last = segment[0], segment[-1]
    stats: dict[str, Any] = {
        "start_date": first.get("date"),
        "end_date": last.get("date"),
        "trading_days": len(segment),
    }
    for key in value_keys:
        if key in first and key in last:
            try:
                start_v = float(first[key])
                end_v = float(last[key])
                stats[f"{key}_start"] = start_v
                stats[f"{key}_end"] = end_v
                if start_v:
                    stats[f"{key}_change_pct"] = (end_v - start_v) / start_v
            except (TypeError, ValueError):
                pass
    return stats


def _period_extremes(rows: list[dict[str, Any]], value_key: str) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    worst: dict[str, Any] | None = None
    for row in rows:
        try:
            value = float(row.get(value_key))
        except (TypeError, ValueError):
            continue
        if best is None or value > float(best.get(value_key)):
            best = row
        if worst is None or value < float(worst.get(value_key)):
            worst = row
    return {"high": best, "low": worst}


def _margin_trajectory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    first, last = rows[0], rows[-1]
    peak_buy = max(
        rows,
        key=lambda row: float(row.get("buy_on_margin_value") or 0),
        default=last,
    )
    result: dict[str, Any] = {
        "start_date": first.get("date"),
        "end_date": last.get("date"),
        "margin_balance_start": first.get("margin_balance"),
        "margin_balance_end": last.get("margin_balance"),
        "short_selling_balance_end": last.get("short_selling_balance"),
    }
    if peak_buy:
        result["peak_buy_date"] = peak_buy.get("date")
        result["peak_buy_on_margin_value"] = peak_buy.get("buy_on_margin_value")
    return result
