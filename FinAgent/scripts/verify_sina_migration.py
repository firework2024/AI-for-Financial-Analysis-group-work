#!/usr/bin/env python3
"""
FinAgent 新浪财经迁移验证脚本

验证要点（静态代码分析）：
  1. workflow.py 从 sina_finance 导入 latest_annual_report
  2. workflow.py 不再直接从 cninfo 导入 latest_annual_report / download_report
  3. workflow.py 不含 "巨潮资讯网" 字符串
  4. workflow.py 不含 extract_pdf_text 调用
  5. workflow.py 步骤 1 标题含 "新浪财经"
  6. report.py 不含 "local_pdf" 和 "PDF：" 引用
  7. 其他模块导入已改为 stock_utils

运行时验证（可选，需网络）：
  对各板块抽样测试新浪财经接口连通性。

用法:
  python scripts/verify_sina_migration.py          # 仅静态分析
  python scripts/verify_sina_migration.py --live   # 静态分析 + 网络测试
"""

from __future__ import annotations

import importlib.util
import re
import sys
import time
from pathlib import Path
from typing import Any

CHECK_PASS = "[PASS]"
CHECK_FAIL = "[FAIL]"

# ── 项目根目录 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_file(path: str) -> str:
    filepath = PROJECT_ROOT / path
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8")


def check(condition: bool, msg: str, *, fix: str = "") -> dict:
    return {"pass": condition, "msg": msg, "fix": fix}


# ═══════════════════════════════════════════════════════════
#  检查项
# ═══════════════════════════════════════════════════════════


def check_workflow_no_cninfo_import(content: str) -> list[dict]:
    """检查 workflow.py 不再直接从 cninfo 导入 download_report / latest_annual_report。"""
    results = []
    for func in ("latest_annual_report", "download_report"):
        pattern = re.compile(
            r'from\s+\.cninfo\s+import\s+[^#]*\b' + re.escape(func) + r'\b'
        )
        if pattern.search(content):
            results.append(check(
                False,
                f" {CHECK_FAIL} workflow.py 仍从 .cninfo 导入 {func}",
                fix=f"将 {func} 的导入改为 from .sina_finance import {func}",
            ))
        else:
            results.append(check(
                True,
                f" {CHECK_PASS} workflow.py 未从 .cninfo 导入 {func}",
            ))
    return results


def check_workflow_sina_import(content: str) -> list[dict]:
    """检查 workflow.py 从 sina_finance 导入 latest_annual_report。"""
    if "from .sina_finance import latest_annual_report" in content:
        return [check(True, f" {CHECK_PASS} workflow.py 从 sina_finance 导入 latest_annual_report")]
    return [check(False, f" {CHECK_FAIL} workflow.py 未从 sina_finance 导入 latest_annual_report",
                  fix="添加 from .sina_finance import latest_annual_report")]


def check_workflow_no_juchao(content: str) -> list[dict]:
    """检查 workflow.py 不含 '巨潮资讯网'。"""
    if "巨潮资讯网" in content:
        return [check(False, f" {CHECK_FAIL} workflow.py 仍包含 '巨潮资讯网'",
                      fix="替换为 '新浪财经'")]
    return [check(True, f" {CHECK_PASS} workflow.py 不含 '巨潮资讯网'")]


def check_workflow_no_extract_pdf_text(content: str) -> list[dict]:
    """检查 workflow.py 不含 extract_pdf_text 调用。"""
    if "extract_pdf_text" in content:
        return [check(False, f" {CHECK_FAIL} workflow.py 仍调用 extract_pdf_text",
                      fix="移除该调用，full_text 已来自 sina_finance")]
    return [check(True, f" {CHECK_PASS} workflow.py 不含 extract_pdf_text 调用")]


def check_workflow_step1_title(content: str) -> list[dict]:
    """检查 workflow.py 步骤 1 标题含 '新浪财经'。"""
    if "获取新浪财经年报" in content:
        return [check(True, f" {CHECK_PASS} workflow.py 步骤 1 标题已改为 '获取新浪财经年报'")]
    return [check(False, f" {CHECK_FAIL} workflow.py 步骤 1 标题未更新",
                  fix="将 '查询巨潮资讯网年报' 改为 '获取新浪财经年报'")]


def check_report_no_local_pdf(content: str) -> list[dict]:
    """检查 report.py 不含 'local_pdf'。"""
    results = []
    if "local_pdf" in content:
        results.append(check(False, f" {CHECK_FAIL} report.py 仍引用 local_pdf",
                             fix="改为 local_text"))
    else:
        results.append(check(True, f" {CHECK_PASS} report.py 不含 local_pdf"))
    return results


def check_report_no_pdf_colon(content: str) -> list[dict]:
    """检查 report.py 不含 'PDF：' 原文引用。"""
    if "PDF：" in content:
        return [check(False, f" {CHECK_FAIL} report.py 仍包含 'PDF：'",
                      fix="改为 '来源：新浪财经纯文本'")]
    return [check(True, f" {CHECK_PASS} report.py 不含旧 PDF 引用")]


def check_imports_use_stock_utils() -> list[dict]:
    """检查各模块导入已改为 stock_utils。"""
    checks = {
        "finagent/chat/data_tools.py": "from ..stock_utils import",
        "finagent/multiagent.py": "from .stock_utils import",
        "finagent/rqdata_client.py": "from .stock_utils import",
    }
    results = []
    for filepath, expected_import in checks.items():
        content = read_file(filepath)
        if "cninfo" in content and expected_import not in content:
            results.append(check(False, f" {CHECK_FAIL} {filepath} 仍引用 cninfo",
                                 fix=f"改为 {expected_import}"))
        elif expected_import in content:
            results.append(check(True, f" {CHECK_PASS} {filepath} 已使用 stock_utils"))
        else:
            results.append(check(True, f" {CHECK_PASS} {filepath} 无 cninfo 引用"))
    return results


def check_cli_no_cache_help(content: str) -> list[dict]:
    """检查 cli.py 中 --no-download-cache 帮助文本已更新。"""
    if "新浪财经模式不适用" in content:
        return [check(True, f" {CHECK_PASS} cli.py --no-download-cache 帮助文本已更新")]
    return [check(False, f" {CHECK_FAIL} cli.py --no-download-cache 帮助文本未更新",
                  fix="添加 '（新浪财经模式不适用此参数）'")]


# ═══════════════════════════════════════════════════════════
#  运行时验证（需网络）
# ═══════════════════════════════════════════════════════════


LIVE_TESTS = [
    ("600519", "贵州茅台", 2024),
    ("000858", "五粮液", 2024),
    ("300750", "宁德时代", 2024),
    ("688981", "中芯国际", 2024),
]


def run_live_tests() -> list[dict]:
    """对各板块抽样测试新浪财经接口。"""
    results = []

    # 动态导入项目模块
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from finagent.sina_finance import latest_annual_report
        from finagent.stock_utils import default_as_of
        from finagent.pdf_text import extract_mda
    except ImportError as e:
        results.append(check(False, f" {CHECK_FAIL} 运行时测试无法导入项目模块: {e}"))
        return results
    except Exception as e:
        results.append(check(False, f" {CHECK_FAIL} 运行时初始化失败: {e}"))
        return results

    for code, name, year in LIVE_TESTS:
        print(f"\n  [{code}] {name} {year}年报 ... ", end="", flush=True)
        try:
            as_of = default_as_of(f"{year}-06-01")
            t0 = time.time()
            fetch_result = latest_annual_report(code, as_of)
            elapsed = time.time() - t0

            report = fetch_result.report
            if not report:
                results.append(check(False, f" {CHECK_FAIL} {code} 未返回元数据"))
                continue

            text_len = len(fetch_result.full_text)
            if text_len < 50000:
                results.append(check(False, f" {CHECK_FAIL} {code} 文本过短: {text_len:,} 字符"))
                continue

            if report.report_year != year:
                results.append(check(
                    False,
                    f" {CHECK_FAIL} {code} 年份不匹配: 期望 {year}, 实际 {report.report_year}",
                ))
                continue

            mda = extract_mda(fetch_result.full_text)
            if len(mda.mda_text) < 100:
                results.append(check(
                    False,
                    f" {CHECK_FAIL} {code} MD&A 提取文本过短 ({len(mda.mda_text)} 字符)",
                ))
                continue

            results.append(check(
                True,
                f" {CHECK_PASS} {code} ({text_len:,} 字符, MD&A {len(mda.mda_text):,} 字符, {elapsed:.1f}s)",
            ))

        except Exception as e:
            results.append(check(False, f" {CHECK_FAIL} {code} 异常: {e}"))

        time.sleep(1.5)

    return results


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(description="FinAgent 新浪财经迁移验证")
    parser.add_argument("--live", action="store_true", help="包含网络连通性测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示所有检查详情")
    args = parser.parse_args()

    workflow_content = read_file("finagent/workflow.py")
    report_content = read_file("finagent/report.py")
    cli_content = read_file("finagent/cli.py")

    all_checks: list[dict[str, Any]] = []

    # ── 静态分析 ──
    print("=" * 60)
    print("  1. 静态代码分析")
    print("=" * 60)

    checks = [
        ("workflow 导入检查", check_workflow_no_cninfo_import(workflow_content)),
        ("workflow sina 导入", check_workflow_sina_import(workflow_content)),
        ("workflow 无巨潮", check_workflow_no_juchao(workflow_content)),
        ("workflow 无 PDF 提取", check_workflow_no_extract_pdf_text(workflow_content)),
        ("workflow 步骤 1 标题", check_workflow_step1_title(workflow_content)),
        ("report local_pdf", check_report_no_local_pdf(report_content)),
        ("report PDF 引用", check_report_no_pdf_colon(report_content)),
        ("其他模块导入", check_imports_use_stock_utils()),
        ("CLI 帮助文本", check_cli_no_cache_help(cli_content)),
    ]

    for group_name, group_checks in checks:
        all_checks.extend(group_checks)
        for c in group_checks:
            if not c["pass"] or args.verbose:
                print(f"  {c['msg']}")
                if not c["pass"] and c.get("fix"):
                    print(f"    -> 修复建议: {c['fix']}")

    # ── 运行时验证 ──
    if args.live:
        print()
        print("=" * 60)
        print("  2. 运行时网络验证")
        print("=" * 60)
        live_results = run_live_tests()
        all_checks.extend(live_results)
        for c in live_results:
            print(f"  {c['msg']}")

    # ── 汇总 ──
    print()
    total = len(all_checks)
    passed = sum(1 for c in all_checks if c["pass"])
    failed = total - passed

    print("=" * 60)
    print(f"  汇总: {passed} / {total} 通过", end="")
    if failed:
        print(f", {failed} 项失败", end="")
    print()
    print("=" * 60)

    if failed > 0:
        print("\n[WARNING] 部分检查失败，请查看以上细节。")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
