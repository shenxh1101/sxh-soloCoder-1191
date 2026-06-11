import yaml
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class DRCRules:
    min_trace_width_mm: float = 0.15
    min_clearance_mm: float = 0.15
    min_pad_to_trace_mm: float = 0.20
    min_via_diameter_mm: float = 0.30
    min_via_hole_mm: float = 0.15
    min_annular_ring_mm: float = 0.10
    max_aspect_ratio: float = 8.0
    min_silkscreen_text_height_mm: float = 0.80
    min_silkscreen_line_width_mm: float = 0.12
    min_solder_mask_clearance_mm: float = 0.05

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DRCRules":
        rules = data.get("drc_rules", data)
        return cls(
            min_trace_width_mm=float(rules.get("min_trace_width_mm", 0.15)),
            min_clearance_mm=float(rules.get("min_clearance_mm", 0.15)),
            min_pad_to_trace_mm=float(rules.get("min_pad_to_trace_mm", 0.20)),
            min_via_diameter_mm=float(rules.get("min_via_diameter_mm", 0.30)),
            min_via_hole_mm=float(rules.get("min_via_hole_mm", 0.15)),
            min_annular_ring_mm=float(rules.get("min_annular_ring_mm", 0.10)),
            max_aspect_ratio=float(rules.get("max_aspect_ratio", 8.0)),
            min_silkscreen_text_height_mm=float(rules.get("min_silkscreen_text_height_mm", 0.80)),
            min_silkscreen_line_width_mm=float(rules.get("min_silkscreen_line_width_mm", 0.12)),
            min_solder_mask_clearance_mm=float(rules.get("min_solder_mask_clearance_mm", 0.05)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drc_rules": {
                "min_trace_width_mm": self.min_trace_width_mm,
                "min_clearance_mm": self.min_clearance_mm,
                "min_pad_to_trace_mm": self.min_pad_to_trace_mm,
                "min_via_diameter_mm": self.min_via_diameter_mm,
                "min_via_hole_mm": self.min_via_hole_mm,
                "min_annular_ring_mm": self.min_annular_ring_mm,
                "max_aspect_ratio": self.max_aspect_ratio,
                "min_silkscreen_text_height_mm": self.min_silkscreen_text_height_mm,
                "min_silkscreen_line_width_mm": self.min_silkscreen_line_width_mm,
                "min_solder_mask_clearance_mm": self.min_solder_mask_clearance_mm,
            }
        }


def load_config(config_path: str = None) -> DRCRules:
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "default_rules.yaml")

    if not os.path.exists(config_path):
        return DRCRules()

    ext = os.path.splitext(config_path)[1].lower()
    with open(config_path, "r", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            data = yaml.safe_load(f)
        elif ext == ".json":
            data = json.load(f)
        else:
            raise ValueError(f"Unsupported config format: {ext}")

    return DRCRules.from_dict(data)


DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "default_rules.yaml")