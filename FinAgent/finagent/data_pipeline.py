"""FinAgent 统一数据拉取链路门面。

各入口与编排函数映射：
┌─────────────────┬──────────────────────────┬─────────────────────────────┐
│ 入口            │ 编排                     │ 数据源                       │
├─────────────────┼──────────────────────────┼─────────────────────────────┤
│ CLI analyze     │ workflow.run             │ 新浪年报文本 + RQData PIT    │
│ CLI multi       │ run_multi_agent          │ RQData 全量 + SQLite 缓存    │
│ Web 侧栏报告    │ POST /api/multi-analyze  │ 同上                         │
│ Web 年报分析    │ POST /api/analyze        │ workflow.run                 │
│ 新对话          │ bootstrap_stock_data     │ 行情+PIT(+可选年报 PDF)      │
│ 对话发消息      │ ensure_stored_data       │ 按问题缺口按需补拉           │
│ 对话同步按钮    │ fetch_stock_data_full    │ 行情+PIT+年报 全量入库       │
│ Agent ensure_data│ run_data_ingest         │ query_driven / manual_full   │
│ 多智能体生成前  │ ensure_report_data_for_generation │ 报告级量价+年报+PIT │
│ 多智能体基本面  │ ensure_annual_report_in_store │ 巨潮 PDF + PIT          │
│ GET /api/data/* │ query_data_api           │ SQLite 只读                  │
└─────────────────┴──────────────────────────┴─────────────────────────────┘

所有「写入 SQLite」路径最终汇聚到 chat.data_ingest._run_ingest_plan。
"""

from __future__ import annotations

from .chat.data_ingest import (
    AnnualCacheError,
    IngestMode,
    bootstrap_stock_data,
    ensure_annual_report_in_store,
    ensure_report_data_for_generation,
    ensure_stored_data,
    fetch_stock_data_full,
    get_data_coverage,
    get_data_gaps,
    ingest_annual_report,
    ingest_market_snapshot,
    ingest_pit_financials,
    run_data_ingest,
)

__all__ = [
    "AnnualCacheError",
    "IngestMode",
    "bootstrap_stock_data",
    "ensure_annual_report_in_store",
    "ensure_report_data_for_generation",
    "ensure_stored_data",
    "fetch_stock_data_full",
    "get_data_coverage",
    "get_data_gaps",
    "ingest_annual_report",
    "ingest_market_snapshot",
    "ingest_pit_financials",
    "run_data_ingest",
]
