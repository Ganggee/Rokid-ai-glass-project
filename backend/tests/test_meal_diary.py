"""Voice meal diary: parser table, confirmation, idempotency, gram policy, snapshots, summary/TTS text."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.app.services import meal_diary, nutrition_lookup
from backend.app.services.diary_parser import normalize_numerals, parse

KST = timezone(timedelta(hours=9))
JAN2 = datetime(2026, 1, 2, 12, 0, tzinfo=KST)
NOV6_0030 = datetime(2026, 11, 6, 0, 30, tzinfo=KST)
MAR31 = datetime(2026, 3, 31, 9, 0, tzinfo=KST)
MAR30 = datetime(2026, 3, 30, 9, 0, tzinfo=KST)
NOV6 = datetime(2026, 11, 6, 12, 0, tzinfo=KST)

# (now, text, intent, date, date_status, meal)
CASES = [
    (NOV6, "2026년 11월 6일 아침 기록 쌀밥", "record", "2026-11-06", "ok", "breakfast"),
    (NOV6, "11월 6일 점심 기록 김밥", "record", "2026-11-06", "ok", "lunch"),
    (NOV6, "6일 저녁 김치찌개 먹었어", "record", "2026-11-06", "ok", "dinner"),
    (NOV6, "7일 저녁 김치찌개 먹었어", "record", "2026-10-07", "ok", "dinner"),
    (JAN2, "12월 31일 저녁 기록 보여줘", "view", "2025-12-31", "ok", "dinner"),
    (JAN2, "1월 2일 아침 기록 쌀밥", "record", "2026-01-02", "ok", "breakfast"),
    (JAN2, "1월 3일 아침 기록 쌀밥", "record", "2025-01-03", "ok", "breakfast"),
    (MAR30, "31일 점심 기록 김밥", "record", None, "ask", "lunch"),
    (MAR31, "31일 점심 기록 김밥", "record", "2026-03-31", "ok", "lunch"),
    (NOV6, "십일월 육일 아침 기록 읽어줘", "read", "2026-11-06", "ok", "breakfast"),
    (NOV6, "이천이십육년 십일월 육일 점심 기록 보여줘", "view", "2026-11-06", "ok", "lunch"),
    (NOV6, "이천이십오년 십이월 삼십일일 저녁 기록 보여줘", "view", "2025-12-31", "ok", "dinner"),
    (NOV6, "삼일 아침 기록 쌀밥", "record", "2026-11-03", "ok", "breakfast"),
    (NOV6, "그저께 아침 미역국 먹었어", "record", "2026-11-04", "ok", "breakfast"),
    (NOV6, "그제 점심 기록 보여줘", "view", "2026-11-04", "ok", "lunch"),
    (NOV6, "어제 저녁 기록 읽어줘", "read", "2026-11-05", "ok", "dinner"),
    (NOV6, "오늘 간식 바나나 하나 기록", "record", "2026-11-06", "ok", "snack"),
    (NOV6, "11/6 간식 기록 사과", "record", "2026-11-06", "ok", "snack"),
    (NOV6, "2026-11-05 아침 기록 쌀밥", "record", "2026-11-05", "ok", "breakfast"),
    (NOV6, "내일 아침 기록 쌀밥", "record", "2026-11-07", "future", "breakfast"),
    (NOV6, "모레 점심 기록 쌀밥", "record", "2026-11-08", "future", "lunch"),
    (NOV6, "엊그제 저녁 기록 쌀밥", "record", None, "ask", "dinner"),
    (NOV6, "월요일 점심 기록 보여줘", "view", None, "ask", "lunch"),
    (NOV6, "아침 기록 김밥", "record", "2026-11-06", "ok", "breakfast"),
    (NOV6, "오늘 기록 김밥", "record", "2026-11-06", "ok", None),
    (NOV6, "2024년 11월 1일 아침 기록 쌀밥", "record", "2024-11-01", "out_of_range", "breakfast"),
    (NOV6, "2월 30일 아침 기록 쌀밥", "record", None, "ask", "breakfast"),
    (NOV6, "조식으로 쌀밥 먹었어", "record", "2026-11-06", "ok", "breakfast"),
    (NOV6, "석식 기록 보여줘", "view", "2026-11-06", "ok", "dinner"),
    (NOV6_0030, "오늘 아침 기록 쌀밥", "record", "2026-11-06", "ok", "breakfast"),
    (NOV6, "취소", "cancel", None, "missing", None),
    (NOV6, "확인", "confirm", None, "missing", None),
]


@pytest.mark.parametrize("now,text,intent,d,status,meal", CASES)
def test_parser_table(now, text, intent, d, status, meal):
    r = parse(text, now)
    assert (r["intent"], r["date"], r["date_status"], r["meal_type"]) == (intent, d, status, meal), r


def test_parser_questions_and_warnings():
    assert any("끼니" in q for q in parse("오늘 기록 김밥", NOV6)["questions"])
    assert any("미래" in q for q in parse("내일 아침 기록 쌀밥", NOV6)["questions"])
    assert any("2월" in q for q in parse("31일 점심 기록 김밥", MAR30)["questions"])
    assert any("late_night" in w for w in parse("오늘 아침 기록 쌀밥", NOV6_0030)["warnings"])
    assert parse("기록 보여줘", NOV6)["questions"]  # view without date/meal -> ask which date


def test_numeral_normalisation():
    assert normalize_numerals("이천이십육년 십일월 육일") == "2026년 11월 6일"
    assert normalize_numerals("십일일 일요일") == "11일 일요일"
    assert normalize_numerals("삼십일일") == "31일"


def test_food_quantities():
    foods = parse("어제 저녁 밥 한 공기랑 계란 2개, 삼겹살구이 200g 그리고 미역국 반 그릇 먹었어", NOV6)["foods"]
    got = [(f["name"], f["quantity"], f["unit"], f["grams"]) for f in foods]
    assert got == [("밥", 1, "공기", None), ("계란", 2.0, "개", None), ("삼겹살구이", None, None, 200.0),
                   ("미역국", 0.5, "그릇", None)]


def test_gram_policy(conn):
    stated = meal_diary.compute_item(conn, {"name": "삼겹살구이", "grams": 200})
    assert stated["grams_basis"] == "stated" and stated["grams"] == 200 and stated["kcal"] is not None
    serving = meal_diary.compute_item(conn, {"name": "김밥"})  # no unit -> 1 x 1인분
    ref = nutrition_lookup.resolve_label(conn, "김밥")
    assert serving["grams_basis"] == "serving_size" and serving["grams"] == ref["serving_size_g"]
    assert serving["kcal"] == round(ref["kcal_per_100g"] * ref["serving_size_g"] / 100, 1) and serving["is_estimate"]
    two = meal_diary.compute_item(conn, {"name": "김밥", "quantity": 2, "unit": "인분"})
    assert two["grams"] == 2 * ref["serving_size_g"]
    mismatch = meal_diary.compute_item(conn, {"name": "쌀밥", "quantity": 1, "unit": "공기"})
    assert mismatch["grams"] is None and mismatch["kcal"] is None and "unit_mismatch" in mismatch["null_reason"]
    ml = meal_diary.compute_item(conn, {"name": "탕수육"})  # 100 mL basis: volume in mL, no grams, kcal withheld
    assert ml["grams"] is None and ml["volume_ml"] == 343 and ml["kcal"] is None and "volume_basis" in ml["null_reason"]
    stated = meal_diary.compute_item(conn, {"name": "쌀밥", "grams": 210})
    assert stated["is_estimate"] is True  # stated grams, but kcal comes from a reference table (review D-1)
    unknown = meal_diary.compute_item(conn, {"name": "참치김밥"})
    assert unknown["nutrition_ref_id"] is None and unknown["kcal"] is None and unknown["candidates"]


YDAY = (date.today() - timedelta(days=1)).isoformat()


def _post(client, **kw):
    body = {"log_date": YDAY, "meal_type": "breakfast", "confirmed": True,
            "idempotency_key": kw.pop("key", uuid.uuid4().hex), "items": [{"food_name": "김밥"}, {"food_name": "배추김치", "grams": 50}]}
    body.update(kw)
    return client.post("/api/v1/meal-logs", json=body)


def test_confirmation_idempotency_future(client):
    r = _post(client, confirmed=False)
    assert r.status_code == 400 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert client.get("/api/v1/meal-logs", params={"date": YDAY}).json()["items"] == []
    a = _post(client, key="diary-key-001")
    b = _post(client, key="diary-key-001")
    assert a.status_code == b.status_code == 200 and b.json()["replayed"] is True
    assert a.json()["log"]["id"] == b.json()["log"]["id"]
    assert len(client.get("/api/v1/meal-logs", params={"date": YDAY}).json()["items"]) == 1
    c = _post(client, key="diary-key-001", meal_type="lunch")
    assert c.status_code == 409
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    f = _post(client, log_date=tomorrow)
    assert f.status_code == 422 and f.json()["error"]["code"] == "FUTURE_DATE"


def test_parse_endpoint_never_writes_and_fixes_date(client):
    y = date.fromisoformat(YDAY)
    r = client.post("/api/v1/meal-logs/parse-command",
                    json={"text": f"{y.month}월 {y.day}일 저녁 김밥 1인분이랑 배추김치 먹었어",
                          "now": f"{YDAY}T23:59:00+09:00"}).json()
    assert r["intent"] == "record" and r["date"] == YDAY and r["requires_confirmation"] is True
    assert [i["food_name"] for i in r["items"]] == ["김밥", "배추김치"] and r["items"][0]["kcal"] is not None
    assert client.get("/api/v1/meal-logs", params={"date": YDAY}).json()["items"] == []
    # client confirms after midnight: the parsed date is what gets stored
    saved = _post(client, log_date=r["date"], meal_type=r["meal_type"],
                  items=[{"food_name": i["food_name"], "nutrition_ref_id": i["nutrition_ref_id"]} for i in r["items"]]).json()
    assert saved["log"]["log_date"] == YDAY and saved["log"]["meal_type"] == "dinner"


def test_snapshot_survives_reference_update(client, settings):
    log = _post(client).json()["log"]
    kcal_before = log["items"][0]["kcal"]
    from backend.app.db import connect

    c = connect(settings.database_path)
    ref_id = log["items"][0]["nutrition_ref_id"]
    c.execute("UPDATE nutrition_references SET kcal_per_100g = kcal_per_100g * 3 WHERE id = ?", (ref_id,))
    c.close()
    again = client.get(f"/api/v1/meal-logs/{log['id']}").json()
    assert again["items"][0]["kcal"] == kcal_before


def test_summary_speech_text_rules(client):
    empty = client.get("/api/v1/meal-logs/summary", params={"date": "2026-11-01"}).json()
    assert "기록이 없습니다" in empty["speech_text"]
    many = [{"food_name": n} for n in ("김밥", "배추김치", "쌀밥", "미역국", "라면", "참치김밥", "멸치볶음")]
    _post(client, items=many)
    _post(client, meal_type="dinner", items=[{"food_name": "삼겹살구이", "grams": 200}])
    s = client.get("/api/v1/meal-logs/summary", params={"date": YDAY}).json()
    sp = s["speech_text"]
    assert len(sp) <= 150 and len(re.findall(r"[.!?]", sp)) <= 3
    assert "아침" in sp and "저녁" in sp and "추정" in sp and "미상" in sp  # 라면(100mL)/참치김밥 -> unknown kcal
    assert s["totals_complete"] is False and s["totals"]["kcal"] > 0
    assert len(s["display_lines"]) == 2


def test_from_session_is_idempotent(client):
    from .synthetic_meal import encode_jpeg, render_meal

    before, after, truth = render_meal(seed=7)
    sid = client.post("/api/v1/meals/sessions", json={}).json()["session_id"]
    client.post(f"/api/v1/meals/{sid}/photos/before", files={"file": ("b.jpg", encode_jpeg(before), "image/jpeg")})
    client.post(f"/api/v1/meals/{sid}/photos/after", files={"file": ("a.jpg", encode_jpeg(after), "image/jpeg")})
    client.post(f"/api/v1/meals/{sid}/items", json={"items": [
        {"label": "밥", "nutrition_ref_id": "DEMO-RICE", "initial_serving_grams": 200, "serving_source": "demo_assumption",
         "before_region": truth["밥"]["bbox"]}, {"label": "김치", "before_region": truth["김치"]["bbox"]}]})
    client.post(f"/api/v1/meals/{sid}/analyze", json={})
    body = {"meal_type": "lunch", "log_date": YDAY, "confirmed": True}
    a = client.post(f"/api/v1/meal-logs/from-session/{sid}", json=body).json()
    b = client.post(f"/api/v1/meal-logs/from-session/{sid}", json=body).json()
    assert a["replayed"] is False and b["replayed"] is True and a["log"]["id"] == b["log"]["id"]
    items = a["log"]["items"]
    assert items[0]["grams_basis"] == "analysis" and items[0]["kcal"] is not None and items[0]["ref_is_demo"]
    assert items[1]["kcal"] is None and items[1]["null_reason"]
    assert client.post(f"/api/v1/meal-logs/from-session/{sid}", json=dict(body, confirmed=False)).status_code == 400


def test_soft_delete_requires_confirmation(client):
    log = _post(client).json()["log"]
    assert client.delete(f"/api/v1/meal-logs/{log['id']}").status_code == 400
    assert client.delete(f"/api/v1/meal-logs/{log['id']}", params={"confirmed": True}).json()["deleted"]
    assert client.get("/api/v1/meal-logs", params={"date": YDAY}).json()["items"] == []
