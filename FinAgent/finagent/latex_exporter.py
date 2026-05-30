from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def escape_latex(text: str) -> str:
    replacements = {
        '\\': r'\textbackslash{}',
        '{': r'\{',
        '}': r'\}',
        '_': r'\_',
        '$': r'\$',
        '%': r'\%',
        '&': r'\&',
        '#': r'\#',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
        '"': r"''",
        '|': r'\textbar{}',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def clean_latex_residue(text: str) -> str:
    text = re.sub(r'\\\{\}n', '', text)
    text = re.sub(r'\\\{\}', '', text)
    text = re.sub(r'n\s*n', ' ', text)
    return text


def markdown_to_latex(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    latex_lines = []
    in_table = False
    table_rows = []
    in_list = False
    list_items = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            latex_lines.append(f"\\section{{{escape_latex(stripped[2:])}}}")
            continue
        if stripped.startswith("## "):
            latex_lines.append(f"\\subsection{{{escape_latex(stripped[2:])}}}")
            continue

        if stripped.startswith("- "):
            if not in_list:
                in_list = True
                latex_lines.append("\\begin{itemize}")
            list_items.append(escape_latex(stripped[2:]))
            continue
        else:
            if in_list:
                for item in list_items:
                    latex_lines.append(f"\\item {item}")
                latex_lines.append("\\end{itemize}")
                in_list = False
                list_items = []

        if "|" in line and not stripped.startswith("---"):
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(line)
            continue
        elif in_table:
            latex_lines.append(markdown_table_to_latex(table_rows))
            in_table = False
            table_rows = []

        img_match = re.search(r'!\[.*?\]\((.*?)\)', line)
        if img_match:
            img_path = img_match.group(1)
            safe_path = img_path.replace("\\", "/")
            latex_lines.append("\\begin{figure}[htbp]")
            latex_lines.append("\\centering")
            latex_lines.append(f"\\includegraphics[width=0.8\\textwidth]{{{safe_path}}}")
            latex_lines.append(f"\\caption{{{escape_latex(Path(safe_path).name)}}}")
            latex_lines.append("\\end{figure}")
            continue

        if stripped:
            escaped = escape_latex(line)
            cleaned = clean_latex_residue(escaped)
            latex_lines.append(cleaned)
        else:
            latex_lines.append("")

    if in_list:
        for item in list_items:
            latex_lines.append(f"\\item {item}")
        latex_lines.append("\\end{itemize}")
    if in_table:
        latex_lines.append(markdown_table_to_latex(table_rows))

    return "\n".join(latex_lines)


def markdown_table_to_latex(rows: list[str]) -> str:
    if not rows:
        return ""

    header = rows[0].split("|")[1:-1]
    n_cols = len(header)
    align_row = rows[1] if len(rows) > 1 else ""
    aligns = []
    if align_row:
        parts = align_row.split("|")[1:-1]
        for part in parts:
            if part.startswith(":") and part.endswith(":"):
                aligns.append("c")
            elif part.endswith(":"):
                aligns.append("r")
            else:
                aligns.append("l")
    else:
        aligns = ["l"] * n_cols

    latex = "\\begin{table}[htbp]\n\\centering\n"
    latex += "\\begin{tabular}{" + "".join(aligns) + "}\n"
    latex += "\\toprule\n"
    latex += " & ".join(escape_latex(cell.strip()) for cell in header) + " \\\\\n"
    latex += "\\midrule\n"
    for row in rows[2:]:
        cells = row.split("|")[1:-1]
        if len(cells) != n_cols:
            continue
        latex += " & ".join(escape_latex(cell.strip()) for cell in cells) + " \\\\\n"
    latex += "\\bottomrule\n"
    latex += "\\end{tabular}\n\\end{table}\n"
    return latex


def export_latex(
    markdown_text: str,
    output_tex_path: Path,
    title: str = "研究报告",
    author: str = "FinAgent",
    compile_pdf: bool = False,
) -> Path:
    preamble = f"""\\documentclass[12pt,a4paper]{{article}}
\\usepackage{{geometry}}
\\geometry{{margin=2.54cm}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{grffile}}
\\usepackage{{xcolor}}
\\usepackage{{hyperref}}
\\hypersetup{{colorlinks=true, linkcolor=blue, urlcolor=blue}}
\\usepackage{{xeCJK}}
\\setCJKmainfont{{SimSun}}
\\setCJKsansfont{{SimHei}}
\\setCJKmonofont{{FangSong}}
\\title{{{escape_latex(title)}}}
\\author{{{escape_latex(author)}}}
\\date{{\\today}}
\\begin{{document}}
\\maketitle
\\tableofcontents
\\newpage
\\sloppy
"""
    body = markdown_to_latex(markdown_text)
    postamble = "\\end{document}\n"
    full_tex = preamble + body + postamble

    output_tex_path.parent.mkdir(parents=True, exist_ok=True)
    output_tex_path.write_text(full_tex, encoding="utf-8")

    if compile_pdf:
        tex_dir = output_tex_path.parent
        try:
            result = subprocess.run(
                ["xelatex", "-interaction=nonstopmode", output_tex_path.name],
                cwd=tex_dir,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=120,
            )
            if result.returncode == 0:
                subprocess.run(
                    ["xelatex", "-interaction=nonstopmode", output_tex_path.name],
                    cwd=tex_dir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=120,
                )
                print(f"PDF 生成成功: {output_tex_path.with_suffix('.pdf')}")
            else:
                print("===== LaTeX 编译错误 =====")
                print(result.stdout[-2000:] if result.stdout else "")
                print(result.stderr[-2000:] if result.stderr else "")
                print("=========================")
        except FileNotFoundError:
            print("未找到 xelatex 命令，请安装 TeX Live 或 MiKTeX 并确保 xelatex 在 PATH 中。")
        except Exception as e:
            print(f"编译异常: {e}")
    return output_tex_path