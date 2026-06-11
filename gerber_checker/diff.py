import math
import json
from typing import List, Optional, Dict, Any, Tuple
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
    risk: str = "LOW"
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
            "risk": self.risk,
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
    risk: str = "NONE"
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
            "risk_summary": self._build_risk_summary(),
            "layers": [],
        }

        for ld in self.layer_diffs:
            layer_entry = {
                "name": ld.name,
                "layer_type": ld.layer_type,
                "status": ld.status,
                "risk": ld.risk,
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

    def _build_risk_summary(self) -> Dict[str, Any]:
        high_items = []
        medium_items = []
        low_items = []
        changed_layers = 0

        for ld in self.layer_diffs:
            if ld.status == "IDENTICAL":
                continue
            changed_layers += 1
            for d in ld.details:
                entry = {
                    "layer": d.layer,
                    "type": d.obj_type,
                    "change": d.change_type,
                    "details": d.details,
                    "position": d.new_position or d.old_position,
                }
                if d.risk == "HIGH":
                    high_items.append(entry)
                elif d.risk == "MEDIUM":
                    medium_items.append(entry)
                else:
                    low_items.append(entry)

        overall = "NONE"
        if high_items:
            overall = "HIGH"
        elif medium_items:
            overall = "MEDIUM"
        elif low_items:
            overall = "LOW"

        return {
            "overall_risk": overall,
            "changed_layers": changed_layers,
            "high": {"count": len(high_items), "items": high_items},
            "medium": {"count": len(medium_items), "items": medium_items},
            "low": {"count": len(low_items), "items": low_items},
        }

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
            lines.append(f"\n  [{ld.name}] ({ld.layer_type}) - {ld.status} [Risk: {ld.risk}]")
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
                lines.append(f"{prefix} {d.obj_type}{pos_str}{extra} [{d.risk}]")
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

        rs = self._build_risk_summary()
        lines.append(f"  Overall Risk: {rs['overall_risk']}")
        lines.append(f"  Changed Layers: {rs['changed_layers']}")
        lines.append(f"  HIGH: {rs['high']['count']}  MEDIUM: {rs['medium']['count']}  LOW: {rs['low']['count']}")
        lines.append("")

        total_added = total_removed = total_modified = 0
        total_holes_added = total_holes_removed = total_holes_modified = 0

        lines.append(f"  {'Layer':<24s} {'Type':<16s} {'Risk':>5s} {'+Add':>5s} {'-Del':>5s} {'~Mod':>5s} {'=Same':>5s}")
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

            if ld.status != "IDENTICAL":
                lines.append(
                    f"  * {ld.name:<23s} {ld.layer_type:<16s} {ld.risk:>5s} "
                    f"{added:>5d} {removed:>5d} {modified:>5d} {same:>5d}"
                )

        lines.append("  " + "-" * 62)
        lines.append(f"  {'TOTAL':<24s} {'':16s} {'':5s} {total_added:>5d} {total_removed:>5d} {total_modified:>5d}")
        if total_holes_added or total_holes_removed or total_holes_modified:
            lines.append(f"  {'DRILL HOLES':<24s} {'':16s} {'':5s} {total_holes_added:>5d} {total_holes_removed:>5d} {total_holes_modified:>5d}")
        lines.append("")

        for ld in self.layer_diffs:
            if ld.status == "IDENTICAL" or not ld.details:
                continue
            lines.append(f"  ── {ld.name} ({ld.layer_type}) [Risk: {ld.risk}] ──")
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
                lines.append(f"    {prefix}{detail}{pos} [{d.risk}]")
            if len(ld.details) > 5:
                lines.append(f"    ... ({len(ld.details)} total changes)")
            lines.append("")

        lines.append(f"  Summary: {rs['changed_layers']} layer(s) changed, "
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
        ld = LayerDiff(name=name, layer_type=lt, status="IDENTICAL", risk="NONE")

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
                            change_type="modified", risk="MEDIUM",
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
                        change_type="removed", risk="HIGH",
                        old_position={"x": hole_a.position.x, "y": hole_a.position.y},
                        old_tool_diameter=hole_a.tool_diameter,
                        details=f"Removed hole at ({hole_a.position.x:.4f}, {hole_a.position.y:.4f})",
                    ))

            for pos_key, hole_b in holes_b_by_pos.items():
                if pos_key not in matched_positions:
                    ld.added_holes += 1
                    ld.details.append(PrimitiveDiff(
                        layer=name, layer_type=lt, obj_type="drill_hole",
                        change_type="added", risk="LOW",
                        new_position={"x": hole_b.position.x, "y": hole_b.position.y},
                        new_tool_diameter=hole_b.tool_diameter,
                        details=f"Added hole at ({hole_b.position.x:.4f}, {hole_b.position.y:.4f})",
                    ))

            if ld.added_holes or ld.removed_holes or ld.modified_holes:
                ld.status = "MODIFIED"
        else:
            prims_a = layer_a.primitives
            prims_b = layer_b.primitives

            idx_a = self._build_primitive_index(prims_a)
            idx_b = self._build_primitive_index(prims_b)

            matched_a_keys = set()
            matched_b_keys = set()

            for key_a, plist_a in idx_a.items():
                for i_a, pa in enumerate(plist_a):
                    if (key_a, i_a) in matched_a_keys:
                        continue
                    typed_key = (key_a[0], key_a[1], self._prim_type_key(pa))
                    if typed_key not in idx_b:
                        continue
                    for j_b, pb in enumerate(idx_b[typed_key]):
                        if (typed_key, j_b) in matched_b_keys:
                            continue
                        if self._primitives_equal(pa, pb):
                            ld.identical_primitives += 1
                            matched_a_keys.add((key_a, i_a))
                            matched_b_keys.add((typed_key, j_b))
                            break
                    else:
                        for j_b, pb in enumerate(idx_b[typed_key]):
                            if (typed_key, j_b) in matched_b_keys:
                                continue
                            if type(pa) == type(pb):
                                ld.modified_primitives += 1
                                detail = self._build_primitive_diff(pa, pb, name)
                                detail.risk = self._assess_risk(pa, pb, detail.change_type)
                                ld.details.append(detail)
                                matched_a_keys.add((key_a, i_a))
                                matched_b_keys.add((typed_key, j_b))
                                break

            for key_a, plist_a in idx_a.items():
                for i_a, pa in enumerate(plist_a):
                    if (key_a, i_a) not in matched_a_keys:
                        ld.removed_primitives += 1
                        detail = self._primitive_as_removed(pa, name)
                        detail.risk = "HIGH"
                        ld.details.append(detail)

            for key_b, plist_b in idx_b.items():
                for j_b, pb in enumerate(plist_b):
                    if (key_b, j_b) not in matched_b_keys:
                        ld.added_primitives += 1
                        detail = self._primitive_as_added(pb, name)
                        detail.risk = self._assess_added_risk(pb)
                        ld.details.append(detail)

            if ld.added_primitives or ld.removed_primitives or ld.modified_primitives:
                ld.status = "MODIFIED"

        ld.risk = self._layer_risk(ld)
        return ld

    def _build_primitive_index(self, prims) -> Dict[Tuple, List]:
        idx = {}
        for i, p in enumerate(prims):
            tk = self._prim_type_key(p)
            if isinstance(p, (LinePrimitive, ArcPrimitive)):
                key = (round(p.start.x, 3), round(p.start.y, 3))
            elif isinstance(p, FlashPrimitive):
                key = (round(p.position.x, 3), round(p.position.y, 3))
            elif isinstance(p, RegionPrimitive):
                if p.points:
                    key = (round(p.points[0].x, 3), round(p.points[0].y, 3))
                else:
                    key = (0, 0)
            else:
                key = (0, 0)
            full_key = (key[0], key[1], tk)
            idx.setdefault(full_key, []).append(p)
        return idx

    def _prim_type_key(self, p) -> str:
        if isinstance(p, LinePrimitive):
            return "trace"
        if isinstance(p, ArcPrimitive):
            return "arc"
        if isinstance(p, FlashPrimitive):
            return "pad"
        if isinstance(p, RegionPrimitive):
            return "region"
        return "other"

    def _assess_risk(self, pa, pb, change_type: str) -> str:
        if isinstance(pa, FlashPrimitive):
            if change_type == "removed":
                return "HIGH"
            if change_type == "modified":
                diff = abs(pa.position.x - pb.position.x) + abs(pa.position.y - pb.position.y)
                return "HIGH" if diff > 0.1 else "MEDIUM"
        if isinstance(pa, LinePrimitive):
            if change_type == "removed":
                return "HIGH"
            if change_type == "modified":
                diff = abs(pa.start.x - pb.start.x) + abs(pa.start.y - pb.start.y)
                if diff > 0.1:
                    return "HIGH"
                w_a = pa.aperture.params[0] if pa.aperture and pa.aperture.params else 0
                w_b = pb.aperture.params[0] if pb.aperture and pb.aperture.params else 0
                return "HIGH" if abs(w_a - w_b) > 0.01 else "MEDIUM"
        if isinstance(pa, ArcPrimitive):
            return "MEDIUM" if change_type == "modified" else "HIGH"
        return "MEDIUM"

    def _assess_added_risk(self, p) -> str:
        if isinstance(p, FlashPrimitive):
            return "LOW"
        if isinstance(p, LinePrimitive):
            return "MEDIUM"
        if isinstance(p, ArcPrimitive):
            return "MEDIUM"
        return "LOW"

    def _layer_risk(self, ld: LayerDiff) -> str:
        risks = [d.risk for d in ld.details]
        if "HIGH" in risks:
            return "HIGH"
        if "MEDIUM" in risks:
            return "MEDIUM"
        if "LOW" in risks:
            return "LOW"
        return "NONE"

    def _layer_only_in_a(self, name: str, layer: LayerData) -> LayerDiff:
        lt = layer.layer_type.value
        if layer.layer_type == LayerType.DRILL:
            ld = LayerDiff(name=name, layer_type=lt, status="REMOVED", risk="HIGH",
                          removed_holes=len(layer.drill_holes))
            for h in layer.drill_holes:
                ld.details.append(PrimitiveDiff(
                    layer=name, layer_type=lt, obj_type="drill_hole", change_type="removed", risk="HIGH",
                    old_position={"x": h.position.x, "y": h.position.y},
                    old_tool_diameter=h.tool_diameter,
                ))
        else:
            ld = LayerDiff(name=name, layer_type=lt, status="REMOVED", risk="HIGH",
                          removed_primitives=len(layer.primitives))
            for p in layer.primitives:
                d = self._primitive_as_removed(p, name)
                d.risk = "HIGH"
                ld.details.append(d)
        return ld

    def _layer_only_in_b(self, name: str, layer: LayerData) -> LayerDiff:
        lt = layer.layer_type.value
        if layer.layer_type == LayerType.DRILL:
            ld = LayerDiff(name=name, layer_type=lt, status="ADDED", risk="LOW",
                          added_holes=len(layer.drill_holes))
            for h in layer.drill_holes:
                ld.details.append(PrimitiveDiff(
                    layer=name, layer_type=lt, obj_type="drill_hole", change_type="added", risk="LOW",
                    new_position={"x": h.position.x, "y": h.position.y},
                    new_tool_diameter=h.tool_diameter,
                ))
        else:
            ld = LayerDiff(name=name, layer_type=lt, status="ADDED", risk="LOW",
                          added_primitives=len(layer.primitives))
            for p in layer.primitives:
                d = self._primitive_as_added(p, name)
                d.risk = self._assess_added_risk(p)
                ld.details.append(d)
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