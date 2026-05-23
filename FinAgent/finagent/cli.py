from __future__ import annotations

import argparse

from .env import load_dotenv
from .workflow import WorkflowOptions, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finagent", description="年报智能体命令行工作流")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="分析单只 A 股最新年报")
    analyze.add_argument("--stock", required=True, help="6 位 A 股代码，例如 600519")
    analyze.add_argument("--as-of", default=None, help="查询截止日期，格式 YYYY-MM-DD")
    analyze.add_argument("--years", type=int, default=3, help="财务数据年数，默认 3")
    analyze.add_argument("--output", default=None, help="Markdown 输出路径")
    analyze.add_argument("--no-download-cache", action="store_true", help="忽略本地 PDF 缓存，重新下载")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    if args.command == "analyze":
        result = run(
            WorkflowOptions(
                stock=args.stock,
                as_of=args.as_of,
                years=args.years,
                output=args.output,
                no_download_cache=args.no_download_cache,
            )
        )
        print(f"Markdown report: {result['output_markdown']}")
        print(f"JSON data: {result['output_json']}")
