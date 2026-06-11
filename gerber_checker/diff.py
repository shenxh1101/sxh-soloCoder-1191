import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)
from .parser import parse_multiple_files


@dataclass
class PrimitiveDiff:
    layer: str = ""
    obj_type: str = ""
    old_position: Optional[Point] = None
    new_position: Optional[Point] = None
    old_aperture_width: Optional[float] = None
    new_aperture_width: Optional[float] = None
    old_tool_diameter: Optional[float] = None
    new_tool_diameter: Optional[float] = None
    details: str = ""
    change_type: str = ""

    def to_dict(self):
        d = {
            "layer": self.layer,
            "type": self.obj_type,
            "change": self.change_type,
            "details": self.details,
        }
        if self.old_position:
            d["old_position"] = {"x": round(self.old_position.x, 4), "y": round(self.old_position.y, 4)}
        if self.new_position:
            d["new_position"] = {"x": round(self.new_position.x, 4), "y": round(self.new_position.y, 4)}
        if self.old_aperture_width is not None:
            d["old_width_mm"] = round(self.old_aperture_width, 4)
        if self.new_aperture_width is not None:
            d["new_width_mm"] = round(self.new_aperture_width, 4)
        if self.old_tool_diameter is not None:
            d["old_diameter_mm"] = round(self.old_tool_diameter, 4)
        if self.new_tool_diameter is not None:
            d["new_diameter_mm"] = round(self.new_tool_diameter, 4)
        return d


@dataclass
class LayerDiff:
    layer_name: str
    layer_type: str = ""
    identical: bool = False
    added_primitives: int = 0
    removed_primitives: int = 0
    modified_primitives: int = 0
    added_holes: int = 0
    removed_holes: int = 0
    modified_holes: int = 0
    details: List[PrimitiveDiff] = field(default_factory=list)

    def to_dict(self):
        return {
            "layer_name": self.layer_name,
            "layer_type": self.layer_type,
            "identical": self.identical,
            "primitives": {
                "added": self.added_primitives,
                "removed": self.removed_primitives,
                "modified": self.modified_primitives,
            },
            "drill_holes": {
                "added": self.added_holes,
                "removed": self.removed_holes,
                "modified": self.modified_holes,
            },
            "changes": [d.to_dict() for d in self.details],
        }


@dataclass
class DiffReport:
    version_a: str
    version_b: str
    layers_only_a: List[str]
    layers_only_b: List[str]
    common_layers: List[LayerDiff]
    summary: str = ""

    @property
    def is_identical(self) -> bool:
        if self.layers_only_a or self.layers_only_b:
            return False
        for ld in self.common_layers:
            if not ld.identical:
                return False
        return True

    def to_dict(self):
        return {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "identical": self.is_identical,
            "layers_only_in_a": self.layers_only_a,
            "layers_only_in_b": self.layers_only_b,
            "common_layers": [ld.to_dict() for ld in self.common_layers],
            "summary": self.summary,
        }

    def to_text(self) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("  GERBER DIFF REPORT")
        lines.append("=" * 70)
        lines.append(f"  Version A: {self.version_a}")
        lines.append(f"  Version B: {self.version_b}")
        lines.append("-" * 70)

        if self.is_identical:
            lines.append("\n  *** BOARDS ARE IDENTICAL — NO DIFFERENCES FOUND ***")
            lines.append("=" * 70)
            self.summary = "\n".join(lines)
            return self.summary

        if self.layers_only_a:
            lines.append(f"\n  Layers only in Version A:")
            for l in self.layers_only_a:
                lines.append(f"    + {l}")
        if self.layers_only_b:
            lines.append(f"\n  Layers only in Version B:")
            for l in self.layers_only_b:
                lines.append(f"    + {l}")

        any_changes = False
        for ld in self.common_layers:
            if not ld.identical:
                any_changes = True
                break

        if not any_changes and not self.layers_only_a and not self.layers_only_b:
            lines.append("\n  *** BOARDS ARE IDENTICAL — NO DIFFERENCES FOUND ***")
        else:
            lines.append(f"\n  Common layers ({len(self.common_layers)}):")
            total_added = 0; total_removed = 0; total_modified = 0
            for ld in self.common_layers:
                total_added += ld.added_primitives + ld.added_holes
                total_removed += ld.removed_primitives + ld.removed_holes
                total_modified += ld.modified_primitives + ld.modified_holes
                if ld.identical:
                    lines.append(f"    [{ld.layer_name}] ({ld.layer_type}) — IDENTICAL")
                else:
                    lines.append(f"    [{ld.layer_name}] ({ld.layer_type})")
                    if ld.added_primitives:
                        lines.append(f"      Primitives +{ld.added_primitives}/-{ld.removed_primitives}/~{ld.modified_primitives}")
                    if ld.added_holes or ld.modified_holes:
                        lines.append(f"      Holes      +{ld.added_holes}/-{ld.removed_holes}/~{ld.modified_holes}")
                    for det in ld.details:
                        extra = ""
                        if det.old_aperture_width is not None:
                            extra += f" w:{det.old_aperture_width:.3f}→{det.new_aperture_width:.3f}"
                        if det.old_tool_diameter is not None:
                            extra += f" ∅:{det.old_tool_diameter:.3f}→{det.new_tool_diameter:.3f}"
                        pos = ""
                        if det.old_position:
                            pos = f" ({det.old_position.x:.3f},{det.old_position.y:.3f})"
                        lines.append(f"        [{det.change_type}] {det.obj_type}{pos}: {det.details}{extra}")
            lines.append(f"\n  Totals: +{total_added} / -{total_removed} / ~{total_modified}")
        lines.append("=" * 70)
        self.summary = "\n".join(lines)
        return self.summary


class GerberDiff:
    def __init__(self, version_a_paths, version_b_paths,
                 label_a="Version A", label_b="Version B", tolerance_mm=0.005):
        self.label_a = label_a
        self.label_b = label_b
        self.tolerance = tolerance_mm
        if isinstance(version_a_paths, BoardData):
            self.board_a = version_a_paths
        elif isinstance(version_a_paths, list):
            self.board_a = parse_multiple_files(version_a_paths)
        else:
            raise TypeError("version_a_paths must be list or BoardData")
        if isinstance(version_b_paths, BoardData):
            self.board_b = version_b_paths
        elif isinstance(version_b_paths, list):
            self.board_b = parse_multiple_files(version_b_paths)
        else:
            raise TypeError("version_b_paths must be list or BoardData")

    def compare(self) -> DiffReport:
        layers_a = set(self.board_a.layers.keys())
        layers_b = set(self.board_b.layers.keys())

        only_a_names = sorted(layers_a - layers_b)
        only_b_names = sorted(layers_b - layers_a)
        common_names = sorted(layers_a & layers_b)

        type_a = {name: self.board_a.layers[name].layer_type for name in only_a_names}
        type_b = {name: self.board_b.layers[name].layer_type for name in only_b_names}

        matched_a = set()
        matched_b = set()
        cross_matches = []

        for name_a in only_a_names:
            if name_a in matched_a:
                continue
            lt_a = type_a[name_a]
            for name_b in only_b_names:
                if name_b in matched_b:
                    continue
                lt_b = type_b[name_b]
                if lt_a == lt_b and lt_a.value != "unknown":
                    cross_matches.append((name_a, name_b))
                    matched_a.add(name_a)
                    matched_b.add(name_b)
                    break

        final_only_a = [n for n in only_a_names if n not in matched_a]
        final_only_b = [n for n in only_b_names if n not in matched_b]

        common_diffs = []
        for name_a, name_b in cross_matches:
            ld = self._compare_layers(f"{name_a} ↔ {name_b}",
                                       self.board_a.layers[name_a],
                                       self.board_b.layers[name_b])
            common_diffs.append(ld)
        for name in common_names:
            ld = self._compare_layers(name,
                                       self.board_a.layers[name],
                                       self.board_b.layers[name])
            common_diffs.append(ld)

        report = DiffReport(
            version_a=self.label_a,
            version_b=self.label_b,
            layers_only_a=list(final_only_a),
            layers_only_b=list(final_only_b),
            common_layers=common_diffs,
        )
        report.summary = report.to_text()
        return report

    def _compare_layers(self, name: str, layer_a: LayerData, layer_b: LayerData) -> LayerDiff:
        count_a = len(layer_a.primitives)
        count_b = len(layer_b.primitives)
        holes_a = layer_a.drill_holes
        holes_b = layer_b.drill_holes

        details = []
        min_prims = min(count_a, count_b)
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
                details.append(detail)

        prim_added = max(0, count_b - count_a)
        prim_removed = max(0, count_a - count_b)

        for k in range(min_prims, count_b):
            details.append(PrimitiveDiff(
                layer=name, obj_type=self._get_primitive_type(layer_b.primitives[k]),
                new_position=self._get_primitive_position(layer_b.primitives[k]),
                change_type="added", details="New primitive added",
            ))
        for k in range(min_prims, count_a):
            details.append(PrimitiveDiff(
                layer=name, obj_type=self._get_primitive_type(layer_a.primitives[k]),
                old_position=self._get_primitive_position(layer_a.primitives[k]),
                change_type="removed", details="Primitive removed",
            ))

        hole_added = 0; hole_removed = 0; hole_modified = 0; matching_holes = 0

        holes_a_by_pos = {}
        for h in holes_a:
            key = (round(h.position.x, 4), round(h.position.y, 4))
            holes_a_by_pos.setdefault(key, []).append(h)
        holes_b_by_pos = {}
        for h in holes_b:
            key = (round(h.position.x, 4), round(h.position.y, 4))
            holes_b_by_pos.setdefault(key, []).append(h)

        matched_b_keys = set()
        for key, ha_list in holes_a_by_pos.items():
            if key in holes_b_by_pos:
                hb_list = holes_b_by_pos[key]
                matched_b_keys.add(key)
                n_a = len(ha_list)
                n_b = len(hb_list)
                mn = min(n_a, n_b)
                for i in range(mn):
                    ha = ha_list[i]
                    hb = hb_list[i]
                    if abs(ha.tool_diameter - hb.tool_diameter) < self.tolerance:
                        matching_holes += 1
                    else:
                        hole_modified += 1
                        details.append(PrimitiveDiff(
                            layer=name, obj_type="drill",
                            old_position=ha.position, new_position=hb.position,
                            old_tool_diameter=ha.tool_diameter,
                            new_tool_diameter=hb.tool_diameter,
                            change_type="modified",
                            details=f"Hole diameter changed: {ha.tool_diameter:.3f}→{hb.tool_diameter:.3f}mm",
                        ))
                hole_added += max(0, n_b - n_a)
                hole_removed += max(0, n_a - n_b)
            else:
                hole_removed += len(ha_list)
                for ha in ha_list:
                    details.append(PrimitiveDiff(
                        layer=name, obj_type="drill",
                        old_position=ha.position,
                        old_tool_diameter=ha.tool_diameter,
                        change_type="removed",
                        details=f"Drill hole removed ∅{ha.tool_diameter:.3f}mm",
                    ))

        for key, hb_list in holes_b_by_pos.items():
            if key not in matched_b_keys:
                hole_added += len(hb_list)
                for hb in hb_list:
                    details.append(PrimitiveDiff(
                        layer=name, obj_type="drill",
                        new_position=hb.position,
                        new_tool_diameter=hb.tool_diameter,
                        change_type="added",
                        details=f"Drill hole added ∅{hb.tool_diameter:.3f}mm",
                    ))

        all_identical = (
            count_a == count_b and
            matching_prims == count_a and
            hole_added == 0 and hole_removed == 0 and hole_modified == 0
        ) if holes_a or holes_b else (
            count_a == count_b and matching_prims == count_a
        )

        return LayerDiff(
            layer_name=name,
            layer_type=layer_a.layer_type.value,
            identical=all_identical,
            added_primitives=prim_added,
            removed_primitives=prim_removed,
            modified_primitives=different_prims,
            added_holes=hole_added,
            removed_holes=hole_removed,
            modified_holes=hole_modified,
            details=details,
        )

    def _build_primitive_diff(self, pa, pb, layer_name):
        obj_type = self._get_primitive_type(pa)
        pos_a = self._get_primitive_position(pa)
        pos_b = self._get_primitive_position(pb)

        detail = PrimitiveDiff(layer=layer_name, obj_type=obj_type,
                                old_position=pos_a, new_position=pos_b)

        w_a = self._get_primitive_width(pa)
        w_b = self._get_primitive_width(pb)

        if pos_a and pos_b:
            dist = pos_a.distance_to(pos_b)
            if dist > self.tolerance:
                detail.change_type = "modified"
                detail.details = f"Position changed by {dist:.4f}mm"
        if w_a is not None and w_b is not None and abs(w_a - w_b) > self.tolerance:
            detail.old_aperture_width = w_a
            detail.new_aperture_width = w_b
            if detail.change_type == "modified":
                detail.details += f"; Width {w_a:.3f}→{w_b:.3f}mm"
            else:
                detail.change_type = "modified"
                detail.details = f"Width changed {w_a:.3f}→{w_b:.3f}mm"
        if not detail.change_type:
            detail.change_type = "modified"
            detail.details = "Aperture or shape changed"
        return detail

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

    def _get_primitive_position(self, prim):
        if isinstance(prim, LinePrimitive):
            return Point((prim.start.x + prim.end.x) / 2, (prim.start.y + prim.end.y) / 2)
        elif isinstance(prim, ArcPrimitive):
            return prim.start
        elif isinstance(prim, FlashPrimitive):
            return prim.position
        elif isinstance(prim, RegionPrimitive):
            return prim.points[0] if prim.points else None
        return None

    def _get_primitive_type(self, prim):
        if isinstance(prim, LinePrimitive):
            return "trace"
        elif isinstance(prim, ArcPrimitive):
            return "arc"
        elif isinstance(prim, FlashPrimitive):
            return "pad"
        elif isinstance(prim, RegionPrimitive):
            return "region"
        return "unknown"

    def _get_primitive_width(self, prim):
        if prim.aperture and prim.aperture.params:
            return prim.aperture.params[0]
        return None


def diff_gerber_versions(paths_a, paths_b, label_a="Version A", label_b="Version B"):
    differ = GerberDiff(paths_a, paths_b, label_a, label_b)
    return differ.compare()