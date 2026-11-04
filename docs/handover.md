# Handover

## 필요한 계정·권한·키
| 항목 | 용도 | 보관 |
|---|---|---|
| GitHub (Private repo 접근) | 소스 | 조직 정책 |
| Rokid 계정 + AIUI Studio Global | Import, Simulator, AIX 패키징 | 개인 계정 — 안경과 1:1 페어링 |
| Hi Rokid 앱 (페어링된 폰) | 안경 리소스 업데이트, 네트워크 경유 | 안경 소유자 |
| `API_TOKEN` | 서버 인증, `aiui-agent/lib/config.js` | `.env` (커밋 금지), 시험 후 교체 |
| `MFDS_API_KEY` (선택) | 식약처 영양 DB | `.env` |
| HTTPS 호스트/터널 | 안경→서버 | 운영 담당 |

## 버전
Python 3.10+ (개발 3.13), Node 20+ (개발 22), FastAPI ≥0.115, OpenCV ≥4.8, AIUI Studio Global 1.3.x(사용자 환경), aiui-dev skill = yodaos-project/AIUI `main` (2026-11).

## 후임자 시작 순서
```powershell
git clone <repo> ; cd rokid-ai-glasses-dual-poc
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env   # API_TOKEN 변경
python scripts\seed_demo_data.py --reset
python -m pytest -q
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```
그 다음 `docs/aiui-studio-deploy.md`로 자신의 Rokid 계정에서 Import → 패키징 → 리소스 업데이트.

## 주의
- 안경 Agent는 **패키징한 계정**의 안경에만 내려갑니다. 계정이 바뀌면 다시 Import/패키징.
- `config.js`에 URL/토큰을 넣은 채 커밋하지 말 것(CI가 실패시킴). `python scripts\configure_agent.py --reset`.
- 실제 재고 파일은 `sample-data/real/`(gitignore), 식사 사진은 `uploads/`(gitignore). 보관기간: `scripts/purge_uploads.py`.
- 재고 정본은 SQLite. Excel은 입력/내보내기 형식일 뿐, 재수입은 기본 `seed`(기존 재고 유지).
- 차감 로직을 바꿀 때는 `backend/tests/test_inventory_api.py`와 AIUI 하네스를 같이 돌릴 것.
- 측정하지 않은 정확도를 문서/보고에 쓰지 말 것.
