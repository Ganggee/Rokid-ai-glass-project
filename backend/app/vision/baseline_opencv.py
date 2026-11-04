"""OpenCV baseline for before/after meal comparison.

Baseline 0 (manual): the user draws the food region in each photo; area = region area.
Baseline 1 (auto-in-region): the user (or the candidate detector) gives the food
  region in the BEFORE photo only. The AFTER photo is aligned to the BEFORE photo
  (ORB + RANSAC homography on tray/table features); inside the region, food pixels
  are separated from the plate by colour distance to the plate colour (estimated
  from the region's inner border band) plus local texture. One threshold, learned
  on the BEFORE region, is applied to both photos.

Known limits (reported as warnings, never hidden): 2D area is not volume or mass;
stacked/overlapping foods, sauces and soups, food moved to another spot, strong
viewpoint changes, reflections and white food on white plates all distort ratios.
"""
from __future__ import annotations

from typing import Any, Optional

import cv2
import numpy as np

from .interfaces import Alignment, RegionMeasurement

PROC_MAX_SIDE = 1024
MIN_SCORE_THRESHOLD = 6.0  # floor so an empty plate's noise is not counted as food
LOW_CONTRAST = 8.0  # food vs plate score gap below this -> low-contrast warning


# ------------------------------------------------------------------ IO / scaling
def decode(image_bytes: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot decode image")
    return img


def to_proc(img: np.ndarray, max_side: int = PROC_MAX_SIDE) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
    return img, scale


def region_polygon(region: dict[str, Any], scale: float = 1.0) -> np.ndarray:
    if region["type"] == "bbox":
        x, y, w, h = (float(region[k]) for k in ("x", "y", "w", "h"))
        pts = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    else:
        pts = region["points"]
    return (np.array(pts, np.float64) * scale).astype(np.float32)


def polygon_area(poly: np.ndarray) -> float:
    if len(poly) < 3:
        return 0.0
    return float(abs(cv2.contourArea(poly.astype(np.float32))))


def region_mask(shape: tuple[int, int], region: dict[str, Any], scale: float) -> np.ndarray:
    mask = np.zeros(shape[:2], np.uint8)
    poly = region_polygon(region, scale)
    cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 255)
    return mask > 0


# ------------------------------------------------------------------ quality checks
def image_quality(img: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {"brightness": float(gray.mean()), "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var())}


# ------------------------------------------------------------------ alignment
def _validate_h(H: np.ndarray) -> bool:
    det = float(np.linalg.det(H[:2, :2]))
    return 0.5 < det < 2.0 and abs(H[2, 0]) < 2e-3 and abs(H[2, 1]) < 2e-3


def _feature_align(gb: np.ndarray, ga: np.ndarray, detector, norm) -> Alignment:
    kb, db = detector.detectAndCompute(gb, None)
    ka, da = detector.detectAndCompute(ga, None)
    if db is None or da is None or len(kb) < 30 or len(ka) < 30:
        return Alignment("failed", None, message="not enough features (plain background?)")
    pairs = cv2.BFMatcher(norm).knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 20:
        return Alignment("failed", None, matches=len(good), message="too few feature matches")
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None:
        return Alignment("failed", None, matches=len(good), message="homography estimation failed")
    inliers = int(inl.sum())
    ratio = inliers / len(good)
    if inliers < 15 or ratio < 0.2 or not _validate_h(H):
        return Alignment("failed", None, inliers=inliers, matches=len(good), inlier_ratio=ratio,
                         message="unstable homography (large viewpoint change?)")
    det = float(np.linalg.det(H[:2, :2]))
    return Alignment("ok", H, inliers=inliers, matches=len(good), inlier_ratio=round(ratio, 3),
                     scale_change=round(1.0 / det, 4))


def _ecc_align(gb: np.ndarray, ga: np.ndarray) -> Alignment:
    """Intensity-based affine alignment for small camera motion (fallback)."""
    small_b, s = to_proc(gb, 480)
    small_a, _ = to_proc(ga, 480)
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        cc, warp = cv2.findTransformECC(small_b.astype(np.float32), small_a.astype(np.float32), warp,
                                        cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5),
                                        None, 5)
    except cv2.error:
        return Alignment("failed", None, message="ECC did not converge")
    if cc < 0.8:
        return Alignment("failed", None, message=f"ECC correlation too low ({cc:.2f})")
    # ECC warp maps before(template) coords -> after(input) coords; invert to get after -> before
    A = np.vstack([warp, [0, 0, 1]]).astype(np.float64)
    A[:2, 2] /= s
    H = np.linalg.inv(A)
    if not _validate_h(H):
        return Alignment("failed", None, message="ECC warp out of range")
    det = float(np.linalg.det(H[:2, :2]))
    return Alignment("ok", H, inlier_ratio=round(float(cc), 3), scale_change=round(1.0 / det, 4),
                     message="ecc_affine")


def align(before: np.ndarray, after: np.ndarray) -> Alignment:
    """Estimate homography mapping AFTER -> BEFORE (both at processing scale).
    Order: SIFT features -> ORB features -> ECC affine (small motion)."""
    gb = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    ga = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    attempts = []
    if hasattr(cv2, "SIFT_create"):
        attempts.append(("sift", lambda: _feature_align(gb, ga, cv2.SIFT_create(nfeatures=4000), cv2.NORM_L2)))
    attempts.append(("orb", lambda: _feature_align(gb, ga, cv2.ORB_create(nfeatures=4000), cv2.NORM_HAMMING)))
    attempts.append(("ecc", lambda: _ecc_align(gb, ga)))
    last = Alignment("failed", None, message="no method")
    for name, fn in attempts:
        result = fn()
        if result.status == "ok":
            result.message = result.message or name
            return result
        last = result
        last.message = f"{name}: {result.message}"
    return last


def warp_to_before(after: np.ndarray, alignment: Alignment, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    if alignment.status == "ok":
        return cv2.warpPerspective(after, alignment.homography, (w, h), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_REPLICATE)
    if after.shape[:2] != (h, w):
        return cv2.resize(after, (w, h), interpolation=cv2.INTER_AREA)
    return after


# ------------------------------------------------------------------ food score
def _texture(gray: np.ndarray, k: int = 7) -> np.ndarray:
    g = gray.astype(np.float32)
    mean = cv2.blur(g, (k, k))
    sq = cv2.blur(g * g, (k, k))
    return np.sqrt(np.maximum(sq - mean * mean, 0))


def food_score(img: np.ndarray, band: np.ndarray) -> np.ndarray:
    """Per-pixel 'not plate' score: Lab distance to the band's median colour + texture."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    bg = np.median(lab[band], axis=0) if band.any() else np.median(lab.reshape(-1, 3), axis=0)
    # L channel is weighted down so exposure differences matter less than hue/chroma
    d = lab - bg
    dist = np.sqrt((0.5 * d[..., 0]) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)
    tex = _texture(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    bg_tex = float(np.median(tex[band])) if band.any() else 0.0
    score = dist + 1.2 * np.maximum(tex - bg_tex, 0)
    return cv2.GaussianBlur(score, (5, 5), 0)


def inner_band(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return mask
    width = max(3, int(0.08 * min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)))
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((width, width), np.uint8))
    return mask & ~(eroded > 0)


def _clean(binary: np.ndarray) -> np.ndarray:
    b = binary.astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return b > 0


def _otsu(values: np.ndarray) -> float:
    v = np.clip(values, 0, 255).astype(np.uint8).reshape(-1, 1)
    t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(t)


def measure_auto_region(before: np.ndarray, after_aligned: np.ndarray, region: dict[str, Any],
                        scale: float) -> RegionMeasurement:
    """Baseline 1: food pixels inside the same region of both (aligned) photos."""
    warnings: list[str] = []
    mask = region_mask(before.shape, region, scale)
    if mask.sum() < 400:
        return RegionMeasurement(None, None, "auto_mask_in_region", ["region_too_small"])
    band = inner_band(mask)
    # exposure normalisation: match the plate band colour of the AFTER photo to the BEFORE photo
    mb = np.median(before[band].astype(np.float32), axis=0)
    ma = np.median(after_aligned[band].astype(np.float32), axis=0)
    gain = np.clip(mb / np.maximum(ma, 1.0), 0.6, 1.6)
    if np.any(np.abs(gain - 1.0) > 0.12):
        warnings.append("exposure_differs_between_photos")
    for name, im in (("before", before), ("after", after_aligned)):
        clipped = float((im[mask].max(axis=1) >= 250).mean())
        if clipped > 0.15:
            warnings.append(f"overexposed_{name}_photo")
    after_norm = np.clip(after_aligned.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    blur_b = cv2.GaussianBlur(before, (5, 5), 1.2)
    blur_a = cv2.GaussianBlur(after_norm, (5, 5), 1.2)
    sb = food_score(blur_b, band)
    sa = food_score(blur_a, band)
    thr = max(_otsu(sb[mask & ~band]), MIN_SCORE_THRESHOLD)
    fb = _clean((sb > thr) & mask & ~band)
    fa = _clean((sa > thr) & mask & ~band)
    b_px, a_px = float(fb.sum()), float(fa.sum())
    interior = float((mask & ~band).sum())
    inside = mask & ~band
    if fb.any() and (inside & ~fb).any():
        gap = float(np.median(sb[fb]) - np.median(sb[inside & ~fb]))
        if gap < LOW_CONTRAST:
            warnings.append("low_contrast_food_vs_plate")
    if b_px < 0.03 * interior:
        warnings.append("no_food_detected_in_before_region")
    if b_px > 0.97 * interior:
        warnings.append("food_fills_region_add_plate_margin")
    inv = 1.0 / (scale * scale)  # report in original-image pixels
    return RegionMeasurement(b_px * inv, a_px * inv, "auto_mask_in_region", warnings,
                             {"threshold": round(thr, 2), "region_interior_px": interior * inv})


def measure_manual(before_region: dict[str, Any], after_region: dict[str, Any],
                   alignment: Optional[Alignment]) -> RegionMeasurement:
    """Baseline 0: user-drawn regions. After-area is corrected by the alignment scale."""
    b = polygon_area(region_polygon(before_region))
    a = polygon_area(region_polygon(after_region))
    warnings = []
    debug: dict[str, Any] = {"after_area_raw_px": a}
    if alignment is not None and alignment.status == "ok" and alignment.scale_change:
        a = a / alignment.scale_change  # express after-area in before-image scale
        debug["scale_correction"] = alignment.scale_change
    else:
        warnings.append("manual_areas_not_scale_corrected")
    return RegionMeasurement(b, a, "manual_region_area", warnings, debug)


# ------------------------------------------------------------------ candidate food regions
def detect_food_regions(img_bytes: bytes, max_regions: int = 6) -> list[dict[str, Any]]:
    """Unlabelled candidate regions (bbox with plate margin) for the HUD labelling step.
    Uses saturation + texture; plain white plates and the table are mostly excluded."""
    img = decode(img_bytes)
    proc, scale = to_proc(img, 800)
    h, w = proc.shape[:2]
    hsv = cv2.cvtColor(proc, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32)
    tex = _texture(cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY), 9)
    score = cv2.GaussianBlur(sat * 0.6 + tex * 3.0, (9, 9), 0)
    thr = max(_otsu(score), 40.0)
    binary = _clean(score > thr).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 0.004 * w * h or area > 0.35 * w * h:
            continue
        if x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2:
            continue  # touches the frame: table/tray edge, not a portion
        pad = int(0.12 * max(bw, bh))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        out.append({"area": int(area), "region": {"type": "bbox", "x": round(x0 / scale, 1), "y": round(y0 / scale, 1),
                                                  "w": round((x1 - x0) / scale, 1), "h": round((y1 - y0) / scale, 1)}})
    out.sort(key=lambda r: r["area"], reverse=True)
    out = out[:max_regions]
    # reading order (top-left first) and a coarse position hint for the HUD
    out.sort(key=lambda r: (round((r["region"]["y"] + r["region"]["h"] / 2) / (img.shape[0] / 2.0)), r["region"]["x"]))
    for i, r in enumerate(out, start=1):
        cx = (r["region"]["x"] + r["region"]["w"] / 2) / img.shape[1]
        cy = (r["region"]["y"] + r["region"]["h"] / 2) / img.shape[0]
        r["id"] = f"R{i}"
        r["position"] = ("top" if cy < 0.5 else "bottom") + "-" + ("left" if cx < 0.4 else "right" if cx > 0.6 else "center")
        r.pop("area")
    return out
