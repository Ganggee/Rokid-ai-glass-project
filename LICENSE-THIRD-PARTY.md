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

## Data

| Data | Source / licence | How it is used |
|---|---|---|
| `sample-data/nutrition_reference_public.csv` (124 rows) | 음식 행(`source=MFDS_FOOD_DB`): 식품의약품안전처 식품영양성분 데이터베이스 (공공데이터포털 data.go.kr 15100070, 이용허락범위 제한 없음 / 공공누리 제1유형: 출처표시). 원재료 행(`source=RDA_NFCDB_10.4`): 농촌진흥청 국립식량과학원 국가표준식품성분 DB 10.4 (공공누리 제1유형: 출처표시). Values were taken from public GitHub redistributions (`toadsam/Ajou_MuscleUp`, `minseok08262-web/carb-loading-tracker`, `kangsogo7/meal-log`, `sirloinbh/health-log`; commits in `source_detail`) and cross-checked between them. | per-100 g reference values for meal estimates. **Attribution: 출처 식품의약품안전처 식품영양성분 데이터베이스; 농촌진흥청 국가표준식품성분표(DB 10.4).** No code from the mirror repositories is copied. |
| `sample-data/nutrition_demo.csv` | DEMO mock values written for this PoC | pipeline tests only (`verification=demo_mock`) |

Not used: Ultralytics YOLO (AGPL-3.0).
No third-party source code or model weights are committed to this repository.
