"""章节 scope、去重、表格与 MD&A 集成的本地验证（供 validation_agent / revise 使用）。"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from .narrative_plan import (
    is_macro_section,
    is_operating_quality_section,
    section_kind_for_name,
)
from .peer_analysis import _dedupe
from .report_writing import peer_compare_table_writing_rule

CHART_QUALITY_REQUIREMENTS = [
    "每张图必须回答一个明确的分析问题，不画冗余或纯信息重复的图。",
    "同一种分析视角只保留最有解释力的一张图（例如价格走势用均线图就够了，无需同时画价格+收益）。",
    "优先使用能同时展示多个相关指标趋势的图表（如双轴图：股价 vs 资金流、PE vs 利润增速）。",
    "对于财务指标，尽量展示 3~5 年历史趋势并标注 CAGR 或近两年变动幅度。",
    "对于估值指标（PE/PB/PS），若数据充足应叠加历史百分位带（如 30%/70% 分位线），否则应在正文说明缺乏历史对比。",
    "不同量纲的指标禁止堆在同一柱状图；如需对比，可拆分为子图或使用双轴（左轴市值/右轴比率）。",
    "柱状图适用于离散事件（分红、股本变动）或少量分类对比；趋势数据优先用折线图。",
    "宏观利率图（Shibor、国债收益率）必须与目标股票的估值逻辑挂钩（如 DCF 折现率、股息率利差），否则不单独成图。",
    "自由现金流应搭配资本开支共同展示，以判断扩张效率。",
    "ROE 允许用杜邦分解图（净利率×周转率×权益乘数）替代单柱。",
    "两融余额图应同时展示融资余额与融券余额（双轴），突出杠杆结构。",
    "行业对比图必须同时显示目标股票与行业中位数/均值，不能只画个股绝对值。",
]

TABLE_QUALITY_REQUIREMENTS = [
    "section_writer 禁止在正文输出任何 Markdown 表格（| 列 |）；多年财务、技术指标等对比用句子或 - 列表，表格由系统 mechanical placement 插入。",
    "若正文出现 LLM 自画的 | 表格（含多年宽表、技术指标表、TTM 快照表），必须在 section_feedback 要求全部删除。",
    peer_compare_table_writing_rule(),
    "系统机械插入的「表·同行横向坐标」「表·行业横向坐标」「表·行业估值对比」等不得再在正文逐条重复数值；正文只保留一句定性判断。",
    "禁止在正文重复系统「表·xxx」机械表内容；同一表头不得跨章重复出现。",
]

SECTION_DEDUP_REQUIREMENTS = [
    "每一类分析只在一个主章节展开：宏观利率→宏观利率背景；两融/资金流→资金与交易结构；估值倍数→基本面与估值；盈利/同行→经营质量；量价→量价与技术面；风险汇总→综合风险与数据局限。",
    "「宏观利率背景」只写 Shibor/国债/无风险利率及其与目标股股息率、PE 或负债率的逻辑联系，禁止重复两融余额、营收利润、同行对比表格等已在其他章节展开的内容。",
    "若两章出现相同数据点或高度相似段落，必须在 structural_feedback 标明 keep_in（保留章节）与 rewrite_sections（需删重复并重写的章节），并在 section_feedback 给出具体删改方向。",
    "「综合风险与数据局限」只做风险与数据缺口汇总，不得大段复述前面章节的分析段落。",
    "MD&A 基本业务/业务发展：经营质量章可展开管理层解释与勾稽；其他章只引用 1–2 句支撑本节量化结论，禁止各章大段复制相同 MD&A 原文。",
    "全报告禁止跨章重复同一张 Markdown 表（相同表头或相同「表·xxx」标题）；同一表头不得在宏观/资金/基本面/量价章各出现一次。",
]

SECTION_SCOPE_REQUIREMENTS = [
    "量价/技术章（kind=market）：只允许价格、均线、成交量、换手率、RSI/MACD、累计收益、回撤；禁止 PE/PB/PS、股息率、市值、营收/利润/现金流、两融、Shibor/国债及基本面/估值图。",
    "宏观利率章（kind=macro）：只允许 Shibor、国债曲线、期限利差、股息率与无风险利率利差、负债率对融资成本的一句话；禁止融资余额/两融表格与段落、禁止营收/利润/现金流/存货多年表。",
    "资金章（kind=capital）：只写两融、成交、股本、分红记录；禁止 Shibor/国债大段分析与营收利润表。",
    "估值/经营质量章：不得复述量价均线或两融余额细节；同行对比数值只进机械表。",
    "验证发现 scope 或 duplicate_table 违规时，必须在 section_feedback 与 structural_feedback.rewrite_sections 中点名需删段落/表头，revise_agent 必须整段删除而非改写措辞。",
]

MDA_INTEGRATION_REQUIREMENTS = [
    "若 data_inventory 或 JSON 含 annual_report_context / mda_business_brief，相关章节须引用管理层对基本业务、业务发展、行业或风险的表述，与量化指标形成论述支撑。",
    "经营质量章（kind=operating_quality）须使用 mda_crosswalk 做报表事实与 MD&A 对照，并给出独立判断；不得只罗列数字。",
    "量价/估值/资金/宏观/风险章至少 1 处将 MD&A 业务表述与本节数据挂钩；无 MD&A 时须说明局限，不得编造管理层口径。",
    "MD&A 引用用于解释与论证，不得替代系统机械表中的同行对比数值；勿设独立「MD&A 勾稽」章节。",
]

_VALIDATION_LLM_USER_TAIL = (
    "\n你可以通过 refinement_requests 要求系统再次调用 data_agent 或 chart_agent。"
    "\n如果图表低信息量、重复、量纲混乱或无法支撑正文结论，请在 chart_quality_review.delete/redraw 中列出，并把 refresh_charts 设为 true。"
    "\n如果需要更长回看期或补充已支持的数据源，请把 refresh_data 设为 true，并给出 lookback_days。"
    "\n必须返回 score/action_items/section_feedback/unsupported_claims/missing_data_notes/chart_quality_review/stock_relevance_review/refinement_requests/final_decision/structural_feedback。"
    "\nscore 为 0-100；section_feedback 是对象，key 是章节名，value 是修改建议列表。"
)

_MACRO_FORBIDDEN_CAPITAL = ("融资余额", "融券余额", "融资买入", "两融余额", "表 · 两融", "表·两融", "融资融券快照")
_MACRO_FORBIDDEN_OPERATING = ("归母净利润", "经营现金流", "营收（亿元）", "净现比", "存货增速", "负债合计（亿元）")
_MARKET_FORBIDDEN_EXTRA = ("融资余额", "融券余额", "两融", "Shibor", "国债", "无风险利率", "归母净利润", "经营现金流", "营收同比")

_PROSE_PEER_METRIC_LINE = re.compile(
    r"(毛利率|净利率|ROE|营收|利润|资产负债率|流动比率|速动比率|PE\s*\(|PB\s*\(|PS\s*\(|PE\(TTM\)|PB\(TTM\)|PS\(TTM\))"
    r".{0,24}[：:].{0,40}(行业中位数|行业均值|行业分位|P25|P75|四分位)"
)

_DISABLED_FACTOR_SNAPSHOT_HEADINGS = (
    "表 · 最新盈利质量因子",
    "表·最新盈利质量因子",
    "表 · 最新偿债与流动性",
    "表·最新偿债与流动性",
)

_TOPIC_MARKERS: dict[str, tuple[str, ...]] = {
    "macro": ("Shibor", "国债", "收益率曲线", "无风险利率", "折现率", "DCF", "期限利差", "同业拆借"),
    "capital": ("融资余额", "融券余额", "两融", "融资买入", "杠杆资金", "融资融券", "融券余量"),
    "valuation": ("PE(TTM)", "PB(TTM)", "PS(TTM)", "市盈率", "市净率", "市销率", "估值分位", "股息率(TTM)"),
    "operating": ("毛利率", "净利率", "ROE", "经营现金流", "归母净利润", "同行横向", "行业中位数", "营收同比"),
    "market": ("MA20", "MA60", "RSI", "换手率", "累计收益", "回撤", "收盘价", "成交量"),
    "risk": ("数据局限", "风险提示", "样本不足"),
}

_TOPIC_LABELS: dict[str, str] = {
    "macro": "宏观利率",
    "capital": "资金与两融",
    "valuation": "估值",
    "operating": "经营质量",
    "market": "量价与技术",
    "risk": "风险汇总",
}

_TOPIC_KIND_MAP = {
    "macro": "macro",
    "capital": "capital",
    "valuation": "valuation",
    "operating_quality": "operating",
    "market": "market",
    "risk": "risk",
}

_MDA_NARRATIVE_MARKERS = re.compile(
    r"(MD&A|管理层|年报披露|公司经营|主营业务|业务发展|经营情况|报告期内|公司表示|"
    r"发展战略|行业需求|竞争格局|风险因素|勾稽|mda_crosswalk|mda_business_brief)",
    re.IGNORECASE,
)


def _coerce_notes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def merge_section_feedback(*sources: dict[str, Any]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for source in sources:
        for section_name, value in source.items():
            notes = _coerce_notes(value)
            if notes:
                merged.setdefault(str(section_name), [])
                merged[str(section_name)] = _dedupe([*merged[str(section_name)], *notes])
    return merged


def merge_structural_feedback(*items: list[Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in items:
        for item in batch or []:
            if not isinstance(item, dict):
                continue
            key = "|".join(
                [
                    str(item.get("section") or ""),
                    str(item.get("issue") or ""),
                    str(item.get("keep_in") or ""),
                    str(item.get("suggestion") or "")[:120],
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def section_is_market_technical(section_name: str) -> bool:
    return any(token in section_name for token in ("量价", "技术", "趋势", "K线", "均线"))


def markdown_tables(content: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in str(content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            current.append(cells)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _table_text(rows: list[list[str]]) -> str:
    return " ".join(" ".join(row) for row in rows).lower()


def _table_covers_technical_metrics(rows: list[list[str]]) -> bool:
    text = _table_text(rows)
    markers = ("ma20", "ma60", "rsi", "20 日", "60 日", "收盘价", "收益率", "macd")
    return sum(1 for marker in markers if marker in text) >= 3


def _is_wide_technical_table(rows: list[list[str]]) -> bool:
    if len(rows) < 1:
        return False
    header = rows[0]
    if not header:
        return False
    if header[0] in {"维度", "统计维度"} and len(header) >= 4:
        return True
    if "维度" in header and any("ma" in cell.lower() or "rsi" in cell.lower() for cell in header[1:]):
        return True
    return False


def technical_table_section_review(sections: dict[str, str]) -> dict[str, list[str]]:
    feedback: dict[str, list[str]] = {}
    note = "禁止 LLM 自画 Markdown 表格；请删去正文中的 | 技术指标/量价表，改用句子或 - 列表表述。"
    for section_name, content in sections.items():
        if not section_is_market_technical(section_name):
            continue
        text = str(content or "")
        tables = markdown_tables(text)
        if not tables:
            continue
        technical_tables = [table for table in tables if _table_covers_technical_metrics(table)]
        if technical_tables or len(tables) >= 1:
            feedback.setdefault(section_name, []).append(note)
    return feedback


def _section_is_peer_compare_section(section_name: str, plan: dict[str, Any] | None = None) -> bool:
    if is_operating_quality_section(section_name, plan):
        return True
    return any(token in section_name for token in ("基本面", "估值"))


def section_has_prose_peer_metric_list(content: str) -> bool:
    text = str(content or "")
    if not text.strip():
        return False
    prose_stat_lines = [
        line
        for line in text.splitlines()
        if line.strip()
        and ("行业中位数" in line or "行业分位" in line or "行业均值" in line)
        and not line.strip().startswith("|")
    ]
    if len(prose_stat_lines) >= 2:
        return True
    if len(_PROSE_PEER_METRIC_LINE.findall(text)) >= 2:
        return True
    if any(heading in text for heading in ("同行横向坐标", "行业横向坐标", "行业估值对比")):
        numbered = sum(1 for line in prose_stat_lines if re.search(r"[：:]\s*\d", line))
        if numbered >= 2:
            return True
    return False


def peer_compare_table_section_review(sections: dict[str, str], *, plan: dict[str, Any] | None = None) -> dict[str, list[str]]:
    feedback: dict[str, list[str]] = {}
    for section_name, content in sections.items():
        if not _section_is_peer_compare_section(section_name, plan):
            continue
        text = str(content or "")
        if section_has_prose_peer_metric_list(text):
            feedback.setdefault(section_name, []).append(
                "同行/行业横向对比不应在正文逐条写「指标：本公司 x，行业中位数 y，分位 z」；"
                "请删去 prose 数值列举，只保留小标题下一句定性判断，具体对比交给系统机械表（表·同行横向坐标等）。"
            )
    return feedback


def factor_snapshot_table_section_review(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    feedback: dict[str, list[str]] = {}
    note = (
        "请删去正文中的 Markdown 表格（含「表·最新盈利质量因子」类自画表、多年宽表、TTM 快照表）；"
        "盈利/现金流/营运效率多年对比改用句子或 - 列表，勿输出 | 表格。"
    )
    for section_name, content in sections.items():
        if not is_operating_quality_section(section_name, plan) and not any(
            token in section_name for token in ("经营质量", "基本面", "财务")
        ):
            continue
        text = str(content or "")
        if any(heading in text for heading in _DISABLED_FACTOR_SNAPSHOT_HEADINGS):
            feedback.setdefault(section_name, []).append(note)
            continue
        if re.search(r"\|\s*维度\s*\|\s*毛利率\(TTM\)", text):
            feedback.setdefault(section_name, []).append(note)
    return feedback


def section_is_market_kind(section_name: str, plan: dict[str, Any] | None = None) -> bool:
    if section_kind_for_name(section_name, plan) == "market":
        return True
    return section_is_market_technical(section_name)


def section_mentions_capital_metrics(content: str) -> bool:
    return any(token in str(content or "") for token in ("融资余额", "融券余额", "融资买入", "两融余额", "融资融券"))


def section_mentions_operating_financials(content: str) -> bool:
    text = str(content or "")
    if any(token in text for token in _MACRO_FORBIDDEN_OPERATING):
        return True
    return bool(re.search(r"\|\s*指标\s*\|\s*202\d", text) and ("净利润" in text or "经营现金流" in text or "营收" in text))


def section_mentions_macro_rates(content: str) -> bool:
    return any(token in str(content or "") for token in ("Shibor", "国债", "无风险利率", "收益率曲线", "期限利差"))


def section_mentions_valuation(content: str) -> bool:
    text = str(content or "")
    forbidden = ("PE", "PB", "PS", "市盈率", "市净率", "市销率", "股息率", "估值分位", "估值吸引力", "估值匹配")
    return any(term in text for term in forbidden)


def section_mentions_peer_comparison(content: str, *, table_first: bool = False, operating_quality: bool = False) -> bool:
    text = str(content or "")
    peer_terms = ("同行", "横向", "同业", "同行横向坐标", "行业横向坐标")
    statistic_terms = ("分位", "中位数", "均值", "P25", "P75", "四分位")
    anomaly_terms = ("DBSCAN", "聚类", "噪声点", "样本不足", "有效同行", "中信")
    has_peer = any(term in text for term in peer_terms)
    if table_first or operating_quality:
        return has_peer or any(term in text for term in anomaly_terms)
    has_statistic = any(term in text for term in statistic_terms)
    has_anomaly_or_count = any(term in text for term in anomaly_terms)
    return has_peer and has_statistic and has_anomaly_or_count


def mechanical_table_captions(content: str) -> list[str]:
    return [match.strip() for match in re.findall(r"####\s*表\s*[·•]\s*([^\n]+)", str(content or ""))]


def _table_header_fingerprint(rows: list[list[str]]) -> str:
    if not rows or not rows[0]:
        return ""
    return "|".join(cell.strip().lower() for cell in rows[0])


def section_topic_key(section_name: str, plan: dict[str, Any] | None = None) -> str | None:
    kind = section_kind_for_name(section_name, plan)
    if kind in _TOPIC_KIND_MAP:
        return _TOPIC_KIND_MAP[kind]
    name = str(section_name or "")
    if is_macro_section(name, plan):
        return "macro"
    if any(token in name for token in ("资金", "两融", "融资", "融券")):
        return "capital"
    if any(token in name for token in ("估值", "基本面")) and not is_operating_quality_section(name, plan):
        return "valuation"
    if is_operating_quality_section(name, plan):
        return "operating"
    if any(token in name for token in ("量价", "技术", "趋势", "K线", "均线")):
        return "market"
    if any(token in name for token in ("风险", "局限")):
        return "risk"
    return None


def find_owner_section(topic: str, sections: dict[str, str], plan: dict[str, Any] | None = None) -> str | None:
    for name in sections:
        if section_topic_key(name, plan) == topic:
            return name
    return None


def section_scope_review(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_feedback: dict[str, list[str]] = {}
    structural_feedback: list[dict[str, Any]] = []

    def _flag(section_name: str, *, keep_in: str, note: str) -> None:
        section_feedback.setdefault(section_name, []).append(note)
        structural_feedback.append(
            {
                "section": section_name,
                "issue": "scope_violation",
                "keep_in": keep_in,
                "rewrite_sections": [section_name],
                "suggestion": note,
            }
        )

    capital_owner = find_owner_section("capital", sections, plan) or "资金与交易结构"
    valuation_owner = find_owner_section("valuation", sections, plan) or "基本面与估值"
    operating_owner = find_owner_section("operating", sections, plan) or "经营质量分析"
    macro_owner = find_owner_section("macro", sections, plan)
    market_owner = find_owner_section("market", sections, plan) or "量价与技术面"

    for section_name, content in sections.items():
        topic = section_topic_key(section_name, plan)
        text = str(content or "")

        if topic == "market" or section_is_market_kind(section_name, plan):
            if section_mentions_valuation(text):
                _flag(
                    section_name,
                    keep_in=valuation_owner,
                    note=(
                        f"「{section_name}」不得出现 PE/PB/PS、股息率、估值分位或估值图；"
                        f"估值内容只保留在《{valuation_owner}》。"
                    ),
                )
            if section_mentions_capital_metrics(text):
                _flag(
                    section_name,
                    keep_in=capital_owner,
                    note=f"「{section_name}」不得写两融/融资余额；该类内容只保留在《{capital_owner}》。",
                )
            if section_mentions_operating_financials(text):
                _flag(
                    section_name,
                    keep_in=operating_owner,
                    note=f"「{section_name}」不得写营收/利润/现金流多年表；财务分析保留在《{operating_owner}》或《{valuation_owner}》。",
                )
            if section_mentions_macro_rates(text):
                owner = macro_owner or "宏观利率背景"
                _flag(
                    section_name,
                    keep_in=owner,
                    note=f"「{section_name}」不得写 Shibor/国债；宏观利率只保留在《{owner}》。",
                )

        if topic == "macro" or is_macro_section(section_name, plan):
            if section_mentions_capital_metrics(text) or any(token in text for token in _MACRO_FORBIDDEN_CAPITAL):
                _flag(
                    section_name,
                    keep_in=capital_owner,
                    note=(
                        f"「{section_name}」禁止展开融资余额/两融段落与表格；"
                        f"两融细节只保留在《{capital_owner}》。宏观章仅保留利率与目标股股息率/负债率联系。"
                    ),
                )
            if section_mentions_operating_financials(text):
                _flag(
                    section_name,
                    keep_in=valuation_owner,
                    note=(
                        f"「{section_name}」禁止重复营收/利润/现金流/存货多年表；"
                        f"该类表格只保留在《{valuation_owner}》或《{operating_owner}》。"
                    ),
                )

        if topic == "capital" and macro_owner and section_mentions_macro_rates(text):
            hits = count_topic_markers(text, "macro")
            if hits >= 2:
                _flag(
                    section_name,
                    keep_in=macro_owner,
                    note=f"「{section_name}」不应复述 Shibor/国债分析（命中 {hits} 处），宏观内容保留在《{macro_owner}》。",
                )

    return {"section_feedback": section_feedback, "structural_feedback": structural_feedback}


def duplicate_table_review(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_feedback: dict[str, list[str]] = {}
    structural_feedback: list[dict[str, Any]] = []
    caption_map: dict[str, list[str]] = {}
    header_map: dict[str, list[str]] = {}

    for section_name, content in sections.items():
        text = str(content or "")
        for caption in mechanical_table_captions(text):
            caption_map.setdefault(caption, []).append(section_name)
        captions_in_section = mechanical_table_captions(text)
        if len(captions_in_section) != len(set(captions_in_section)):
            dupes = {c for c in captions_in_section if captions_in_section.count(c) > 1}
            note = f"本章重复出现相同机械表标题：{', '.join(sorted(dupes))}；请只保留一张或删去重复块。"
            section_feedback.setdefault(section_name, []).append(note)
        for table in markdown_tables(text):
            fp = _table_header_fingerprint(table)
            if len(fp) < 8:
                continue
            body = _table_text(table)
            if not any(token in body for token in ("融资余额", "经营现金流", "归母净利润", "shibor", "2025-", "2026-")):
                continue
            header_map.setdefault(fp, []).append(section_name)

    for caption, owners in caption_map.items():
        unique = list(dict.fromkeys(owners))
        if len(unique) <= 1:
            continue
        keep = next((name for name in sections if name in unique), unique[0])
        for section_name in unique:
            if section_name == keep:
                continue
            note = f"「表·{caption}」已在《{keep}》出现；请从《{section_name}》删除该表及重复解读，只保留 owner 章节。"
            section_feedback.setdefault(section_name, []).append(note)
            structural_feedback.append(
                {
                    "section": section_name,
                    "issue": "duplicate_table",
                    "keep_in": keep,
                    "rewrite_sections": [section_name],
                    "suggestion": note,
                }
            )

    for fp, owners in header_map.items():
        unique = list(dict.fromkeys(owners))
        if len(unique) <= 1:
            continue
        keep = next((name for name in sections if name in unique), unique[0])
        for section_name in unique:
            if section_name == keep:
                continue
            preview = fp if len(fp) <= 60 else fp[:60] + "…"
            note = (
                f"《{section_name}》与《{keep}》存在相同表头 Markdown 表（{preview}）；"
                f"请删除《{section_name}》中的重复表，数据保留在《{keep}》。"
            )
            section_feedback.setdefault(section_name, []).append(note)
            structural_feedback.append(
                {
                    "section": section_name,
                    "issue": "duplicate_table",
                    "keep_in": keep,
                    "rewrite_sections": [section_name],
                    "suggestion": note,
                }
            )

    return {"section_feedback": section_feedback, "structural_feedback": structural_feedback}


def _strip_section_prose(content: str) -> str:
    text = str(content or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*#{1,6}\s+.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*[^*]+\*\*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _section_sentences(content: str) -> list[str]:
    prose = _strip_section_prose(content)
    if not prose:
        return []
    parts = re.split(r"(?<=[。；;！!？?])\s+", prose)
    return [part.strip() for part in parts if len(part.strip()) >= 18]


def _sentence_similarity(left: str, right: str) -> float:
    a = re.sub(r"\s+", "", left)
    b = re.sub(r"\s+", "", right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def count_topic_markers(content: str, topic: str) -> int:
    text = _strip_section_prose(content)
    return sum(text.count(marker) for marker in _TOPIC_MARKERS.get(topic, ()))


def _pick_keep_section(
    left_name: str,
    right_name: str,
    left_topic: str | None,
    right_topic: str | None,
    macro_name: str | None,
) -> str:
    priority = {"market": 1, "operating": 2, "valuation": 3, "capital": 4, "macro": 5, "risk": 6}
    left_rank = priority.get(left_topic or "", 99)
    right_rank = priority.get(right_topic or "", 99)
    if left_topic == "macro" and right_topic != "macro" and right_topic is not None:
        return right_name
    if right_topic == "macro" and left_topic != "macro" and left_topic is not None:
        return left_name
    if left_rank <= right_rank:
        return left_name
    return right_name


def section_overlap_review(
    sections: dict[str, str],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_feedback: dict[str, list[str]] = {}
    structural_feedback: list[dict[str, Any]] = []
    names = list(sections.keys())
    macro_name = find_owner_section("macro", sections, plan)

    for section_name, content in sections.items():
        topic = section_topic_key(section_name, plan)
        text = str(content or "")
        if topic == "macro":
            for foreign in ("capital", "valuation", "operating", "market"):
                hits = count_topic_markers(text, foreign)
                if hits < 1:
                    continue
                owner = find_owner_section(foreign, sections, plan) or _TOPIC_LABELS[foreign]
                note = (
                    f"「{section_name}」重复了{_TOPIC_LABELS[foreign]}内容（命中 {hits} 处关键词），"
                    f"应删去；该类分析保留在《{owner}》。"
                    "宏观章只保留 Shibor/国债/无风险利率及与目标股股息率、PE 或负债率的联系。"
                )
                section_feedback.setdefault(section_name, []).append(note)
                structural_feedback.append(
                    {
                        "section": section_name,
                        "issue": "duplication",
                        "keep_in": owner,
                        "rewrite_sections": [section_name],
                        "suggestion": note,
                    }
                )
        elif topic == "risk":
            for foreign in ("macro", "capital", "valuation", "operating", "market"):
                hits = count_topic_markers(text, foreign)
                if hits < 4:
                    continue
                owner = find_owner_section(foreign, sections, plan) or _TOPIC_LABELS[foreign]
                note = f"风险章大段复述{_TOPIC_LABELS[foreign]}分析（命中 {hits} 处），应精简为风险要点，细节保留在《{owner}》。"
                section_feedback.setdefault(section_name, []).append(note)
                structural_feedback.append(
                    {
                        "section": section_name,
                        "issue": "duplication",
                        "keep_in": owner,
                        "rewrite_sections": [section_name],
                        "suggestion": note,
                    }
                )
        elif macro_name and section_name != macro_name:
            hits = count_topic_markers(text, "macro")
            if hits >= 2:
                note = (
                    f"删去 Shibor/国债/无风险利率等宏观复述（命中 {hits} 处）；"
                    f"宏观利率分析只保留在《{macro_name}》。"
                )
                section_feedback.setdefault(section_name, []).append(note)
                structural_feedback.append(
                    {
                        "section": section_name,
                        "issue": "duplication",
                        "keep_in": macro_name,
                        "rewrite_sections": [section_name],
                        "suggestion": note,
                    }
                )

    for i, left_name in enumerate(names):
        left_sentences = _section_sentences(sections.get(left_name, ""))
        if not left_sentences:
            continue
        left_topic = section_topic_key(left_name, plan)
        for right_name in names[i + 1 :]:
            right_sentences = _section_sentences(sections.get(right_name, ""))
            if not right_sentences:
                continue
            right_topic = section_topic_key(right_name, plan)
            duplicates = 0
            for left in left_sentences[:12]:
                for right in right_sentences[:12]:
                    if _sentence_similarity(left, right) >= 0.78:
                        duplicates += 1
                        break
            if duplicates < 2:
                continue
            keep_name = _pick_keep_section(left_name, right_name, left_topic, right_topic, macro_name)
            rewrite_name = right_name if keep_name == left_name else left_name
            note = (
                f"「{left_name}」与「{right_name}」存在 {duplicates} 处高度相似段落；"
                f"保留详细分析在《{keep_name}》，请重写《{rewrite_name}》删重复并补该章独有点。"
            )
            section_feedback.setdefault(rewrite_name, []).append(note)
            structural_feedback.append(
                {
                    "section": rewrite_name,
                    "issue": "duplication",
                    "keep_in": keep_name,
                    "rewrite_sections": [rewrite_name],
                    "related_section": left_name if rewrite_name == right_name else right_name,
                    "suggestion": note,
                }
            )

    return {"section_feedback": section_feedback, "structural_feedback": structural_feedback}


def structural_notes_for_section(structural_feedback: list[Any], section_name: str) -> list[str]:
    notes: list[str] = []
    for item in structural_feedback:
        if not isinstance(item, dict):
            continue
        rewrite_sections = [str(name) for name in (item.get("rewrite_sections") or []) if str(name).strip()]
        if section_name not in rewrite_sections and str(item.get("section") or "") != section_name:
            continue
        suggestion = str(item.get("suggestion") or "").strip()
        keep_in = str(item.get("keep_in") or "").strip()
        if suggestion:
            notes.append(suggestion if not keep_in else f"{suggestion}（保留在《{keep_in}》）")
    return notes


def rewrite_constraints_for_section(
    section_name: str,
    *,
    sections: dict[str, str],
    plan: dict[str, Any] | None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = sections.get(section_name, "")
    topic = section_topic_key(section_name, plan)
    forbidden_keywords: list[str] = []
    forbidden_tables: list[str] = []
    delete_blocks: list[str] = []
    keep_detail_in: list[str] = []

    if topic == "market" or section_is_market_kind(section_name, plan):
        forbidden_keywords.extend(["PE(TTM)", "PB(TTM)", "PS(TTM)", "股息率", "融资余额", "Shibor", "归母净利润", "经营现金流"])
        forbidden_tables.extend(["最新盈利质量因子", "最新估值因子", "两融", "同行横向坐标"])
    if topic == "macro" or is_macro_section(section_name, plan):
        forbidden_keywords.extend(["融资余额", "融资买入", "融券余额", "两融余额"])
        forbidden_tables.extend(["两融区间变动", "融资融券快照", "成交活跃度"])
        delete_blocks.extend(["融资成本与杠杆资金行为", "融资余额表格", "营收/利润/现金流多年表"])
        keep_detail_in.extend(
            name
            for name in (find_owner_section("capital", sections, plan), find_owner_section("valuation", sections, plan))
            if name
        )

    for item in (validation or {}).get("structural_feedback") or []:
        if not isinstance(item, dict):
            continue
        rewrites = [str(x) for x in (item.get("rewrite_sections") or []) if str(x).strip()]
        if section_name not in rewrites and str(item.get("section") or "") != section_name:
            continue
        suggestion = str(item.get("suggestion") or "").strip()
        if suggestion:
            delete_blocks.append(suggestion[:200])
        keep = str(item.get("keep_in") or "").strip()
        if keep:
            keep_detail_in.append(keep)

    if section_mentions_capital_metrics(content) and topic == "macro":
        delete_blocks.append("删除所有融资余额/两融相关段落与 Markdown 表")

    return {
        "forbidden_keywords": sorted(set(forbidden_keywords)),
        "forbidden_table_captions": sorted(set(forbidden_tables)),
        "delete_blocks": _dedupe(delete_blocks)[:6],
        "keep_detail_in": _dedupe(keep_detail_in)[:4],
    }


def revise_section_guidance(
    section_name: str,
    *,
    sections: dict[str, str],
    plan: dict[str, Any] | None,
    validation: dict[str, Any] | None = None,
) -> str:
    constraints = rewrite_constraints_for_section(section_name, sections=sections, plan=plan, validation=validation)
    parts = ["改写硬约束：必须整段删除验证意见点名的重复内容，不得仅改措辞保留相同数据表。"]
    if constraints.get("forbidden_keywords"):
        parts.append(f"本章禁止再出现关键词：{', '.join(constraints['forbidden_keywords'])}。")
    if constraints.get("forbidden_table_captions"):
        parts.append(f"禁止保留表标题含：{', '.join(constraints['forbidden_table_captions'])}。")
    if constraints.get("keep_detail_in"):
        parts.append(f"被删内容应已在《{'》《'.join(constraints['keep_detail_in'])}》展开，本章勿复述。")
    if constraints.get("delete_blocks"):
        parts.append("必须删除：" + "；".join(constraints["delete_blocks"][:4]))
    return " ".join(parts)


def market_writer_guidance() -> str:
    return (
        "本章节仅写量价与技术面：收盘价、均线、成交量、换手率、RSI/MACD、累计收益、回撤。"
        "禁止 PE/PB/PS、股息率、市值、营收/净利润/现金流、两融、Shibor/国债、同行对比及 valuation 类图表。"
        "禁止自画 Markdown 表格；技术指标用句子或 - 列表表述，系统会机械插入「表·技术指标快照」等表。"
    )


def section_scope_writer_guidance(section_name: str, plan: dict[str, Any] | None = None) -> str:
    if section_is_market_kind(section_name, plan):
        return market_writer_guidance()
    if is_macro_section(section_name, plan):
        return ""
    if section_kind_for_name(section_name, plan) == "capital":
        return "本章节只写两融、成交、股本、分红；禁止 Shibor/国债大段分析与营收利润多年表。"
    return ""


def industry_comparison_section_feedback(data: dict[str, Any], sections: dict[str, str]) -> dict[str, list[str]]:
    comparison = data.get("industry_comparison") if isinstance(data.get("industry_comparison"), dict) else {}
    metrics = comparison.get("metrics") if isinstance(comparison.get("metrics"), dict) else {}
    if not metrics:
        return {}
    feedback: dict[str, list[str]] = {}
    for section_name, content in sections.items():
        is_operating = is_operating_quality_section(section_name)
        if not is_operating and "基本面" not in section_name and "估值" not in section_name:
            continue
        text = str(content or "")
        if is_operating and section_mentions_valuation(text):
            feedback.setdefault(section_name, []).append("经营质量分析不应出现 PE/PB/PS、股息率、估值分位或估值吸引力判断。")
        if not section_mentions_peer_comparison(text, table_first=True):
            feedback[section_name] = [
                *feedback.get(section_name, []),
                "已有 industry_comparison 数据：请设置「同行横向坐标」/「行业横向坐标」小标题并引用系统机械对比表；"
                "勿在正文逐条写行业中位数/分位，数值由表格展示。",
            ]
    return feedback


def _section_uses_mda_narrative(content: str) -> bool:
    return bool(_MDA_NARRATIVE_MARKERS.search(str(content or "")))


def mda_integration_section_review(
    *,
    data: dict[str, Any],
    sections: dict[str, str],
    plan: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    from .section_prompts import mda_context_available

    if not mda_context_available(data):
        return {}
    feedback: dict[str, list[str]] = {}
    note = (
        "请结合 JSON 中 mda_business_brief 或 mda_crosswalk 的管理层表述（基本业务、业务发展、行业或风险），"
        "为本节量化结论提供 1–2 处论述支撑；经营质量章须做报表与 MD&A 对照并给出独立判断。"
    )
    for section_name, content in sections.items():
        kind = section_kind_for_name(section_name, plan)
        if kind not in {"operating_quality", "market", "valuation", "capital", "macro", "risk"}:
            if not any(token in section_name for token in ("基本面", "财务", "风险", "经营")):
                continue
        if _section_uses_mda_narrative(content):
            continue
        if kind == "operating_quality" or "经营质量" in section_name or "基本面" in section_name:
            feedback.setdefault(section_name, []).append(note)
        elif kind in {"market", "valuation", "capital", "macro", "risk"}:
            feedback.setdefault(section_name, []).append(note)
    return feedback


def coerce_string_list(value: Any) -> list[str]:
    return _coerce_notes(value)


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def data_inventory(data: dict[str, Any]) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict) and "row_count" in value:
            inventory[key] = {"row_count": value.get("row_count"), "columns": value.get("columns")}
        elif key in {"factor", "industry", "technical"}:
            inventory[key] = value
    return inventory


def chart_quality_review(*, data: dict[str, Any], charts: dict[str, str]) -> dict[str, Any]:
    delete: dict[str, str] = {}
    redraw: dict[str, str] = {}
    keep: dict[str, str] = {}
    if "latest_valuation_snapshot" in charts:
        delete["latest_valuation_snapshot"] = "市值、PE、PB、PS、股息率量纲差异过大，放在同一柱状图会误导比较。"
    if "latest_quality_snapshot" in charts:
        delete["latest_quality_snapshot"] = "盈利质量指标量纲不同，改以表格展示。"
    shares = pd.DataFrame(data.get("shares", {}).get("rows", []))
    if "share_structure" in charts and not shares.empty:
        cols = [col for col in ("total", "circulation_a", "free_circulation") if col in shares.columns]
        if cols and all(pd.to_numeric(shares[col], errors="coerce").nunique(dropna=True) <= 1 for col in cols):
            delete["share_structure"] = "股本结构在区间内基本不变，折线图信息量低，正文说明即可。"
    dividend = pd.DataFrame(data.get("dividend", {}).get("rows", []))
    if "dividend_history" in charts and len(dividend) < 3:
        delete["dividend_history"] = "分红样本点过少，图形解释力不足。"
    from .chart_catalog import DISABLED_INDUSTRY_BAR_CHART_KEYS

    for chart_key in DISABLED_INDUSTRY_BAR_CHART_KEYS:
        if chart_key in charts:
            delete[chart_key] = "同行横截面条形图量纲不可比，改由 Markdown 表格展示。"
    if "price_volume" in charts and "moving_averages" in charts:
        keep["price_volume"] = "量价结合展示交易活跃度。"
        keep["moving_averages"] = "均线图用于趋势判断，和量价图用途不同。"
    if len(charts) - len(delete) < 8:
        redraw["chart_count"] = "删除低质量图后图表不足 8 张，应优先补充非重复、可解释的两融/宏观/估值趋势图。"
    return {"requirements": CHART_QUALITY_REQUIREMENTS, "keep": keep, "redraw": redraw, "delete": delete}


def prune_charts(charts: dict[str, str], chart_review: dict[str, Any]) -> dict[str, str]:
    delete = chart_review.get("delete") if isinstance(chart_review.get("delete"), dict) else {}
    if not delete:
        return charts
    return {name: path for name, path in charts.items() if name not in delete}


_NARRATIVE_THESIS_HEADING = re.compile(r"^###\s+[^:\n：]+[：:]\S+", re.MULTILINE)
_NARRATIVE_SYNTHESIS = re.compile(r"(综合判断|的影响|格局|显示|表明|结论|动能|压力|支撑|反转|修复)")
_NARRATIVE_DATE_BULLET = re.compile(r"^[-*]\s.*?\d+月\d+日", re.MULTILINE)


def _narrative_structure_ok(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    if text.startswith("**核心结论**"):
        return True
    if _NARRATIVE_THESIS_HEADING.search(text):
        return True
    if _NARRATIVE_SYNTHESIS.search(text):
        prose_lines = [
            line
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith(("#", "-", "*", "|"))
        ]
        if len(prose_lines) >= 2:
            return True
    heading = re.search(r"^###\s+(.+)$", text, re.MULTILINE)
    if not heading:
        return bool(_NARRATIVE_SYNTHESIS.search(text))
    rest = text[heading.end() :].lstrip("\n")
    first_lines = [line.strip() for line in rest.splitlines() if line.strip()][:3]
    if first_lines and all(line.startswith(("-", "*")) for line in first_lines):
        dated_bullets = len(_NARRATIVE_DATE_BULLET.findall(text))
        if dated_bullets >= 2 and not _NARRATIVE_SYNTHESIS.search(text):
            return False
        return False
    return True


def section_narrative_review(*, sections: dict[str, str]) -> dict[str, dict[str, str]]:
    review: dict[str, dict[str, str]] = {}
    for name, content in sections.items():
        text = str(content or "").strip()
        if not text:
            review[name] = {"decision": "rewrite", "reason": "章节为空，无法评估叙事结构。"}
            continue
        if _narrative_structure_ok(text):
            review[name] = {"decision": "pass", "reason": "章节首段或首个小节标题已给出结论，并包含分析性表述。"}
        else:
            review[name] = {"decision": "rewrite", "reason": "章节以数据罗列为主，缺少结论先行的小结或影响判断。"}
    return review


def stock_relevance_review(*, data: dict[str, Any], sections: dict[str, str]) -> dict[str, Any]:
    target = str(data.get("order_book_id") or "")
    code = target.split(".")[0] if target else ""
    industry = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    industry_terms = [str(value) for key, value in industry.items() if "industry" in key and value]
    target_terms = [term for term in [target, code, "该股", "该公司", "目标股票", *industry_terms] if term]
    data_terms = [
        "close", "volume", "turnover", "PE", "PB", "PS", "market_cap", "dividend", "margin",
        "Shibor", "yield", "资金流", "换手", "分红", "两融", "股本", "估值", "收益率", "图",
    ]
    generic_terms = ["宏观", "行业", "市场", "方法论", "一般而言", "整体来看", "通常", "投资者应"]
    review: dict[str, Any] = {}
    for name, content in sections.items():
        text = str(content or "")
        has_target = any(term in text for term in target_terms)
        has_data = any(term in text for term in data_terms)
        is_generic = any(term in text for term in generic_terms)
        if has_target and has_data:
            review[name] = {"decision": "pass", "reason": "章节同时引用目标股票或行业归属，并使用了目标股票数据/图表口径。"}
        elif has_data and not is_generic:
            review[name] = {"decision": "pass", "reason": "章节使用了目标股票数据口径，但建议在改写时更明确点名目标股票。"}
        else:
            review[name] = {
                "decision": "rewrite",
                "reason": f"本节缺少对 {target or '目标股票'} 的直接数据、图表或行业归属连接，容易变成泛泛分析。",
            }
    return review


def local_validation(
    *,
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    draft_markdown: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_items: list[str] = []
    chart_review = chart_quality_review(data=data, charts=charts)
    relevance_review = stock_relevance_review(data=data, sections=sections)
    narrative_review = section_narrative_review(sections=sections)
    if len(charts) < 8:
        action_items.append(f"图表数量只有 {len(charts)} 张，建议补充到至少 8 张。")
    for name, reason in chart_review.get("delete", {}).items():
        action_items.append(f"图表 {name} 信息含量不足或量纲不合适，建议删除或重画：{reason}")
    for name, review in relevance_review.items():
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 与目标股票关联不足，需要改写：{review.get('reason')}")
    for name, review in narrative_review.items():
        if review.get("decision") == "rewrite":
            action_items.append(f"章节 {name} 叙事结构需优化：{review.get('reason')}")
    for key in ("price", "factor_history", "capital_flow", "securities_margin", "dividend", "shares", "interbank_rate", "yield_curve"):
        value = data.get(key)
        if isinstance(value, dict) and int(value.get("row_count") or 0) == 0:
            action_items.append(f"{key} 没有返回可用行，需要在报告中说明数据局限。")
    industry_feedback = industry_comparison_section_feedback(data, sections)
    table_feedback = merge_section_feedback(
        technical_table_section_review(sections),
        peer_compare_table_section_review(sections, plan=plan),
        factor_snapshot_table_section_review(sections, plan=plan),
    )
    overlap_review = section_overlap_review(sections, plan=plan)
    scope_review = section_scope_review(sections, plan=plan)
    duplicate_review = duplicate_table_review(sections, plan=plan)
    section_feedback = merge_section_feedback(
        {},
        industry_feedback,
        table_feedback,
        overlap_review.get("section_feedback") if isinstance(overlap_review.get("section_feedback"), dict) else {},
        scope_review.get("section_feedback") if isinstance(scope_review.get("section_feedback"), dict) else {},
        duplicate_review.get("section_feedback") if isinstance(duplicate_review.get("section_feedback"), dict) else {},
    )
    structural_feedback = merge_structural_feedback(
        overlap_review.get("structural_feedback") if isinstance(overlap_review.get("structural_feedback"), list) else [],
        scope_review.get("structural_feedback") if isinstance(scope_review.get("structural_feedback"), list) else [],
        duplicate_review.get("structural_feedback") if isinstance(duplicate_review.get("structural_feedback"), list) else [],
    )
    for section_name, notes in industry_feedback.items():
        action_items.extend(f"章节 {section_name} 缺少同行横向比较：{note}" for note in notes)
    for section_name, notes in table_feedback.items():
        action_items.extend(f"章节 {section_name} 表格问题：{note}" for note in notes)
    for section_name, notes in scope_review.get("section_feedback", {}).items():
        action_items.extend(f"章节 {section_name} scope 违规：{note}" for note in notes)
    for section_name, notes in duplicate_review.get("section_feedback", {}).items():
        action_items.extend(f"章节 {section_name} 重复表：{note}" for note in notes)
    for item in structural_feedback:
        if isinstance(item, dict):
            suggestion = str(item.get("suggestion") or "").strip()
            if suggestion:
                action_items.append(f"章节去重：{suggestion}")
    unsupported = [token for token in ("Wind", "券商预测", "新闻", "管理层指引") if token in draft_markdown]
    return {
        "score": 80 if not unsupported and len(charts) >= 8 and not structural_feedback else 65,
        "action_items": action_items,
        "section_feedback": section_feedback,
        "structural_feedback": structural_feedback,
        "unsupported_claims": unsupported,
        "missing_data_notes": action_items,
        "chart_quality_review": chart_review,
        "stock_relevance_review": relevance_review,
        "section_narrative_review": narrative_review,
        "final_decision": "revise" if action_items or unsupported or structural_feedback else "pass",
        "refinement_requests": {
            "refresh_data": False,
            "refresh_charts": len(charts) < 8 or bool(chart_review.get("redraw")),
            "lookback_days": None,
            "reason": "图表数量不足或存在低质量图" if len(charts) < 8 or chart_review.get("redraw") else None,
        },
    }


def sanitize_validation(validation: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(validation) if isinstance(validation, dict) else {}
    result["score"] = int(_safe_float(result.get("score")) or fallback["score"])
    result["action_items"] = _dedupe([*coerce_string_list(fallback.get("action_items")), *coerce_string_list(result.get("action_items"))])
    result["unsupported_claims"] = coerce_string_list(result.get("unsupported_claims"))
    result["missing_data_notes"] = _dedupe([*coerce_string_list(fallback.get("missing_data_notes")), *coerce_string_list(result.get("missing_data_notes"))])
    chart_review = result.get("chart_quality_review")
    result["chart_quality_review"] = chart_review if isinstance(chart_review, dict) else fallback.get("chart_quality_review", {})
    relevance_review = result.get("stock_relevance_review")
    result["stock_relevance_review"] = relevance_review if isinstance(relevance_review, dict) else fallback.get("stock_relevance_review", {})
    feedback = result.get("section_feedback")
    result["section_feedback"] = merge_section_feedback(
        fallback.get("section_feedback") if isinstance(fallback.get("section_feedback"), dict) else {},
        feedback if isinstance(feedback, dict) else {},
    )
    decision = str(result.get("final_decision") or fallback["final_decision"]).lower()
    result["final_decision"] = decision if decision in {"pass", "revise", "block"} else "revise"
    if fallback.get("final_decision") == "revise" and result["section_feedback"]:
        result["final_decision"] = "revise"
    requests = result.get("refinement_requests")
    result["refinement_requests"] = requests if isinstance(requests, dict) else fallback.get("refinement_requests", {})
    structural = result.get("structural_feedback")
    result["structural_feedback"] = merge_structural_feedback(
        fallback.get("structural_feedback") if isinstance(fallback.get("structural_feedback"), list) else [],
        structural if isinstance(structural, list) else [],
    )
    if result["structural_feedback"]:
        result["final_decision"] = "revise"
    return result


def refinement_requests(validation: dict[str, Any]) -> dict[str, Any]:
    requests = validation.get("refinement_requests") if isinstance(validation.get("refinement_requests"), dict) else {}
    action_text = " ".join(coerce_string_list(validation.get("action_items")))
    refresh_charts = bool(requests.get("refresh_charts")) or "图表" in action_text
    refresh_data = bool(requests.get("refresh_data"))
    result = {
        "refresh_data": refresh_data,
        "refresh_charts": refresh_charts,
        "lookback_days": requests.get("lookback_days"),
        "reason": requests.get("reason") or action_text[:160],
    }
    return result if refresh_data or refresh_charts else {}


def finalize_validation_after_refinement(validation: dict[str, Any], charts: dict[str, str]) -> None:
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    has_relevance_rewrite = any(isinstance(item, dict) and item.get("decision") == "rewrite" for item in relevance.values())
    chart_review = validation.get("chart_quality_review") if isinstance(validation.get("chart_quality_review"), dict) else {}
    remaining_redraw = chart_review.get("redraw") if isinstance(chart_review.get("redraw"), dict) else {}
    unsupported = coerce_string_list(validation.get("unsupported_claims"))
    if len(charts) >= 8 and not has_relevance_rewrite and not remaining_redraw and not unsupported:
        validation["final_decision"] = "pass_after_revision"
        validation["score"] = max(int(_safe_float(validation.get("score")) or 0), 85)


def _numbered_rules(rules: list[str]) -> str:
    return "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(rules))


def validation_agent_system_prompt() -> str:
    return (
        "你是研报验证 Agent。只返回 JSON，不写 Markdown。\n"
        "你的任务是检查报告是否忠于已采集数据、是否遗漏重要图表解读、是否有应补充或应收敛的结论。\n"
        "你必须逐章节检查是否和目标股票直接相关；泛泛讲宏观、行业、市场或方法论但没有落到目标股票的数据、图表或结论的部分，必须要求改写。\n"
        "禁止要求补充 Wind、新闻、券商预测、管理层指引等本系统未采集数据。\n\n"
        "## 图表质量标准（必须逐条核对每张图）\n"
        + _numbered_rules(CHART_QUALITY_REQUIREMENTS)
        + "\n\n对每张图判断是否满足上述标准。\n"
        "不满足的，在 `chart_quality_review.delete` 或 `chart_quality_review.redraw` 中具体说明原因和修改方向。\n"
        "对于信息量可显著提升的图（如单指标折线图可改为双轴对比图、缺少历史分位的估值图），应放在 `redraw` 中，并给出具体建议（例如：'将 PE 和利润增速画在双轴图上'）。\n"
        "如果图表数量不足 8 张或存在大量低质量图，应在 `refinement_requests` 中将 `refresh_charts` 设为 true，并说明原因。\n\n"
        "## 表格质量标准（必须逐章节核对）\n"
        + _numbered_rules(TABLE_QUALITY_REQUIREMENTS)
        + "\n\n若任意章节正文出现 LLM 自画的 | 表格，必须在 section_feedback 要求删除并改为 prose/列表。"
        + "\n若经营质量/估值章节在「同行横向坐标」等小标题下逐条写行业中位数/分位，必须要求删 prose 数值、改由系统机械表展示。"
        + "\n\n## 章节去重与分工（重点）\n"
        + _numbered_rules(SECTION_DEDUP_REQUIREMENTS)
        + "\n\n必须逐对检查「宏观利率背景」与基本面/估值/资金/经营质量/风险章是否重复。"
        "重复时：在 structural_feedback 输出 keep_in、rewrite_sections、suggestion；"
        "并在 rewrite_sections 各章的 section_feedback 中要求删除重复段、只保留该章独有点。"
        + "\n\n## MD&A 与业务论述（重点）\n"
        + _numbered_rules(MDA_INTEGRATION_REQUIREMENTS)
        + "\n\n经营质量章缺 MD&A/管理层对照、或其他有 mda_business_brief 的章完全未引用业务表述时，"
        "须在 section_feedback 要求补充论述支撑。"
        + "\n\n## 章节 scope 硬约束（重点）\n"
        + _numbered_rules(SECTION_SCOPE_REQUIREMENTS)
        + "\n\n## 跨章重复表（重点）\n"
        "逐章检查是否存在与其它章相同表头或相同「表·标题」的 Markdown 表；"
        "若 local_duplicate_table_review 有命中，必须在 rewrite_sections 中要求删除重复表，只保留 owner 章节。"
        + "\n\n## 整体报告质量要求\n"
        "除了逐图审核外，你还需要从整体视角评估报告的可读性和逻辑连贯性：\n"
        "1. **图文布局**：图表不应全部挤在「可视化」章节，应尽量分散到对应分析段落附近（例如在量价分析段插入价格图，在资金流段插入资金图）。\n"
        "2. **章节衔接**：相邻章节之间是否有过渡句或逻辑联系？例如「经营质量分析」之后是否自然引出「资金与交易结构」。\n"
        "3. **段落冗长**：是否有大段纯文字堆砌，缺乏小标题、列表或图表支撑？建议拆分为更易读的子段落。\n"
        "4. **结论先行**：每个章节开头应有小结或关键结论，避免让读者在段落中寻找要点。\n"
        "5. **图表引用**：正文中是否明确引用了图表（如“如图1所示”）？如果图表与正文脱节，应在 `action_items` 中要求补充引用。\n"
        "请在输出 JSON 中增加一个字段 `structural_feedback`，它是一个数组，每个元素包含 `section`（章节名）、`issue`（问题类型，如 `layout`、`cohesion`、`verbosity`）、`suggestion`（具体修改建议）。\n"
        "同时，如果多个章节内容重叠或可以合并，请在 `structural_feedback` 中建议合并，并给出合并后的标题。"
    )


def build_validation_llm_user_payload(
    *,
    plan: dict[str, Any],
    data: dict[str, Any],
    charts: dict[str, str],
    sections: dict[str, str],
    draft_markdown: str,
    fallback: dict[str, Any],
) -> str:
    payload = {
        "plan": plan,
        "target_stock": {"order_book_id": data.get("order_book_id"), "industry": data.get("industry")},
        "data_inventory": data_inventory(data),
        "chart_quality_requirements": CHART_QUALITY_REQUIREMENTS,
        "table_quality_requirements": TABLE_QUALITY_REQUIREMENTS,
        "local_table_review": merge_section_feedback(
            technical_table_section_review(sections),
            peer_compare_table_section_review(sections, plan=plan),
            factor_snapshot_table_section_review(sections, plan=plan),
            mda_integration_section_review(data=data, sections=sections, plan=plan),
            section_scope_review(sections, plan=plan).get("section_feedback", {}),
            duplicate_table_review(sections, plan=plan).get("section_feedback", {}),
        ),
        "local_chart_review": chart_quality_review(data=data, charts=charts),
        "section_dedup_requirements": SECTION_DEDUP_REQUIREMENTS,
        "section_scope_requirements": SECTION_SCOPE_REQUIREMENTS,
        "mda_integration_requirements": MDA_INTEGRATION_REQUIREMENTS,
        "local_overlap_review": section_overlap_review(sections, plan=plan),
        "local_scope_review": section_scope_review(sections, plan=plan),
        "local_duplicate_table_review": duplicate_table_review(sections, plan=plan),
        "local_stock_relevance_review": stock_relevance_review(data=data, sections=sections),
        "charts": charts,
        "sections": sections,
        "draft_markdown": draft_markdown[:14000],
        "local_checks": fallback,
    }
    return json.dumps(payload, ensure_ascii=False)[:22000] + _VALIDATION_LLM_USER_TAIL


def validation_markdown(validation: dict[str, Any] | None) -> list[str]:
    if not validation:
        return ["- 未运行验证 Agent。"]
    lines = [
        f"- 评分：{validation.get('score', 'N/A')}",
        f"- 结论：{validation.get('final_decision', 'N/A')}",
    ]
    if validation.get("refinement_performed"):
        lines.append(f"- 已执行补采/补图：{json.dumps(validation['refinement_performed'], ensure_ascii=False)}")
    for item in coerce_string_list(validation.get("action_items"))[:8]:
        lines.append(f"- 修改建议：{item}")
    relevance = validation.get("stock_relevance_review") if isinstance(validation.get("stock_relevance_review"), dict) else {}
    for name, review in list(relevance.items())[:8]:
        if isinstance(review, dict) and review.get("decision") == "rewrite":
            lines.append(f"- 目标股票相关性：{name} 需要改写，原因：{review.get('reason')}")
    for item in coerce_string_list(validation.get("unsupported_claims"))[:5]:
        lines.append(f"- 疑似未支撑表述：{item}")
    if len(lines) == 2:
        lines.append("- 未发现需要强制返工的问题。")
    return lines
