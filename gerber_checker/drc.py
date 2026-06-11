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
        return {
            "summary": {
                "total_violations": len(self.violations),
                "errors": self.error_count,
                "warnings": self.warning_count,
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
        for layer in board.layers.values():
            self._check_layer(layer, report)
        self._check_inter_layer(board, report)
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
                        message=f"Trace width {width:.3f}mm < {min_width:.3f}mm minimum",
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
                        message=f"Arc trace width {width:.3f}mm < {min_width:.3f}mm minimum",
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
                dist = self._primitive_edge_distance(segments[i], segments[j])
                if dist is not None and dist < min_clearance:
                    pos = self._closest_point_between(segments[i], segments[j])
                    report.violations.append(DRCViolation(
                        rule_name="min_clearance",
                        severity="error",
                        layer_name=layer.name,
                        position=pos,
                        message=f"Copper edge clearance {dist:.3f}mm < {min_clearance:.3f}mm minimum",
                    ))

    def _check_pad_to_trace(self, layer: LayerData, report: DRCReport):
        min_dist = self.rules.min_pad_to_trace_mm

        pads = [p for p in layer.primitives if isinstance(p, FlashPrimitive) and p.polarity]
        traces = [p for p in layer.primitives if isinstance(p, LinePrimitive) and p.polarity]
        traces += [p for p in layer.primitives if isinstance(p, ArcPrimitive) and p.polarity]

        for pad in pads:
            for trace in traces:
                dist = self._primitive_edge_distance(pad, trace)
                if dist is not None and 0 < dist < min_dist:
                    report.violations.append(DRCViolation(
                        rule_name="min_pad_to_trace",
                        severity="warning",
                        layer_name=layer.name,
                        position=pad.position,
                        message=f"Pad edge to trace edge distance {dist:.3f}mm < {min_dist:.3f}mm minimum",
                    ))

    def _check_inter_layer(self, board: BoardData, report: DRCReport):
        pass

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
                        message=f"Drill hole {hole.tool_diameter:.3f}mm < {self.rules.min_via_hole_mm:.3f}mm minimum",
                    ))

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

    def _primitive_edge_distance(self, a, b):
        hw_a = self._get_half_width(a)
        hw_b = self._get_half_width(b)

        if isinstance(a, FlashPrimitive) and isinstance(b, FlashPrimitive):
            d = a.position.distance_to(b.position)
            return max(0.0, d - hw_a - hw_b)

        if isinstance(a, FlashPrimitive) and isinstance(b, LinePrimitive):
            d = self._point_to_segment_dist(a.position, b.start, b.end)
            return max(0.0, d - hw_a - hw_b)
        if isinstance(b, FlashPrimitive) and isinstance(a, LinePrimitive):
            d = self._point_to_segment_dist(b.position, a.start, a.end)
            return max(0.0, d - hw_a - hw_b)

        if isinstance(a, FlashPrimitive) and isinstance(b, ArcPrimitive):
            d = self._point_to_arc_dist(a.position, b)
            return max(0.0, d - hw_a - hw_b)
        if isinstance(b, FlashPrimitive) and isinstance(a, ArcPrimitive):
            d = self._point_to_arc_dist(b.position, a)
            return max(0.0, d - hw_a - hw_b)

        if isinstance(a, LinePrimitive) and isinstance(b, LinePrimitive):
            d = self._segment_to_segment_dist(a.start, a.end, b.start, b.end)
            return max(0.0, d - hw_a - hw_b)

        if isinstance(a, LinePrimitive) and isinstance(b, ArcPrimitive):
            d = self._segment_to_arc_dist(a.start, a.end, b)
            return max(0.0, d - hw_a - hw_b)
        if isinstance(b, LinePrimitive) and isinstance(a, ArcPrimitive):
            d = self._segment_to_arc_dist(b.start, b.end, a)
            return max(0.0, d - hw_a - hw_b)

        return None

    def _point_to_segment_dist(self, p: Point, a: Point, b: Point) -> float:
        dx = b.x - a.x
        dy = b.y - a.y
        if dx == 0 and dy == 0:
            return p.distance_to(a)
        t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)))
        proj = Point(a.x + t * dx, a.y + t * dy)
        return p.distance_to(proj)

    def _point_to_arc_dist(self, p: Point, arc: ArcPrimitive) -> float:
        radius = arc.center.distance_to(arc.start)
        center_dist = p.distance_to(arc.center)
        return abs(center_dist - radius)

    def _segment_to_segment_dist(self, a1: Point, a2: Point, b1: Point, b2: Point) -> float:
        def cross(o, a, b):
            return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

        c1 = cross(a1, a2, b1)
        c2 = cross(a1, a2, b2)
        c3 = cross(b1, b2, a1)
        c4 = cross(b1, b2, a2)

        if c1 * c2 < 0 and c3 * c4 < 0:
            return 0.0

        return min(
            self._point_to_segment_dist(a1, b1, b2),
            self._point_to_segment_dist(a2, b1, b2),
            self._point_to_segment_dist(b1, a1, a2),
            self._point_to_segment_dist(b2, a1, a2),
        )

    def _segment_to_arc_dist(self, a1: Point, a2: Point, arc: ArcPrimitive) -> float:
        radius = arc.center.distance_to(arc.start)
        d1 = self._point_to_segment_dist(arc.center, a1, a2)
        return abs(d1 - radius)

    def _closest_point_between(self, a, b):
        if isinstance(a, FlashPrimitive):
            return a.position
        elif isinstance(b, FlashPrimitive):
            return b.position
        elif isinstance(a, LinePrimitive):
            return Point((a.start.x + a.end.x) / 2, (a.start.y + a.end.y) / 2)
        elif isinstance(b, LinePrimitive):
            return Point((b.start.x + b.end.x) / 2, (b.start.y + b.end.y) / 2)
        elif isinstance(a, ArcPrimitive):
            return a.start
        elif isinstance(b, ArcPrimitive):
            return b.start
        return Point(0, 0)