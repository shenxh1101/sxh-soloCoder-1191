import math
import json
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

from .models import (
    BoardData, LayerData, LayerType, Point,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive,
)


def _get_primitive_width(prim) -> Optional[float]:
    if prim.aperture and prim.aperture.params:
        return prim.aperture.params[0]
    return None


def _get_pad_size(prim: FlashPrimitive) -> Optional[float]:
    if not prim.aperture or not prim.aperture.params:
        return None
    params = prim.aperture.params
    shape = prim.aperture.shape.value
    if shape == "C":
        return params[0]
    if shape == "R":
        return max(params[0], params[1]) if len(params) > 1 else params[0]
    return params[0]


def _get_half_width(prim) -> float:
    if isinstance(prim, FlashPrimitive):
        if prim.aperture and prim.aperture.params:
            if prim.aperture.shape.value == "C":
                return prim.aperture.params[0] / 2.0
            elif prim.aperture.shape.value == "R":
                w = prim.aperture.params[0]
                h = prim.aperture.params[1] if len(prim.aperture.params) > 1 else w
                return max(w, h) / 2.0
            return prim.aperture.params[0] / 2.0
        return 0.5
    elif isinstance(prim, (LinePrimitive, ArcPrimitive)):
        if prim.aperture and prim.aperture.params:
            return prim.aperture.params[0] / 2.0
        return 0.0
    return 0.0


def _point_to_segment_dist(p: Point, a: Point, b: Point) -> float:
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 0 and dy == 0:
        return p.distance_to(a)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)))
    proj = Point(a.x + t * dx, a.y + t * dy)
    return p.distance_to(proj)


def _primitive_edge_distance(a, b) -> Optional[float]:
    hw_a = _get_half_width(a)
    hw_b = _get_half_width(b)

    if isinstance(a, FlashPrimitive) and isinstance(b, FlashPrimitive):
        return max(0.0, a.position.distance_to(b.position) - hw_a - hw_b)

    if isinstance(a, FlashPrimitive) and isinstance(b, LinePrimitive):
        return max(0.0, _point_to_segment_dist(a.position, b.start, b.end) - hw_a - hw_b)
    if isinstance(b, FlashPrimitive) and isinstance(a, LinePrimitive):
        return max(0.0, _point_to_segment_dist(b.position, a.start, a.end) - hw_a - hw_b)

    if isinstance(a, LinePrimitive) and isinstance(b, LinePrimitive):
        d = _point_to_segment_dist(a.start, b.start, b.end)
        d = min(d, _point_to_segment_dist(a.end, b.start, b.end))
        d = min(d, _point_to_segment_dist(b.start, a.start, a.end))
        d = min(d, _point_to_segment_dist(b.end, a.start, a.end))
        return max(0.0, d - hw_a - hw_b)

    return None


def _compute_min_clearance(primitives: List) -> float:
    segments = [p for p in primitives if isinstance(p, (LinePrimitive, ArcPrimitive, FlashPrimitive)) and p.polarity]
    min_clear = float("inf")
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            d = _primitive_edge_distance(segments[i], segments[j])
            if d is not None and d < min_clear:
                min_clear = d
    return min_clear if min_clear != float("inf") else 0.0


def _get_board_outline(board: BoardData) -> Optional[Dict[str, Any]]:
    for layer in board.layers.values():
        if layer.layer_type == LayerType.BOARD_OUTLINE and layer.primitives:
            min_x, min_y, max_x, max_y = layer.bounding_box
            width = max_x - min_x
            height = max_y - min_y
            if width > 0 and height > 0:
                return {
                    "width_mm": round(width, 4),
                    "height_mm": round(height, 4),
                    "origin_x_mm": round(min_x, 4),
                    "origin_y_mm": round(min_y, 4),
                    "from_layer": layer.name,
                    "from_outline_layer": True,
                }
    if board.layers:
        bbox = board.total_bounding_box
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width > 0 and height > 0:
            return {
                "width_mm": round(width, 4),
                "height_mm": round(height, 4),
                "origin_x_mm": round(bbox[0], 4),
                "origin_y_mm": round(bbox[1], 4),
                "from_layer": "total_bounding_box",
                "from_outline_layer": False,
            }
    return None


def _hole_to_edge_distance(hole_pos: Point, outline: Dict[str, Any]) -> Optional[float]:
    if not outline:
        return None
    ox = outline.get("origin_x_mm", 0.0)
    oy = outline.get("origin_y_mm", 0.0)
    ow = outline["width_mm"]
    oh = outline["height_mm"]
    dist_left = hole_pos.x - ox
    dist_right = (ox + ow) - hole_pos.x
    dist_bottom = hole_pos.y - oy
    dist_top = (oy + oh) - hole_pos.y
    return min(dist_left, dist_right, dist_bottom, dist_top)


def _extract_audit_summary(board: BoardData) -> Dict[str, Any]:
    outline = _get_board_outline(board)

    copper_summaries = []
    for layer in board.layers.values():
        if layer.layer_type not in (LayerType.TOP_COPPER, LayerType.BOTTOM_COPPER, LayerType.INNER):
            continue

        trace_widths = []
        pad_sizes = []
        for prim in layer.primitives:
            if not prim.polarity:
                continue
            if isinstance(prim, (LinePrimitive, ArcPrimitive)):
                w = _get_primitive_width(prim)
                if w:
                    trace_widths.append(w)
            elif isinstance(prim, FlashPrimitive):
                s = _get_pad_size(prim)
                if s:
                    pad_sizes.append(s)

        min_clearance = _compute_min_clearance(layer.primitives)

        copper_summaries.append({
            "layer": layer.name,
            "layer_type": layer.layer_type.value,
            "trace_count": len(trace_widths),
            "min_trace_width_mm": round(min(trace_widths), 4) if trace_widths else None,
            "max_trace_width_mm": round(max(trace_widths), 4) if trace_widths else None,
            "pad_count": len(pad_sizes),
            "min_pad_size_mm": round(min(pad_sizes), 4) if pad_sizes else None,
            "max_pad_size_mm": round(max(pad_sizes), 4) if pad_sizes else None,
            "min_intra_layer_clearance_mm": round(min_clearance, 4) if min_clearance != float("inf") else None,
        })

    drill_data = {}
    for layer in board.layers.values():
        if layer.layer_type != LayerType.DRILL:
            continue
        holes = layer.drill_holes
        if not holes:
            continue
        diameters = [h.tool_diameter for h in holes]
        dia_dist = Counter(round(d, 4) for d in diameters)
        drill_data = {
            "layer": layer.name,
            "total_holes": len(holes),
            "diameter_range_mm": {
                "min": round(min(diameters), 4),
                "max": round(max(diameters), 4),
            },
            "diameter_distribution": {str(k): v for k, v in sorted(dia_dist.items())},
        }
        if outline:
            edge_dists = []
            for hole in holes:
                d = _hole_to_edge_distance(hole.position, outline)
                if d is not None:
                    edge_dists.append(d)
            if edge_dists:
                drill_data["min_hole_to_board_edge_mm"] = round(min(edge_dists), 4)
                drill_data["max_hole_to_board_edge_mm"] = round(max(edge_dists), 4)

    flags = _compute_audit_flags(copper_summaries, drill_data)

    return {
        "board_outline_mm": outline,
        "copper_layers": copper_summaries,
        "drill": drill_data if drill_data else None,
        "flags": flags,
    }


def _compute_audit_flags(copper_summaries: list, drill_data: dict) -> Dict[str, Any]:
    flags = {"all_passed": True, "issues": []}

    for cs in copper_summaries:
        if cs["min_trace_width_mm"] is not None and cs["min_trace_width_mm"] < 0.1:
            flags["all_passed"] = False
            flags["issues"].append(f"{cs['layer']}: min trace width {cs['min_trace_width_mm']}mm < 0.1mm")
        if cs["min_intra_layer_clearance_mm"] is not None and cs["min_intra_layer_clearance_mm"] < 0.1:
            flags["all_passed"] = False
            flags["issues"].append(f"{cs['layer']}: min clearance {cs['min_intra_layer_clearance_mm']}mm < 0.1mm")

    if drill_data:
        if drill_data.get("diameter_range_mm", {}).get("min", 0) < 0.15:
            flags["all_passed"] = False
            flags["issues"].append(f"min drill dia {drill_data['diameter_range_mm']['min']}mm < 0.15mm")
        if drill_data.get("min_hole_to_board_edge_mm", float("inf")) < 0.2:
            flags["all_passed"] = False
            flags["issues"].append(f"min hole-to-edge {drill_data['min_hole_to_board_edge_mm']}mm < 0.2mm")

    if not flags["issues"]:
        flags["all_passed"] = True

    return flags


def extract_layer_metadata(layer: LayerData) -> Dict[str, Any]:
    trace_length = 0.0
    trace_widths = []
    pad_sizes = []
    region_count = 0
    arc_count = 0

    for prim in layer.primitives:
        if isinstance(prim, LinePrimitive):
            if prim.polarity:
                trace_length += prim.length()
                w = _get_primitive_width(prim)
                if w:
                    trace_widths.append(w)
        elif isinstance(prim, ArcPrimitive):
            if prim.polarity:
                trace_length += prim.length()
                w = _get_primitive_width(prim)
                if w:
                    trace_widths.append(w)
            arc_count += 1
        elif isinstance(prim, FlashPrimitive):
            s = _get_pad_size(prim)
            if s:
                pad_sizes.append(s)
        elif isinstance(prim, RegionPrimitive):
            region_count += 1

    trace_width_dist = Counter(round(w, 4) for w in trace_widths)
    pad_size_dist = Counter(round(s, 4) for s in pad_sizes)

    return {
        "layer_name": layer.name,
        "layer_type": layer.layer_type.value,
        "total_primitives": len(layer.primitives),
        "trace_count": sum(1 for p in layer.primitives if isinstance(p, (LinePrimitive, ArcPrimitive)) and p.polarity),
        "pad_count": sum(1 for p in layer.primitives if isinstance(p, FlashPrimitive)),
        "arc_count": arc_count,
        "region_count": region_count,
        "total_trace_length_mm": round(trace_length, 4),
        "trace_width_distribution_mm": {str(k): v for k, v in sorted(trace_width_dist.items())},
        "min_trace_width_mm": round(min(trace_widths), 4) if trace_widths else None,
        "max_trace_width_mm": round(max(trace_widths), 4) if trace_widths else None,
        "pad_size_distribution_mm": {str(k): v for k, v in sorted(pad_size_dist.items())},
        "min_pad_size_mm": round(min(pad_sizes), 4) if pad_sizes else None,
        "max_pad_size_mm": round(max(pad_sizes), 4) if pad_sizes else None,
    }


def extract_drill_metadata(layer: LayerData) -> Dict[str, Any]:
    holes = layer.drill_holes
    if not holes:
        return {
            "layer_name": layer.name,
            "total_holes": 0,
            "total_vias": 0,
        }
    diameters = [h.tool_diameter for h in holes]
    dia_dist = Counter(round(d, 4) for d in diameters)
    return {
        "layer_name": layer.name,
        "total_holes": len(holes),
        "total_vias": len(holes),
        "diameter_distribution_mm": {str(k): v for k, v in sorted(dia_dist.items())},
        "min_diameter_mm": round(min(diameters), 4),
        "max_diameter_mm": round(max(diameters), 4),
    }


def extract_metadata(board: BoardData) -> str:
    result = {
        "board_name": "PCB",
        "layers": {},
        "global": {
            "total_trace_length_mm": 0.0,
            "total_holes": 0,
            "total_vias": 0,
            "trace_width_distribution_mm": {},
            "pad_size_distribution_mm": {},
        },
    }

    global_trace_widths = []
    global_pad_sizes = []

    for name, layer in board.layers.items():
        if layer.layer_type == LayerType.DRILL:
            md = extract_drill_metadata(layer)
            result["layers"][name] = md
            result["global"]["total_holes"] += md["total_holes"]
            result["global"]["total_vias"] += md["total_vias"]
        else:
            md = extract_layer_metadata(layer)
            result["layers"][name] = md
            result["global"]["total_trace_length_mm"] += md["total_trace_length_mm"]
            if md["trace_width_distribution_mm"]:
                for w_str, count in md["trace_width_distribution_mm"].items():
                    w = float(w_str)
                    global_trace_widths.extend([w] * count)
            if md["pad_size_distribution_mm"]:
                for s_str, count in md["pad_size_distribution_mm"].items():
                    s = float(s_str)
                    global_pad_sizes.extend([s] * count)

    if global_trace_widths:
        gw_dist = Counter(round(w, 4) for w in global_trace_widths)
        result["global"]["trace_width_distribution_mm"] = {str(k): v for k, v in sorted(gw_dist.items())}
        result["global"]["min_trace_width_mm"] = round(min(global_trace_widths), 4)
        result["global"]["max_trace_width_mm"] = round(max(global_trace_widths), 4)
    if global_pad_sizes:
        gs_dist = Counter(round(s, 4) for s in global_pad_sizes)
        result["global"]["pad_size_distribution_mm"] = {str(k): v for k, v in sorted(gs_dist.items())}
        result["global"]["min_pad_size_mm"] = round(min(global_pad_sizes), 4)
        result["global"]["max_pad_size_mm"] = round(max(global_pad_sizes), 4)

    result["global"]["total_trace_length_mm"] = round(result["global"]["total_trace_length_mm"], 4)

    result["audit_summary"] = _extract_audit_summary(board)

    return json.dumps(result, indent=2, ensure_ascii=False)


def generate_cam_report(board: BoardData) -> str:
    summary = _extract_audit_summary(board)

    lines = []
    lines.append("# PCB CAM Audit Report")
    lines.append("")

    # ── Board Outline ──
    lines.append("## 1. Board Outline")
    lines.append("")
    outline = summary.get("board_outline_mm")
    if outline:
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Width | {outline['width_mm']} mm |")
        lines.append(f"| Height | {outline['height_mm']} mm |")
        lines.append(f"| Origin | ({outline.get('origin_x_mm', 0)}, {outline.get('origin_y_mm', 0)}) mm |")
        lines.append(f"| Source | {outline['from_layer']} |")
        lines.append(f"| From outline layer | {outline['from_outline_layer']} |")
        lines.append("")
    else:
        lines.append("> No board outline layer detected.")
        lines.append("")

    # ── Copper Layers ──
    lines.append("## 2. Copper Layers")
    lines.append("")
    copper_layers = summary.get("copper_layers", [])
    if copper_layers:
        lines.append("| Layer | Traces | Min Width | Max Width | Pads | Min Pad | Max Pad | Min Clearance |")
        lines.append("|-------|--------|-----------|-----------|------|---------|---------|---------------|")
        for cl in copper_layers:
            tw = f"{cl['min_trace_width_mm']}mm" if cl.get("min_trace_width_mm") else "-"
            mxw = f"{cl['max_trace_width_mm']}mm" if cl.get("max_trace_width_mm") else "-"
            mp = f"{cl['min_pad_size_mm']}mm" if cl.get("min_pad_size_mm") else "-"
            mxp = f"{cl['max_pad_size_mm']}mm" if cl.get("max_pad_size_mm") else "-"
            mc = f"{cl['min_intra_layer_clearance_mm']}mm" if cl.get("min_intra_layer_clearance_mm") else "-"
            lines.append(
                f"| {cl['layer']} | {cl['trace_count']} | {tw} | {mxw} | "
                f"{cl['pad_count']} | {mp} | {mxp} | {mc} |"
            )
        lines.append("")
    else:
        lines.append("> No copper layers detected.")
        lines.append("")

    # ── Drill ──
    lines.append("## 3. Drill")
    lines.append("")
    drill = summary.get("drill")
    if drill:
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Total holes | {drill['total_holes']} |")
        lines.append(f"| Diameter range | {drill['diameter_range_mm']['min']}mm – {drill['diameter_range_mm']['max']}mm |")
        if "min_hole_to_board_edge_mm" in drill:
            lines.append(f"| Min hole to edge | {drill['min_hole_to_board_edge_mm']}mm |")
        if "max_hole_to_board_edge_mm" in drill:
            lines.append(f"| Max hole to edge | {drill['max_hole_to_board_edge_mm']}mm |")
        lines.append("")
        lines.append(f"| Diameter (mm) | Count |")
        lines.append(f"|---------------|-------|")
        for dia, cnt in sorted(drill.get("diameter_distribution", {}).items()):
            lines.append(f"| {dia} | {cnt} |")
        lines.append("")
    else:
        lines.append("> No drill data detected.")
        lines.append("")

    # ── Solder Mask ──
    lines.append("## 4. Solder Mask")
    lines.append("")
    mask_layers = [l for l in board.layers.values()
                   if l.layer_type in (LayerType.TOP_SOLDER_MASK, LayerType.BOTTOM_SOLDER_MASK)]
    if mask_layers:
        lines.append("| Layer | Primitives | Pads | Regions |")
        lines.append("|-------|------------|------|---------|")
        for ml in mask_layers:
            pads = sum(1 for p in ml.primitives if isinstance(p, FlashPrimitive))
            regions = sum(1 for p in ml.primitives if isinstance(p, RegionPrimitive))
            lines.append(f"| {ml.name} | {len(ml.primitives)} | {pads} | {regions} |")
        lines.append("")
    else:
        lines.append("> No solder mask layers detected.")
        lines.append("")

    # ── Silkscreen ──
    lines.append("## 5. Silkscreen")
    lines.append("")
    silk_layers = [l for l in board.layers.values()
                   if l.layer_type in (LayerType.TOP_SILKSCREEN, LayerType.BOTTOM_SILKSCREEN)]
    if silk_layers:
        lines.append("| Layer | Primitives | Lines | Pads | Regions |")
        lines.append("|-------|------------|-------|------|---------|")
        for sl in silk_layers:
            lines_cnt = sum(1 for p in sl.primitives if isinstance(p, LinePrimitive))
            pads = sum(1 for p in sl.primitives if isinstance(p, FlashPrimitive))
            regions = sum(1 for p in sl.primitives if isinstance(p, RegionPrimitive))
            lines.append(f"| {sl.name} | {len(sl.primitives)} | {lines_cnt} | {pads} | {regions} |")
        lines.append("")
    else:
        lines.append("> No silkscreen layers detected.")
        lines.append("")

    # ── Audit Flags ──
    lines.append("## 6. Audit Flags")
    lines.append("")
    flags = summary.get("flags", {})
    if flags.get("all_passed"):
        lines.append("**Status: PASS** — All checks passed.")
    else:
        lines.append("**Status: ISSUES FOUND**")
        lines.append("")
        for issue in flags.get("issues", []):
            lines.append(f"- {issue}")
    lines.append("")

    # ── Layer Manifest ──
    lines.append("## 7. Layer Manifest")
    lines.append("")
    lines.append("| File | Type | Primitives | Holes |")
    lines.append("|------|------|------------|-------|")
    for name, layer in board.layers.items():
        prim_count = len(layer.primitives)
        hole_count = len(layer.drill_holes)
        lines.append(f"| {name} | {layer.layer_type.value} | {prim_count} | {hole_count} |")
    lines.append("")

    return "\n".join(lines)