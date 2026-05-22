"""A-share news data sourcing.

Primary: Eastmoney Search API (免费，无需 API Key)
Fallback: Web search via DuckDuckGo/Wikipedia

rqdatac.news 需要额外付费许可，当前 license 无此权限。
"""

import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests

from .rqdata_config import init_rqdata
from .search import search
from backend.utils.ticker_rq import normalize_to_rq, extract_code

logger = logging.getLogger(__name__)

# Chinese financial media authority scores
_AUTHORITY_SCORES = {
    "证券时报": 0.95, "证券时报网": 0.95,
    "中国证券报": 0.95, "上海证券报": 0.95,
    "经济参考报": 0.90, "第一财经": 0.88, "第一财经日报": 0.88,
    "财新": 0.88, "财新网": 0.88,
    "界面新闻": 0.85, "界面": 0.85,
    "澎湃新闻": 0.82,
    "21世纪经济报道": 0.85,
    "每日经济新闻": 0.80,
    "经济观察报": 0.80,
    "中国基金报": 0.80,
    "36氪": 0.72,
    "证券之星": 0.70,
    "金融界": 0.68,
    "东方财富": 0.65, "东方财富网": 0.65,
    "同花顺": 0.62, "同花顺财经": 0.62,
    "新浪财经": 0.60, "新浪网": 0.60,
    "腾讯财经": 0.60, "腾讯网": 0.60,
    "网易财经": 0.58,
    "搜狐财经": 0.55,
}

_AUTHORITATIVE_DOMAINS = {
    "eastmoney.com", "sina.com.cn", "10jqka.com.cn", "cls.cn",
    "yicai.com", "caixin.com", "cninfo.com.cn",
    "sse.com.cn", "szse.cn", "csrc.gov.cn", "pbc.gov.cn",
    "stcn.com", "nbd.com.cn", "eeo.com.cn",
    "21jingji.com", "thepaper.cn",
}

_HIGH_IMPACT_KEYWORDS = {
    "业绩预告", "业绩快报", "预增", "预减", "扭亏",
    "立案", "调查", "处罚", "监管",
    "并购", "重组", "借壳", "定增",
    "减持", "增持", "回购", "质押",
    "分红", "送转", "配股",
    "涨停", "跌停", "异动",
    "中标", "合同", "订单",
    "退税", "补贴", "政策",
    "退市", "ST", "风险警示",
}

_MEDIUM_IMPACT_KEYWORDS = {
    "调研", "路演",
    "评级", "目标价",
    "产能", "投产", "扩产",
    "专利", "研发",
    "合作", "战略",
    "人事", "换届",
    "股权激励",
    "担保", "借款",
}


def get_stock_news(
    ticker: str,
    days: int = 7,
    max_results: int = 20,
    min_relevance: float = 0.0,
) -> list[dict[str, Any]]:
    """Fetch news for an A-share ticker.

    Primary: Eastmoney Search API (免费)
    Secondary: rqdatac.news (需额外许可)
    Fallback: web search

    Returns list of dicts with: title, time, source, url, sentiment, relevance
    """
    rq_ticker = normalize_to_rq(ticker)
    if not rq_ticker:
        return []

    # Primary: Eastmoney search API
    news = _fetch_eastmoney_news(rq_ticker, max_results)
    if news:
        return news

    # Secondary: try rqdatac news (if license permits)
    news = _fetch_rqdata_news(rq_ticker, days, max_results, min_relevance)
    if news:
        return news

    # Fallback to web search
    return _fetch_search_news(rq_ticker, max_results)


def _fetch_rqdata_news(
    ticker: str, days: int, max_results: int, min_relevance: float
) -> Optional[list[dict]]:
    """Fetch news via rqdatac.news.get_stock_news."""
    try:
        if not init_rqdata():
            return None

        try:
            import rqdatac
            import rqdatac_news
        except ImportError:
            logger.info("rqdatac_news not installed. Install with: pip install rqdatac_news")
            return None

        end = datetime.now()
        start = end - timedelta(days=days)

        df = rqdatac.news.get_stock_news(
            ticker,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )

        if df is None or df.empty:
            return None

        if hasattr(df, "index") and isinstance(df.index, type(df.index)):
            df = df.reset_index()

        results = []
        for _, row in df.iterrows():
            relevance = float(row.get("company_relevance", 1.0) or 1.0)
            if relevance < min_relevance:
                continue

            title = str(row.get("title", "") or "")
            if not title.strip():
                continue

            sentiment = int(row.get("news_emotion_indicator", 0) or 0)
            results.append({
                "title": title.strip(),
                "time": str(row.get("original_time", row.get("datetime", ""))),
                "source": str(row.get("source", "") or ""),
                "url": str(row.get("url", "") or ""),
                "sentiment": sentiment,  # -1 negative, 0 neutral, 1 positive
                "relevance": round(relevance, 4),
                "source_score": _AUTHORITY_SCORES.get(
                    str(row.get("source", "")).strip(), 0.5
                ),
            })

        results.sort(key=lambda x: (x["source_score"], x["relevance"]), reverse=True)
        return results[:max_results]
    except Exception as exc:
        logger.warning("rqdatac news failed for %s: %s", ticker, exc)
        return None


def _fetch_eastmoney_news(ticker: str, max_results: int) -> Optional[list[dict]]:
    """Fetch news via Eastmoney Search API (免费，无需API Key)."""
    code = extract_code(ticker) or ticker
    if not code:
        return None

    try:
        param = json.dumps({
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": min(max_results, 50),
                    "preTag": "",
                    "postTag": "",
                }
            }
        }, ensure_ascii=False, separators=(",", ":"))
        url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param={quote(param)}"

        # Use urllib (not requests) — requests.get may double-encode the URL
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()

        text = raw.decode("utf-8").strip()

        # Extract JSON from jQuery(...)
        if text.startswith("jQuery("):
            json_str = text[7:-1]  # remove "jQuery(" prefix and trailing ")"
        else:
            idx = text.index("(")
            json_str = text[idx + 1:text.rindex(")")]

        data = json.loads(json_str)
        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        if not articles:
            return None

        results = []
        for article in articles:
            title = str(article.get("title", "") or "").strip()
            if not title:
                continue
            source = str(article.get("mediaName", "") or "").strip()
            results.append({
                "title": title,
                "time": str(article.get("date", "") or ""),
                "source": source,
                "url": str(article.get("url", "") or ""),
                "sentiment": 0,
                "relevance": 0.5,
                "source_score": _AUTHORITY_SCORES.get(source, 0.5),
            })

        results.sort(key=lambda x: x["source_score"], reverse=True)
        return results[:max_results]
    except Exception as exc:
        logger.warning("eastmoney news failed for %s: %s", ticker, exc)
        return None


def _fetch_search_news(ticker: str, max_results: int) -> list[dict]:
    """Fallback: search the web for news about this stock."""
    code = extract_code(ticker) or ticker
    query = f"{code} 股票 新闻"

    try:
        result_text = search(query)
        if not isinstance(result_text, str) or len(result_text) < 50:
            return []

        # search() returns formatted text — extract URLs and titles via simple patterns
        news = []
        lines = result_text.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith(("=", "-", "🔍", "💡", "【")):
                continue
            # Line potentially has format: "N. Title...\n   URL"
            url_match = re.search(r"https?://[^\s\)\]]+", line)
            url = url_match.group(0) if url_match else ""
            # Extract a reasonable title
            title = re.sub(r"^\d+\.\s*", "", line).strip()
            title = re.sub(r"\s+https?://[^\s]+.*$", "", title).strip()
            title = title[:120]
            if not title or len(title) < 10:
                continue
            domain = _extract_domain(url)
            news.append({
                "title": title,
                "time": "",
                "source": domain or "search",
                "url": url,
                "sentiment": 0,
                "relevance": 0.5,
                "source_score": 0.3 if domain in _AUTHORITATIVE_DOMAINS else 0.1,
                "fallback": True,
            })

        return news[:max_results]
    except Exception as exc:
        logger.warning("Search news fallback failed: %s", exc)
        return []


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return ""


def score_news_article(article: dict) -> dict[str, Any]:
    """Score a news article for importance and relevance.

    Returns dict with: impact_score, source_reliability, is_actionable
    """
    title = (article.get("title") or "") + (article.get("text") or "")
    title_lower = title.lower()

    impact = 0.3  # base
    for kw in _HIGH_IMPACT_KEYWORDS:
        if kw in title:
            impact = 0.8
            break
    if impact < 0.8:
        for kw in _MEDIUM_IMPACT_KEYWORDS:
            if kw in title:
                impact = 0.55
                break

    source = article.get("source", "")
    reliability = _AUTHORITY_SCORES.get(source, 0.5)
    if source in _AUTHORITATIVE_DOMAINS:
        reliability = max(reliability, 0.6)

    return {
        "impact_score": round(impact, 2),
        "source_reliability": round(reliability, 2),
        "is_actionable": impact >= 0.55,
        "overall_score": round((impact * 0.6 + reliability * 0.4), 2),
    }


def get_top_news_for_ticker(ticker: str, days: int = 3, max_count: int = 10) -> list[dict]:
    """Get top impactful news for a ticker, scored and sorted."""
    articles = get_stock_news(ticker, days=days, max_results=max_count * 2)
    for a in articles:
        scoring = score_news_article(a)
        a.update(scoring)
    articles.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    return articles[:max_count]
