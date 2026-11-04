# Third-party components

| Component | License | How it is used |
|---|---|---|
| FastAPI, Starlette, Pydantic, Uvicorn, python-multipart, httpx | MIT / BSD-3 | backend API (installed from PyPI; not vendored) |
| OpenCV (opencv-python-headless) | Apache-2.0 | QR/barcode decoding, alignment, masks |
| NumPy | BSD-3 | image arrays |
| Pillow | MIT-CMU (HPND) | image validation / re-encoding |
| openpyxl | MIT | .xlsx import |
| pytesseract / Tesseract OCR | Apache-2.0 | optional OCR |
| requests, pytest | Apache-2.0 / MIT | tests and smoke test |
| Rokid AIUI (yodaos-project/AIUI) | Apache-2.0 | scaffold structure, `aiui-dev` skill rules; `bench/` validator and loader are **downloaded at test time**, not copied |
| SAM 2 (optional, not bundled) | Apache-2.0 | optional plugin; weights downloaded separately by the user |
| FoodSAM (optional, not bundled) | Apache-2.0 | external experiment only |

Not used: Ultralytics YOLO (AGPL-3.0).
No third-party source code or model weights are committed to this repository.
