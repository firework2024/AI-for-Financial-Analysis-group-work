from __future__ import annotations

import argparse

from .env import load_dotenv
from .multiagent import MultiAgentOptions, run_multi_agent
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
    multi = subparsers.add_parser("multi-analyze", help="运行多智能体 A 股研究报告")
    multi.add_argument("--stock", required=True, help="6 位 A 股代码，例如 600519")
    multi.add_argument("--as-of", default=None, help="查询截止日期，格式 YYYY-MM-DD")
    multi.add_argument("--lookback-days", type=int, default=260, help="量价与资金流回看自然日天数，默认 260")
    multi.add_argument("--output", default=None, help="Markdown 输出路径")
    serve = subparsers.add_parser("serve", help="启动 Web 界面")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    serve.add_argument("--reload", action="store_true", help="开发模式自动重载")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    try:
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
        elif args.command == "multi-analyze":
            result = run_multi_agent(
                MultiAgentOptions(
                    stock=args.stock,
                    as_of=args.as_of,
                    lookback_days=args.lookback_days,
                    output=args.output,
                )
            )
            print(f"Markdown report: {result['output_markdown']}")
            print(f"HTML report: {result['output_html']}")
            print(f"JSON data: {result['output_json']}")
        elif args.command == "serve":
            from .web.server import serve

            print(f"FinAgent Web: http://{args.host}:{args.port}")
            serve(host=args.host, port=args.port, reload=args.reload)
    except Exception as exc:
        raise SystemExit(str(exc)) from exc
