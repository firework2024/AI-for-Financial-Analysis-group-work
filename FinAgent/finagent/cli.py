from __future__ import annotations

import argparse

from .env import load_dotenv, prepare_rqdata_env
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
    analyze.add_argument("--no-download-cache", action="store_true", help="（新浪财经模式不适用此参数）忽略缓存，重新获取")
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
    from .progress import start, end, step, info, ok, fail, section

    load_dotenv()
    prepare_rqdata_env()
    args = build_parser().parse_args()

    start()
    if args.command == "serve":
        step("参数解析", f"命令: {args.command}, 监听: {args.host}:{args.port}, 重载: {args.reload}")
    else:
        step("参数解析", f"命令: {args.command}, 股票: {args.stock}, 截止日: {getattr(args, 'as_of', None) or '今天'}")

    try:
        if args.command == "analyze":
            info("工作模式: 基础年报分析（财务 + MD&A + 经营与财务叙事）")
            result = run(
                WorkflowOptions(
                    stock=args.stock,
                    as_of=args.as_of,
                    years=args.years,
                    output=args.output,
                    no_download_cache=args.no_download_cache,
                )
            )
            ok(f"Markdown 报告已生成: {result['output_markdown']}")
            info(f"JSON 数据已保存: {result['output_json']}")
        elif args.command == "multi-analyze":
            info("工作模式: 多智能体深度研究报告（量价 + 基本面 + 资金流 + 技术 + 图表）")
            result = run_multi_agent(
                MultiAgentOptions(
                    stock=args.stock,
                    as_of=args.as_of,
                    lookback_days=args.lookback_days,
                    output=args.output,
                )
            )
            ok(f"Markdown 报告已生成: {result['output_markdown']}")
            html_path = result.get("output_html") or (result.get("meta") or {}).get("output_html")
            if html_path:
                ok(f"HTML 报告已生成: {html_path}")
            ok(f"JSON 数据已保存: {result['output_json']}")
        elif args.command == "serve":
            from .web.server import serve

            step("启动 Web 界面", f"http://{args.host}:{args.port}")
            serve(host=args.host, port=args.port, reload=args.reload)
    except Exception as exc:
        fail(f"工作流异常终止: {exc}")
        end()
        raise SystemExit(str(exc)) from exc
    end()
