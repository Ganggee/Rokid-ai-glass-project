"""Generate synthetic test images (no real photos, no faces, no patient data).

    python make_test_image.py qr <out.png> <text>
    python make_test_image.py meal_before <out.jpg>
    python make_test_image.py meal_after <out.jpg>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def qr(out: str, text: str) -> None:
    img = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(img, (img.shape[1] * 12, img.shape[0] * 12), interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(img, 80, 80, 80, 80, cv2.BORDER_CONSTANT, value=255)
    canvas = np.full((img.shape[0] + 200, img.shape[1] + 300, 3), 200, np.uint8)  # gray "box" around the label
    canvas[100:100 + img.shape[0], 150:150 + img.shape[1]] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(out, canvas)


def main() -> None:
    kind, out = sys.argv[1], sys.argv[2]
    if kind == "qr":
        qr(out, sys.argv[3])
        return
    from backend.tests.synthetic_meal import render_meal  # noqa: WPS433

    before, after, _truth = render_meal(seed=7)
    cv2.imwrite(out, before if kind == "meal_before" else after, [cv2.IMWRITE_JPEG_QUALITY, 92])


if __name__ == "__main__":
    main()
