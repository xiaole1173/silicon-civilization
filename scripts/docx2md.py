"""docx -> markdown（只处理本项目用到的子集，用于比对用户手改稿）。"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    doc = Document(str(src))
    out = []
    for blk in iter_blocks(doc):
        if isinstance(blk, Paragraph):
            t = (blk.text or "").strip()
            if not t:
                continue
            st = blk.style.name or ""
            if st == "Title":
                out.append("# " + t)
            elif st == "Heading 1":
                out.append("## " + t)
            elif st == "Heading 2":
                out.append("### " + t)
            elif st == "Heading 3":
                out.append("#### " + t)
            elif st == "List Bullet":
                out.append("- " + t)
            elif st == "List Number":
                out.append("1. " + t)
            else:
                out.append(t)
        else:
            rows = []
            for row in blk.rows:
                cells = [(c.text or "").strip().replace("\n", " / ") for c in row.cells]
                rows.append(cells)
            if not rows:
                continue
            width = max(len(r) for r in rows)
            out.append("| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |")
            out.append("|" + "---|" * width)
            for r in rows[1:]:
                out.append("| " + " | ".join(r + [""] * (width - len(r))) + " |")
            out.append("")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("lines:", len(out))


if __name__ == "__main__":
    main()