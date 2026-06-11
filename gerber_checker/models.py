import re
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum


class ApertureShape(Enum):
    CIRCLE = "C"
    RECTANGLE = "R"
    OBROUND = "O"
    POLYGON = "P"


class LayerType(Enum):
    TOP_COPPER = "top_copper"
    BOTTOM_COPPER = "bottom_copper"
    TOP_SOLDER_MASK = "top_solder_mask"
    BOTTOM_SOLDER_MASK = "bottom_solder_mask"
    TOP_SILKSCREEN = "top_silkscreen"
    BOTTOM_SILKSCREEN = "bottom_silkscreen"
    BOARD_OUTLINE = "board_outline"
    DRILL = "drill"
    INNER = "inner"
    UNKNOWN = "unknown"


@dataclass
class Point:
    x: float
    y: float

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Point":
        return Point(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar: float) -> "Point":
        return Point(self.x / scalar, self.y / scalar)


@dataclass
class ApertureDef:
    d_code: int
    shape: ApertureShape
    params: List[float] = field(default_factory=list)


@dataclass
class LinePrimitive:
    start: Point
    end: Point
    aperture: Optional[ApertureDef] = None
    polarity: bool = True

    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass
class ArcPrimitive:
    center: Point
    start: Point
    end: Point
    direction: str = "G03"
    aperture: Optional[ApertureDef] = None
    polarity: bool = True

    def length(self) -> float:
        radius = self.center.distance_to(self.start)
        start_angle = math.atan2(self.start.y - self.center.y, self.start.x - self.center.x)
        end_angle = math.atan2(self.end.y - self.center.y, self.end.x - self.center.x)
        if self.direction == "G03":
            if end_angle <= start_angle:
                end_angle += 2 * math.pi
            angle = end_angle - start_angle
        else:
            if start_angle <= end_angle:
                start_angle += 2 * math.pi
            angle = start_angle - end_angle
        return radius * angle


@dataclass
class FlashPrimitive:
    position: Point
    aperture: Optional[ApertureDef] = None
    polarity: bool = True


@dataclass
class RegionPrimitive:
    points: List[Point]
    polarity: bool = True


@dataclass
class DrillHole:
    position: Point
    tool_diameter: float
    plated: bool = True


GerberPrimitive = LinePrimitive | ArcPrimitive | FlashPrimitive | RegionPrimitive


@dataclass
class LayerData:
    layer_type: LayerType
    name: str
    primitives: List[GerberPrimitive] = field(default_factory=list)
    drill_holes: List[DrillHole] = field(default_factory=list)
    apertures: Dict[int, ApertureDef] = field(default_factory=dict)
    polarity_dark: bool = True

    @property
    def bounding_box(self) -> Tuple[float, float, float, float]:
        if not self.primitives and not self.drill_holes:
            return (0, 0, 0, 0)
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for p in self.primitives:
            if isinstance(p, LinePrimitive):
                min_x = min(min_x, p.start.x, p.end.x)
                min_y = min(min_y, p.start.y, p.end.y)
                max_x = max(max_x, p.start.x, p.end.x)
                max_y = max(max_y, p.start.y, p.end.y)
            elif isinstance(p, ArcPrimitive):
                r = p.center.distance_to(p.start)
                for a in range(0, 360, 45):
                    rad = math.radians(a)
                    px = p.center.x + r * math.cos(rad)
                    py = p.center.y + r * math.sin(rad)
                    min_x = min(min_x, px)
                    min_y = min(min_y, py)
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)
            elif isinstance(p, FlashPrimitive):
                r = 1.0
                if p.aperture and p.aperture.params:
                    r = p.aperture.params[0] / 2
                min_x = min(min_x, p.position.x - r)
                min_y = min(min_y, p.position.y - r)
                max_x = max(max_x, p.position.x + r)
                max_y = max(max_y, p.position.y + r)
            elif isinstance(p, RegionPrimitive):
                for pt in p.points:
                    min_x = min(min_x, pt.x)
                    min_y = min(min_y, pt.y)
                    max_x = max(max_x, pt.x)
                    max_y = max(max_y, pt.y)
        for h in self.drill_holes:
            r = h.tool_diameter / 2
            min_x = min(min_x, h.position.x - r)
            min_y = min(min_y, h.position.y - r)
            max_x = max(max_x, h.position.x + r)
            max_y = max(max_y, h.position.y + r)
        return (min_x, min_y, max_x, max_y)


@dataclass
class BoardData:
    layers: Dict[str, LayerData] = field(default_factory=dict)
    file_paths: Dict[str, str] = field(default_factory=dict)

    @property
    def total_bounding_box(self) -> Tuple[float, float, float, float]:
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for layer in self.layers.values():
            lx1, ly1, lx2, ly2 = layer.bounding_box
            if lx2 > lx1:
                min_x = min(min_x, lx1)
                min_y = min(min_y, ly1)
                max_x = max(max_x, lx2)
                max_y = max(max_y, ly2)
        if min_x == float("inf"):
            return (0, 0, 0, 0)
        return (min_x, min_y, max_x, max_y)


LAYER_NAME_PATTERNS = {
    LayerType.TOP_COPPER: [r"(?i)(gtl|top.*copper|top.*layer|f.*cu|top\.gbr|layer1)"],
    LayerType.BOTTOM_COPPER: [r"(?i)(gbl|bottom.*copper|bottom.*layer|b.*cu|bot\.gbr|bottom\.gbr|layer2)"],
    LayerType.TOP_SOLDER_MASK: [r"(?i)(gts|top.*mask|top.*solder|f.*mask)"],
    LayerType.BOTTOM_SOLDER_MASK: [r"(?i)(gbs|bottom.*mask|bottom.*solder|b.*mask)"],
    LayerType.TOP_SILKSCREEN: [r"(?i)(gto|top.*silk|top.*legend|f.*silk)"],
    LayerType.BOTTOM_SILKSCREEN: [r"(?i)(gbo|bottom.*silk|bottom.*legend|b.*silk)"],
    LayerType.BOARD_OUTLINE: [r"(?i)(gko|gml|outline|board.*outline|edge.*cuts|profile)"],
    LayerType.DRILL: [r"(?i)(drill|.*\.txt$|.*\.drl$|.*\.xln$)"],
}


def detect_layer_type(filename: str) -> LayerType:
    basename = filename.lower()
    for layer_type, patterns in LAYER_NAME_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, basename):
                return layer_type
    if ".gbr" in basename or ".ger" in basename:
        return LayerType.UNKNOWN
    return LayerType.UNKNOWN