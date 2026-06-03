#!/usr/bin/env python3
"""从 outputs 删除不需要的图表文件，并可选剥离 md/html/json 中的图/表块。

示例：
  # 用内置默认列表（行业横截面条形图 + TTM 快照图）清理全部报告
  python scripts/clean_output_charts.py --all --defaults

  # 只删文件，不改报告正文
  python scripts/clean_output_charts.py --all --defaults --files-only

  # 指定报告 + 自定义图键
  python scripts/clean_output_charts.py --report 600519_multi_agent_report \\
      --chart industry_growth_leverage_compare --chart latest_quality_snapshot

  # 同时去掉正文里的「表·最新盈利质量因子」
  python scripts/clean_output_charts.py --all --defaults --default-tables

  # 预览
  python scripts/clean_output_charts.py --all --defaults --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finagent.chart_catalog import (  # noqa: E402
    CHART_CAPTIONS,
    DEFAULT_PURGE_OUTPUT_CHART_KEYS,
    DEFAULT_PURGE_OUTPUT_TABLE_KEYS,
    TABLE_CAPTIONS,
)
from finagent.output_cleanup import (  # noqa: E402
    chart_key_labels,
    clean_report_bundle,
    discover_report_stems,
    resolve_purge_chart_keys,
    resolve_purge_table_keys,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 outputs 中不需要的图表与可选表块")
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=ROOT / "outputs",
        help="outputs 目录（默认 FinAgent/outputs）",
    )
    parser.add_argument(
        "--report",
        action="append",
        dest="reports",
        help="报告 stem，如 600519_multi_agent_report（可多次指定）",
    )
    parser.add_argument("--all", action="store_true", help="处理 outputs 下全部 multi_agent 报告")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help=f"启用默认图键: {', '.join(sorted(DEFAULT_PURGE_OUTPUT_CHART_KEYS))}",
    )
    parser.add_argument(
        "--default-tables",
        action="store_true",
        help=f"同时剥离默认机械表: {', '.join(sorted(DEFAULT_PURGE_OUTPUT_TABLE_KEYS))}",
    )
    parser.add_argument(
        "--chart",
        action="append",
        dest="charts",
        help="额外要删除的 chart_key（可多次指定，见 chart_catalog.CHART_CAPTIONS）",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        help="额外要从正文删除的 table_key（见 chart_catalog.TABLE_CAPTIONS）",
    )
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="只删 charts 目录下的图片，不改 md/html/json",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将删除/更新的内容")
    parser.add_argument("--list-keys", action="store_true", help="列出已知 chart/table 键后退出")
    args = parser.parse_args()

    if args.list_keys:
        print("图表键 (chart_key → 标题):")
        for key, caption in sorted(CHART_CAPTIONS.items()):
            mark = " [default]" if key in DEFAULT_PURGE_OUTPUT_CHART_KEYS else ""
            print(f"  {key}: {caption}{mark}")
        print("\n表键 (table_key → 标题):")
        for key, caption in sorted(TABLE_CAPTIONS.items()):
            mark = " [default-table]" if key in DEFAULT_PURGE_OUTPUT_TABLE_KEYS else ""
            print(f"  {key}: {caption}{mark}")
        return 0

    chart_keys = resolve_purge_chart_keys(use_defaults=args.defaults, extra=set(args.charts or []))
    table_keys = resolve_purge_table_keys(use_defaults=args.default_tables, extra=set(args.tables or []))
    if not chart_keys and not table_keys:
        print("请指定 --defaults / --default-tables / --chart / --table 至少一项。")
        return 1

    outputs_dir = args.outputs_dir.resolve()
    if not outputs_dir.is_dir():
        print(f"outputs 目录不存在: {outputs_dir}")
        return 1

    if args.all:
        report_stems = discover_report_stems(outputs_dir)
    elif args.reports:
        report_stems = list(dict.fromkeys(args.reports))
    else:
        print("请指定 --report 或 --all。")
        return 1

    if not report_stems:
        print("未找到可清理的报告。")
        return 0

    print(f"outputs: {outputs_dir}")
    if chart_keys:
        print("图键:", ", ".join(chart_key_labels(chart_keys)))
    if table_keys:
        print("表键:", ", ".join(sorted(table_keys)))
    if args.dry_run:
        print("（dry-run）")

    summaries = []
    for stem in report_stems:
        summary = clean_report_bundle(
            outputs_dir,
            stem,
            chart_keys=chart_keys,
            table_keys=table_keys,
            strip_reports=not args.files_only,
            dry_run=args.dry_run,
        )
        summaries.append(summary)

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    deleted = sum(len(item.get("deleted_files") or []) for item in summaries)
    updated = sum(len(item.get("updated_files") or []) for item in summaries)
    print(f"完成: {len(summaries)} 份报告, 删除 {deleted} 个图文件, 更新 {updated} 个报告文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
