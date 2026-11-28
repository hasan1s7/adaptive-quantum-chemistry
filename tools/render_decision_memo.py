#!/usr/bin/env python3
"""Render the complete Markdown technical memo as a styled, linked PDF.

Requires pandoc, reportlab, matplotlib and Pillow. All source AST block types
must be handled explicitly; unsupported content raises instead of disappearing.
Math is rendered from its exact source TeX through Matplotlib mathtext.
"""
from __future__ import annotations
import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import subprocess
import tempfile

import matplotlib
matplotlib.use("Agg")
from matplotlib.mathtext import math_to_image
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, Image, KeepTogether, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor("#18323C")
TEXT = colors.HexColor("#263E46")
TEAL = colors.HexColor("#087E83")
MUTED = colors.HexColor("#64777D")
PALE = colors.HexColor("#EDF6F5")
RULE = colors.HexColor("#D4E1E2")
PAGE_W, PAGE_H = A4
MARGIN = 48
WIDTH = PAGE_W - 2 * MARGIN


def normalize(text):
    # Keep semantic punctuation while avoiding fragile nonbreaking dash glyphs.
    return text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2013", "-").replace("\u2014", " - ")


def fonts():
    base = Path("/usr/share/fonts/truetype/dejavu")
    for name, filename in {
        "Body": "DejaVuSerif.ttf", "BodyB": "DejaVuSerif-Bold.ttf",
        "BodyI": "DejaVuSerif-Italic.ttf", "BodyBI": "DejaVuSerif-BoldItalic.ttf",
        "Sans": "DejaVuSans.ttf", "SansB": "DejaVuSans-Bold.ttf",
        "SansI": "DejaVuSans-Oblique.ttf", "SansBI": "DejaVuSans-BoldOblique.ttf",
        "Mono": "DejaVuSansMono.ttf",
    }.items():
        pdfmetrics.registerFont(TTFont(name, str(base / filename)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyB", italic="BodyI", boldItalic="BodyBI")
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="SansB", italic="SansI", boldItalic="SansBI")


def styles():
    body = ParagraphStyle("Body", fontName="Body", fontSize=10.1, leading=14.8,
                          textColor=TEXT, spaceAfter=8, allowWidows=0, allowOrphans=0)
    return {
        "body": body,
        "title": ParagraphStyle("Title", fontName="SansB", fontSize=26, leading=31,
                                textColor=INK, spaceAfter=12),
        "subtitle": ParagraphStyle("Subtitle", fontName="Sans", fontSize=12, leading=17,
                                   textColor=MUTED, spaceAfter=5),
        "authors": ParagraphStyle("Authors", fontName="SansB", fontSize=10.4, leading=15,
                                  textColor=TEAL, spaceAfter=17),
        "h2": ParagraphStyle("H2", fontName="SansB", fontSize=15, leading=19.5,
                             textColor=INK, spaceBefore=17, spaceAfter=9, keepWithNext=1),
        "h3": ParagraphStyle("H3", fontName="SansB", fontSize=11.5, leading=15.6,
                             textColor=TEAL, spaceBefore=10, spaceAfter=6, keepWithNext=1),
        "decision": ParagraphStyle("Decision", parent=body, fontName="Sans", fontSize=10.2,
                                   leading=15, spaceAfter=0, textColor=INK),
        "scope": ParagraphStyle("Scope", parent=body, fontName="Sans", fontSize=8.8,
                                leading=12.3, textColor=MUTED, spaceAfter=0),
        "table": ParagraphStyle("TableBody", fontName="Sans", fontSize=8.1, leading=11.1,
                                textColor=TEXT, spaceAfter=0, splitLongWords=1),
        "table_head": ParagraphStyle("TableHead", fontName="SansB", fontSize=8.1, leading=11.3,
                                     textColor=colors.white, spaceAfter=0),
        "card": ParagraphStyle("Card", fontName="Sans", fontSize=9.1, leading=12.7,
                               textColor=TEXT, spaceAfter=4),
        "caption": ParagraphStyle("Caption", fontName="Sans", fontSize=8.3, leading=11.4,
                                  textColor=MUTED, spaceAfter=8),
        "ref": ParagraphStyle("Reference", fontName="Sans", fontSize=8.3, leading=12,
                              textColor=TEXT, spaceAfter=7, splitLongWords=1),
        "bullet": ParagraphStyle("Bullet", parent=body, leftIndent=12, firstLineIndent=-8,
                                 bulletIndent=0, spaceAfter=6),
    }


class NumberedCanvas(Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page_states = []
        self._page_outline_entries = []

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()
        self._page_outline_entries = []

    def save(self):
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            for key, title, level in self._page_outline_entries:
                self.bookmarkPage(key)
                self.addOutlineEntry(title, key, level=level, closed=False)
            self.setStrokeColor(RULE)
            self.setLineWidth(.5)
            self.line(MARGIN, 39, PAGE_W - MARGIN, 39)
            self.setFont("Sans", 7.4)
            self.setFillColor(MUTED)
            self.drawString(MARGIN, 25, "ERKIDU  /  Technical memo  /  27 November 2026")
            self.drawRightString(PAGE_W - MARGIN, 25, f"{self._pageNumber} / {total}")
            super().showPage()
        super().save()


class MemoDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if getattr(flowable, "outline_id", None):
            self.canv._page_outline_entries.append((flowable.outline_id,
                                                    flowable.getPlainText(),
                                                    flowable.outline_level))


def header(canvas, doc):
    canvas.saveState()
    canvas.setFont("SansB", 8)
    canvas.setFillColor(TEAL)
    canvas.drawString(MARGIN, PAGE_H - 28, "ERKIDU")
    canvas.setFont("Sans", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 28, "MLIP + DFT  /  DECISION SCIENCE")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(.6)
    canvas.line(MARGIN, PAGE_H - 37, PAGE_W - MARGIN, PAGE_H - 37)
    canvas.restoreState()


class Renderer:
    def __init__(self, source, scratch):
        self.source, self.scratch = source, scratch
        self.s = styles()
        self.links = []
        self.math = []
        self.block_counts = Counter()

    def inline(self, items):
        result = []
        for item in items:
            kind, content = item["t"], item.get("c")
            if kind == "Str":
                result.append(escape(normalize(content)))
            elif kind in {"Space", "SoftBreak"}:
                result.append(" ")
            elif kind == "LineBreak":
                result.append("<br/>")
            elif kind in {"Strong", "Emph"}:
                tag = "b" if kind == "Strong" else "i"
                result.append(f"<{tag}>" + self.inline(content) + f"</{tag}>")
            elif kind == "Code":
                result.append('<font name="Mono" size="8.4">' + escape(normalize(content[1])) + "</font>")
            elif kind == "Link":
                label, target = self.inline(content[1]), content[2][0]
                if (label, target) not in self.links:
                    self.links.append((label, target))
                index = self.links.index((label, target)) + 1
                result.append(f'<link href="{escape(target, quote=True)}" color="#087E83">{label}</link><super><font size="7">[{index}]</font></super>')
            elif kind == "Quoted":
                result.append("“" + self.inline(content[1]) + "”")
            elif kind == "Math":
                raise ValueError("Inline math needs an explicit renderer")
            elif kind == "Span":
                result.append(self.inline(content[1]))
            else:
                raise ValueError(f"Unsupported inline content: {kind}")
        return "".join(result)

    def cell(self, blocks):
        return "<br/>".join(self.inline(b["c"]) for b in blocks if b["t"] in {"Plain", "Para"})

    def equation(self, tex):
        self.math.append(tex.strip())
        normalized = tex.strip().rstrip(".")
        normalized = normalized.replace(r"\mathbb E", r"\mathbb{E}")
        normalized = normalized.replace(r"\overline L", r"\overline{L}").replace(r"\overline q", r"\overline{q}")
        normalized = normalized.replace(r"{\rm ref}", r"{\mathrm{ref}}").replace(r"{\rm model}", r"{\mathrm{model}}")
        image = self.scratch / f"equation-{len(self.math)}.png"
        math_to_image("$" + normalized + "$", str(image), dpi=300, format="png", color="#18323C")
        width, height = PILImage.open(image).size
        display_width = min(WIDTH - 24, width * 72 / 300 * 1.10)
        display_height = height / width * display_width
        picture = Image(str(image), display_width, display_height)
        picture.hAlign = "LEFT"
        box = Table([[picture]], colWidths=[WIDTH])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE),
                                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                                ("TOPPADDING", (0, 0), (-1, -1), 10),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        return [box, Spacer(1, 8)]

    def table(self, content):
        head = content[3][1]
        bodies = content[4]
        headers = [self.cell(c[4]) for c in head[0][1]]
        rows = [[self.cell(c[4]) for c in row[1]] for body in bodies for row in body[3]]
        if len(headers) >= 6:
            # A company-comparison card preserves every column without tiny type.
            result = []
            for row in rows:
                title = Paragraph(row[0], self.s["h3"])
                content_rows = [[Paragraph(f"<b>{label}</b>", self.s["card"]),
                                 Paragraph(value, self.s["card"])] for label, value in zip(headers[1:], row[1:])]
                card = Table(content_rows, colWidths=[92, WIDTH - 92])
                card.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                         ("BACKGROUND", (0, 0), (0, -1), PALE),
                                         ("LINEBELOW", (0, -1), (-1, -1), .4, RULE),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                         ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                                         ("TOPPADDING", (0, 0), (-1, -1), 5),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
                result.extend([KeepTogether([title, card]), Spacer(1, 6)])
            return result
        col_count = len(headers)
        if "SHA-256" in headers:
            widths = [125, 65, WIDTH - 190]
        elif col_count == 5:
            widths = [171, 82, 45, 99, WIDTH - 397]
        elif col_count == 4 and "Candidate workflow" in headers[0]:
            widths = [85, 125, 125, WIDTH - 335]
        elif col_count == 4:
            widths = [195, (WIDTH - 195) / 3, (WIDTH - 195) / 3, (WIDTH - 195) / 3]
        else:
            widths = [WIDTH * .49] + [WIDTH * .51 / (col_count - 1)] * (col_count - 1)
        grid = [[Paragraph(h, self.s["table_head"]) for h in headers]]
        grid += [[Paragraph(v, self.s["table"]) for v in row] for row in rows]
        table = Table(grid, colWidths=widths, repeatRows=1, hAlign="LEFT")
        rules = [("BACKGROUND", (0, 0), (-1, 0), INK),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 7),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                 ("TOPPADDING", (0, 0), (-1, -1), 7),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                 ("LINEBELOW", (0, 0), (-1, 0), .8, TEAL),
                 ("LINEBELOW", (0, -1), (-1, -1), .6, RULE)]
        for i in range(1, len(grid)):
            if i % 2:
                rules.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F1F5F6")))
        table.setStyle(TableStyle(rules))
        return [table, Spacer(1, 10)]

    def block(self, block, index):
        kind, content = block["t"], block.get("c")
        self.block_counts[kind] += 1
        if kind == "Header":
            level, attrs, items = content
            text = self.inline(items)
            if index == 0:
                return [Paragraph(text, self.s["title"])]
            if index == 1:
                return [Paragraph(text, self.s["subtitle"])]
            if index == 2:
                return [Paragraph(text, self.s["authors"])]
            p = Paragraph(text, self.s["h2" if level == 2 else "h3"])
            p.outline_id, p.outline_level = attrs[0] or f"h{index}", 0 if level == 2 else 1
            return [p]
        if kind in {"Para", "Plain"}:
            if len(content) == 1 and content[0]["t"] == "Math":
                return self.equation(content[0]["c"][1])
            text = self.inline(content)
            if index in {3, 4}:
                box = Table([[Paragraph(text, self.s["decision" if index == 3 else "scope"])]], colWidths=[WIDTH])
                box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE if index == 3 else colors.HexColor("#F5F7F7")),
                                        ("LINEBEFORE", (0, 0), (0, -1), 3 if index == 3 else 1, TEAL if index == 3 else RULE),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 12),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                                        ("TOPPADDING", (0, 0), (-1, -1), 11),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 11)]))
                return [box, Spacer(1, 10)]
            return [Paragraph(text, self.s["body"])]
        if kind == "Table":
            return self.table(content)
        if kind == "BulletList":
            result = []
            for item in content:
                for child in item:
                    if child["t"] not in {"Para", "Plain"}:
                        raise ValueError("Unsupported complex list")
                    result.append(Paragraph("• " + self.inline(child["c"]), self.s["bullet"]))
            return result
        raise ValueError(f"Unsupported block: {kind}")

    def build(self, output, figure=None):
        ast = json.loads(subprocess.check_output(["pandoc", str(self.source), "-f", "markdown+tex_math_single_backslash", "-t", "json"]))
        story = []
        for i, block in enumerate(ast["blocks"]):
            rendered = self.block(block, i)
            if not rendered:
                raise ValueError(f"Source block {i} disappeared")
            story.extend(rendered)
        if figure is not None:
            story.append(Paragraph("Appendix A. Recorded cost-risk frontier", self.s["h2"]))
            width, height = PILImage.open(figure).size
            display_width = WIDTH
            display_height = height / width * display_width
            story.append(Image(str(figure), display_width, display_height))
            story.append(Paragraph("Executed retrospective test results. Reference calls are historical relaxation-label acquisitions; no measured DFT runtime or monetary saving is inferred. The zero-query model baselines are part of the comparison.", self.s["caption"]))
        story.append(Paragraph("Source links cited in the memo", self.s["h2"]))
        for number, (label, target) in enumerate(self.links, 1):
            story.append(Paragraph(f"<b>[{number}] {label}</b><br/><link href=\"{escape(target, quote=True)}\" color=\"#087E83\">{escape(target)}</link>", self.s["ref"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        doc = MemoDoc(str(output), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                      topMargin=53, bottomMargin=52, title="Erkidu: MLIP and DFT decision engine",
                      author="Hasan Laith and Ahmad Alsheikh", subject="Executed replay results, decision model and company scope")
        doc.addPageTemplates(PageTemplate(id="memo", frames=[Frame(MARGIN, 52, WIDTH, PAGE_H - 105,
                                                                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=header))
        doc.build(story, canvasmaker=NumberedCanvas)
        return {"source_blocks_rendered": sum(self.block_counts.values()), "source_block_types": dict(self.block_counts),
                "equations_rendered": self.math, "source_links": self.links, "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "docs/decision_engine/TECHNICAL_MEMO.md")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--figure", type=Path, default=ROOT / "results/decision_engine/oxide_run/cost_risk_frontier.png")
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    fonts()
    report = Renderer(args.source, args.scratch).build(args.out, args.figure)
    (args.scratch / "render_receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
