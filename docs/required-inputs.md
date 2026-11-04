# Required inputs (아직 받지 못한 자료)

개발은 대체 데이터로 계속 진행했습니다. 아래 자료가 들어오면 해당 부분을 교체/검증합니다.

| 자료 | 현재 대체 | 받으면 할 일 |
|---|---|---|
| 기존 AIUI 코드 Export (`caresens-air-inventory`: app.js, app.json, pages/index, pages/inventory) | 공식 scaffold 기준으로 동등 기능 재구축. 원인(`data.stock = 20` 초기값만 사용)은 **설명 기반 추정** | 기존 디자인/문구 유지하며 `lib/inventory-client.js` 연결(증분 수정), 레이아웃 겹침 수정 |
| 실제 재고 Excel | `sample-data/inventory_demo.csv/.xlsx` (DEMO 20/10/15) | `sample-data/real/`에 두고 `import_inventory.py` 미리보기 → 매핑 JSON → `--mode seed --apply` |
| 실제 QR/바코드 표기 내용 | DEMO 값(제품 ID 문자열, 가짜 바코드) | QR이 품목/LOT/일련번호 중 무엇인지 확인 후 `qr_value`/`barcode` 매핑 |
| GitHub 로그인 | 세션에 GitHub 미연결 → 로컬 커밋만 | Private 저장소 생성 + push (README "GitHub" 절) |
| 안경에서 접근 가능한 HTTPS 서버 | localhost에서만 시험 | `docs/aiui-studio-deploy.md` §0 |
| 식사 원본 이미지(동의된 개인 식사, 얼굴/환자정보 없음) | 합성 식판 이미지 | 실사진 10~20세트로 baseline 오차 측정(라벨·수동 박스 기준) |
| 식약처 식품영양성분DB API 키 | `nutrition_demo.csv` (DEMO_MOCK) | `.env` `MFDS_API_KEY` 설정, 출력메세지.xlsx로 필드명 확인 후 `MFDS_FIELD_CANDIDATES` 조정 |
| 음식 분류 모델/데이터(라이선스 명확) | 사용자 라벨 | `docs/open-source-evaluation.md` 후보 검토 |
| RV101 키/터치패드 매핑, 한국어 STT 지원 여부 | 문서 기준(Rokid Glasses) 구현 | 실기기 체크리스트 D12, D13 |
