"""Compile an existing .tex report to PDF using resolve_xelatex()."""
from __future__ import annotations

import sys
from pathlib import Path

from finagent.env import load_dotenv
from finagent.latex_exporter import export_latex, resolve_xelatex

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv()
    tex = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "outputs" / "300750_multi_agent_report.tex"
    tex = tex.resolve()
    md = tex.with_suffix(".md")
    source = md if md.is_file() else tex
    text = source.read_text(encoding="utf-8")
    print("xelatex:", resolve_xelatex())
    export_latex(text, tex, title=tex.stem, compile_pdf=True)
    pdf = tex.with_suffix(".pdf")
    print("PDF:", pdf, "exists=", pdf.is_file())
    return 0 if pdf.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
