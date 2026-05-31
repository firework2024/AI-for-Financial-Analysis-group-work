"""对话网页搜索：意图识别 + 分域检索 + 权威/相关度综合排序。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from ..env import get_env, load_dotenv
from .rag import _tokenize

WEB_SEARCH_HINTS = (
    "新闻",
    "消息",
    "传闻",
    "舆情",
    "搜索",
    "搜一下",
    "搜一搜",
    "搜搜",
    "再搜",
    "联网",
    "网上",
    "互联网",
    "网页",
    "行业动态",
    "热点",
    "政策",
    "监管",
    "处罚",
    "公告",
    "资讯",
    "报道",
    "怎么看",
    "发生了什么",
    "东方财富",
    "同花顺",
    "巨潮",
    "cninfo",
    "找一下",
    "自己去",
    "你搜",
    "帮我搜",
    "去查",
    "查一下",
    "具体数据",
    "官网",
    "年报",
    "年度报告",
)

FOLLOWUP_HINTS = ("试试", "再搜", "搜搜", "再试试", "继续搜", "再查", "帮我找")

FINANCIAL_METRIC_HINTS = (
    "总资产",
    "资产总计",
    "资产负债",
    "资产负债率",
    "负债",
    "营收",
    "收入",
    "利润",
    "净利",
    "毛利率",
    "现金流",
    "净资产",
    "股本",
    "财务",
    "三表",
    "资产负债表",
    "分红",
    "每股收益",
    "净资产收益率",
)

QUOTE_HINTS = ("股价", "行情", "收盘", "最新价", "现价", "涨跌", "k线", "实时")

DISCLOSURE_HINTS = ("公告", "年报", "年度报告", "季报", "一季报", "半年报", "三季报", "披露", "巨潮", "cninfo", "临时公告")

NEWS_HINTS = ("新闻", "消息", "政策", "监管", "舆情", "传闻", "热点")

_USER_AGENT = "FinAgent/1.0 (+https://github.com/finagent)"

OFFICIAL_DOMAIN_SUFFIXES = (
    "gov.cn",
    "csrc.gov.cn",
    "pbc.gov.cn",
    "safe.gov.cn",
    "sse.com.cn",
    "szse.com.cn",
    "szse.cn",
    "bse.cn",
    "chinamoney.com.cn",
    "chinabond.com.cn",
    "neeq.com.cn",
)

FINANCIAL_DATA_DOMAINS = (
    "cninfo.com.cn",
    "data.eastmoney.com",
    "emweb.securities.eastmoney.com",
    "f10.eastmoney.com",
    "basic.10jqka.com.cn",
)

QUOTE_DOMAINS = (
    "quote.eastmoney.com",
    "qt.gtimg.cn",
    "finance.sina.com.cn",
    "stockpage.10jqka.com.cn",
)

FINANCIAL_MEDIA_SUFFIXES = (
    "caixin.com",
    "yicai.com",
    "cls.cn",
    "stcn.com",
    "cs.com.cn",
    "cnstock.com",
    "wallstreetcn.com",
    "hexun.com",
    "money.163.com",
    "wind.com.cn",
)

LOW_QUALITY_DOMAINS = {
    "sohu.com": 45,
    "tradingview.com": 40,
    "zhihu.com": 35,
    "toutiao.com": 35,
    "weibo.com": 30,
    "xiaohongshu.com": 30,
    "douyin.com": 30,
    "bilibili.com": 25,
    "tieba.baidu.com": 25,
    "blog.csdn.net": 20,
    "baike.baidu.com": 15,
}


@dataclass
class SearchIntent:
    financial_metric: bool = False
    stock_quote: bool = False
    disclosure: bool = False
    news: bool = False
    prefer_cninfo: bool = False
    prefer_eastmoney: bool = False
    labels: list[str] = field(default_factory=list)


def web_search_enabled() -> bool:
    load_dotenv()
    flag = str(get_env("FINAGENT_ENABLE_WEB_SEARCH", "true") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def web_search_configured() -> bool:
    return web_search_enabled()


def needs_web_search(query: str, *, recent_user_messages: list[str] | None = None) -> bool:
    if not web_search_enabled():
        return False
    q = str(query or "").lower()
    if any(hint in q for hint in WEB_SEARCH_HINTS):
        return True
    if any(h in q for h in DISCLOSURE_HINTS):
        return True
    if re.search(r"20\d{2}\s*年", q) and any(h in q for h in ("报", "营收", "净利润", "披露", "财务")):
        return True
    if any(h in q for h in FOLLOWUP_HINTS) and recent_user_messages:
        prior = " ".join(recent_user_messages[-4:]).lower()
        return any(
            h in prior
            for h in ("搜", "联网", "巨潮", "东方财富", "同花顺", "官网", "公告", "股价", "资产", "年报", "营收", "净利润")
        )
    return False


def search_web(
    query: str,
    *,
    max_results: int = 5,
    stock_code: str | None = None,
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return {"query": "", "provider": None, "results": [], "error": "empty_query"}
    if not web_search_enabled():
        return {"query": text, "provider": None, "results": [], "error": "web_search_disabled"}

    intent = detect_search_intent(text)
    plans = build_search_plans(text, stock_code=stock_code, intent=intent)
    limit = max(1, min(int(max_results), 8))
    merged: list[dict[str, Any]] = []
    providers: set[str] = set()

    for plan in plans[:3]:
        batch, provider = _run_search_plan(plan, fetch_limit=min(limit * 5, 15))
        if provider:
            providers.add(provider)
        merged.extend(batch)

    ranked = rank_search_results(merged, max_results=limit, query=text, intent=intent)
    return {
        "query": text,
        "provider": "+".join(sorted(providers)) if providers else None,
        "search_intent": intent.labels,
        "search_plans": [plan.query for plan in plans[:3]],
        "results": ranked,
        "ranked_by": "authority+relevance+intent",
    }


def detect_search_intent(query: str) -> SearchIntent:
    q = str(query or "").lower()
    intent = SearchIntent()
    if any(h in q for h in FINANCIAL_METRIC_HINTS):
        intent.financial_metric = True
        intent.labels.append("financial_metric")
    if any(h in q for h in QUOTE_HINTS):
        intent.stock_quote = True
        intent.labels.append("stock_quote")
    if any(h in q for h in DISCLOSURE_HINTS):
        intent.disclosure = True
        intent.prefer_cninfo = True
        intent.labels.append("disclosure")
    if any(h in q for h in NEWS_HINTS):
        intent.news = True
        intent.labels.append("news")
    if "巨潮" in q or "cninfo" in q:
        intent.prefer_cninfo = True
    if "东方财富" in q or "eastmoney" in q:
        intent.prefer_eastmoney = True
        intent.labels.append("eastmoney")
    if "同花顺" in q or "10jqka" in q:
        intent.labels.append("10jqka")
    if not intent.labels:
        intent.labels.append("general")
    return intent


def build_search_plans(query: str, *, stock_code: str | None, intent: SearchIntent) -> list["SearchPlan"]:
    from ..datastore.query import extract_report_year

    base = str(query or "").strip()
    code = stock_code or _extract_code(base)
    company = _guess_company_name(base, code)
    subject = " ".join(part for part in (company, code, base) if part).strip()
    report_year = extract_report_year(base)
    year_label = f"{report_year}年" if report_year else ""

    plans: list[SearchPlan] = []

    if intent.disclosure or report_year or "年报" in base or "年度报告" in base:
        plans.append(
            SearchPlan(
                f"{code or company} {year_label}年度报告 营业收入 净利润 site:cninfo.com.cn",
                prefer_official=True,
                intent=intent,
            )
        )
        if subject and subject != (code or company):
            plans.append(
                SearchPlan(
                    f"{subject} {year_label} site:cninfo.com.cn",
                    prefer_official=True,
                    intent=intent,
                )
            )
    if intent.disclosure or intent.prefer_cninfo:
        plans.append(SearchPlan(f"{subject} 公告 site:cninfo.com.cn", prefer_official=True, intent=intent))
    if intent.financial_metric:
        plans.append(SearchPlan(f"{subject} 总资产 资产负债表 site:cninfo.com.cn", prefer_official=True, intent=intent))
        plans.append(SearchPlan(f"{code or subject} 财务指标 site:data.eastmoney.com", prefer_official=False, intent=intent))
    if intent.stock_quote or intent.prefer_eastmoney:
        plans.append(SearchPlan(f"{code or subject} 最新收盘 site:quote.eastmoney.com", prefer_official=False, intent=intent))
    if intent.news:
        plans.append(
            SearchPlan(
                f"{subject} 新闻",
                prefer_official=True,
                intent=intent,
            )
        )

    if not plans:
        plans.append(SearchPlan(subject, prefer_official=_prefers_official(base), intent=intent))
    return _dedupe_plans(plans)


@dataclass
class SearchPlan:
    query: str
    prefer_official: bool = False
    intent: SearchIntent | None = None


def rank_search_results(
    results: list[dict[str, Any]],
    *,
    max_results: int,
    query: str = "",
    intent: SearchIntent | None = None,
) -> list[dict[str, Any]]:
    best_by_domain: dict[str, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        if not url:
            continue
        score, tier = score_result(url, title=title, snippet=snippet, query=query, intent=intent)
        domain = extract_domain(url)
        enriched = {
            **item,
            "authority_score": round(score, 1),
            "source_tier": tier,
            "domain": domain,
        }
        existing = best_by_domain.get(domain)
        if existing is None or enriched["authority_score"] > existing["authority_score"]:
            best_by_domain[domain] = enriched

    ranked = sorted(best_by_domain.values(), key=lambda row: row["authority_score"], reverse=True)
    return ranked[:max_results]


def score_result(
    url: str,
    *,
    title: str = "",
    snippet: str = "",
    query: str = "",
    intent: SearchIntent | None = None,
) -> tuple[float, str]:
    auth, tier = authority_score(url, title=title, snippet=snippet, intent=intent)
    rel = relevance_score(query, title, snippet)
    penalty = low_quality_penalty(url)
    total = auth * 0.55 + rel * 28 + penalty
    if tier == "community":
        total = min(total, 30.0)
    return total, tier


def authority_score(
    url: str,
    *,
    title: str = "",
    snippet: str = "",
    intent: SearchIntent | None = None,
) -> tuple[float, str]:
    domain = extract_domain(url)
    path = urlparse(url.lower()).path
    blob = f"{url} {title} {snippet}".lower()
    score = 42.0
    tier = "general"

    if domain.endswith("cninfo.com.cn") or "static.cninfo.com.cn" in domain:
        score, tier = 118.0, "official_disclosure"
    elif _domain_in(domain, FINANCIAL_DATA_DOMAINS):
        score, tier = 112.0, "financial_data"
    elif _domain_in(domain, QUOTE_DOMAINS):
        score, tier = 108.0, "quote_terminal"
    elif _matches_suffix(domain, OFFICIAL_DOMAIN_SUFFIXES):
        score, tier = 105.0, "official"
    elif _matches_suffix(domain, FINANCIAL_MEDIA_SUFFIXES):
        score, tier = 78.0, "financial_media"
    elif domain.endswith("eastmoney.com"):
        score, tier = 58.0, "portal"
    elif "sohu.com" in domain:
        score, tier = 22.0, "community"
    elif "zhihu.com" in domain:
        score, tier = 18.0, "community"
    elif any(part in domain for part in LOW_QUALITY_DOMAINS):
        score, tier = 20.0, "community"

    if intent:
        if intent.financial_metric and _domain_in(domain, FINANCIAL_DATA_DOMAINS + ("cninfo.com.cn",)):
            score += 18
        if intent.stock_quote and _domain_in(domain, QUOTE_DOMAINS):
            score += 16
        if intent.disclosure and "cninfo.com.cn" in domain:
            score += 20
        if intent.prefer_eastmoney and "eastmoney.com" in domain:
            score += 12
        if intent.news and tier == "financial_media":
            score += 8

    if any(k in blob for k in ("公告", "年度报告", "年报", "招股书", "临时公告", "资产负债表")):
        score += 10
    if any(k in blob for k in ("证监会", "交易所", "监管", "立案", "行政处罚")):
        score += 8
    if "/disclosure/" in path or "announcement" in path:
        score += 8
    if "f10" in path or "cwfx" in path or "zcfz" in path:
        score += 6

    return score, tier


def relevance_score(query: str, title: str, snippet: str) -> float:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    text = f"{title} {snippet}".lower()
    t_tokens = _tokenize(text)
    if not t_tokens:
        return 0.0
    overlap = len(q_tokens & t_tokens)
    score = overlap / (len(q_tokens) ** 0.5)
    for token in q_tokens:
        if len(token) >= 2 and token in text:
            score += 0.35
    return score


def low_quality_penalty(url: str) -> float:
    domain = extract_domain(url)
    for bad, weight in LOW_QUALITY_DOMAINS.items():
        if bad in domain:
            return -weight
    if "sohu.com/a/" in url.lower():
        return -20
    return 0.0


def extract_domain(url: str) -> str:
    host = urlparse(str(url or "").lower()).netloc
    if host.startswith("www."):
        host = host[4:]
    return host


def _run_search_plan(plan: SearchPlan, *, fetch_limit: int) -> tuple[list[dict[str, Any]], str | None]:
    api_key = _tavily_api_key()
    if api_key:
        try:
            return _search_tavily(plan.query, api_key, fetch_limit, plan=plan), "tavily"
        except Exception:
            pass
    try:
        return _search_duckduckgo(plan.query, fetch_limit), "duckduckgo"
    except Exception:
        return [], None


def _search_tavily(query: str, api_key: str, max_results: int, *, plan: SearchPlan) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }
    include_domains = _preferred_domains(plan.intent)
    if plan.prefer_official and include_domains:
        body["include_domains"] = include_domains[:12]

    response = requests.post("https://api.tavily.com/search", json=body, timeout=20)
    response.raise_for_status()
    payload = response.json()
    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or "")[:600],
            }
        )
    return results


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": "cn-zh"},
        headers={"User-Agent": _USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    html = response.text
    blocks = re.split(r'<div class="result results_links results_links_deep web-result">', html)
    results: list[dict[str, Any]] = []
    for block in blocks[1:]:
        title_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', block, re.S)
        if not title_match:
            continue
        url = _normalize_ddg_url(title_match.group(1))
        title = _strip_html(title_match.group(2))
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet[:600]})
        if len(results) >= max_results:
            break
    return results


def _preferred_domains(intent: SearchIntent | None) -> list[str]:
    domains = [
        "cninfo.com.cn",
        "data.eastmoney.com",
        "f10.eastmoney.com",
        "quote.eastmoney.com",
        "sse.com.cn",
        "szse.com.cn",
        "csrc.gov.cn",
        "caixin.com",
        "cls.cn",
        "stcn.com",
        "cs.com.cn",
        "10jqka.com.cn",
    ]
    if intent and intent.prefer_eastmoney:
        domains = ["quote.eastmoney.com", "data.eastmoney.com", "f10.eastmoney.com", *domains]
    return domains


def _prefers_official(query: str) -> bool:
    q = str(query or "")
    return any(h in q for h in DISCLOSURE_HINTS)


def _extract_code(text: str) -> str | None:
    match = re.search(r"\b([036]\d{5})\b", str(text or ""))
    return match.group(1) if match else None


def _guess_company_name(text: str, stock_code: str | None) -> str:
    mapping = {
        "300750": "宁德时代",
        "600519": "贵州茅台",
        "000001": "平安银行",
        "000002": "万科A",
    }
    if stock_code and stock_code in mapping:
        return mapping[stock_code]
    return ""


def _dedupe_plans(plans: list[SearchPlan]) -> list[SearchPlan]:
    seen: set[str] = set()
    unique: list[SearchPlan] = []
    for plan in plans:
        key = plan.query.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(plan)
    return unique


def _domain_in(domain: str, suffixes: tuple[str, ...]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") or domain.endswith(item) for item in suffixes)


def _matches_suffix(domain: str, suffixes: tuple[str, ...]) -> bool:
    return _domain_in(domain, suffixes)


def _tavily_api_key() -> str | None:
    key = get_env("TAVILY_API_KEY")
    return key.strip() if key and key.strip() else None


def _normalize_ddg_url(raw: str) -> str:
    href = unescape(str(raw or "")).strip()
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()
