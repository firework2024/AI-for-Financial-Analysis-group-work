"""研报具体分析写作规范与结构化证据包（供年报 / 多智能体章节共用）。"""

from __future__ import annotations

import re
from typing import Any

_ANALYTICAL_CORE = (
    "写作范式：章节必须以 **核心结论** 开头，其下单独 1 句（≤80 字）概括本节判断（含具体数字与日期），"
    "空一行后再写小标题与细节；全报告级执行摘要另由系统生成。"
    "每个判断必须可追溯至 JSON 字段或由其可推导（同比、CAGR、区间收益、简易估值倍数等须注明口径）；"
    "禁止空泛形容词替代数据；"
    "多年/多指标对比可用 Markdown 表格（| 列 |）或连贯句子与 - 列表；系统亦会机械插入「表·xxx」，勿与机械表重复展开。"
    "同行/行业横向比较只引用系统「表·同行横向坐标」等机械表结论，禁止正文逐条列举中位数与分位；"
    "解释「为什么」而不只描述「是什么」；不给买卖建议；"
    "禁止输出思考过程或 <thinking> 标签。"
)

_LOOSE_FUNDAMENTAL_WRITING = (
    "基于给定数据写 Markdown 正文：结论先行、数字具体；多年/多指标可用 Markdown 表格或列表呈现。"
    "小标题与段落顺序按公司实际情况自由组织，聚焦本轮最重要的矛盾（如增收不增利、现金流背离、结构迁移等），"
    "不必套用固定章节模板。"
    "有 MD&A 或 mda_crosswalk 时在叙述中自然对照管理层表述与报表数字，勿单独设「勾稽」章节。"
    "缺数据说明局限；勿输出字段来源概览、免责声明等附录（系统自动追加）。"
)

_LOOSE_SECTION_WRITING = (
    "本节正文：优先用 JSON 中的数字写清判断与因果；数据不足用 - 列表说明局限。"
    "可选用 **加粗短语** 作小标题，无合适切块时可连贯段落书写，勿套用固定小节清单。"
    "有 mda_business_brief 或 mda_crosswalk 时，在相关段落自然融入 MD&A 中基本业务、业务发展、行业与战略等管理层表述，"
    "与量化指标形成「数据事实 + 管理层解释 + 独立判断」三层论述，勿单独设勾稽章节。"
)

def llm_table_writing_rule() -> str:
    return (
        "可用 Markdown 表格（| 分隔行列）展示多年/多指标对比；"
        "系统会机械插入「表·xxx」时，正文只引用表结论一句，勿与机械表重复复述表内数字。"
    )

_MDA_KIND_WRITING: dict[str, str] = {
    "market": (
        "结合 mda_business_brief 中行业需求、产品结构或渠道变化，解释量价/均线/波动背后的业务动因；"
        "勿大段复述 MD&A，1–2 处点到即可。"
    ),
    "valuation": (
        "结合基本业务与盈利驱动（产品、区域、定价等 MD&A 表述），解释估值倍数高低的业务合理性；"
        "同行对比数值仍只引用机械表。"
    ),
    "capital": (
        "结合业务发展或市场关注度（MD&A），解释两融/成交/资金结构变化是否与经营叙事一致。"
    ),
    "macro": (
        "结合 MD&A 中资本开支、负债或融资安排，说明无风险利率/短端资金成本对该公司业务与财务的传导；"
        "勿重复其他章已写的盈利/两融段落。"
    ),
    "operating_quality": (
        "经营质量章须深度使用 mda_crosswalk 与 mda_business_brief："
        "在盈利、现金流、营运效率段落对照管理层解释与报表勾稽项，给出独立判断。"
    ),
    "risk": (
        "将 MD&A 风险披露与 reviewed_signals、articulation_checks 对照，说明哪些风险已被管理层承认、哪些仍存数据缺口。"
    ),
}

PEER_COMPARE_TABLE_HEADINGS = (
    "同行横向坐标",
    "行业横向坐标",
    "行业估值对比",
    "行业盈利能力对比",
    "行业成长与杠杆对比",
)


def peer_compare_table_writing_rule() -> str:
    """同行/行业横向对比：数值进机械表，正文只写定性一句。"""
    return (
        "凡 **同行横向坐标**、**行业横向坐标**、**行业估值对比** 等横向比较小标题下，"
        "本公司/行业中位数/均值/分位等对比数据只放在系统机械插入的 Markdown 竖表，"
        "正文该小标题下至多一句定性判断（如「经营质量全面占优」），"
        "禁止逐条写「毛利率 x%，行业中位数 y%，分位 z%」式列举。"
    )

FUNDAMENTAL_NARRATIVE_SECTION = "经营与财务分析"

_SECTION_LEAD_SKIP = (
    "执行摘要",
    "免责声明",
    "数据与工具",
    "验证 Agent",
    FUNDAMENTAL_NARRATIVE_SECTION,
    "投资总监分析",
)

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


def fundamental_narrative_system_prompt() -> str:
    return (
        "你是财务分析写作助手。"
        + _LOOSE_FUNDAMENTAL_WRITING
        + "优先依据逐年 metrics 表与 interpretation/key_findings 写连贯段落，"
        "不要逐条复述 reviewed_signals 标题。"
        + _ANALYTICAL_CORE
    )


def fundamental_narrative_writing_guide() -> str:
    return _LOOSE_FUNDAMENTAL_WRITING


def mda_business_writing_guide(section_name: str, *, section_kind: str | None = None) -> str:
    """各章节如何引用 MD&A 基本业务/业务发展表述（与章节 kind 对齐）。"""
    kind = str(section_kind or "").strip().lower()
    if not kind:
        from .narrative_plan import infer_section_kind

        kind = infer_section_kind(section_name) or ""
    hint = _MDA_KIND_WRITING.get(kind)
    if not hint:
        if any(token in section_name for token in ("基本面", "财务", "经营")):
            hint = _MDA_KIND_WRITING["operating_quality"]
        elif any(token in section_name for token in ("风险", "局限")):
            hint = _MDA_KIND_WRITING["risk"]
        else:
            hint = (
                "若 JSON 含 mda_business_brief，在论述中至少 1 处引用管理层对基本业务或业务发展的表述，"
                "支撑本节量化结论；无 MD&A 则说明数据局限。"
            )
    return f"MD&A 论述要求：{hint}"


def section_writing_guide(section_name: str, *, section_kind: str | None = None) -> str:
    """多智能体各章节写作补充指引（不重复 analytical_writing_core，无固定分节模板）。"""
    guide = _LOOSE_SECTION_WRITING + llm_table_writing_rule() + mda_business_writing_guide(section_name, section_kind=section_kind)
    if any(token in section_name for token in ("量价", "技术", "趋势", "K线", "均线")):
        guide += (
            "技术指标可用 Markdown 表格或句子表述；系统亦可能插入「表·技术指标快照」等机械表。"
            "禁止 PE/PB/PS、股息率、两融、Shibor/国债、营收利润/现金流及估值类图表。"
        )
    if any(token in section_name for token in ("基本面", "估值")):
        guide += peer_compare_table_writing_rule() + (
            "系统会机械插入「表·行业横向坐标」「表·行业估值对比」等竖表；引用表格结论即可。"
        )
    if "经营质量" in section_name or "财务" in section_name:
        guide += peer_compare_table_writing_rule() + (
            "系统会机械插入「表·同行横向坐标」「表·三表核心指标对比」等竖表。"
            "盈利/现金流/营运效率可用 Markdown 表格或机械表展示，正文写 MD&A 对照与独立判断。"
        )
    if any(token in section_name for token in ("宏观", "利率", "Shibor", "国债")):
        guide += (
            "无风险利率来自 JSON 的 macro_rate_recent（Shibor + 国债收益率曲线）；"
            "必须引用 macro_rate_brief 中的具体数值，并与目标股股息率/PE/负债率挂钩，"
            "禁止写「JSON 未提供利率」若 brief 中已有数据。"
            "禁止写融资余额/两融表格与段落，禁止重复营收/利润/现金流多年表。"
        )
    return guide


def section_writing_style_hint(section_name: str) -> str:
    """兼容 report_format 旧入口。"""
    return section_writing_guide(section_name)


def section_opening_conclusion_rule() -> str:
    return (
        "章节第一行必须是 **核心结论**，下一行单独 1 句结论（≤80 字，含数字）；"
        "结论句直接写内容，行前不要加冒号（勿写「：2025年…」）；"
        "然后再空一行写 **趋势概览** 等小标题与正文细节。"
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
                "metrics",
                "interpretation",
                "key_findings",
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
