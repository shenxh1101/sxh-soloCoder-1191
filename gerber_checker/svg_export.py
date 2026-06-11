import math
import os
from typing import List, Dict, Optional, Tuple

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)

LAYER_STROKE_COLORS = {
    LayerType.TOP_COPPER: "#CC0000",
    LayerType.BOTTOM_COPPER: "#0000CC",
    LayerType.TOP_SOLDER_MASK: "#9900CC",
    LayerType.BOTTOM_SOLDER_MASK: "#660099",
    LayerType.TOP_SILKSCREEN: "#CCCC00",
    LayerType.BOTTOM_SILKSCREEN: "#999900",
    LayerType.BOARD_OUTLINE: "#00CC00",
    LayerType.DRILL: "#009999",
    LayerType.INNER: "#CC6600",
    LayerType.UNKNOWN: "#888888",
}

LAYER_FILL_COLORS = {
    LayerType.TOP_COPPER: "#FF6666",
    LayerType.BOTTOM_COPPER: "#6666FF",
    LayerType.TOP_SOLDER_MASK: "#CC66FF",
    LayerType.BOTTOM_SOLDER_MASK: "#9944CC",
    LayerType.TOP_SILKSCREEN: "#EEEE66",
    LayerType.BOTTOM_SILKSCREEN: "#BBBB44",
    LayerType.BOARD_OUTLINE: "none",
    LayerType.DRILL: "#33AAAA",
    LayerType.UNKNOWN: "#AAAAAA",
}

LAYER_BG_COLORS = {
    LayerType.TOP_COPPER: "#1A0000",
    LayerType.BOTTOM_COPPER: "#00001A",
    LayerType.TOP_SOLDER_MASK: "#0F001A",
    LayerType.BOTTOM_SOLDER_MASK: "#0A0014",
    LayerType.TOP_SILKSCREEN: "#1A1A00",
    LayerType.BOTTOM_SILKSCREEN: "#141400",
    LayerType.BOARD_OUTLINE: "#FFFFFF",
    LayerType.DRILL: "#FFFFFF",
    LayerType.UNKNOWN: "#FFFFFF",
}


class SVGExporter:
    def __init__(self, scale: float = 10.0, margin: float = 20.0):
        self.scale = scale
        self.margin = margin
        self._element_id = 0

    def export_layer(self, layer: LayerData, output_path: str, width: int = 800, height: int = 600):
        min_x, min_y, max_x, max_y = layer.bounding_box
        if max_x <= min_x:
            max_x = min_x + 100
        if max_y <= min_y:
            max_y = min_y + 100

        board_w = max_x - min_x
        board_h = max_y - min_y

        view_w = board_w * self.scale + 2 * self.margin
        view_h = board_h * self.scale + 2 * self.margin

        layer_color = LAYER_STROKE_COLORS.get(layer.layer_type, "#000000")
        layer_fill = LAYER_FILL_COLORS.get(layer.layer_type, "none")

        svg_parts = []
        svg_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        svg_parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {view_w:.1f} {view_h:.1f}" '
            f'width="{width}" height="{height}">'
        )
        svg_parts.append('<style>')
        svg_parts.append(f'.layer-path {{ fill: none; stroke: {layer_color}; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }}')
        svg_parts.append(f'.layer-fill {{ fill: {layer_fill}; fill-opacity: 0.3; stroke: {layer_color}; stroke-width: 1.0; }}')
        svg_parts.append(f'.layer-pad {{ fill: {layer_color}; stroke: none; }}')
        svg_parts.append(f'.layer-hole {{ fill: #FFFFFF; stroke: {layer_color}; stroke-width: 1.0; }}')
        svg_parts.append('</style>')

        if layer.layer_type != LayerType.DRILL:
            bg_color = LAYER_BG_COLORS.get(layer.layer_type, "#FFFFFF")
            svg_parts.append(
                f'<rect x="0" y="0" width="{view_w:.1f}" height="{view_h:.1f}" fill="{bg_color}"/>'
            )

        svg_parts.append(f'<g transform="translate({self.margin:.1f},{self.margin:.1f}) scale({self.scale},{-self.scale}) '
                         f'translate({-min_x:.3f},{-max_y:.3f})">')

        region_primitives = []
        other_primitives = []
        for p in layer.primitives:
            if isinstance(p, RegionPrimitive):
                region_primitives.append(p)
            else:
                other_primitives.append(p)

        for prim in region_primitives:
            self._render_primitive(svg_parts, prim, is_region=True)

        for prim in other_primitives:
            self._render_primitive(svg_parts, prim)

        if layer.drill_holes:
            for hole in layer.drill_holes:
                self._render_drill_hole(svg_parts, hole)

        svg_parts.append('</g>')
        svg_parts.append('</svg>')

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(svg_parts))

    def _render_primitive(self, parts: List[str], prim, is_region: bool = False):
        from .models import LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive

        self._element_id += 1
        eid = self._element_id

        if isinstance(prim, LinePrimitive):
            parts.append(
                f'<line class="layer-path" x1="{prim.start.x:.3f}" y1="{prim.start.y:.3f}" '
                f'x2="{prim.end.x:.3f}" y2="{prim.end.y:.3f}" '
                f'id="l{eid}"/>'
            )
        elif isinstance(prim, ArcPrimitive):
            radius = prim.center.distance_to(prim.start)
            start_angle = math.degrees(math.atan2(prim.start.y - prim.center.y, prim.start.x - prim.center.x))
            end_angle = math.degrees(math.atan2(prim.end.y - prim.center.y, prim.end.x - prim.center.x))

            if prim.direction == "G02":
                start_angle, end_angle = end_angle, start_angle

            large_arc = 0 if abs(end_angle - start_angle) <= 180 else 1
            sweep = 0 if prim.direction == "G02" else 1

            parts.append(
                f'<path class="layer-path" d="M {prim.start.x:.3f} {prim.start.y:.3f} '
                f'A {radius:.3f} {radius:.3f} 0 {large_arc} {sweep} '
                f'{prim.end.x:.3f} {prim.end.y:.3f}" '
                f'id="l{eid}"/>'
            )
        elif isinstance(prim, FlashPrimitive):
            if prim.aperture:
                if prim.aperture.shape.value == "C":
                    r = prim.aperture.params[0] / 2 if prim.aperture.params else 1.0
                    parts.append(
                        f'<circle class="layer-pad" cx="{prim.position.x:.3f}" cy="{prim.position.y:.3f}" '
                        f'r="{r:.3f}" id="l{eid}"/>'
                    )
                elif prim.aperture.shape.value == "R":
                    w = prim.aperture.params[0] / 2 if prim.aperture.params else 1.0
                    h = (prim.aperture.params[1] / 2) if len(prim.aperture.params) > 1 else w
                    parts.append(
                        f'<rect class="layer-pad" x="{prim.position.x - w:.3f}" y="{prim.position.y - h:.3f}" '
                        f'width="{w*2:.3f}" height="{h*2:.3f}" id="l{eid}"/>'
                    )
                else:
                    r = prim.aperture.params[0] / 2 if prim.aperture.params else 1.0
                    parts.append(
                        f'<circle class="layer-pad" cx="{prim.position.x:.3f}" cy="{prim.position.y:.3f}" '
                        f'r="{r:.3f}" id="l{eid}"/>'
                    )
        elif isinstance(prim, RegionPrimitive):
            if len(prim.points) >= 3:
                d = f'M {prim.points[0].x:.3f} {prim.points[0].y:.3f} '
                for pt in prim.points[1:]:
                    d += f'L {pt.x:.3f} {pt.y:.3f} '
                d += 'Z'
                cls = "layer-fill" if is_region else "layer-path"
                parts.append(f'<path class="{cls}" d="{d}" id="l{eid}"/>')

    def _render_drill_hole(self, parts: List[str], hole: DrillHole):
        self._element_id += 1
        eid = self._element_id
        r = hole.tool_diameter / 2
        parts.append(
            f'<circle class="layer-hole" cx="{hole.position.x:.3f}" cy="{hole.position.y:.3f}" '
            f'r="{r:.3f}" id="l{eid}"/>'
        )

    def export_board_all_layers(self, board: BoardData, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        for name, layer in board.layers.items():
            safe_name = name.replace(".", "_").replace(" ", "_")
            out_path = os.path.join(output_dir, f"{safe_name}.svg")
            self.export_layer(layer, out_path)


def export_layer_svg(layer: LayerData, output_path: str):
    exporter = SVGExporter()
    exporter.export_layer(layer, output_path)


def export_board_svg(board: BoardData, output_dir: str):
    exporter = SVGExporter()
    exporter.export_board_all_layers(board, output_dir)