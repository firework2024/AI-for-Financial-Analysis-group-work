from finagent.chat.web_search import (
    authority_score,
    build_search_plans,
    detect_search_intent,
    needs_web_search,
    rank_search_results,
    score_result,
)


def test_authority_score_official_first():
    official, _ = authority_score("https://www.cninfo.com.cn/new/disclosure/detail?plate=sse")
    eastmoney_data, _ = authority_score("https://data.eastmoney.com/stockdata/300750.html")
    sohu, _ = authority_score("https://q.stock.sohu.com/cn/300750/index.shtml")
    zhihu, _ = authority_score("https://www.zhihu.com/question/123")
    caixin, _ = authority_score("https://www.caixin.com/finance/123.html")
    assert official > eastmoney_data > caixin > sohu > zhihu


def test_rank_search_results_promotes_official():
    raw = [
        {"title": "知乎讨论", "url": "https://www.zhihu.com/question/1", "snippet": "网友说法"},
        {"title": "巨潮公告", "url": "https://www.cninfo.com.cn/new/disclosure/detail", "snippet": "临时公告"},
        {"title": "财新报道", "url": "https://www.caixin.com/2024/story.html", "snippet": "监管动态"},
    ]
    ranked = rank_search_results(raw, max_results=3, query="300750 公告")
    assert ranked[0]["source_tier"] == "official_disclosure"
    assert ranked[0]["domain"] == "cninfo.com.cn"
    assert all("authority_score" in item for item in ranked)


def test_rank_search_results_limits_duplicate_domains():
    raw = [
        {"title": "公告1", "url": "https://www.cninfo.com.cn/a", "snippet": ""},
        {"title": "公告2", "url": "https://www.cninfo.com.cn/b", "snippet": ""},
        {"title": "财新", "url": "https://www.caixin.com/x", "snippet": ""},
    ]
    ranked = rank_search_results(raw, max_results=2)
    domains = [item["domain"] for item in ranked]
    assert domains.count("cninfo.com.cn") == 1


def test_sohu_ranks_below_cninfo_for_total_assets():
    intent = detect_search_intent("300750 总资产")
    raw = [
        {
            "title": "宁德时代总资产",
            "url": "https://q.stock.sohu.com/cn/300750/index.shtml",
            "snippet": "总资产7771.86亿",
        },
        {
            "title": "宁德时代2024年度报告",
            "url": "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=300750",
            "snippet": "总资产9748.28亿元",
        },
        {
            "title": "财务指标",
            "url": "https://data.eastmoney.com/stockdata/300750.html",
            "snippet": "总资产9748.28亿",
        },
    ]
    ranked = rank_search_results(raw, max_results=3, query="300750 总资产", intent=intent)
    assert ranked[0]["domain"] in {"cninfo.com.cn", "data.eastmoney.com"}
    assert "sohu.com" not in ranked[0]["domain"]


def test_detect_search_intent_and_plans():
    intent = detect_search_intent("去巨潮查300750总资产")
    assert intent.disclosure
    assert intent.financial_metric
    plans = build_search_plans("300750 总资产", stock_code="300750", intent=intent)
    joined = " ".join(plan.query for plan in plans)
    assert "site:cninfo.com.cn" in joined
    assert "site:data.eastmoney.com" in joined


def test_needs_web_search_followup():
    assert needs_web_search("试试", recent_user_messages=["你去巨潮搜一下总资产"])
    assert needs_web_search("再搜一下", recent_user_messages=["联网查公告"])
    assert not needs_web_search("试试")


def test_score_result_boosts_relevant_title():
    intent = detect_search_intent("300750 总资产")
    cninfo, _ = score_result(
        "https://www.cninfo.com.cn/new/disclosure/detail",
        title="宁德时代年度报告 总资产9748.28亿元",
        snippet="",
        query="300750 总资产",
        intent=intent,
    )
    sohu, _ = score_result(
        "https://q.stock.sohu.com/cn/300750/index.shtml",
        title="搜狐证券",
        snippet="总资产7771",
        query="300750 总资产",
        intent=intent,
    )
    assert cninfo > sohu
