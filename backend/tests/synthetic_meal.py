"""Synthetic before/after meal tray images with known ground truth.

No real food photos, people or hospital context. Used to verify that the
pipeline (alignment -> per-region mask -> area ratio -> nutrition math) works
end to end. Accuracy on these images says nothing about real photos.
"""
from __future__ import annotations

import cv2
import numpy as np

W, H = 1512, 1134  # 4:3 like the telephoto capture mode (scaled down)

FOODS = [
    # label, center, axes, color BGR, texture sigma, eaten fraction (ground truth by area)
    ("밥", (430, 420), (170, 130), (222, 228, 232), 14, 0.60),
    ("김치", (1080, 400), (150, 110), (40, 50, 200), 18, 0.50),
    ("계란", (450, 820), (140, 110), (60, 200, 235), 10, 1.00),
    ("샐러드", (1060, 800), (160, 120), (60, 170, 70), 22, 0.25),
]


def _table(rng: np.random.Generator) -> np.ndarray:
    img = np.full((H, W, 3), (95, 105, 115), np.uint8)
    noise = rng.normal(0, 4, (H, W, 1)).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # fiducial-like printed pattern on the tray rim gives ORB stable corners
    for _ in range(140):
        x, y = int(rng.integers(10, W - 40)), int(rng.integers(10, H - 40))
        if 60 < x < W - 90 and 60 < y < H - 90:
            continue
        s = int(rng.integers(8, 22))
        c = (20, 20, 20) if rng.random() < 0.5 else (235, 235, 235)
        cv2.rectangle(img, (x, y), (x + s, y + s), c, -1)
    cv2.rectangle(img, (60, 60), (W - 60, H - 60), (180, 185, 190), -1)  # tray
    for cx, cy in ((430, 420), (1080, 400), (450, 820), (1060, 800)):
        cv2.circle(img, (cx, cy), 230 if cy < 600 else 210, (245, 246, 247), -1)  # white plates
        cv2.circle(img, (cx, cy), 230 if cy < 600 else 210, (200, 202, 205), 3)
    return img


def _food_layer(img, mask, color, sigma, rng):
    noise = rng.normal(0, sigma, img.shape).astype(np.int16)
    food = np.clip(np.array(color, np.int16) + noise, 0, 255).astype(np.uint8)
    img[mask] = food[mask]


def render_meal(seed: int = 7, shift=(18, -12), angle=2.5, gain=1.08):
    """Return (before_bgr, after_bgr, truth) where truth maps label -> dict."""
    rng = np.random.default_rng(seed)
    base = _table(rng)
    before, after = base.copy(), base.copy()
    truth = {}
    for label, (cx, cy), (ax, ay), color, sigma, eaten in FOODS:
        m_before = np.zeros((H, W), np.uint8)
        cv2.ellipse(m_before, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        m_after = m_before.copy()
        if eaten >= 1.0:
            m_after[:] = 0
        elif eaten > 0:
            # remove the left part of the portion until the eaten share is reached
            total = int((m_before > 0).sum())
            cols = np.where(m_before.any(axis=0))[0]
            for x in range(cols.min(), cols.max() + 1):
                if (m_after > 0).sum() <= total * (1 - eaten):
                    break
                m_after[:, x] = 0
        _food_layer(before, m_before > 0, color, sigma, rng)
        _food_layer(after, m_after > 0, color, sigma, rng)
        pad = 40
        truth[label] = {
            "eaten_ratio": 1 - (m_after > 0).sum() / (m_before > 0).sum(),
            "bbox": {"type": "bbox", "x": cx - ax - pad, "y": cy - ay - pad, "w": 2 * (ax + pad), "h": 2 * (ay + pad)},
            "after_bbox": _bbox_of(m_after, pad),
            "before_area": int((m_before > 0).sum()),
            "after_area": int((m_after > 0).sum()),
        }
    # camera moved slightly between shots + exposure change
    M = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    M[:, 2] += shift
    after = cv2.warpAffine(after, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    after = np.clip(after.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    return before, after, truth


def _bbox_of(mask: np.ndarray, pad: int):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return {"type": "bbox", "x": 0, "y": 0, "w": 0, "h": 0}
    return {"type": "bbox", "x": int(xs.min()), "y": int(ys.min()), "w": int(xs.max() - xs.min() + 1),
            "h": int(ys.max() - ys.min() + 1)}


def encode_jpeg(img: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return buf.tobytes()
