import re
import math
import os
from typing import List, Tuple, Optional, Dict

from .models import (
    Point, ApertureDef, ApertureShape, LayerType, LayerData, BoardData,
    LinePrimitive, ArcPrimitive, FlashPrimitive, RegionPrimitive, DrillHole,
    detect_layer_type,
)


class GerberParser:
    def __init__(self):
        self.apertures: Dict[int, ApertureDef] = {}
        self.current_aperture: Optional[ApertureDef] = None
        self.current_point: Point = Point(0, 0)
        self.primitives: List = []
        self.polarity_dark: bool = True
        self.unit: str = "mm"
        self.format: Tuple[int, int] = (2, 4)
        self.zero_suppression: str = "trailing"
        self.region_mode: bool = False
        self.region_points: List[Point] = []
        self.step_and_repeat: bool = False
        self.interpolation_mode: Optional[str] = None
        self.quadrant_mode: str = "single"
        self.x: float = 0.0
        self.y: float = 0.0
        self.i: float = 0.0
        self.j: float = 0.0
        self._g01_traverse: bool = True

    def parse_file(self, filepath: str) -> LayerData:
        layer_type = detect_layer_type(os.path.basename(filepath))
        layer_name = os.path.basename(filepath)

        self._reset()
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        self._parse_lines(lines)

        return LayerData(
            layer_type=layer_type,
            name=layer_name,
            primitives=self.primitives,
            apertures=self.apertures,
            polarity_dark=self.polarity_dark,
        )

    def _reset(self):
        self.apertures = {}
        self.current_aperture = None
        self.current_point = Point(0, 0)
        self.primitives = []
        self.polarity_dark = True
        self.region_mode = False
        self.region_points = []
        self.step_and_repeat = False
        self.interpolation_mode = None
        self.x = 0.0
        self.y = 0.0
        self.i = 0.0
        self.j = 0.0

    def _parse_lines(self, lines: List[str]):
        combined = self._combine_blocks(lines)
        for line in combined:
            line = line.strip()
            if not line:
                continue
            self._parse_block(line)

    def _combine_blocks(self, lines: List[str]) -> List[str]:
        result = []
        buffer = ""
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            buffer += stripped
            if buffer.endswith("*%") or buffer.endswith("*"):
                if buffer.endswith("*%"):
                    buffer = buffer[:-1]
                result.append(buffer)
                buffer = ""
        if buffer:
            result.append(buffer)
        return result

    def _parse_block(self, block: str):
        if block.startswith("%"):
            self._parse_extended(block)
            return

        codes = re.findall(r"[A-Za-z]\d+", block)
        coords = re.findall(r"[XYIJ]\-?\d+", block)
        d_codes = re.findall(r"D\d+", block)

        new_x = self.x
        new_y = self.y
        new_i = self.i
        new_j = self.j

        for coord in coords:
            letter = coord[0]
            value = int(coord[1:])
            decimal = self._coord_to_decimal(value)
            if letter == "X":
                new_x = decimal
            elif letter == "Y":
                new_y = decimal
            elif letter == "I":
                new_i = decimal
            elif letter == "J":
                new_j = decimal

        for code in codes:
            if code.startswith("G"):
                self._handle_g_code(code)
            elif code.startswith("M"):
                self._handle_m_code(code)
            elif code.startswith("D"):
                self._handle_d_code(code, new_x, new_y, new_i, new_j)

        d_match = re.search(r"D\d+", block)
        if not codes and d_match:
            self._handle_d_code(d_match.group(0), new_x, new_y, new_i, new_j)

    def _coord_to_decimal(self, value: int) -> float:
        int_part, frac_part = self.format
        total_digits = int_part + frac_part
        s = str(abs(value)).zfill(total_digits)
        if len(s) > total_digits:
            s = s[-total_digits:]
        result = float(s[:int_part] + "." + s[int_part:])
        return result if value >= 0 else -result

    def _handle_g_code(self, code: str):
        if code == "G01":
            self.interpolation_mode = "linear"
        elif code == "G02":
            self.interpolation_mode = "circular_cw"
        elif code == "G03":
            self.interpolation_mode = "circular_ccw"
        elif code == "G04":
            pass
        elif code == "G36":
            self.region_mode = True
            self.region_points = []
        elif code == "G37":
            self.region_mode = False
            if len(self.region_points) >= 3:
                self.primitives.append(RegionPrimitive(
                    points=list(self.region_points),
                    polarity=self.polarity_dark,
                ))
            self.region_points = []
        elif code == "G54":
            self.current_aperture = self.apertures.get(10)
        elif code == "G55":
            pass
        elif code == "G70":
            self.unit = "inch"
        elif code == "G71":
            self.unit = "mm"
        elif code == "G74":
            self.quadrant_mode = "single"
        elif code == "G75":
            self.quadrant_mode = "multi"
        elif code == "G90":
            pass

    def _handle_m_code(self, code: str):
        if code == "M00":
            pass
        elif code == "M02":
            pass

    def _handle_d_code(self, code: str, x: float, y: float, i: float, j: float):
        d_num = int(code[1:])
        if d_num >= 10:
            if d_num in self.apertures:
                self.current_aperture = self.apertures[d_num]
        elif d_num == 1:
            if self.region_mode:
                if not self.region_points or self.region_points[-1] != Point(x, y):
                    self.region_points.append(Point(x, y))
            elif self.interpolation_mode in (None, "linear"):
                start = self.current_point
                end = Point(x, y)
                if start.distance_to(end) > 0.0001:
                    self.primitives.append(LinePrimitive(
                        start=start, end=end,
                        aperture=self.current_aperture,
                        polarity=self.polarity_dark,
                    ))
                self.current_point = Point(x, y)
            elif self.interpolation_mode in ("circular_cw", "circular_ccw"):
                direction = "G02" if self.interpolation_mode == "circular_cw" else "G03"
                center = Point(self.current_point.x + i, self.current_point.y + j)
                self.primitives.append(ArcPrimitive(
                    center=center,
                    start=self.current_point,
                    end=Point(x, y),
                    direction=direction,
                    aperture=self.current_aperture,
                    polarity=self.polarity_dark,
                ))
                self.current_point = Point(x, y)
            self.x = x
            self.y = y
            self.i = i
            self.j = j
        elif d_num == 2:
            self.current_point = Point(x, y)
            self.x = x
            self.y = y
        elif d_num == 3:
            if self.current_aperture:
                self.primitives.append(FlashPrimitive(
                    position=Point(x, y),
                    aperture=self.current_aperture,
                    polarity=self.polarity_dark,
                ))
            self.current_point = Point(x, y)
            self.x = x
            self.y = y

    def _parse_extended(self, block: str):
        content = block.strip("%")
        parts = content.split("*")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.startswith("AD"):
                self._parse_aperture_definition(part)
            elif part.startswith("FS"):
                self._parse_format_spec(part)
            elif part.startswith("MO"):
                self._parse_unit(part)
            elif part.startswith("LP"):
                self.polarity_dark = (part[2:] == "D")
            elif part.startswith("SR"):
                pass
            elif part.startswith("TF"):
                pass
            elif part.startswith("TA"):
                pass
            elif part.startswith("TO"):
                pass
            elif part.startswith("TD"):
                pass

    def _parse_aperture_definition(self, ad: str):
        match = re.match(r"ADD(\d+)([CROP])\s*,\s*(.+)", ad)
        if not match:
            return
        d_code = int(match.group(1))
        shape_char = match.group(2)
        params_str = match.group(3)

        shape_map = {"C": ApertureShape.CIRCLE, "R": ApertureShape.RECTANGLE,
                     "O": ApertureShape.OBROUND, "P": ApertureShape.POLYGON}
        shape = shape_map.get(shape_char, ApertureShape.CIRCLE)

        params = []
        for token in params_str.split("X"):
            token = token.strip()
            if token:
                try:
                    params.append(float(token))
                except ValueError:
                    pass

        self.apertures[d_code] = ApertureDef(d_code=d_code, shape=shape, params=params)

    def _parse_format_spec(self, fs: str):
        match = re.match(r"FS([LT])([AI])(\d)(\d)", fs)
        if match:
            self.zero_suppression = "leading" if match.group(1) == "L" else "trailing"
            int_part = int(match.group(3))
            frac_part = int(match.group(4))
            self.format = (int_part, frac_part)

    def _parse_unit(self, mo: str):
        if "IN" in mo.upper():
            self.unit = "inch"
        elif "MM" in mo.upper():
            self.unit = "mm"


class DrillParser:
    def __init__(self):
        self.tools: Dict[int, float] = {}
        self.current_tool: int = 0
        self.drill_holes: List[DrillHole] = []
        self.unit: str = "mm"
        self.format: Tuple[int, int] = (2, 4)
        self.zero_suppression: str = "trailing"

    def parse_file(self, filepath: str) -> LayerData:
        layer_name = os.path.basename(filepath)

        self._reset()
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        self._parse_drill_lines(lines)

        return LayerData(
            layer_type=LayerType.DRILL,
            name=layer_name,
            drill_holes=self.drill_holes,
        )

    def _reset(self):
        self.tools = {}
        self.current_tool = 0
        self.drill_holes = []
        self.last_x = 0.0
        self.last_y = 0.0
        self.last_x_is_decimal = False
        self.last_y_is_decimal = False

    def _drill_coord_to_mm(self, value: float, is_decimal: bool = False) -> float:
        if is_decimal:
            result = value
        else:
            int_part, frac_part = self.format
            total_digits = int_part + frac_part
            s = str(int(abs(value))).zfill(total_digits)
            if len(s) > total_digits:
                s = s[-total_digits:]
            result = float(s[:int_part] + "." + s[int_part:])
            if value < 0:
                result = -result
        if self.unit == "inch":
            result = result * 25.4
        return result

    def _has_decimal(self, s: str) -> bool:
        return "." in s

    def _parse_drill_lines(self, lines: List[str]):
        in_header = True
        self.last_x = 0.0
        self.last_y = 0.0
        self.last_x_is_decimal = False
        self.last_y_is_decimal = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.upper().startswith("M48"):
                in_header = True
                continue
            if line.upper().startswith("M95"):
                continue
            if line.upper().startswith("M30"):
                continue
            if line.upper() == "%":
                in_header = False
                continue

            if line.upper() == "METRIC":
                self.unit = "mm"
                continue
            if line.upper() == "INCH":
                self.unit = "inch"
                continue

            if line.upper().startswith("FMAT"):
                match = re.match(r"FMAT\s*,\s*(\d)", line, re.IGNORECASE)
                if match:
                    fmt = int(match.group(1))
                    if fmt == 1:
                        self.format = (2, 4)
                    elif fmt == 2:
                        self.format = (3, 3)
                continue

            if line.upper().startswith("T"):
                if in_header:
                    match = re.match(r"T(\d+)\s*C?([\d.]+)", line, re.IGNORECASE)
                    if match:
                        tool_num = int(match.group(1))
                        dia_str = match.group(2)
                        if dia_str:
                            self.tools[tool_num] = float(dia_str)
                else:
                    match = re.match(r"T(\d+)", line, re.IGNORECASE)
                    if match:
                        tool_num = int(match.group(1))
                        self.current_tool = tool_num
                continue

            if line.upper().startswith("G90"):
                continue
            if line.upper().startswith("G05"):
                continue
            if line.upper().startswith("R"):
                continue

            if in_header:
                continue

            has_x = False
            has_y = False

            x_match = re.search(r"X([\d.\-]+)", line, re.IGNORECASE)
            if x_match:
                x_str = x_match.group(1)
                self.last_x_is_decimal = self._has_decimal(x_str)
                self.last_x = float(x_str)
                has_x = True

            y_match = re.search(r"Y([\d.\-]+)", line, re.IGNORECASE)
            if y_match:
                y_str = y_match.group(1)
                self.last_y_is_decimal = self._has_decimal(y_str)
                self.last_y = float(y_str)
                has_y = True

            if has_x or has_y:
                x = self._drill_coord_to_mm(self.last_x, self.last_x_is_decimal)
                y = self._drill_coord_to_mm(self.last_y, self.last_y_is_decimal)
                dia = self.tools.get(self.current_tool, 0.8)
                if self.unit == "inch":
                    dia = dia * 25.4
                self.drill_holes.append(DrillHole(
                    position=Point(x, y),
                    tool_diameter=dia,
                    plated=True,
                ))


def parse_gerber_file(filepath: str) -> LayerData:
    parser = GerberParser()
    return parser.parse_file(filepath)


def parse_drill_file(filepath: str) -> LayerData:
    parser = DrillParser()
    return parser.parse_file(filepath)


def parse_multiple_files(filepaths: List[str]) -> BoardData:
    board = BoardData()
    for fp in filepaths:
        ext = os.path.splitext(fp)[1].lower()
        if ext in (".txt", ".drl", ".xln"):
            layer = parse_drill_file(fp)
        else:
            layer = parse_gerber_file(fp)
        board.layers[layer.name] = layer
        board.file_paths[layer.name] = fp
    return board