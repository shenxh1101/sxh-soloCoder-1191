import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)
from .parser import parse_multiple_files


@dataclass
class PrimitiveDiff:
    type: str
    position: Point
    details: str


@dataclass
class LayerDiff:
    layer_name: str
    added_primitives: int
    removed_primitives: int
    modified_primitives: int
    added_holes: int
    removed_holes: int
    details: List[PrimitiveDiff] = field(default_factory=list)


@dataclass
class DiffReport:
    version_a: str
    version_b: str
    layers_only_a: List[str]
    layers_only_b: List[str]
    common_layers: List[LayerDiff]
    summary: str = ""

    def to_dict(self):
        return {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "layers_only_in_a": self.layers_only_a,
            "layers_only_in_b": self.layers_only_b,
            "common_layers": [
                {
                    "layer_name": ld.layer_name,
                    "added_primitives": ld.added_primitives,
                    "removed_primitives": ld.removed_primitives,
                    "modified_primitives": ld.modified_primitives,
                    "added_holes": ld.added_holes,
                    "removed_holes": ld.removed_holes,
                    "detail_count": len(ld.details),
                }
                for ld in self.common_layers
            ],
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

        if self.layers_only_a:
            lines.append(f"\n  Layers only in Version A:")
            for l in self.layers_only_a:
                lines.append(f"    + {l}")

        if self.layers_only_b:
            lines.append(f"\n  Layers only in Version B:")
            for l in self.layers_only_b:
                lines.append(f"    + {l}")

        lines.append(f"\n  Common layers ({len(self.common_layers)}):")
        total_added = 0
        total_removed = 0
        total_modified = 0
        for ld in self.common_layers:
            total_added += ld.added_primitives
            total_removed += ld.removed_primitives
            total_modified += ld.modified_primitives
            lines.append(f"    [{ld.layer_name}]")
            lines.append(f"      Added: {ld.added_primitives} primitives, {ld.added_holes} holes")
            lines.append(f"      Removed: {ld.removed_primitives} primitives, {ld.removed_holes} holes")
            lines.append(f"      Modified: {ld.modified_primitives} primitives")

        lines.append(f"\n  Totals: +{total_added} / -{total_removed} / ~{total_modified}")
        lines.append("=" * 70)
        self.summary = "\n".join(lines)
        return self.summary


class GerberDiff:
    def __init__(self, version_a_paths: List[str], version_b_paths: List[str],
                 label_a: str = "Version A", label_b: str = "Version B",
                 tolerance_mm: float = 0.01):
        self.label_a = label_a
        self.label_b = label_b
        self.tolerance = tolerance_mm
        self.board_a = parse_multiple_files(version_a_paths) if not isinstance(version_a_paths, BoardData) else version_a_paths
        self.board_b = parse_multiple_files(version_b_paths) if not isinstance(version_b_paths, BoardData) else version_b_paths

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
            layer_a = self.board_a.layers[name_a]
            layer_b = self.board_b.layers[name_b]
            ld = self._compare_layers(f"{name_a} ↔ {name_b}", layer_a, layer_b)
            common_diffs.append(ld)

        for name in common_names:
            layer_a = self.board_a.layers[name]
            layer_b = self.board_b.layers[name]
            ld = self._compare_layers(name, layer_a, layer_b)
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
        holes_a = len(layer_a.drill_holes)
        holes_b = len(layer_b.drill_holes)

        added = max(0, count_b - count_a)
        removed = max(0, count_a - count_b)
        modified = min(count_a, count_b)

        details = []
        few_a = min(len(layer_a.primitives), len(layer_b.primitives))
        for i in range(min(10, few_a)):
            pa = layer_a.primitives[i]
            pb = layer_b.primitives[i]

            pos_a = self._get_primitive_position(pa)
            pos_b = self._get_primitive_position(pb)

            if pos_a and pos_b and pos_a.distance_to(pos_b) > self.tolerance:
                details.append(PrimitiveDiff(
                    type=self._get_primitive_type(pa),
                    position=pos_a,
                    details=f"Position changed by {pos_a.distance_to(pos_b):.3f}mm",
                ))

        return LayerDiff(
            layer_name=name,
            added_primitives=added,
            removed_primitives=removed,
            modified_primitives=modified,
            added_holes=max(0, holes_b - holes_a),
            removed_holes=max(0, holes_a - holes_b),
            details=details,
        )

    def _get_primitive_position(self, prim):
        if isinstance(prim, LinePrimitive):
            return Point((prim.start.x + prim.end.x) / 2, (prim.start.y + prim.end.y) / 2)
        elif isinstance(prim, ArcPrimitive):
            return prim.start
        elif isinstance(prim, FlashPrimitive):
            return prim.position
        elif isinstance(prim, RegionPrimitive):
            if prim.points:
                return prim.points[0]
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


def diff_gerber_versions(paths_a: List[str], paths_b: List[str],
                         label_a: str = "Version A", label_b: str = "Version B") -> DiffReport:
    differ = GerberDiff(paths_a, paths_b, label_a, label_b)
    return differ.compare()