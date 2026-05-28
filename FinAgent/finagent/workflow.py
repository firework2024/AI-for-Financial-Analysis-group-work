from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .cninfo import default_as_of
from .env import load_dotenv
from .fundamental_pipeline import run_fundamental_pipeline
from .report import render_markdown, write_report


@dataclass
class WorkflowOptions:
    stock: str
    as_of: str | None = None
    years: int = 3
    output: str | None = None
    no_download_cache: bool = False
    workdir: str = "."
    use_sina_text: bool = True


def _log_step(step: str, input_summary: str = "", output_summary: str = "") -> None:
    print(f"\n{'=' * 60}")
    print(f"[STEP] {step}")
    if input_summary:
        print(f"[INPUT ] {input_summary}")
    if output_summary:
        print(f"[OUTPUT] {output_summary}")
    print("=" * 60)


def _log_dict(label: str, data: dict[str, Any]) -> None:
    print(f"\n[{label}]")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def run(options: WorkflowOptions) -> dict[str, Any]:
    load_dotenv()
    root = Path(options.workdir)
    as_of_date = default_as_of(options.as_of)

    _log_step(
        "1/2 运行共享基本面管线",
        f"stock={options.stock}, as_of={as_of_date}, use_sina_text={options.use_sina_text}",
    )
    pipeline_result = run_fundamental_pipeline(
        stock=options.stock,
        as_of=as_of_date,
        years=options.years,
        workdir=root,
        no_download_cache=options.no_download_cache,
        use_sina_text=options.use_sina_text,
    )
    result = pipeline_result.to_report_dict()
    analysis = result["financial_analysis"]
    report = result["annual_report"]
    raw_signals = analysis.get("raw_signals", {})
    print(f"  -> 公司简称: {report.get('sec_name', '')}")
    print(f"  -> 标题: {report.get('title', '')}")
    print(f"  -> 公告日期: {report.get('pub_date', '')}")
    print(f"  -> 报告年份: {report.get('report_year', '')}")
    print(f"  -> MD&A 提取置信度: {result['mda']['confidence']}")
    print(f"  -> 结构化信号: {len(raw_signals.get('structured_signals', []))} 个")
    print(f"  -> 组合信号: {len(raw_signals.get('compound_signals', []))} 个")
    print(f"  -> 审核后信号: {len(analysis.get('reviewed_signals', []))} 个")
    print(f"  -> 积极信号: {len(analysis.get('positive_signals', []))} 条")
    print(f"  -> 消极信号: {len(analysis.get('negative_signals', []))} 条")
    print(f"  -> 关键风险: {len(analysis.get('key_risks', []))} 条")

    _log_step("2/2 渲染报告并输出")
    output_path = Path(options.output) if options.output else root / "outputs" / f"{options.stock}_{report['report_year']}_report.md"
    write_report(render_markdown(result), output_path)
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps(_json_ready(result), ensure_ascii=False, indent=2), encoding="utf-8")
    _log_step(
        "2/2 渲染报告并输出",
        output_summary=f"markdown={output_path}, json={json_path}",
    )
    result["output_markdown"] = str(output_path)
    result["output_json"] = str(json_path)
    return result


def _json_ready(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "__dict__"):
        return asdict(value)
    return value
