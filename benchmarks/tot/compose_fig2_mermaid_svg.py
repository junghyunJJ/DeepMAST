#!/usr/bin/env python3
"""Insert rendered workflow PNGs into the empty A/B slots of fig2.

Mermaid's SVG labels can render poorly outside browsers, so the composed SVG
embeds the browser-rendered workflow PNGs for stable journal/PDF conversion.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path


TOP_ROW_REL_HEIGHT = 0.0
DIAGRAM_REL_HEIGHT_WITHIN_LOWER_ROW = 0.65
COVER_SIDE_MARGIN = 20.0
COVER_TOP_MARGIN = 25.0
COVER_BOTTOM_MARGIN = 10.0
FLOW_SIDE_MARGIN = 40.0
FLOW_TOP_MARGIN = 30.0
FLOW_BOTTOM_MARGIN = 10.0


def _extract_document_view_box(svg_text: str) -> str:
    match = re.search(r"<svg\b([^>]*)>", svg_text, flags=re.DOTALL)
    if not match:
        raise ValueError("Base SVG is missing an <svg> tag")

    view_box_match = re.search(r"\bviewBox=(['\"])(.*?)\1", match.group(1))
    if not view_box_match:
        raise ValueError("Base SVG is missing a viewBox")

    return view_box_match.group(2)


def _parse_view_box(view_box: str) -> tuple[float, float, float, float]:
    parts = [float(part) for part in re.split(r"[\s,]+", view_box.strip()) if part]
    if len(parts) != 4:
        raise ValueError(f"Invalid viewBox: {view_box}")

    return parts[0], parts[1], parts[2], parts[3]


def _png_data_uri(png_path: Path) -> str:
    if not png_path.exists():
        raise FileNotFoundError(f"Missing rendered workflow PNG: {png_path}")

    encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _panel_geometry(
    *,
    base_view_box: str,
    mermaid_view_box: str,
    panel_index: int,
) -> tuple[dict[str, float], dict[str, float]]:
    _, _, base_width, base_height = _parse_view_box(base_view_box)
    _, _, mermaid_width, mermaid_height = _parse_view_box(mermaid_view_box)

    panel_width = base_width / 2
    panel_x = panel_width * panel_index
    diagram_y = base_height * TOP_ROW_REL_HEIGHT
    diagram_height = (
        base_height
        * (1 - TOP_ROW_REL_HEIGHT)
        * DIAGRAM_REL_HEIGHT_WITHIN_LOWER_ROW
    )

    max_flow_width = panel_width - (2 * FLOW_SIDE_MARGIN)
    max_flow_height = diagram_height - FLOW_TOP_MARGIN - FLOW_BOTTOM_MARGIN
    aspect_ratio = mermaid_width / mermaid_height

    flow_height = max_flow_height
    flow_width = flow_height * aspect_ratio
    if flow_width > max_flow_width:
        flow_width = max_flow_width
        flow_height = flow_width / aspect_ratio

    cover = {
        "x": panel_x + COVER_SIDE_MARGIN,
        "y": diagram_y + COVER_TOP_MARGIN,
        "width": panel_width - (2 * COVER_SIDE_MARGIN),
        "height": diagram_height - COVER_TOP_MARGIN - COVER_BOTTOM_MARGIN,
    }
    flow = {
        "x": panel_x + ((panel_width - flow_width) / 2),
        "y": diagram_y + FLOW_TOP_MARGIN,
        "width": flow_width,
        "height": flow_height,
    }

    return cover, flow


def _make_insert(
    *,
    base_view_box: str,
    source_svg: Path,
    group_id: str,
    svg_id: str,
    panel_index: int,
) -> str:
    view_box = _extract_document_view_box(source_svg.read_text(encoding="utf-8"))
    png_data_uri = _png_data_uri(source_svg.with_suffix(".png"))
    cover, flow = _panel_geometry(
        base_view_box=base_view_box,
        mermaid_view_box=view_box,
        panel_index=panel_index,
    )

    return f"""
<g id="{group_id}">
  <rect x="{cover['x']:.2f}" y="{cover['y']:.2f}" width="{cover['width']:.2f}" height="{cover['height']:.2f}" style="stroke: none; fill: #FFFFFF;" />
  <image id="{svg_id}" x="{flow['x']:.2f}" y="{flow['y']:.2f}" width="{flow['width']:.2f}" height="{flow['height']:.2f}" href="{png_data_uri}" preserveAspectRatio="xMidYMid meet" />
</g>
"""


def compose(base_svg: Path, d_svg: Path, e_svg: Path, output_svg: Path) -> None:
    base_text = base_svg.read_text(encoding="utf-8")
    base_view_box = _extract_document_view_box(base_text)

    insertions = [
        _make_insert(
            base_view_box=base_view_box,
            source_svg=d_svg,
            group_id="fig2-panel-d-mermaid-flow",
            svg_id="fig2-panel-d-svg",
            panel_index=0,
        ),
        _make_insert(
            base_view_box=base_view_box,
            source_svg=e_svg,
            group_id="fig2-panel-e-mermaid-flow",
            svg_id="fig2-panel-e-svg",
            panel_index=1,
        ),
    ]

    if "</svg>" not in base_text:
        raise ValueError("Base SVG is missing a closing </svg> tag")

    output_text = base_text.rsplit("</svg>", 1)[0] + "".join(insertions) + "</svg>\n"
    output_svg.write_text(output_text, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            "usage: compose_fig2_mermaid_svg.py BASE_SVG D_SVG E_SVG OUTPUT_SVG",
            file=sys.stderr,
        )
        return 2

    compose(Path(argv[1]), Path(argv[2]), Path(argv[3]), Path(argv[4]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
