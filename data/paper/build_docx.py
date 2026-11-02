"""Build data/paper/manuscript.docx from data/paper/manuscript.md.

Run from the repo root:  .venv/bin/python data/paper/build_docx.py
Handles the small Markdown subset the manuscript uses: # / ## / ### headings, paragraphs,
**bold**, *italic*, bullet and numbered lists, pipe tables, figure images, horizontal rules.
Text in [TO CONFIRM ...] brackets is highlighted yellow so unresolved items are easy to find.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_COLOR_INDEX, WD_PARAGRAPH_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

SRC = Path("data/paper/manuscript.md")
OUT = Path("data/paper/manuscript.docx")
FIG_DIR = SRC.parent

TOKEN = re.compile(r"(\*\*.+?\*\*|\*.+?\*|\[[^\]]*TO CONFIRM[^\]]*(?:\[[^\]]*\][^\]]*)*\])")


def add_runs(par, text: str, size: float | None = None) -> None:
    text = text.replace("\\*", "∗")
    for chunk in TOKEN.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            run = par.add_run(chunk[2:-2]); run.bold = True
        elif chunk.startswith("*") and chunk.endswith("*") and len(chunk) > 2:
            run = par.add_run(chunk[1:-1]); run.italic = True
        elif "TO CONFIRM" in chunk and chunk.startswith("["):
            run = par.add_run(chunk); run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            run = par.add_run(chunk)
        if size:
            run.font.size = Pt(size)


def shade(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def add_table(doc: Document, rows: list[list[str]]) -> None:
    ncols = len(rows[0])
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"; table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j in range(ncols):
            cell = table.cell(i, j); cell.text = ""
            par = cell.paragraphs[0]
            add_runs(par, row[j] if j < len(row) else "", size=8.5)
            par.paragraph_format.space_after = Pt(0)
            if i == 0:
                shade(cell, "E5E7EB")
                for r in par.runs:
                    r.bold = True
    doc.add_paragraph()


def main() -> None:
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.4); sec.top_margin = sec.bottom_margin = Cm(2.2)
    normal = doc.styles["Normal"]; normal.font.name = "Times New Roman"; normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6); normal.paragraph_format.line_spacing = 1.25
    for name, size in (("Heading 1", 14), ("Heading 2", 12.5), ("Heading 3", 11.5)):
        st = doc.styles[name]; st.font.name = "Times New Roman"; st.font.size = Pt(size); st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)

    lines = SRC.read_text(encoding="utf-8").splitlines()
    i, first_h1 = 0, True
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line == "---":
            i += 1; continue
        if line.startswith("# ") and first_h1:
            first_h1 = False
            p = doc.add_paragraph(); p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            r = p.add_run(line[2:]); r.bold = True; r.font.size = Pt(16)
            i += 1; continue
        if line.startswith("## "):
            doc.add_heading(line[3:], level=1); i += 1; continue
        if line.startswith("### "):
            doc.add_heading(line[4:], level=2); i += 1; continue
        if line.startswith("!["):
            m = re.match(r"!\[(.*)\]\((.*)\)", line)
            cap, path = m.group(1), FIG_DIR / m.group(2)
            doc.add_picture(str(path), width=Cm(15.5)); doc.paragraphs[-1].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            p = doc.add_paragraph(); add_runs(p, "*" + cap + "*", size=9.5); p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            i += 1; continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            add_table(doc, rows); continue
        if re.match(r"^- ", line):
            p = doc.add_paragraph(style="List Bullet"); add_runs(p, line[2:]); i += 1; continue
        if re.match(r"^\d+\. ", line):
            p = doc.add_paragraph(style="List Number"); add_runs(p, re.sub(r"^\d+\. ", "", line)); i += 1; continue
        p = doc.add_paragraph(); add_runs(p, line)
        if re.match(r"^[A-Z][^.]+\(\d{4}\)\.", line):
            p.paragraph_format.left_indent = Cm(0.8); p.paragraph_format.first_line_indent = Cm(-0.8)
        i += 1
    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
