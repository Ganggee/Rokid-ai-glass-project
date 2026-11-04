"""Measure the OpenCV baseline on SYNTHETIC trays with known ground truth.

    python scripts/eval_synthetic_meals.py --n 20 --out reports/synthetic_eval.json

Results describe behaviour on generated images only (flat colours, white plates,
small camera motion). They are not an accuracy claim for real meals.
"""
from __future__ import annotations

import argparse
import json
import statistics

import _bootstrap  # noqa: F401
import numpy as np

from backend.app.vision import baseline_opencv as cvb
from backend.tests.synthetic_meal import encode_jpeg, render_meal


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--out")
    a = p.parse_args(argv)
    rng = np.random.default_rng(2026)
    errors: dict[str, list[float]] = {}
    aligned = 0  # count of ok alignments
    rows = []
    for i in range(a.n):
        angle = float(rng.uniform(-4, 4))
        shift = (int(rng.integers(-35, 36)), int(rng.integers(-35, 36)))
        gain = float(rng.uniform(0.92, 1.10))
        before, after, truth = render_meal(seed=100 + i, shift=shift, angle=angle, gain=gain)
        B, s = cvb.to_proc(cvb.decode(encode_jpeg(before)))
        A, _ = cvb.to_proc(cvb.decode(encode_jpeg(after)))
        al = cvb.align(B, A)
        aligned += int(al.status == "ok")
        AA = cvb.warp_to_before(A, al, (B.shape[1], B.shape[0]))
        row = {"seed": 100 + i, "angle": round(angle, 2), "shift": shift, "gain": round(gain, 3),
               "alignment": al.status, "align_method": al.message, "foods": {}}
        for label, t in truth.items():
            m = cvb.measure_auto_region(B, AA, t["bbox"], s)
            est = None if not m.before_area_px else 1 - m.after_area_px / m.before_area_px
            err = None if est is None else abs(est - t["eaten_ratio"])
            if err is not None:
                errors.setdefault(label, []).append(float(err))
            row["foods"][label] = {"truth": round(float(t["eaten_ratio"]), 3), "est": None if est is None else round(float(est), 3),
                                   "warnings": m.warnings}
        rows.append(row)
    summary = {
        "images": a.n,
        "alignment_ok": aligned,
        "abs_error_consumed_ratio": {k: {"mean": round(statistics.mean(v), 3), "max": round(max(v), 3),
                                         "within_0.10": int(sum(e <= 0.10 for e in v))} for k, v in errors.items()},
        "note": "Synthetic images only. Not representative of real food photos.",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.out:
        from pathlib import Path

        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
