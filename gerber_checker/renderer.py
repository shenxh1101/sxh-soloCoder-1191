import math
import shutil
from typing import List, Dict, Optional, Tuple

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)

LAYER_CHARS = {
    LayerType.TOP_COPPER: "█",
    LayerType.BOTTOM_COPPER: "▓",
    LayerType.TOP_SOLDER_MASK: "░",
    LayerType.BOTTOM_SOLDER_MASK: "▒",
    LayerType.TOP_SILKSCREEN: "○",
    LayerType.BOTTOM_SILKSCREEN: "●",
    LayerType.BOARD_OUTLINE: "╋",
    LayerType.DRILL: "◉",
    LayerType.INNER: "╌",
    LayerType.UNKNOWN: "?",
}

LAYER_COLORS_ANSI = {
    LayerType.TOP_COPPER: "\033[31m",
    LayerType.BOTTOM_COPPER: "\033[34m",
    LayerType.TOP_SOLDER_MASK: "\033[35m",
    LayerType.BOTTOM_SOLDER_MASK: "\033[35m",
    LayerType.TOP_SILKSCREEN: "\033[33m",
    LayerType.BOTTOM_SILKSCREEN: "\033[33m",
    LayerType.BOARD_OUTLINE: "\033[37m",
    LayerType.DRILL: "\033[32m",
    LayerType.UNKNOWN: "\033[0m",
}
ANSI_RESET = "\033[0m"


class ASCIITerminalRenderer:
    def __init__(self, width: int = None, height: int = None):
        term_size = shutil.get_terminal_size((80, 24))
        self.width = width or min(term_size.columns - 2, 120)
        self.height = height or min(term_size.lines - 4, 60)
        self._grid: List[List[str]] = []
        self._color_grid: List[List[str]] = []
        self.use_color: bool = True

    def render_layer(self, layer: LayerData) -> str:
        min_x, min_y, max_x, max_y = layer.bounding_box
        if max_x <= min_x or max_y <= min_y:
            return f"  [Empty layer: {layer.name}]"

        scale, scale_y, offset_x, offset_y = self._compute_transform(
            min_x, min_y, max_x, max_y
        )
        scale_x = scale

        self._init_grid()

        if layer.drill_holes:
            self._draw_drill_holes(layer.drill_holes, scale_x, scale_y, offset_x, offset_y, min_x, min_y, layer.layer_type)
        for prim in layer.primitives:
            self._draw_primitive(prim, scale_x, scale_y, offset_x, offset_y, min_x, min_y, layer.layer_type)

        return self._render_grid(min_x, min_y, max_x, max_y, layer.name, layer.layer_type)

    def render_board(self, board: BoardData) -> str:
        min_x, min_y, max_x, max_y = board.total_bounding_box
        if max_x <= min_x or max_y <= min_y:
            return "  [Empty board - no data]"

        scale, scale_y, offset_x, offset_y = self._compute_transform(
            min_x, min_y, max_x, max_y
        )
        scale_x = scale

        self._init_grid()

        for layer in board.layers.values():
            if layer.drill_holes:
                self._draw_drill_holes(layer.drill_holes, scale_x, scale_y, offset_x, offset_y, min_x, min_y, layer.layer_type)
            for prim in layer.primitives:
                self._draw_primitive(prim, scale_x, scale_y, offset_x, offset_y, min_x, min_y, layer.layer_type)

        return self._render_grid_overview(min_x, min_y, max_x, max_y, board)

    def _compute_transform(self, min_x, min_y, max_x, max_y):
        board_w = max_x - min_x
        board_h = max_y - min_y
        if board_w < 0.001:
            board_w = 0.001
        if board_h < 0.001:
            board_h = 0.001

        scale_x = (self.width - 2) / board_w
        scale_y = (self.height - 2) / board_h
        scale = min(scale_x, scale_y)

        draw_w = int(board_w * scale)
        draw_h = int(board_h * scale)
        offset_x = (self.width - draw_w) // 2
        offset_y = (self.height - draw_h) // 2

        return scale, scale, offset_x, offset_y

    def _init_grid(self):
        self._grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        self._color_grid = [["" for _ in range(self.width)] for _ in range(self.height)]

    def _draw_point(self, gx: int, gy: int, char: str, color: str = ""):
        if 0 <= gx < self.width and 0 <= gy < self.height:
            self._grid[gy][gx] = char
            self._color_grid[gy][gx] = color

    def _project(self, x: float, y: float, scale: float, ox: float, oy: float,
                  bbox_min_x: float, bbox_min_y: float) -> Tuple[int, int]:
        gx = int((x - bbox_min_x) * scale + ox)
        gy = self.height - 1 - int((y - bbox_min_y) * scale + oy)
        return gx, gy

    def _draw_drill_holes(self, holes: List[DrillHole], scale_x, scale_y, offset_x, offset_y,
                            bbox_min_x, bbox_min_y, layer_type):
        char = LAYER_CHARS.get(layer_type, "?")
        color = LAYER_COLORS_ANSI.get(layer_type, "")
        for hole in holes:
            gx, gy = self._project(hole.position.x, hole.position.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)
            radius_px = max(1, int(hole.tool_diameter * scale_x / 2))
            for dx in range(-radius_px, radius_px + 1):
                for dy in range(-radius_px, radius_px + 1):
                    if dx * dx + dy * dy <= radius_px * radius_px:
                        self._draw_point(gx + dx, gy + dy, char, color)

    def _draw_primitive(self, prim, scale_x, scale_y, offset_x, offset_y, bbox_min_x, bbox_min_y, layer_type):
        char = LAYER_CHARS.get(layer_type, "?")
        color = LAYER_COLORS_ANSI.get(layer_type, "")

        if not prim.polarity:
            return

        if isinstance(prim, LinePrimitive):
            self._draw_line_primitive(prim, scale_x, scale_y, offset_x, offset_y, bbox_min_x, bbox_min_y, char, color)
        elif isinstance(prim, ArcPrimitive):
            self._draw_arc_primitive(prim, scale_x, scale_y, offset_x, offset_y, bbox_min_x, bbox_min_y, char, color)
        elif isinstance(prim, FlashPrimitive):
            self._draw_flash_primitive(prim, scale_x, scale_y, offset_x, offset_y, bbox_min_x, bbox_min_y, char, color)
        elif isinstance(prim, RegionPrimitive):
            self._draw_region_primitive(prim, scale_x, scale_y, offset_x, offset_y, bbox_min_x, bbox_min_y, char, color)

    def _draw_line_primitive(self, prim: LinePrimitive, scale_x, scale_y, offset_x, offset_y,
                               bbox_min_x, bbox_min_y, char, color):
        gx1, gy1 = self._project(prim.start.x, prim.start.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)
        gx2, gy2 = self._project(prim.end.x, prim.end.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)
        self._raster_line(gx1, gy1, gx2, gy2, char, color)

        width_px = 1
        if prim.aperture and prim.aperture.params:
            width_px = max(1, int(prim.aperture.params[0] * scale_x))
        for w in range(1, width_px):
            self._raster_line(gx1 + w, gy1, gx2 + w, gy2, char, color)
            self._raster_line(gx1, gy1 + w, gx2, gy2 + w, char, color)

    def _draw_arc_primitive(self, prim: ArcPrimitive, scale_x, scale_y, offset_x, offset_y,
                              bbox_min_x, bbox_min_y, char, color):
        cgx, cgy = self._project(prim.center.x, prim.center.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)
        sgx, sgy = self._project(prim.start.x, prim.start.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)
        egx, egy = self._project(prim.end.x, prim.end.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)

        radius = math.hypot(sgx - cgx, sgy - cgy)
        if radius < 1:
            return

        start_angle = math.atan2(sgy - cgy, sgx - cgx)
        end_angle = math.atan2(egy - cgy, egx - cgx)

        if prim.direction == "G03":
            if end_angle <= start_angle:
                end_angle += 2 * math.pi
            step = 0.5 / radius
            angle = start_angle
            prev_x, prev_y = None, None
            while angle <= end_angle:
                px = int(cgx + radius * math.cos(angle))
                py = int(cgy + radius * math.sin(angle))
                if prev_x is not None:
                    self._raster_line(prev_x, prev_y, px, py, char, color)
                self._draw_point(px, py, char, color)
                prev_x, prev_y = px, py
                angle += step
        else:
            if start_angle <= end_angle:
                start_angle += 2 * math.pi
            step = 0.5 / radius
            angle = start_angle
            prev_x, prev_y = None, None
            while angle >= end_angle:
                px = int(cgx + radius * math.cos(angle))
                py = int(cgy + radius * math.sin(angle))
                if prev_x is not None:
                    self._raster_line(prev_x, prev_y, px, py, char, color)
                self._draw_point(px, py, char, color)
                prev_x, prev_y = px, py
                angle -= step

        self._draw_point(sgx, sgy, char, color)
        self._draw_point(egx, egy, char, color)

    def _draw_flash_primitive(self, prim: FlashPrimitive, scale_x, scale_y, offset_x, offset_y,
                                bbox_min_x, bbox_min_y, char, color):
        gx, gy = self._project(prim.position.x, prim.position.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y)

        if prim.aperture and prim.aperture.params:
            if prim.aperture.shape.value == "C":
                radius = max(1, int(prim.aperture.params[0] * scale_x / 2))
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        if dx * dx + dy * dy <= radius * radius:
                            self._draw_point(gx + dx, gy + dy, char, color)
            elif prim.aperture.shape.value == "R":
                w = max(1, int(prim.aperture.params[0] * scale_x / 2))
                h = max(1, int((prim.aperture.params[1] if len(prim.aperture.params) > 1 else prim.aperture.params[0]) * scale_y / 2))
                for dx in range(-w, w + 1):
                    for dy in range(-h, h + 1):
                        self._draw_point(gx + dx, gy + dy, char, color)
            else:
                self._draw_point(gx, gy, "■", color)
        else:
            self._draw_point(gx, gy, "■", color)

    def _draw_region_primitive(self, prim: RegionPrimitive, scale_x, scale_y, offset_x, offset_y,
                                 bbox_min_x, bbox_min_y, char, color):
        if len(prim.points) < 3:
            return
        pts = [self._project(p.x, p.y, scale_x, offset_x, offset_y, bbox_min_x, bbox_min_y) for p in prim.points]
        self._fill_polygon(pts, char, color)
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            self._raster_line(x1, y1, x2, y2, char, color)

    def _raster_line(self, x0: int, y0: int, x1: int, y1: int, char: str, color: str):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            self._draw_point(x0, y0, char, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _fill_polygon(self, points: List[Tuple[int, int]], char: str, color: str):
        if not points:
            return
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)

        for y in range(min_y, max_y + 1):
            intersections = []
            for i in range(len(points)):
                x1, y1 = points[i]
                x2, y2 = points[(i + 1) % len(points)]
                if y1 == y2:
                    continue
                if min(y1, y2) <= y < max(y1, y2):
                    t = (y - y1) / (y2 - y1)
                    x_int = x1 + t * (x2 - x1)
                    intersections.append(x_int)
            intersections.sort()
            for i in range(0, len(intersections) - 1, 2):
                x_start = max(0, int(intersections[i]))
                x_end = min(self.width - 1, int(intersections[i + 1]))
                for x in range(x_start, x_end + 1):
                    self._draw_point(x, y, char, color)

    def _render_grid(self, min_x, min_y, max_x, max_y, name, layer_type) -> str:
        lines = []
        lines.append(f"╔{'═' * (self.width)}╗")
        title = f" Layer: {name} ({layer_type.value}) "
        header = f"║{title:^{self.width}}║"
        lines.append(header)
        lines.append(f"╠{'═' * (self.width)}╣")

        last_color = ""
        for y in range(self.height):
            row = "║"
            for x in range(self.width):
                col = self._color_grid[y][x]
                ch = self._grid[y][x]
                if self.use_color and col and col != last_color:
                    row += col + ch
                    last_color = col
                elif self.use_color and col:
                    row += ch
                else:
                    row += ch
            if self.use_color:
                row += ANSI_RESET
            row += "║"
            lines.append(row)

        lines.append(f"╚{'═' * (self.width)}╝")
        info = f"  BBox: ({min_x:.1f}, {min_y:.1f}) → ({max_x:.1f}, {max_y:.1f}) mm"
        lines.append(info)
        return "\n".join(lines)

    def _render_grid_overview(self, min_x, min_y, max_x, max_y, board) -> str:
        lines = []
        lines.append(f"╔{'═' * (self.width)}╗")
        title = " Board Overview - All Layers "
        header = f"║{title:^{self.width}}║"
        lines.append(header)
        lines.append(f"╠{'═' * (self.width)}╣")

        last_color = ""
        for y in range(self.height):
            row = "║"
            for x in range(self.width):
                col = self._color_grid[y][x]
                ch = self._grid[y][x]
                if self.use_color and col and col != last_color:
                    row += col + ch
                    last_color = col
                elif self.use_color and col:
                    row += ch
                else:
                    row += ch
            if self.use_color:
                row += ANSI_RESET
            row += "║"
            lines.append(row)

        lines.append(f"╚{'═' * (self.width)}╝")
        lines.append(f"  Board: ({min_x:.1f}, {min_y:.1f}) → ({max_x:.1f}, {max_y:.1f}) mm")
        lines.append("")
        lines.append("  Layers:")
        for name, layer in board.layers.items():
            lt = layer.layer_type.value
            p_count = len(layer.primitives)
            h_count = len(layer.drill_holes)
            lines.append(f"    - {name} [{lt}] ({p_count} primitives, {h_count} holes)")
        return "\n".join(lines)


def render_layer(layer: LayerData, terminal_width: int = None, terminal_height: int = None) -> str:
    renderer = ASCIITerminalRenderer(terminal_width, terminal_height)
    return renderer.render_layer(layer)


def render_board(board: BoardData, terminal_width: int = None, terminal_height: int = None) -> str:
    renderer = ASCIITerminalRenderer(terminal_width, terminal_height)
    return renderer.render_board(board)