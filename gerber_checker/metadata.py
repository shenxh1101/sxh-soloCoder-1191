import json
import math
from typing import Dict, Any, List

from .models import (
    Point, LayerData, BoardData, LayerType,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
)


class MetadataExtractor:
    def __init__(self, board: BoardData):
        self.board = board

    def extract(self) -> Dict[str, Any]:
        metadata = {
            "board": self._extract_board_info(),
            "layers": self._extract_layers_info(),
            "statistics": self._extract_statistics(),
        }
        return metadata

    def _extract_board_info(self) -> Dict[str, Any]:
        min_x, min_y, max_x, max_y = self.board.total_bounding_box
        return {
            "dimensions_mm": {
                "width": round(max_x - min_x, 3),
                "height": round(max_y - min_y, 3),
            },
            "bounding_box": {
                "min_x": round(min_x, 3),
                "min_y": round(min_y, 3),
                "max_x": round(max_x, 3),
                "max_y": round(max_y, 3),
            },
            "area_mm2": round((max_x - min_x) * (max_y - min_y), 3),
        }

    def _extract_layers_info(self) -> List[Dict[str, Any]]:
        layers_info = []
        for name, layer in self.board.layers.items():
            info = self._extract_layer_info(name, layer)
            layers_info.append(info)
        return layers_info

    def _extract_layer_info(self, name: str, layer: LayerData) -> Dict[str, Any]:
        trace_length = 0.0
        trace_count = 0
        pad_count = 0
        region_count = 0
        arc_count = 0

        for prim in layer.primitives:
            if isinstance(prim, LinePrimitive):
                trace_length += prim.length()
                trace_count += 1
            elif isinstance(prim, ArcPrimitive):
                trace_length += prim.length()
                arc_count += 1
            elif isinstance(prim, FlashPrimitive):
                pad_count += 1
            elif isinstance(prim, RegionPrimitive):
                region_count += 1

        min_x, min_y, max_x, max_y = layer.bounding_box

        return {
            "name": name,
            "type": layer.layer_type.value,
            "primitives": {
                "traces": trace_count,
                "arcs": arc_count,
                "pads": pad_count,
                "regions": region_count,
                "total": len(layer.primitives),
            },
            "total_trace_length_mm": round(trace_length, 3),
            "drill_holes": len(layer.drill_holes),
            "bounding_box": {
                "min_x": round(min_x, 3),
                "min_y": round(min_y, 3),
                "max_x": round(max_x, 3),
                "max_y": round(max_y, 3),
            },
        }

    def _extract_statistics(self) -> Dict[str, Any]:
        total_traces = 0
        total_pads = 0
        total_trace_length = 0.0
        total_vias = 0
        total_regions = 0
        total_arcs = 0

        drill_hole_count = 0
        drill_diameters = []

        for layer in self.board.layers.values():
            for prim in layer.primitives:
                if isinstance(prim, LinePrimitive):
                    total_traces += 1
                    total_trace_length += prim.length()
                elif isinstance(prim, ArcPrimitive):
                    total_arcs += 1
                    total_trace_length += prim.length()
                elif isinstance(prim, FlashPrimitive):
                    total_pads += 1
                elif isinstance(prim, RegionPrimitive):
                    total_regions += 1

            if layer.layer_type == LayerType.DRILL:
                drill_hole_count = len(layer.drill_holes)
                total_vias += drill_hole_count
                for hole in layer.drill_holes:
                    drill_diameters.append(round(hole.tool_diameter, 3))

        drill_diameters_unique = sorted(set(drill_diameters))
        plated_count = sum(
            1 for layer in self.board.layers.values()
            if layer.layer_type == LayerType.DRILL
            for hole in layer.drill_holes if hole.plated
        )
        non_plated = drill_hole_count - plated_count

        return {
            "total_traces": total_traces,
            "total_arcs": total_arcs,
            "total_pads": total_pads,
            "total_regions": total_regions,
            "total_vias": total_vias,
            "total_trace_length_mm": round(total_trace_length, 3),
            "drill": {
                "total_holes": total_vias,
                "plated_holes": plated_count,
                "non_plated_holes": non_plated,
                "unique_diameters_mm": drill_diameters_unique,
                "diameters_distribution": {
                    str(d): drill_diameters.count(d) for d in drill_diameters_unique
                },
            },
        }

    def to_json(self, output_path: str = None, indent: int = 2) -> str:
        data = self.extract()
        json_str = json.dumps(data, indent=indent, ensure_ascii=False, default=str)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
        return json_str


def extract_metadata(board: BoardData, output_path: str = None) -> str:
    extractor = MetadataExtractor(board)
    return extractor.to_json(output_path)