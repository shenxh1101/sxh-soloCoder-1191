import math
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from .models import (
    Point, LayerData, LayerType, BoardData,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
    detect_layer_type,
)
from .parser import parse_gerber_file, parse_drill_file, parse_multiple_files


@dataclass
class PrimitiveDiff:
    layer: str
    layer_type: str
    obj_type: str
    change_type: str
    old_position: Optional[Dict[str, float]] = None
    new_position: Optional[Dict[str, float]] = None
    old_aperture_width: Optional[float] = None
    new_aperture_width: Optional[float] = None
    old_tool_diameter: Optional[float] = None
    new_tool_diameter: Optional[float] = None
    details: str = ""

    def to_dict(self):
        d = {
            "layer": self.layer,
            "layer_type": self.layer_type,
            "type": self.obj_type,
            "change": self.change_type,
            "details": self.details,
        }
        if self.old_position:
            d["old_position"] = {"x": round(self.old_position["x"], 4), "y": round(self.old_position["y"], 4)}
        if self.new_position:
            d["new_position"] = {"x": round(self.new_position["x"], 4), "y": round(self.new_position["y"], 4)}
        if self.old_aperture_width is not None:
            d["old_aperture_width_mm"] = round(self.old_aperture_width, 4)
        if self.new_aperture_width is not None:
            d["new_aperture_width_mm"] = round(self.new_aperture_width, 4)
        if self.old_tool_diameter is not None:
            d["old_diameter_mm"] = round(self.old_tool_diameter, 4)
        if self.new_tool_diameter is not None:
            d["new_diameter_mm"] = round(self.new_tool_diameter, 4)
        return d


@dataclass
class LayerDiff:
    name: str
    layer_type: str
    status: str
    added_primitives: int = 0
    removed_primitives: int = 0
    modified_primitives: int = 0
    identical_primitives: int = 0
    added_holes: int = 0
    removed_holes: int = 0
    modified_holes: int = 0
    identical_holes: int = 0
    details: List[PrimitiveDiff] = field(default_factory=list)


@dataclass
class DiffReport:
    version_a: str
    version_b: str
    files_a: List[str]
    files_b: List[str]
    layer_diffs: List[LayerDiff] = field(default_factory=list)
    is_identical: bool = True

    def to_dict(self):
        result = {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "files_a": self.files_a,
            "files_b": self.files_b,
            "is_identical": self.is_identical,
            "layers": [],
        }

        for ld in self.layer_diffs:
            layer_entry = {
                "name": ld.name,
                "layer_type": ld.layer_type,
                "status": ld.status,
                "primitives": {
                    "added": ld.added_primitives,
                    "removed": ld.removed_primitives,
                    "modified": ld.modified_primitives,
                    "identical": ld.identical_primitives,
                },
            }
            if ld.layer_type == "drill":
                layer_entry["drill_holes"] = {
                    "added": ld.added_holes,
                    "removed": ld.removed_holes,
                    "modified": ld.modified_holes,
                    "identical": ld.identical_holes,
                }
            layer_entry["changes"] = [d.to_dict() for d in ld.details]
            result["layers"].append(layer_entry)

        return result

    def to_text(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("  GERBER VERSION DIFF REPORT")
        lines.append("=" * 70)
        lines.append(f"  Version A: {self.version_a}")
        lines.append(f"  Version B: {self.version_b}")
        if self.is_identical:
            lines.append("")
            lines.append("  ✓ NO CHANGES DETECTED - Both versions are identical")
            lines.append("=" * 70)
            return "\n".join(lines)
        lines.append("-" * 70)

        for ld in self.layer_diffs:
            if ld.status == "IDENTICAL":
                continue
            lines.append(f"\n  [{ld.name}] ({ld.layer_type}) - {ld.status}")
            if ld.layer_type == "drill":
                if ld.added_holes:
                    lines.append(f"    + Added holes: {ld.added_holes}")
                if ld.removed_holes:
                    lines.append(f"    - Removed holes: {ld.removed_holes}")
                if ld.modified_holes:
                    lines.append(f"    ~ Modified holes: {ld.modified_holes}")
                if ld.identical_holes:
                    lines.append(f"    = Identical holes: {ld.identical_holes}")
            else:
                if ld.added_primitives:
                    lines.append(f"    + Added primitives: {ld.added_primitives}")
                if ld.removed_primitives:
                    lines.append(f"    - Removed primitives: {ld.removed_primitives}")
                if ld.modified_primitives:
                    lines.append(f"    ~ Modified primitives: {ld.modified_primitives}")
                if ld.identical_primitives:
                    lines.append(f"    = Identical primitives: {ld.identical_primitives}")

            for d in ld.details[:10]:
                prefix = "  +" if d.change_type == "added" else ("  -" if d.change_type == "removed" else "  ~")
                pos_str = ""
                if d.old_position:
                    pos_str = f" from ({d.old_position['x']:.3f},{d.old_position['y']:.3f})"
                if d.new_position:
                    pos_str += f" to ({d.new_position['x']:.3f},{d.new_position['y']:.3f})"
                extra = ""
                if d.old_tool_diameter is not None and d.new_tool_diameter is not None:
                    extra = f" dia {d.old_tool_diameter:.3f}→{d.new_tool_diameter:.3f}mm"
                elif d.old_aperture_width is not None and d.new_aperture_width is not None:
                    extra = f" width {d.old_aperture_width:.3f}→{d.new_aperture_width:.3f}mm"
                lines.append(f"{prefix} {d.obj_type}{pos_str}{extra}")
            if len(ld.details) > 10:
                lines.append(f"    ... and {len(ld.details) - 10} more changes")

        lines.append("")
        lines.append("=" * 70)
        return "\n".join(lines)

    def to_audit_text(self) -> str:
        lines = []
        lines.append("=" * 64)
        lines.append("  GERBER REVISION ACCEPTANCE REVIEW")
        lines.append("=" * 64)
        lines.append(f"  Base:    {self.version_a}")
        lines.append(f"  Target:  {self.version_b}")
        lines.append("")

        if self.is_identical:
            lines.append("  ✓ PASS — No differences detected between versions.")
            lines.append("=" * 64)
            return "\n".join(lines)

        total_added = total_removed = total_modified = 0
        total_holes_added = total_holes_removed = total_holes_modified = 0
        changed_layers = 0

        lines.append(f"  {'Layer':<24s} {'Type':<16s} {'+Add':>5s} {'-Del':>5s} {'~Mod':>5s} {'=Same':>5s}")
        lines.append("  " + "-" * 62)

        for ld in self.layer_diffs:
            if ld.layer_type == "drill":
                added = ld.added_holes
                removed = ld.removed_holes
                modified = ld.modified_holes
                same = ld.identical_holes
                total_holes_added += added
                total_holes_removed += removed
                total_holes_modified += modified
            else:
                added = ld.added_primitives
                removed = ld.removed_primitives
                modified = ld.modified_primitives
                same = ld.identical_primitives
                total_added += added
                total_removed += removed
                total_modified += modified

            if added or removed or modified:
                changed_layers += 1
                flag = "  *" if ld.status != "IDENTICAL" else "   "
                lines.append(
                    f"{flag} {ld.name:<23s} {ld.layer_type:<16s} "
                    f"{added:>5d} {removed:>5d} {modified:>5d} {same:>5d}"
                )

        lines.append("  " + "-" * 62)
        lines.append(f"  {'TOTAL':<24s} {'':16s} {total_added:>5d} {total_removed:>5d} {total_modified:>5d}")
        if total_holes_added or total_holes_removed or total_holes_modified:
            lines.append(f"  {'DRILL HOLES':<24s} {'':16s} {total_holes_added:>5d} {total_holes_removed:>5d} {total_holes_modified:>5d}")
        lines.append("")

        for ld in self.layer_diffs:
            if ld.status == "IDENTICAL" or not ld.details:
                continue
            lines.append(f"  ── {ld.name} ({ld.layer_type}) ──")
            for d in ld.details[:5]:
                prefix = "+" if d.change_type == "added" else ("-" if d.change_type == "removed" else "~")
                pos = ""
                if d.new_position:
                    pos = f" ({d.new_position['x']:.3f}, {d.new_position['y']:.3f})"
                elif d.old_position:
                    pos = f" ({d.old_position['x']:.3f}, {d.old_position['y']:.3f})"
                detail = f" [{d.obj_type}]"
                if d.old_tool_diameter is not None and d.new_tool_diameter is not None:
                    detail += f" ∅{d.old_tool_diameter:.3f}→{d.new_tool_diameter:.3f}mm"
                elif d.old_aperture_width is not None and d.new_aperture_width is not None:
                    detail += f" {d.old_aperture_width:.3f}→{d.new_aperture_width:.3f}mm"
                lines.append(f"    {prefix}{detail}{pos}")
            if len(ld.details) > 5:
                lines.append(f"    ... ({len(ld.details)} total changes)")
            lines.append("")

        lines.append(f"  Summary: {changed_layers} layer(s) changed, "
                     f"{total_added + total_holes_added} added, "
                     f"{total_removed + total_holes_removed} removed, "
                     f"{total_modified + total_holes_modified} modified")
        lines.append("=" * 64)
        return "\n".join(lines)


class DiffEngine:
    def __init__(self, tolerance: float = 0.001):
        self.tolerance = tolerance

    def compare_boards(self, board_a: BoardData, board_b: BoardData) -> DiffReport:
        report = DiffReport(version_a="A", version_b="B", files_a=[], files_b=[])

        all_names = set(board_a.layers.keys()) | set(board_b.layers.keys())
        matched_b = set()
        matched_a = set()

        for name_a in sorted(board_a.layers.keys()):
            if name_a in board_b.layers:
                layer_a = board_a.layers[name_a]
                layer_b = board_b.layers[name_a]
                ld = self._compare_layer(name_a, layer_a, layer_b)
                report.layer_diffs.append(ld)
                matched_a.add(name_a)
                matched_b.add(name_a)
                if ld.status != "IDENTICAL":
                    report.is_identical = False
            else:
                la = board_a.layers[name_a]
                la_type = la.layer_type.value
                matched = False
                for name_b in sorted(board_b.layers.keys()):
                    if name_b in matched_b:
                        continue
                    lb = board_b.layers[name_b]
                    if lb.layer_type == la.layer_type:
                        ld = self._compare_layer(name_a, la, lb)
                        report.layer_diffs.append(ld)
                        matched_a.add(name_a)
                        matched_b.add(name_b)
                        if ld.status != "IDENTICAL":
                            report.is_identical = False
                        matched = True
                        break
                if not matched:
                    ld = self._layer_only_in_a(name_a, la)
                    report.layer_diffs.append(ld)
                    report.is_identical = False

        for name_b in sorted(board_b.layers.keys()):
            if name_b not in matched_b:
                lb = board_b.layers[name_b]
                ld = self._layer_only_in_b(name_b, lb)
                report.layer_diffs.append(ld)
                report.is_identical = False

        return report

    def _compare_layer(self, name: str, layer_a: LayerData, layer_b: LayerData) -> LayerDiff:
        lt = layer_a.layer_type.value
        ld = LayerDiff(name=name, layer_type=lt, status="IDENTICAL")

        if layer_a.layer_type == LayerType.DRILL:
            holes_a_by_pos = {}
            for h in layer_a.drill_holes:
                key = (round(h.position.x, 3), round(h.position.y, 3))
                holes_a_by_pos[key] = h

            holes_b_by_pos = {}
            for h in layer_b.drill_holes:
                key = (round(h.position.x, 3), round(h.position.y, 3))
                holes_b_by_pos[key] = h

            matched_positions = set()
            for pos_key, hole_a in holes_a_by_pos.items():
                if pos_key in holes_b_by_pos:
                    hole_b = holes_b_by_pos[pos_key]
                    matched_positions.add(pos_key)
                    if abs(hole_a.tool_diameter - hole_b.tool_diameter) < self.tolerance:
                        ld.identical_holes += 1
                    else:
                        ld.modified_holes += 1
                        ld.details.append(PrimitiveDiff(
                            layer=name, layer_type=lt, obj_type="drill_hole",
                            change_type="modified",
                            old_position={"x": hole_a.position.x, "y": hole_a.position.y},
                            new_position={"x": hole_b.position.x, "y": hole_b.position.y},
                            old_tool_diameter=hole_a.tool_diameter,
                            new_tool_diameter=hole_b.tool_diameter,
                            details=f"Diameter changed from {hole_a.tool_diameter:.4f}mm to {hole_b.tool_diameter:.4f}mm",
                        ))
                else:
                    ld.removed_holes += 1
                    ld.details.append(PrimitiveDiff(
                        layer=name, layer_type=lt, obj_type="drill_hole",
                        change_type="removed",
                        old_position={"x": hole_a.position.x, "y": hole_a.position.y},
                        old_tool_diameter=hole_a.tool_diameter,
                        details=f"Removed hole at ({hole_a.position.x:.4f}, {hole_a.position.y:.4f})",
                    ))

            for pos_key, hole_b in holes_b_by_pos.items():
                if pos_key not in matched_positions:
                    ld.added_holes += 1
                    ld.details.append(PrimitiveDiff(
                        layer=name, layer_type=lt, obj_type="drill_hole",
                        change_type="added",
                        new_position={"x": hole_b.position.x, "y": hole_b.position.y},
                        new_tool_diameter=hole_b.tool_diameter,
                        details=f"Added hole at ({hole_b.position.x:.4f}, {hole_b.position.y:.4f})",
                    ))

            if ld.added_holes or ld.removed_holes or ld.modified_holes:
                ld.status = "MODIFIED"
        else:
            ld.added_primitives = max(0, len(layer_b.primitives) - len(layer_a.primitives))
            ld.removed_primitives = max(0, len(layer_a.primitives) - len(layer_b.primitives))
            min_prims = min(len(layer_a.primitives), len(layer_b.primitives))
            matching_prims = 0
            different_prims = 0

            for i in range(min_prims):
                pa = layer_a.primitives[i]
                pb = layer_b.primitives[i]
                if self._primitives_equal(pa, pb):
                    matching_prims += 1
                else:
                    different_prims += 1
                    detail = self._build_primitive_diff(pa, pb, name)
                    ld.details.append(detail)

            ld.identical_primitives = matching_prims
            ld.modified_primitives = different_prims
            ld.added_primitives = max(0, len(layer_b.primitives) - min_prims - different_prims)
            ld.removed_primitives = max(0, len(layer_a.primitives) - min_prims - different_prims)

            if ld.added_primitives > 0:
                for i in range(min_prims, len(layer_b.primitives)):
                    ld.details.append(self._primitive_as_added(layer_b.primitives[i], name))
            if ld.removed_primitives > 0:
                for i in range(min_prims, len(layer_a.primitives)):
                    ld.details.append(self._primitive_as_removed(layer_a.primitives[i], name))

            if ld.added_primitives or ld.removed_primitives or ld.modified_primitives:
                ld.status = "MODIFIED"

        return ld

    def _layer_only_in_a(self, name: str, layer: LayerData) -> LayerDiff:
        lt = layer.layer_type.value
        if layer.layer_type == LayerType.DRILL:
            ld = LayerDiff(name=name, layer_type=lt, status="REMOVED", removed_holes=len(layer.drill_holes))
            for h in layer.drill_holes:
                ld.details.append(PrimitiveDiff(
                    layer=name, layer_type=lt, obj_type="drill_hole", change_type="removed",
                    old_position={"x": h.position.x, "y": h.position.y},
                    old_tool_diameter=h.tool_diameter,
                ))
        else:
            ld = LayerDiff(name=name, layer_type=lt, status="REMOVED", removed_primitives=len(layer.primitives))
            for p in layer.primitives:
                ld.details.append(self._primitive_as_removed(p, name))
        return ld

    def _layer_only_in_b(self, name: str, layer: LayerData) -> LayerDiff:
        lt = layer.layer_type.value
        if layer.layer_type == LayerType.DRILL:
            ld = LayerDiff(name=name, layer_type=lt, status="ADDED", added_holes=len(layer.drill_holes))
            for h in layer.drill_holes:
                ld.details.append(PrimitiveDiff(
                    layer=name, layer_type=lt, obj_type="drill_hole", change_type="added",
                    new_position={"x": h.position.x, "y": h.position.y},
                    new_tool_diameter=h.tool_diameter,
                ))
        else:
            ld = LayerDiff(name=name, layer_type=lt, status="ADDED", added_primitives=len(layer.primitives))
            for p in layer.primitives:
                ld.details.append(self._primitive_as_added(p, name))
        return ld

    def _build_primitive_diff(self, pa, pb, name: str) -> PrimitiveDiff:
        lt = detect_layer_type(name).value
        if isinstance(pa, LinePrimitive) and isinstance(pb, LinePrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="trace", change_type="modified",
                old_position={"x": pa.start.x, "y": pa.start.y},
                new_position={"x": pb.start.x, "y": pb.start.y},
                old_aperture_width=pa.aperture.params[0] if pa.aperture and pa.aperture.params else None,
                new_aperture_width=pb.aperture.params[0] if pb.aperture and pb.aperture.params else None,
                details=f"Trace moved from ({pa.start.x:.3f},{pa.start.y:.3f})-({pa.end.x:.3f},{pa.end.y:.3f}) to ({pb.start.x:.3f},{pb.start.y:.3f})-({pb.end.x:.3f},{pb.end.y:.3f})",
            )
        if isinstance(pa, FlashPrimitive) and isinstance(pb, FlashPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="pad", change_type="modified",
                old_position={"x": pa.position.x, "y": pa.position.y},
                new_position={"x": pb.position.x, "y": pb.position.y},
                old_aperture_width=pa.aperture.params[0] if pa.aperture and pa.aperture.params else None,
                new_aperture_width=pb.aperture.params[0] if pb.aperture and pb.aperture.params else None,
                details=f"Pad moved from ({pa.position.x:.3f},{pa.position.y:.3f}) to ({pb.position.x:.3f},{pb.position.y:.3f})",
            )
        if isinstance(pa, ArcPrimitive) and isinstance(pb, ArcPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="arc", change_type="modified",
                old_position={"x": pa.center.x, "y": pa.center.y},
                new_position={"x": pb.center.x, "y": pb.center.y},
                old_aperture_width=pa.aperture.params[0] if pa.aperture and pa.aperture.params else None,
                new_aperture_width=pb.aperture.params[0] if pb.aperture and pb.aperture.params else None,
                details=f"Arc moved from ({pa.center.x:.3f},{pa.center.y:.3f}) to ({pb.center.x:.3f},{pb.center.y:.3f})",
            )
        return PrimitiveDiff(
            layer=name, layer_type=lt, obj_type="primitive", change_type="modified",
            details="Primitive changed type or structure",
        )

    def _primitive_as_added(self, p, name: str) -> PrimitiveDiff:
        lt = detect_layer_type(name).value
        if isinstance(p, LinePrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="trace", change_type="added",
                new_position={"x": p.start.x, "y": p.start.y},
                new_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"New trace ({p.start.x:.3f},{p.start.y:.3f})-({p.end.x:.3f},{p.end.y:.3f})",
            )
        if isinstance(p, FlashPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="pad", change_type="added",
                new_position={"x": p.position.x, "y": p.position.y},
                new_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"New pad at ({p.position.x:.3f},{p.position.y:.3f})",
            )
        if isinstance(p, ArcPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="arc", change_type="added",
                new_position={"x": p.center.x, "y": p.center.y},
                new_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"New arc at ({p.center.x:.3f},{p.center.y:.3f})",
            )
        return PrimitiveDiff(layer=name, layer_type=lt, obj_type="primitive", change_type="added")

    def _primitive_as_removed(self, p, name: str) -> PrimitiveDiff:
        lt = detect_layer_type(name).value
        if isinstance(p, LinePrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="trace", change_type="removed",
                old_position={"x": p.start.x, "y": p.start.y},
                old_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"Removed trace ({p.start.x:.3f},{p.start.y:.3f})-({p.end.x:.3f},{p.end.y:.3f})",
            )
        if isinstance(p, FlashPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="pad", change_type="removed",
                old_position={"x": p.position.x, "y": p.position.y},
                old_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"Removed pad at ({p.position.x:.3f},{p.position.y:.3f})",
            )
        if isinstance(p, ArcPrimitive):
            return PrimitiveDiff(
                layer=name, layer_type=lt, obj_type="arc", change_type="removed",
                old_position={"x": p.center.x, "y": p.center.y},
                old_aperture_width=p.aperture.params[0] if p.aperture and p.aperture.params else None,
                details=f"Removed arc at ({p.center.x:.3f},{p.center.y:.3f})",
            )
        return PrimitiveDiff(layer=name, layer_type=lt, obj_type="primitive", change_type="removed")

    def _get_primitive_width(self, p) -> Optional[float]:
        if p.aperture and p.aperture.params:
            return p.aperture.params[0]
        return None

    def _primitives_equal(self, a, b) -> bool:
        if type(a) != type(b):
            return False
        if isinstance(a, LinePrimitive):
            if not (abs(a.start.x - b.start.x) < self.tolerance and
                    abs(a.start.y - b.start.y) < self.tolerance and
                    abs(a.end.x - b.end.x) < self.tolerance and
                    abs(a.end.y - b.end.y) < self.tolerance):
                return False
        elif isinstance(a, ArcPrimitive):
            if not (abs(a.center.x - b.center.x) < self.tolerance and
                    abs(a.center.y - b.center.y) < self.tolerance and
                    abs(a.start.x - b.start.x) < self.tolerance and
                    abs(a.start.y - b.start.y) < self.tolerance and
                    abs(a.end.x - b.end.x) < self.tolerance and
                    abs(a.end.y - b.end.y) < self.tolerance and
                    a.direction == b.direction):
                return False
        elif isinstance(a, FlashPrimitive):
            if not (abs(a.position.x - b.position.x) < self.tolerance and
                    abs(a.position.y - b.position.y) < self.tolerance):
                return False
        elif isinstance(a, RegionPrimitive):
            if len(a.points) != len(b.points):
                return False
            for pa, pb in zip(a.points, b.points):
                if (abs(pa.x - pb.x) >= self.tolerance or
                        abs(pa.y - pb.y) >= self.tolerance):
                    return False
        else:
            return False

        w_a = self._get_primitive_width(a)
        w_b = self._get_primitive_width(b)
        if w_a is not None and w_b is not None:
            if abs(w_a - w_b) >= self.tolerance:
                return False
        elif w_a is not None or w_b is not None:
            return False

        return True


def diff_gerber_versions(
    files_a: List[str],
    files_b: List[str],
    version_a: str = "A",
    version_b: str = "B",
) -> DiffReport:
    board_a = parse_multiple_files(files_a)
    board_b = parse_multiple_files(files_b)

    engine = DiffEngine()
    report = engine.compare_boards(board_a, board_b)
    report.version_a = version_a
    report.version_b = version_b
    report.files_a = list(files_a)
    report.files_b = list(files_b)
    return report