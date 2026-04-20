"""Generate SkillLoadHarness benchmark figures as PPTX slides.

Slide 1: SkillLoadHarness Protocol flowchart
Slide 2: Passive Listing vs SkillLoadHarness comparison with metrics
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pathlib import Path

# Colors
PINK = RGBColor(0xCC, 0x79, 0xA7)
GREY = RGBColor(0x99, 0x99, 0x99)
GREEN = RGBColor(0x00, 0x9E, 0x73)
ORANGE = RGBColor(0xE6, 0x9F, 0x00)
RED = RGBColor(0xD5, 0x5E, 0x00)
BLUE = RGBColor(0x21, 0x96, 0xF3)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x00, 0x00, 0x00)
LIGHT_PINK = RGBColor(0xF3, 0xE5, 0xF5)
LIGHT_GREEN = RGBColor(0xE8, 0xF5, 0xE9)
LIGHT_ORANGE = RGBColor(0xFF, 0xF3, 0xE0)
LIGHT_RED = RGBColor(0xFF, 0xEB, 0xEE)
LIGHT_GREY = RGBColor(0xF5, 0xF5, 0xF5)
LIGHT_YELLOW = RGBColor(0xFF, 0xFD, 0xE7)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def _add_box(slide, left, top, width, height, fill_color, border_color, text="",
             font_size=10, bold=False, font_color=BLACK, align=PP_ALIGN.CENTER, line_width=Pt(1)):
    """Add a rounded rectangle with text."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.color.rgb = border_color
    shape.line.width = line_width
    shape.shadow.inherit = False

    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Pt(6)
    tf.margin_right = Pt(6)
    tf.margin_top = Pt(4)
    tf.margin_bottom = Pt(4)

    if text:
        for i, line in enumerate(text.split("\n")):
            if i == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.text = line
            p.font.size = Pt(font_size)
            p.font.color.rgb = font_color
            if bold and i == 0:
                p.font.bold = True
            p.alignment = align

    return shape


def _add_arrow(slide, x1, y1, x2, y2, color=BLACK):
    """Add a connector arrow."""
    connector = slide.shapes.add_connector(
        1, x1, y1, x2, y2  # MSO_CONNECTOR.STRAIGHT
    )
    connector.line.color.rgb = color
    connector.line.width = Pt(1.5)
    # Add arrowhead
    connector.end_x = x2
    connector.end_y = y2
    return connector


def _add_text(slide, left, top, width, height, text, font_size=10,
              font_color=BLACK, bold=False, align=PP_ALIGN.LEFT):
    """Add a plain text box."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text.split("\n")):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = line
        p.font.size = Pt(font_size)
        p.font.color.rgb = font_color
        p.font.bold = bold if i == 0 else False
        p.alignment = align
    return txBox


def make_slide1_protocol(prs):
    """Slide 1: SkillLoadHarness Protocol flowchart."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Title
    _add_text(slide, Inches(0.5), Inches(0.2), Inches(12), Inches(0.5),
              "SkillLoadHarness Evaluation Protocol", font_size=24, bold=True, font_color=PINK,
              align=PP_ALIGN.CENTER)
    _add_text(slide, Inches(0.5), Inches(0.65), Inches(12), Inches(0.3),
              "Middleware — injected into system prompt as structured evaluation instructions",
              font_size=12, font_color=GREY, align=PP_ALIGN.CENTER)

    cx = Inches(6.666)  # center x
    bw = Inches(5)      # box width

    # User Task
    _add_box(slide, cx - bw/2, Inches(1.2), bw, Inches(0.5),
             RGBColor(0xE3, 0xF2, 0xFD), BLUE,
             "User Task", font_size=14, bold=True, font_color=BLUE)

    # Phase 1
    _add_box(slide, cx - bw/2, Inches(2.0), bw, Inches(1.2),
             WHITE, PINK,
             "Phase 1: QUICK SCREEN\n\n\"Does this task require reading a skill guide\nfor interpreting results or planning a query strategy?\"\n\nDefault answer: NO",
             font_size=11, bold=True, font_color=BLACK)

    # YES / NO branches
    # YES arrow (left-center)
    _add_text(slide, cx - Inches(1.8), Inches(3.3), Inches(0.6), Inches(0.3),
              "YES", font_size=10, font_color=PINK, bold=True, align=PP_ALIGN.CENTER)
    # NO arrow (right-center)
    _add_text(slide, cx + Inches(1.3), Inches(3.3), Inches(0.5), Inches(0.3),
              "NO", font_size=10, font_color=ORANGE, bold=True, align=PP_ALIGN.CENTER)

    # Phase 2 (left branch)
    p2_left = cx - bw/2 - Inches(0.5)
    p2_w = Inches(4.5)
    _add_box(slide, p2_left, Inches(3.8), p2_w, Inches(1.8),
             WHITE, PINK,
             "Phase 2: EVALUATE\n\nFor each registered skill:\nSkill 1: [desc] -> YES / NO + reason\nSkill 2: [desc] -> YES / NO + reason\n...\nSkill N: [desc] -> YES / NO + reason\n\nRules: 1. Context match -> YES  2. When in doubt -> NO",
             font_size=10, bold=True, font_color=BLACK)

    # NO_SKILLS_NEEDED (right branch)
    skip_left = cx + Inches(0.5)
    _add_box(slide, skip_left, Inches(3.8), Inches(3.5), Inches(0.8),
             LIGHT_ORANGE, ORANGE,
             "NO_SKILLS_NEEDED\nSkip directly to Phase 3",
             font_size=11, bold=True, font_color=BLACK)

    # read_skill_file box
    _add_box(slide, p2_left + Inches(0.5), Inches(5.9), Inches(3.5), Inches(0.6),
             LIGHT_GREEN, GREEN,
             "read_skill_file(path)\nLoad selected SKILL.md guides into context",
             font_size=10, bold=True, font_color=BLACK)

    # Phase 3
    _add_box(slide, cx - bw/2, Inches(6.7), bw, Inches(0.6),
             WHITE, PINK,
             "Phase 3: IMPLEMENT — Execute the task with activated skill guidance",
             font_size=12, bold=True, font_color=BLACK)


def make_slide2_comparison(prs):
    """Slide 2: Passive Listing vs SkillLoadHarness with metrics."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Title
    _add_text(slide, Inches(0.5), Inches(0.15), Inches(12), Inches(0.4),
              "Passive Skill Listing vs SkillLoadHarness Protocol", font_size=22, bold=True,
              font_color=BLACK, align=PP_ALIGN.CENTER)
    _add_text(slide, Inches(0.5), Inches(0.55), Inches(12), Inches(0.3),
              "qwen3.5:122b | 7 categories x 20 prompts = 140 trials | 420 paired skill-decisions",
              font_size=11, font_color=GREY, align=PP_ALIGN.CENTER)

    # === Column A: Passive ===
    ax = Inches(0.3)
    aw = Inches(4.0)

    _add_box(slide, ax, Inches(1.1), aw, Inches(0.5),
             LIGHT_GREY, GREY,
             "(A) Passive Listing", font_size=14, bold=True, font_color=GREY)

    _add_box(slide, ax + Inches(0.2), Inches(1.8), aw - Inches(0.4), Inches(1.2),
             WHITE, GREY,
             'System Prompt:\n"Available Skills:\n  - Skill 1: desc\n  - Skill 2: desc\n  - Skill N: desc"',
             font_size=10, font_color=BLACK)

    _add_box(slide, ax + Inches(0.2), Inches(3.2), aw - Inches(0.4), Inches(0.7),
             LIGHT_ORANGE, ORANGE,
             "LLM decides implicitly\nNo forced evaluation, no gate question",
             font_size=10, bold=True, font_color=BLACK)

    _add_box(slide, ax + Inches(0.2), Inches(4.1), aw - Inches(0.4), Inches(1.2),
             LIGHT_RED, RED,
             "Failure modes:\n\nx  Over-activation (FP) — \"might be useful\" bias\nx  Under-activation (FN) — skills overlooked\nx  No reasoning trace — opaque decisions",
             font_size=9, bold=True, font_color=RED)

    # Metrics A
    _add_box(slide, ax, Inches(5.5), aw, Inches(1.3),
             WHITE, GREY,
             "F1 = 81.7%\nPrecision = 96.6%  |  Recall = 70.8%\nFP rate = 2.5%",
             font_size=13, bold=True, font_color=GREY)

    # === Column B: SkillLoadHarness ===
    bx = Inches(4.7)
    bwidth = Inches(4.0)

    _add_box(slide, bx, Inches(1.1), bwidth, Inches(0.5),
             LIGHT_PINK, PINK,
             "(B) SkillLoadHarness", font_size=14, bold=True, font_color=PINK)

    _add_box(slide, bx + Inches(0.2), Inches(1.8), bwidth - Inches(0.4), Inches(0.6),
             WHITE, PINK,
             "Phase 1: QUICK SCREEN\nGate question  |  Default: NO",
             font_size=10, bold=True, font_color=PINK)

    _add_box(slide, bx + Inches(0.2), Inches(2.55), bwidth - Inches(0.4), Inches(0.7),
             WHITE, PINK,
             "Phase 2: EVALUATE\nPer-skill YES/NO + explicit reasoning",
             font_size=10, bold=True, font_color=PINK)

    _add_box(slide, bx + Inches(0.2), Inches(3.4), bwidth - Inches(0.4), Inches(0.5),
             WHITE, PINK,
             "Phase 3: IMPLEMENT\nExecute with loaded guidance",
             font_size=10, bold=True, font_color=PINK)

    _add_box(slide, bx + Inches(0.2), Inches(4.1), bwidth - Inches(0.4), Inches(1.2),
             LIGHT_GREEN, GREEN,
             "Mitigations:\n\n+  Gate filters irrelevant tasks\n+  Explicit eval forces consideration\n+  Auditable YES/NO reasoning",
             font_size=9, bold=True, font_color=GREEN)

    # Metrics B
    _add_box(slide, bx, Inches(5.5), bwidth, Inches(1.3),
             WHITE, PINK,
             "F1 = 94.8%\nPrecision = 98.2%  |  Recall = 91.7%\nFP rate = 1.2%",
             font_size=13, bold=True, font_color=PINK)

    # === Column C: Statistical Results ===
    cx = Inches(9.1)
    cw = Inches(4.0)

    _add_box(slide, cx, Inches(1.1), cw, Inches(0.5),
             LIGHT_GREEN, GREEN,
             "Statistical Results", font_size=14, bold=True, font_color=GREEN)

    _add_box(slide, cx + Inches(0.2), Inches(1.8), cw - Inches(0.4), Inches(1.8),
             WHITE, GREEN,
             "Bootstrap F1 Difference\n(10,000 resamples, prompt-level)\n\ndF1 = +13.1%\n95% CI = [+6.7%, +20.8%]\np < 0.001",
             font_size=11, bold=True, font_color=BLACK)

    _add_box(slide, cx + Inches(0.2), Inches(3.8), cw - Inches(0.4), Inches(1.5),
             WHITE, GREEN,
             "McNemar's Exact Test\n(420 paired decisions)\n\nDiscordant: b=2, c=28\nOdds ratio = 14.0\np = 0.000001 ***",
             font_size=11, bold=True, font_color=BLACK)

    _add_box(slide, cx + Inches(0.2), Inches(5.5), cw - Inches(0.4), Inches(1.3),
             LIGHT_YELLOW, RGBColor(0xF9, 0xA8, 0x25),
             "Effect Size\n\nCohen's h = 0.42\n(small-to-medium)\n\nRecall improvement\nis the primary driver: +20.8%p",
             font_size=10, bold=True, font_color=BLACK)


def main():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    make_slide1_protocol(prs)
    make_slide2_comparison(prs)

    out_dir = Path(__file__).parent
    out_path = out_dir / "fig_skill_harness.pptx"
    prs.save(str(out_path))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
