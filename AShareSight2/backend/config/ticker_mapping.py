# -*- coding: utf-8 -*-
"""Centralized A-share Ticker Mapping and Extraction."""

import re
from typing import Dict

# A-share ticker <-> Chinese company name mapping
COMPANY_MAP: Dict[str, str] = {
    # 上海主板 (XSHG)
    '600519.XSHG': '贵州茅台', '贵州茅台': '600519.XSHG', '茅台': '600519.XSHG',
    '600036.XSHG': '招商银行', '招商银行': '600036.XSHG', '招行': '600036.XSHG',
    '601398.XSHG': '工商银行', '工商银行': '601398.XSHG', '工行': '601398.XSHG',
    '601318.XSHG': '中国平安', '中国平安': '601318.XSHG', '平安': '601318.XSHG',
    '601166.XSHG': '兴业银行', '兴业银行': '601166.XSHG',
    '600900.XSHG': '长江电力', '长江电力': '600900.XSHG',
    '600276.XSHG': '恒瑞医药', '恒瑞医药': '600276.XSHG', '恒瑞': '600276.XSHG',
    '600030.XSHG': '中信证券', '中信证券': '600030.XSHG',
    '600809.XSHG': '山西汾酒', '山西汾酒': '600809.XSHG',
    '600031.XSHG': '三一重工', '三一重工': '600031.XSHG',
    '600887.XSHG': '伊利股份', '伊利股份': '600887.XSHG', '伊利': '600887.XSHG',
    '601012.XSHG': '隆基绿能', '隆基绿能': '601012.XSHG', '隆基': '601012.XSHG',
    '601899.XSHG': '紫金矿业', '紫金矿业': '601899.XSHG',
    '600028.XSHG': '中国石化', '中国石化': '600028.XSHG',
    '600050.XSHG': '中国联通', '中国联通': '600050.XSHG',
    '600585.XSHG': '海螺水泥', '海螺水泥': '600585.XSHG',
    '600048.XSHG': '保利发展', '保利发展': '600048.XSHG', '保利': '600048.XSHG',
    '601688.XSHG': '华泰证券', '华泰证券': '601688.XSHG',
    '601138.XSHG': '工业富联', '工业富联': '601138.XSHG',
    # 深圳主板 (XSHE)
    '000858.XSHE': '五粮液', '五粮液': '000858.XSHE',
    '000001.XSHE': '平安银行', '平安银行': '000001.XSHE',
    '000002.XSHE': '万科A', '万科': '000002.XSHE', '万科A': '000002.XSHE',
    '000333.XSHE': '美的集团', '美的集团': '000333.XSHE', '美的': '000333.XSHE',
    '000651.XSHE': '格力电器', '格力电器': '000651.XSHE', '格力': '000651.XSHE',
    '002594.XSHE': '比亚迪', '比亚迪': '002594.XSHE',
    '002415.XSHE': '海康威视', '海康威视': '002415.XSHE', '海康': '002415.XSHE',
    '002475.XSHE': '立讯精密', '立讯精密': '002475.XSHE',
    '002714.XSHE': '牧原股份', '牧原股份': '002714.XSHE',
    '002129.XSHE': 'TCL中环', 'TCL中环': '002129.XSHE',
    # 创业板 (XSHE 300)
    '300750.XSHE': '宁德时代', '宁德时代': '300750.XSHE', '宁德': '300750.XSHE',
    '300760.XSHE': '迈瑞医疗', '迈瑞医疗': '300760.XSHE',
    '300059.XSHE': '东方财富', '东方财富': '300059.XSHE',
    '300124.XSHE': '汇川技术', '汇川技术': '300124.XSHE',
    '300015.XSHE': '爱尔眼科', '爱尔眼科': '300015.XSHE',
    '300274.XSHE': '阳光电源', '阳光电源': '300274.XSHE',
    '300014.XSHE': '亿纬锂能', '亿纬锂能': '300014.XSHE',
    # 科创板 (XSHG 688)
    '688981.XSHG': '中芯国际', '中芯国际': '688981.XSHG',
    '688012.XSHG': '中微公司', '中微公司': '688012.XSHG',
    '688111.XSHG': '金山办公', '金山办公': '688111.XSHG',
    '688041.XSHG': '海光信息', '海光信息': '688041.XSHG',
    '688256.XSHG': '寒武纪', '寒武纪': '688256.XSHG',
    '688036.XSHG': '传音控股', '传音控股': '688036.XSHG',
}

# Chinese name to ticker (short aliases)
CN_TO_TICKER: Dict[str, str] = {
    '茅台': '600519.XSHG', '贵州茅台': '600519.XSHG',
    '招行': '600036.XSHG', '招商银行': '600036.XSHG',
    '工行': '601398.XSHG', '工商银行': '601398.XSHG',
    '平安': '601318.XSHG', '中国平安': '601318.XSHG',
    '宁德': '300750.XSHE', '宁德时代': '300750.XSHE',
    '比亚迪': '002594.XSHE',
    '海康': '002415.XSHE', '海康威视': '002415.XSHE',
    '格力': '000651.XSHE', '格力电器': '000651.XSHE',
    '美的': '000333.XSHE', '美的集团': '000333.XSHE',
    '五粮液': '000858.XSHE',
    '伊利': '600887.XSHG', '伊利股份': '600887.XSHG',
    '恒瑞': '600276.XSHG', '恒瑞医药': '600276.XSHG',
    '万科': '000002.XSHE', '万科A': '000002.XSHE',
    '隆基': '601012.XSHG', '隆基绿能': '601012.XSHG',
    '保利': '600048.XSHG', '保利发展': '600048.XSHG',
}

# A-share index aliases
INDEX_ALIASES: Dict[str, str] = {
    '沪深300': '000300.XSHG', 'csi300': '000300.XSHG', '沪深三百': '000300.XSHG',
    '上证指数': '000001.XSHG', '上证综指': '000001.XSHG', '上证': '000001.XSHG',
    '深证成指': '399001.XSHE', '深证': '399001.XSHE',
    '创业板指': '399006.XSHE', '创业板': '399006.XSHE',
    '科创50': '000688.XSHG', '科创板': '000688.XSHG',
    '中证500': '000905.XSHG', '中证1000': '000852.XSHG',
    '北证50': '899050.XBEX',
    '全A指数': '000985.XSHG',
}

# Known valid A-share tickers (for validation)
KNOWN_TICKERS = {
    t for t in COMPANY_MAP if re.match(r'\d{6}\.X(SHE|SHG|BEX)$', t)
}

# Common Chinese words that could be confused as tickers
COMMON_WORDS = {
    '的', '了', '是', '在', '和', '也', '就', '都', '而', '及', '与',
    '这', '那', '这个', '那个', '什么', '哪个', '哪些',
    '我', '你', '他', '她', '它', '我们', '你们', '他们',
    '不', '没', '很', '太', '非常', '特别', '比较', '最',
    '会', '能', '可以', '应该', '需要', '要', '想', '可能',
    '已经', '正在', '将', '还', '再', '又',
    '有', '没有', '无',
    '大', '小', '多', '少', '高', '低', '长', '短',
    '前', '后', '左', '右', '中', '上', '下', '里', '外',
    '现在', '今天', '昨天', '明天', '最近', '之前', '之后',
    '因为', '所以', '但是', '虽然', '如果', '或者',
    '涨', '跌', '涨跌', '涨停', '跌停', '停牌', '复牌',
    '买入', '卖出', '持有', '增持', '减持', '回购',
    'PE', 'PB', 'PS', 'ROE', 'ROA', 'EPS', 'EBIT', 'EBITDA',
    'GDP', 'CPI', 'PPI', 'PMI', 'LPR', 'M2', 'MLF', 'SLF',
    'IPO', 'ETF', 'LOF', 'QDII',
    '怎么', '如何', '为什么', '多少', '怎样',
    '分析', '查询', '查看', '比较', '对比',
    '行情', '走势', '趋势', '技术', '基本面', '财务',
}


def is_probably_ticker(word: str) -> bool:
    """Check if a word looks like an A-share ticker."""
    if re.match(r'^\d{6}\.(XSHE|XSHG|XBEX|SS|SZ|BJ)$', word.strip().upper()):
        return True
    return word.strip().upper() in KNOWN_TICKERS


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker to rqdatac format."""
    t = ticker.strip().upper()
    # Already correct format
    if re.match(r'^\d{6}\.X(SHE|SHG|BEX)$', t):
        return t
    # Convert .SS -> .XSHG, .SZ -> .XSHE, .BJ -> .XBEX
    match = re.search(r'(\d{6})', t)
    if not match:
        return t
    code = match.group(1)
    if '.SS' in t or code.startswith('6'):
        return f'{code}.XSHG'
    if '.SZ' in t or code.startswith(('0', '3', '2')):
        return f'{code}.XSHE'
    if '.BJ' in t or code.startswith('8'):
        return f'{code}.XBEX'
    return t


def extract_tickers(text: str, as_info: bool = True) -> dict | list[str]:
    """Extract A-share tickers from text.

    Returns either a dict with 'tickers' list key, or a plain list if as_info=False.
    """
    found = set()
    # Try direct ticker patterns
    for m in re.finditer(r'\d{6}\.(XSHE|XSHG|XBEX|SS|SZ|BJ)', text.upper()):
        found.add(normalize_ticker(m.group(0)))
    # Try known company names
    for name in CN_TO_TICKER:
        if name in text:
            found.add(CN_TO_TICKER[name])
    tickers = list(found)
    if as_info:
        return {"tickers": tickers}
    return tickers


def dedup_tickers(tickers: list[str]) -> list[str]:
    """Deduplicate and normalize a list of tickers."""
    seen: set[str] = set()
    result: list[str] = []
    for t in (tickers or []):
        n = normalize_ticker(t)
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result
