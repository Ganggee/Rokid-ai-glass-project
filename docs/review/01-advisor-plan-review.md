# 01 — 지도교수 계획 검토 (2026-11-06)

역할: 지도교수(advisor). iteration-2 계획 초안(docs/iteration-2-plan.md v1)에 대한 검토 결과를 그대로 기록. PM 보완: 영양 데이터는 공식 사이트 접근 불가로 GitHub 미러 ≥2개 교차검증 경로(A-1)를 채택.

## 주요 위험 (요약)
- P0-1 오래된 Excel 사본 덮어쓰기 → 사용 기록 되돌림. export마다 export_id 발급, 스냅숏을 DB `excel_exports`에 영구 보관, `_sync` 시트(veryHidden)에는 export_id만. 모르거나 없으면 자동 반영 금지·conflict 보고.
- P0-2 `tx_type` CHECK 제약 → 'adjust' + source 'excel_sync', 충돌은 별도 기록. 마이그레이션은 PRAGMA table_info 확인 + SCHEMA_VERSION 상향.
- P0-3 WebFetch 전사 값은 원문 보장 없음 → 공식 파일 import가 정본, 전사는 web_transcribed 표시.
- P0-4 한국어 TTS 미확인(`utterance.lang` not supported), 화면 텍스트가 1차 출력. STT 한글 수사 처리.
- P1-5 1회 제공량 기반 g는 단위 일치 시에만, 항상 추정. 빈 기준량을 100 g로 보는 버그 수정.
- P1-6 기록 시점 영양값 스냅숏. P1-7 짧은 별칭 오매칭(김밥→밥) 방지.
- P1-8 동기화 클라이언트: 부분 다운로드(BadZipFile), `~$` 잠금, 충돌 사본, PermissionError, 서식 손실, 수식 셀 None.
- P1-9 커밋 후 export 전 크래시 → outbox/dirty, 재기동 시 export, 파일 I/O는 트랜잭션 밖, 단일 lock.

## 결정사항
1. 재고 merge_delta = base + (DB−base) + (Excel−base), base = 파일의 export_id 스냅숏. 음수·base 미상 → conflict. 메타데이터는 DB 미변경 시 Excel 우선, 양쪽 변경 시 DB 유지+conflict. db_wins/excel_wins는 옵션.
2. Excel 행 삭제 → DB 불변, 다음 export에서 복원, row_missing 경고.
3. 충돌 사본은 경고만, 정확한 경로만 읽음. `~$` 존재·크기/mtime 불안정 시 보류.
4. 날짜: Asia/Seoul, parse 시점 확정. 연도 생략 = 오늘 이전 가장 가까운 날. '6일'만 = 이번 달(오늘 이전이면) 아니면 전월, 없는 날은 되묻기. 11/6 = 월/일. 요일·엊그제는 되묻기. 00:00–03:59 '오늘'은 경고만.
5. 미래 날짜 기록 422 FUTURE_DATE, 조회 허용. 기록 범위 오늘−365일 ~ 오늘.
6. 날짜 없는 '아침 기록' = 오늘(확인 화면에 전체 날짜). 끼니 없으면 되묻기, 시각으로 추론 금지.
7. g: 말한 g → 사용. count×serving_size_g는 단위 일치 또는 단위 미언급 시만. 그 외 null + 사유.
8. TTS speech_text ≤150자·≤3문장, '추정' 명시, speak 1회.
9. 영양 출처 우선순위: MFDS 공식 파일/API > 농진청 > USDA(원재료) > DEMO. 행당 단일 출처, 평균 금지. 최소 30, 목표 60, (전사 행) 상한 150. 부족하면 부족하다고 보고.
10. 식사 기록 삭제는 soft delete + 확인, 음성 삭제 없음.

## 합격 기준 (체크리스트)
- 회귀: pytest 0 failed(기존 40 포함); confirmed 없는 /use·/meal-logs·/excel-sync apply → 400, DB 불변; 멱등 replayed·다른 payload 409·동시 8회 1회; 음수·소수 재고 invalid; 기준 중량 없으면 g·kcal null+사유; DEMO/추정 표시가 응답·화면·speech_text에; 비밀·실데이터 미추적; 정확도 주장은 명령+출력 동반, RV101 NOT VERIFIED.
- 영양: validate_nutrition_csv.py exit 0(필수 필드·도메인 allowlist·값 범위·C+P+F≤100·Atwater 허용치/예외 사유); 정규화 픽스처(100 g/200 g/100 mL/빈 값); 김밥≠밥 자동 확정; 공식 행 > DEMO; 기준값 갱신 후 과거 기록 kcal 불변.
- 음성 일지: 파서 표 테스트 ≥30건(now 주입: 2026-01-02, 2026-11-06 00:30, 2026-03-31; 6일, 12월 31일, 31일(4월), 한글 수사, 그저께, 11/6, 내일, 끼니 생략, 밥 한 공기, 계란 2개, 200g); 자정 경계; speech_text 제한·'미상'; from-session 멱등; 하네스 diary(확인 전 POST 0, 취소 0, speak 1), validator issues 0.
- Excel: 오래된 사본 → 19 유지·adjust 0; _sync 없음/모르는 export_id → apply 0·conflict; 잠금 → /use 성공·pending·해제 후 1회; 잘린 zip transient; 충돌 사본 경고만; 행 삭제 → DB 불변·복원·경고; 커밋 직후 kill → 재기동 시 pending export; soak(2000+ 사용, 50+ 외부 수정, 5+ 재기동) 불변조건(stock=Σdelta, 음수 없음, Excel=DB, 멱등 중복 없음, 같은 export_id 2회 적용 없음).

## 범위 제외
Graph/Drive OAuth, 여러 파일, 실시간 협업, 서식 보존 엔진, transactions 시트 import, 요일/주 표현, 시각 기반 끼니 추론, LLM 파서, 이미지 인식 모델, mL→g 환산, 전사 값으로 행 채우기, 출처 평균, TTS 음성 선택 UI, 음성 삭제, 식단 계획, LOCAL 모드 Excel 동기화.
