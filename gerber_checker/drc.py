import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)
from .config import DRCRules, load_config


@dataclass
class DRCViolation:
    rule_name: str
    severity: str
    layer_name: str
    position: Point
    message: str
    details: str = ""

    def to_dict(self):
        return {
            "rule": self.rule_name,
            "severity": self.severity,
            "layer": self.layer_name,
            "position": {"x": round(self.position.x, 4), "y": round(self.position.y, 4)},
            "message": self.message,
            "details": self.details,
        }


@dataclass
class DRCReport:
    violations: List[DRCViolation] = field(default_factory=list)
    passed_checks: int = 0
    failed_checks: int = 0

    @property
    def error_count(self):
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self):
        return sum(1 for v in self.violations if v.severity == "warning")

    def to_dict(self):
        by_rule = {}
        for v in self.violations:
            by_rule.setdefault(v.rule_name, []).append(v)

        rule_summaries = {}
        for rule, viols in by_rule.items():
            types = {}
            for v in viols:
                tag = v.message.split("[")[-1].rstrip("]") if "[" in v.message else "unknown"
                types[tag] = types.get(tag, 0) + 1
            rule_summaries[rule] = {"count": len(viols), "by_type": types}

        return {
            "summary": {
                "total_violations": len(self.violations),
                "errors": self.error_count,
                "warnings": self.warning_count,
                "by_rule": rule_summaries,
            },
            "violations": [v.to_dict() for v in self.violations],
        }

    def to_text(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("  DESIGN RULE CHECK REPORT")
        lines.append("=" * 70)
        lines.append(f"  Total violations: {len(self.violations)}")
        lines.append(f"  Errors:   {self.error_count}")
        lines.append(f"  Warnings: {self.warning_count}")
        lines.append("-" * 70)

        by_rule = {}
        for v in self.violations:
            by_rule.setdefault(v.rule_name, []).append(v)

        for rule, viols in by_rule.items():
            lines.append(f"\n  [{rule}] - {len(viols)} violations:")
            for v in viols[:20]:
                tag = "[ERROR]" if v.severity == "error" else "[WARN] "
                lines.append(f"    {tag} {v.layer_name}: ({v.position.x:.3f}, {v.position.y:.3f}) - {v.message}")
            if len(viols) > 20:
                lines.append(f"    ... and {len(viols) - 20} more violations")

        lines.append("")
        lines.append("=" * 70)
        return "\n".join(lines)


class DRCEngine:
    def __init__(self, rules: DRCRules = None, config_path: str = None):
        self.rules = rules or load_config(config_path)

    def check_board(self, board: BoardData) -> DRCReport:
        report = DRCReport()
        copper_layers = [l for l in board.layers.values()
                         if l.layer_type in (LayerType.TOP_COPPER, LayerType.BOTTOM_COPPER, LayerType.INNER)
                         or (l.layer_type == LayerType.UNKNOWN and l.primitives)]
        drill_layer = None
        for l in board.layers.values():
            if l.layer_type == LayerType.DRILL:
                drill_layer = l
                break

        for layer in copper_layers:
            self._check_layer(layer, report)
        for layer in copper_layers:
            self._check_inter_layer_drill(layer, drill_layer, report)
        self._check_drill(board, report)
        return report

    def _check_layer(self, layer: LayerData, report: DRCReport):
        self._check_trace_width(layer, report)
        self._check_clearance(layer, report)
        self._check_pad_to_trace(layer, report)

    def _check_trace_width(self, layer: LayerData, report: DRCReport):
        if layer.layer_type not in (LayerType.TOP_COPPER, LayerType.BOTTOM_COPPER, LayerType.INNER):
            return

        min_width = self.rules.min_trace_width_mm
        for prim in layer.primitives:
            if not prim.polarity:
                continue
            if isinstance(prim, LinePrimitive):
                width = 0
                if prim.aperture and prim.aperture.params:
                    width = prim.aperture.params[0]
                if width > 0 and width < min_width:
                    mid = Point(
                        (prim.start.x + prim.end.x) / 2,
                        (prim.start.y + prim.end.y) / 2,
                    )
                    report.violations.append(DRCViolation(
                        rule_name="min_trace_width",
                        severity="error",
                        layer_name=layer.name,
                        position=mid,
                        message=f"Trace width {width:.3f}mm < {min_width:.3f}mm minimum [trace-width]",
                        details=f"From ({prim.start.x:.3f},{prim.start.y:.3f}) to ({prim.end.x:.3f},{prim.end.y:.3f})",
                    ))
            elif isinstance(prim, ArcPrimitive):
                width = 0
                if prim.aperture and prim.aperture.params:
                    width = prim.aperture.params[0]
                if width > 0 and width < min_width:
                    report.violations.append(DRCViolation(
                        rule_name="min_trace_width",
                        severity="error",
                        layer_name=layer.name,
                        position=prim.start,
                        message=f"Arc trace width {width:.3f}mm < {min_width:.3f}mm minimum [arc-width]",
                    ))

    def _check_clearance(self, layer: LayerData, report: DRCReport):
        min_clearance = self.rules.min_clearance_mm

        segments = []
        for prim in layer.primitives:
            if not prim.polarity:
                continue
            if isinstance(prim, (LinePrimitive, ArcPrimitive, FlashPrimitive)):
                segments.append(prim)

        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                dist, edge_pt = self._primitive_edge_distance_with_point(segments[i], segments[j])
                if dist is not None and dist < min_clearance:
                    tag = f"{self._tag(segments[i])}-{self._tag(segments[j])}"
                    report.violations.append(DRCViolation(
                        rule_name="min_clearance",
                        severity="error",
                        layer_name=layer.name,
                        position=edge_pt,
                        message=f"Copper edge clearance {dist:.3f}mm < {min_clearance:.3f}mm [{tag}]",
                    ))

    def _check_pad_to_trace(self, layer: LayerData, report: DRCReport):
        min_dist = self.rules.min_pad_to_trace_mm

        pads = [p for p in layer.primitives if isinstance(p, FlashPrimitive) and p.polarity]
        traces = [p for p in layer.primitives if isinstance(p, LinePrimitive) and p.polarity]
        traces += [p for p in layer.primitives if isinstance(p, ArcPrimitive) and p.polarity]

        for pad in pads:
            for trace in traces:
                dist, edge_pt = self._primitive_edge_distance_with_point(pad, trace)
                if dist is not None and 0 < dist < min_dist:
                    report.violations.append(DRCViolation(
                        rule_name="min_pad_to_trace",
                        severity="warning",
                        layer_name=layer.name,
                        position=edge_pt,
                        message=f"Pad edge to trace edge distance {dist:.3f}mm < {min_dist:.3f}mm [pad-trace]",
                    ))

    def _check_inter_layer_drill(self, copper: LayerData, drill: LayerData, report: DRCReport):
        if drill is None:
            return
        min_clearance = self.rules.min_clearance_mm

        copper_segments = []
        for prim in copper.primitives:
            if not prim.polarity:
                continue
            if isinstance(prim, (LinePrimitive, ArcPrimitive, FlashPrimitive)):
                copper_segments.append(prim)

        for hole in drill.drill_holes:
            hole_radius = hole.tool_diameter / 2.0
            for seg in copper_segments:
                seg_hw = self._get_half_width(seg)
                if isinstance(seg, FlashPrimitive):
                    center_dist = hole.position.distance_to(seg.position)
                    edge_dist = center_dist - hole_radius - seg_hw
                elif isinstance(seg, LinePrimitive):
                    d, proj = self._point_to_segment_dist_with_point(
                        hole.position, seg.start, seg.end)
                    edge_dist = d - hole_radius - seg_hw
                elif isinstance(seg, ArcPrimitive):
                    d, proj = self._point_to_arc_dist_with_point(hole.position, seg)
                    edge_dist = d - hole_radius - seg_hw
                else:
                    continue

                if edge_dist < min_clearance:
                    tag = f"drill-{self._tag(seg)}"
                    report.violations.append(DRCViolation(
                        rule_name="min_clearance",
                        severity="error",
                        layer_name=f"{copper.name} ↔ {drill.name}",
                        position=hole.position,
                        message=f"Drill hole edge to copper edge clearance {edge_dist:.3f}mm < {min_clearance:.3f}mm [{tag}]",
                    ))

    def _check_drill(self, board: BoardData, report: DRCReport):
        for layer in board.layers.values():
            if layer.layer_type != LayerType.DRILL:
                continue
            for hole in layer.drill_holes:
                if hole.tool_diameter < self.rules.min_via_hole_mm:
                    report.violations.append(DRCViolation(
                        rule_name="min_via_hole",
                        severity="error",
                        layer_name=layer.name,
                        position=hole.position,
                        message=f"Drill hole ∅{hole.tool_diameter:.3f}mm < {self.rules.min_via_hole_mm:.3f}mm minimum [drill-size]",
                    ))

    def _tag(self, prim) -> str:
        if isinstance(prim, LinePrimitive):
            return "trace"
        if isinstance(prim, ArcPrimitive):
            return "arc"
        if isinstance(prim, FlashPrimitive):
            return "pad"
        return "obj"

    def _get_half_width(self, prim) -> float:
        if isinstance(prim, FlashPrimitive):
            if prim.aperture and prim.aperture.params:
                if prim.aperture.shape.value == "C":
                    return prim.aperture.params[0] / 2.0
                elif prim.aperture.shape.value == "R":
                    w = prim.aperture.params[0]
                    h = prim.aperture.params[1] if len(prim.aperture.params) > 1 else w
                    return max(w, h) / 2.0
                else:
                    return prim.aperture.params[0] / 2.0 if prim.aperture.params else 0.5
            return 0.5
        elif isinstance(prim, (LinePrimitive, ArcPrimitive)):
            if prim.aperture and prim.aperture.params:
                return prim.aperture.params[0] / 2.0
            return 0.0
        return 0.0

    def _primitive_edge_distance_with_point(self, a, b) -> Tuple[Optional[float], Point]:
        hw_a = self._get_half_width(a)
        hw_b = self._get_half_width(b)

        if isinstance(a, FlashPrimitive) and isinstance(b, FlashPrimitive):
            center_dist = a.position.distance_to(b.position)
            edge_dist = max(0.0, center_dist - hw_a - hw_b)
            if center_dist < 1e-9:
                return edge_dist, a.position
            t = hw_a / (hw_a + hw_b) if (hw_a + hw_b) > 0 else 0.5
            edge_pt = Point(
                a.position.x + (b.position.x - a.position.x) * t,
                a.position.y + (b.position.y - a.position.y) * t,
            )
            return edge_dist, edge_pt

        if isinstance(a, FlashPrimitive) and isinstance(b, LinePrimitive):
            return self._flash_to_line_edge_mid(a, b, hw_a, hw_b)
        if isinstance(b, FlashPrimitive) and isinstance(a, LinePrimitive):
            return self._flash_to_line_edge_mid(b, a, hw_b, hw_a)

        if isinstance(a, FlashPrimitive) and isinstance(b, ArcPrimitive):
            d, pt = self._point_to_arc_dist_with_point(a.position, b)
            edge_dist = max(0.0, d - hw_a - hw_b)
            if d < 1e-9:
                return edge_dist, a.position
            dx = pt.x - a.position.x
            dy = pt.y - a.position.y
            n = math.hypot(dx, dy)
            if n < 1e-9:
                return edge_dist, a.position
            edge_pt = Point(
                a.position.x + dx / n * hw_a,
                a.position.y + dy / n * hw_a,
            )
            return edge_dist, edge_pt
        if isinstance(b, FlashPrimitive) and isinstance(a, ArcPrimitive):
            d, pt = self._point_to_arc_dist_with_point(b.position, a)
            edge_dist = max(0.0, d - hw_a - hw_b)
            if d < 1e-9:
                return edge_dist, b.position
            dx = pt.x - b.position.x
            dy = pt.y - b.position.y
            n = math.hypot(dx, dy)
            if n < 1e-9:
                return edge_dist, b.position
            edge_pt = Point(
                b.position.x + dx / n * hw_b,
                b.position.y + dy / n * hw_b,
            )
            return edge_dist, edge_pt

        if isinstance(a, LinePrimitive) and isinstance(b, LinePrimitive):
            return self._trace_to_trace_edge_mid(a, b, hw_a, hw_b)

        if isinstance(a, LinePrimitive) and isinstance(b, ArcPrimitive):
            d, pt_a, pt_b = self._segment_to_arc_closest_points(a.start, a.end, b)
            edge_dist = max(0.0, d - hw_a - hw_b)
            if d < 1e-9:
                edge_pt = Point((a.start.x + a.end.x) / 2, (a.start.y + a.end.y) / 2)
            else:
                dx = pt_b.x - pt_a.x
                dy = pt_b.y - pt_a.y
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    edge_pt = pt_a
                else:
                    edge_a = Point(pt_a.x + dx / n * hw_a, pt_a.y + dy / n * hw_a)
                    edge_b = Point(pt_b.x - dx / n * hw_b, pt_b.y - dy / n * hw_b)
                    edge_pt = Point((edge_a.x + edge_b.x) / 2, (edge_a.y + edge_b.y) / 2)
            return edge_dist, edge_pt
        if isinstance(b, LinePrimitive) and isinstance(a, ArcPrimitive):
            d, pt_a, pt_b = self._segment_to_arc_closest_points(b.start, b.end, a)
            edge_dist = max(0.0, d - hw_a - hw_b)
            if d < 1e-9:
                edge_pt = Point((b.start.x + b.end.x) / 2, (b.start.y + b.end.y) / 2)
            else:
                dx = pt_b.x - pt_a.x
                dy = pt_b.y - pt_a.y
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    edge_pt = pt_a
                else:
                    edge_a = Point(pt_a.x + dx / n * hw_a, pt_a.y + dy / n * hw_a)
                    edge_b = Point(pt_b.x - dx / n * hw_b, pt_b.y - dy / n * hw_b)
                    edge_pt = Point((edge_a.x + edge_b.x) / 2, (edge_a.y + edge_b.y) / 2)
            return edge_dist, edge_pt

        return None, Point(0, 0)

    def _trace_to_trace_edge_mid(self, a: LinePrimitive, b: LinePrimitive,
                                  hw_a: float, hw_b: float) -> Tuple[float, Point]:
        d, pt_a, pt_b = self._segment_to_segment_closest_points(a.start, a.end, b.start, b.end)
        edge_dist = max(0.0, d - hw_a - hw_b)
        if d < 1e-9:
            edge_pt = Point((a.start.x + a.end.x + b.start.x + b.end.x) / 4,
                            (a.start.y + a.end.y + b.start.y + b.end.y) / 4)
        else:
            dx = pt_b.x - pt_a.x
            dy = pt_b.y - pt_a.y
            n = math.hypot(dx, dy)
            edge_a = Point(pt_a.x + dx / n * hw_a, pt_a.y + dy / n * hw_a)
            edge_b = Point(pt_b.x - dx / n * hw_b, pt_b.y - dy / n * hw_b)
            edge_pt = Point((edge_a.x + edge_b.x) / 2, (edge_a.y + edge_b.y) / 2)
        return edge_dist, edge_pt

    def _flash_to_line_edge_mid(self, flash: FlashPrimitive, line: LinePrimitive,
                                 hw_pad: float, hw_trace: float) -> Tuple[float, Point]:
        d, proj = self._point_to_segment_dist_with_point(flash.position, line.start, line.end)
        edge_dist = max(0.0, d - hw_pad - hw_trace)
        if d < 1e-9:
            return edge_dist, flash.position
        dx = proj.x - flash.position.x
        dy = proj.y - flash.position.y
        n = math.hypot(dx, dy)
        if n < 1e-9:
            return edge_dist, flash.position
        edge_pad = Point(
            flash.position.x + dx / n * hw_pad,
            flash.position.y + dy / n * hw_pad,
        )
        edge_trace = Point(
            proj.x - dx / n * hw_trace,
            proj.y - dy / n * hw_trace,
        )
        edge_pt = Point((edge_pad.x + edge_trace.x) / 2, (edge_pad.y + edge_trace.y) / 2)
        return edge_dist, edge_pt

    def _point_to_segment_dist_with_point(self, p: Point, a: Point, b: Point) -> Tuple[float, Point]:
        dx = b.x - a.x
        dy = b.y - a.y
        if dx == 0 and dy == 0:
            return p.distance_to(a), a
        t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)))
        proj = Point(a.x + t * dx, a.y + t * dy)
        return p.distance_to(proj), proj

    def _point_to_arc_dist_with_point(self, p: Point, arc: ArcPrimitive) -> Tuple[float, Point]:
        radius = arc.center.distance_to(arc.start)
        center_dist = p.distance_to(arc.center)
        if center_dist < 1e-9:
            nearest = Point(arc.center.x + radius, arc.center.y)
        else:
            dx = p.x - arc.center.x
            dy = p.y - arc.center.y
            s = radius / center_dist
            nearest = Point(arc.center.x + dx * s, arc.center.y + dy * s)
        return abs(center_dist - radius), nearest

    def _segment_to_segment_closest_points(self, a1: Point, a2: Point, b1: Point, b2: Point) -> Tuple[float, Point, Point]:
        dx_a = a2.x - a1.x
        dy_a = a2.y - a1.y
        dx_b = b2.x - b1.x
        dy_b = b2.y - b1.y

        d_ab = Point(b1.x - a1.x, b1.y - a1.y)
        d_aa = dx_a * dx_a + dy_a * dy_a
        d_bb = dx_b * dx_b + dy_b * dy_b
        d_ab_dot_a = d_ab.x * dx_a + d_ab.y * dy_a
        d_ab_dot_b = d_ab.x * dx_b + d_ab.y * dy_b
        d_a_cross_b = dx_a * dx_b + dy_a * dy_b

        denom = d_aa * d_bb - d_a_cross_b * d_a_cross_b

        if denom < 1e-12:
            t = 0.0
            u = max(0.0, min(1.0, -d_ab_dot_b / d_bb)) if d_bb > 0 else 0.0
        else:
            t = max(0.0, min(1.0, (d_ab_dot_a * d_bb - d_ab_dot_b * d_a_cross_b) / denom))
            u = max(0.0, min(1.0, (d_ab_dot_a * d_a_cross_b - d_ab_dot_b * d_aa) / denom))

        pt_a = Point(a1.x + t * dx_a, a1.y + t * dy_a)
        pt_b = Point(b1.x + u * dx_b, b1.y + u * dy_b)
        d = pt_a.distance_to(pt_b)
        return d, pt_a, pt_b

    def _segment_to_segment_dist_with_point(self, a1: Point, a2: Point, b1: Point, b2: Point) -> Tuple[float, Point]:
        candidates = [
            self._point_to_segment_dist_with_point(a1, b1, b2),
            self._point_to_segment_dist_with_point(a2, b1, b2),
            self._point_to_segment_dist_with_point(b1, a1, a2),
            self._point_to_segment_dist_with_point(b2, a1, a2),
        ]
        best = min(candidates, key=lambda x: x[0])
        return best

    def _segment_to_arc_closest_points(self, a1: Point, a2: Point, arc: ArcPrimitive) -> Tuple[float, Point, Point]:
        d, proj = self._point_to_segment_dist_with_point(arc.center, a1, a2)
        radius = arc.center.distance_to(arc.start)
        if d < 1e-9:
            nearest = Point(arc.center.x + radius, arc.center.y)
        else:
            dx = proj.x - arc.center.x
            dy = proj.y - arc.center.y
            n = math.hypot(dx, dy)
            s = radius / n
            nearest = Point(arc.center.x + dx * s, arc.center.y + dy * s)
        edge_dist = abs(d - radius)
        return edge_dist, proj, nearest

    def _segment_to_arc_dist_with_point(self, a1: Point, a2: Point, arc: ArcPrimitive) -> Tuple[float, Point]:
        d, proj = self._point_to_segment_dist_with_point(arc.center, a1, a2)
        radius = arc.center.distance_to(arc.start)
        edge_dist = abs(d - radius)
        return edge_dist, proj