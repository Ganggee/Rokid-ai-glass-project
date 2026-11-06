"""Rule-based Korean parser for voice meal-diary commands (no LLM, never writes).

Examples
  "2026년 11월 6일 아침 기록, 밥 한 공기랑 김치찌개 먹었어"  -> record, 2026-11-06, breakfast, foods
  "이천이십육년 십일월 육일 점심 기록 보여줘"                  -> view
  "어제 저녁 기록 읽어줘"                                     -> read
Date rules (advisor decisions 4-6), relative to `now` in APP_TIMEZONE:
  * year omitted  -> the most recent such date that is not in the future
  * day only ("6일") -> this month if not after today, else previous month; nonexistent day -> ask
  * "11/6" = month/day; 오늘/어제/그제/그저께; 엊그제 and weekdays -> ask; 내일/모레 -> future
  * the resolved date is fixed in the parse result (the client sends it back; never recomputed)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

SINO = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
SINO_UNITS = {"십": 10, "백": 100, "천": 1000}
NATIVE = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6,
          "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "반": 0.5}
MEALS = [
    ("breakfast", r"아침\s*식사|아침밥|아침|조식|breakfast"),
    ("lunch", r"점심\s*식사|점심밥|점심|중식|lunch"),
    ("dinner", r"저녁\s*식사|저녁밥|저녁|석식|dinner"),
    ("snack", r"간식|야식|snack"),
]
MEAL_KO = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁", "snack": "간식"}
UNITS = "공기|그릇|인분|개|접시|조각|컵|잔|봉지|봉|줄|마리|장|스푼|숟가락"
WEEKDAY = re.compile(r"[월화수목금토일]요일|주말|지난주|이번주")


def get_tz(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # Windows without tzdata: Asia/Seoul has no DST
        return timezone(timedelta(hours=9)) if name == "Asia/Seoul" else timezone.utc


def sino_to_int(s: str) -> int | None:
    total, cur = 0, 0
    if not s:
        return None
    for ch in s:
        if ch in SINO:
            cur = SINO[ch]
        elif ch in SINO_UNITS:
            total += (cur or 1) * SINO_UNITS[ch]
            cur = 0
        else:
            return None
    return total + cur


_SINO_CH = "영공일이삼사오육칠팔구십백천"


def normalize_numerals(text: str) -> str:
    """'이천이십육년 십일월 육일' -> '2026년 11월 6일' (only before 년/월/일 units)."""
    def rep(unit):
        def _r(m):
            n = sino_to_int(m.group(2))
            return m.group(1) + (str(n) if n is not None else m.group(2)) + unit
        return _r
    t = re.sub(rf"(^|[\s,]|\d)([{_SINO_CH}]+)년", rep("년"), text)
    t = re.sub(rf"(^|[\s,년])([영일이삼사오육칠팔구십]+)월(?!요일)", rep("월"), t)
    t = re.sub(rf"(^|[\s,월])([일이삼사오육칠팔구십]+)일(?!요일)", rep("일"), t)
    return t


def _safe_date(y, m, d) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str, today: date) -> dict[str, Any]:
    """{'date': iso|None, 'status': ok|missing|ask|future|out_of_range, 'matched': str, 'relative': bool}"""
    t = text
    out = {"date": None, "status": "missing", "matched": "", "relative": False, "question": None}

    def done(d: date | None, matched: str, relative=False, question=None):
        if d is None:
            out.update(status="ask", matched=matched, question=question or "날짜를 다시 말씀해 주세요 (예: 11월 6일)")
            return out
        out.update(date=d.isoformat(), matched=matched, relative=relative)
        if d > today:
            out["status"] = "future"
        elif (today - d).days > 365:
            out["status"] = "out_of_range"
        else:
            out["status"] = "ok"
        return out

    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", t) or re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", t)
    if m:
        return done(_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0))
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", t) or re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        cand = _safe_date(today.year, mo, d)
        if cand is None and not (mo == 2 and d == 29):
            return done(None, m.group(0))
        if cand is None or cand > today:
            cand = _safe_date(today.year - 1, mo, d)
        return done(cand, m.group(0))
    if re.search(r"엊그제", t):
        return done(None, "엊그제", question="엊그제가 며칠인지 날짜로 말씀해 주세요")
    if WEEKDAY.search(t):
        return done(None, WEEKDAY.search(t).group(0), question="요일 대신 날짜로 말씀해 주세요 (예: 11월 6일)")
    rel = [("그저께", -2), ("그제", -2), ("어제", -1), ("오늘", 0), ("모레", 2), ("내일", 1)]
    for word, delta in rel:
        if word in t:
            return done(today + timedelta(days=delta), word, relative=True)
    m = re.search(r"(?<![\d월])(\d{1,2})\s*일(?!요일)", t)
    if m:
        d = int(m.group(1))
        cand = _safe_date(today.year, today.month, d)
        if cand is None or cand > today:
            prev_month_last = today.replace(day=1) - timedelta(days=1)
            cand = _safe_date(prev_month_last.year, prev_month_last.month, d)
            if cand is None:
                return done(None, m.group(0), question=f"{prev_month_last.month}월에는 {d}일이 없습니다. 날짜를 다시 말씀해 주세요")
        return done(cand, m.group(0))
    return out


def parse_meal(text: str) -> tuple[str | None, str]:
    for key, pat in MEALS:
        m = re.search(pat, text, re.I)
        if m:
            return key, m.group(0)
    return None, ""


def parse_intent(text: str) -> str:
    t = text.strip()
    if re.fullmatch(r"(취소|그만|아니(요|오)?|cancel|no)\s*[.!]?", t, re.I):
        return "cancel"
    if re.fullmatch(r"(확인|기록\s*확인|저장\s*확인|예|네|응|맞아|confirm|yes|ok(ay)?)\s*[.!]?", t, re.I):
        return "confirm"
    if re.search(r"읽어|들려|말해\s*줘|소리로|read", t, re.I):
        return "read"
    if re.search(r"보여|조회|로그|뭐\s*먹었|무엇을\s*먹었|show|view", t, re.I):
        return "view"
    if re.search(r"기록|저장|먹었|먹음|먹은|추가|log|record", t, re.I):
        return "record"
    return "unknown"


_FILLER = re.compile(r"(기록\s*해\s*줘|기록해|기록\s*좀|기록|저장\s*해\s*줘|저장해|저장|추가\s*해\s*줘|추가해|추가|"
                     r"먹었어요|먹었어|먹었다|먹었음|먹음|먹은\s*거|먹은|으로|로|에는|에|은|는|식사)", re.I)


def parse_foods(text: str, date_matched: str, meal_matched: str) -> list[dict[str, Any]]:
    t = text
    for s in (date_matched, meal_matched):
        if s:
            t = t.replace(s, " ", 1)
    t = re.sub(r"\d{4}\s*년", " ", t)
    t = _FILLER.sub(" ", t)
    chunks = re.split(r"\s*(?:,|，|그리고|이랑|랑|하고|및|&|\+)\s*", t)
    foods = []
    for ch in chunks:
        c = ch.strip(" .!?~")
        if not c:
            continue
        item: dict[str, Any] = {"text": c, "quantity": None, "unit": None, "grams": None}
        m = re.search(r"(\d+(?:\.\d+)?)\s*(g|그램|kg|킬로그램)\b", c, re.I) or re.search(r"(\d+(?:\.\d+)?)\s*(g|그램)", c, re.I)
        if m:
            g = float(m.group(1)) * (1000 if m.group(2).lower() in ("kg", "킬로그램") else 1)
            item["grams"] = g
            c = (c[:m.start()] + c[m.end():]).strip()
        m = re.search(rf"(\d+(?:\.\d+)?|한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉|열|반)\s*({UNITS})", c)
        if m:
            q = m.group(1)
            item["quantity"] = float(q) if re.match(r"\d", q) else NATIVE[q]
            item["unit"] = m.group(2)
            c = (c[:m.start()] + c[m.end():]).strip()
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*$", c)
            n = re.search(r"\s(하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉|열|반)\s*$", " " + c)
            if m and item["grams"] is None:
                item["quantity"] = float(m.group(1))
                c = c[:m.start()].strip()
            elif n:
                item["quantity"] = NATIVE[n.group(1)]
                c = (" " + c)[:n.start()].strip()
        name = re.sub(r"(을|를|도|만)$", "", c).strip()
        if name:
            item["name"] = name
            foods.append(item)
    return foods


def parse(text: str, now: datetime) -> dict[str, Any]:
    raw = text.strip()
    norm = normalize_numerals(raw)
    today = now.date()
    intent = parse_intent(raw)
    d = parse_date(norm, today)
    meal, meal_matched = parse_meal(norm)
    questions, warnings = [], []
    if intent in ("record", "view", "read"):
        if d["status"] == "missing":
            if intent == "record" or meal:
                d.update(date=today.isoformat(), status="ok", relative=True, matched="")
                warnings.append("date_defaulted_to_today")
            else:
                questions.append("어느 날짜의 기록인가요?")
        if d["status"] == "ask":
            questions.append(d["question"])
        if d["relative"] and d["matched"] == "오늘" and now.hour < 4:
            warnings.append("late_night_today: 자정 이후입니다. 어제 기록이면 '어제'라고 말씀해 주세요")
        if intent == "record":
            if d["status"] == "future":
                questions.append("미래 날짜에는 기록할 수 없습니다")
            if d["status"] == "out_of_range":
                questions.append("1년보다 오래된 날짜는 기록할 수 없습니다")
            if meal is None:
                questions.append("아침, 점심, 저녁, 간식 중 어느 끼니인가요?")
    foods = parse_foods(norm, d["matched"], meal_matched) if intent == "record" else []
    if intent == "record" and not foods and not questions:
        questions.append("무엇을 드셨는지 말씀해 주세요 (예: 밥 한 공기, 김치찌개)")
    return {
        "text": raw, "normalized": norm, "intent": intent,
        "date": d["date"], "date_status": d["status"], "date_text": d["matched"],
        "meal_type": meal, "meal_label": MEAL_KO.get(meal) if meal else None,
        "foods": foods, "questions": questions, "warnings": warnings,
        "today": today.isoformat(), "resolved_at": now.isoformat(),
    }
