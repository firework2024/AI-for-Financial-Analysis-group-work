"""Tests for finagent.stock_utils — shared A‑share utility functions."""

import pytest
from datetime import date
from finagent.stock_utils import (
    AnnualReport,
    calendar_trading_as_of,
    classify_stock,
    default_as_of,
    normalize_stock_code,
    parse_report_year,
    resolve_as_of,
    to_order_book_id,
)


class TestClassifyStock:
    def test_sse_main(self):
        assert classify_stock("600519") == ("sse", "sh", "XSHG")

    def test_sse_kcb(self):
        assert classify_stock("688981") == ("sse", "shkcp", "XSHG")

    def test_szse_main(self):
        assert classify_stock("000858") == ("szse", "sz", "XSHE")

    def test_szse_cyb(self):
        assert classify_stock("300750") == ("szse", "szcy", "XSHE")

    def test_invalid_code(self):
        with pytest.raises(ValueError, match="不支持"):
            classify_stock("999999")


class TestNormalizeStockCode:
    def test_plain_six_digits(self):
        assert normalize_stock_code("600519") == "600519"

    def test_with_dot_suffix(self):
        assert normalize_stock_code("000858.XSHE") == "000858"

    def test_with_whitespace(self):
        assert normalize_stock_code(" 300750 ") == "300750"

    def test_uppercase(self):
        assert normalize_stock_code("000001.XSHE") == "000001"

    def test_less_than_six_digits(self):
        with pytest.raises(ValueError, match="6 位数字"):
            normalize_stock_code("12345")

    def test_non_digit(self):
        with pytest.raises(ValueError, match="6 位数字"):
            normalize_stock_code("ABCDEF")


class TestToOrderBookId:
    def test_sse(self):
        assert to_order_book_id("600519") == "600519.XSHG"

    def test_szse(self):
        assert to_order_book_id("000858") == "000858.XSHE"

    def test_szse_gem(self):
        assert to_order_book_id("300750") == "300750.XSHE"


class TestParseReportYear:
    def test_normal(self):
        assert parse_report_year("贵州茅台2025年年度报告") == 2025

    def test_with_summary_suffix(self):
        assert parse_report_year("2024年年度报告摘要") == 2024

    def test_old_year(self):
        assert parse_report_year("三安光电1999年年度报告") == 1999

    def test_no_match(self):
        assert parse_report_year("中期报告") is None


class TestDefaultAsOf:
    def test_with_value(self):
        assert default_as_of("2025-06-01") == date(2025, 6, 1)

    def test_none_returns_today(self):
        assert default_as_of(None) == date.today()


class TestResolveAsOf:
    def test_weekend_rolls_back_to_friday(self):
        # 2026-05-31 周日 → 最近交易日 2026-05-29（周五）
        assert resolve_as_of("2026-05-31") == date(2026, 5, 29)
        assert calendar_trading_as_of(date(2026, 5, 31)) == date(2026, 5, 29)

    def test_weekday_unchanged(self):
        assert resolve_as_of("2026-05-29") == date(2026, 5, 29)


class TestAnnualReportDataclass:
    def test_to_dict(self):
        report = AnnualReport(
            stock_code="600519",
            sec_name="贵州茅台",
            title="贵州茅台2025年年度报告",
            announcement_time=1743000000000,
            adjunct_url="some/path.pdf",
            pdf_url="http://example.com/some/path.pdf",
            report_year=2025,
        )
        d = report.to_dict()
        assert d["stock_code"] == "600519"
        assert d["report_year"] == 2025
        assert d["pdf_url"] == "http://example.com/some/path.pdf"
