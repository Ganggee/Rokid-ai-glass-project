"""Vision plugin contracts.

Segmentation (where is food) and classification (what food) are separate
concerns: SAM 2 produces class-agnostic masks; FoodSAM/FoodSeg103-style models
add food classes. Baseline OpenCV only produces masks within regions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import numpy as np


@dataclass
class RegionMeasurement:
    before_area_px: Optional[float]
    after_area_px: Optional[float]
    method: str
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class Alignment:
    status: str  # ok | failed | skipped
    homography: Optional[np.ndarray]  # maps after-image coords -> before-image coords (processing scale)
    inliers: int = 0
    matches: int = 0
    inlier_ratio: float = 0.0
    scale_change: Optional[float] = None  # area scale of after relative to before
    message: str = ""


class FoodSegmenter(Protocol):
    """Optional model plugin (see vision/optional_food_model.py)."""

    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def masks(self, image_bgr: np.ndarray) -> list[dict[str, Any]]:
        """Return [{"mask": bool HxW, "label": str | None, "score": float}]"""
        ...
