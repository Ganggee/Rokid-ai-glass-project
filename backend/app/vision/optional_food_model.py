"""Optional open-source segmentation plugin (FOOD_MODEL_PLUGIN = sam2 | foodsam).

Neither model is installed by default: both need PyTorch (SAM 2: torch>=2.5.1,
python>=3.10, CUDA kernel build recommended) and separately downloaded weights.
When unavailable the analysis falls back to the OpenCV baseline and says so.

* sam2   — facebookresearch/sam2 (Apache-2.0 code + checkpoints). Class-agnostic
           masks only: it does not tell which food is which, so labels still come
           from the user or a separate classifier.
* foodsam — jamesjg/FoodSAM (Apache-2.0). Combines SAM with a FoodSeg103 semantic
           segmenter; old mmcv/torch stack, run as a separate experiment (see
           docs/open-source-evaluation.md), not inside this API process.
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any

import numpy as np


class Sam2Plugin:
    name = "sam2"

    def __init__(self) -> None:
        self.checkpoint = os.environ.get("SAM2_CHECKPOINT", "checkpoints/sam2.1_hiera_small.pt")
        self.config = os.environ.get("SAM2_CONFIG", "configs/sam2.1/sam2.1_hiera_s.yaml")
        self._generator = None

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("torch") is None:
            return False, "torch not installed"
        if importlib.util.find_spec("sam2") is None:
            return False, "sam2 package not installed (pip install -e facebookresearch/sam2)"
        if not os.path.isfile(self.checkpoint):
            return False, f"checkpoint not found: {self.checkpoint}"
        return True, "ok"

    def masks(self, image_bgr: np.ndarray) -> list[dict[str, Any]]:  # pragma: no cover - needs weights
        if self._generator is None:
            import torch  # noqa: F401
            from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
            from sam2.build_sam import build_sam2

            device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
            self._generator = SAM2AutomaticMaskGenerator(build_sam2(self.config, self.checkpoint, device=device))
        rgb = image_bgr[..., ::-1].copy()
        return [{"mask": m["segmentation"], "label": None, "score": float(m.get("predicted_iou", 0))}
                for m in self._generator.generate(rgb)]


class FoodSamPlugin:
    name = "foodsam"

    def available(self) -> tuple[bool, str]:
        return False, "FoodSAM runs as an external experiment (old mmcv stack); not wired into the API process"

    def masks(self, image_bgr: np.ndarray) -> list[dict[str, Any]]:  # pragma: no cover
        raise RuntimeError("not available")


def get_plugin(name: str):
    if name == "sam2":
        return Sam2Plugin()
    if name == "foodsam":
        return FoodSamPlugin()
    return None


def plugin_status(name: str) -> dict[str, Any]:
    plugin = get_plugin(name)
    if plugin is None:
        return {"plugin": "none", "available": False, "reason": "FOOD_MODEL_PLUGIN=none"}
    ok, reason = plugin.available()
    return {"plugin": plugin.name, "available": ok, "reason": reason}
