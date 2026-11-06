// Meal diary API client (server parses, computes nutrition and stores snapshots).
import { request } from './api-client.js';

const base = '/api/v1/meal-logs';

export const diaryClient = {
  parse(text) { return request(base + '/parse-command', { method: 'POST', json: { text } }); },
  save(entry) {
    return request(base, { method: 'POST', json: {
      log_date: entry.date, meal_type: entry.meal_type, idempotency_key: entry.key, confirmed: true,
      source: 'voice', utterance: entry.utterance || null,
      items: entry.items.map((i) => ({ food_name: i.food_name, nutrition_ref_id: i.nutrition_ref_id || null,
        quantity: i.quantity || null, unit: i.unit || null, grams: i.grams_basis === 'stated' ? i.grams : null,
        spoken_text: i.spoken_text || null })),
    } });
  },
  summary(date, mealType) {
    const q = [];
    if (date) q.push('date=' + encodeURIComponent(date));
    if (mealType) q.push('meal_type=' + encodeURIComponent(mealType));
    return request(base + '/summary' + (q.length ? '?' + q.join('&') : ''));
  },
  fromSession(sessionId, mealType) {
    return request(base + '/from-session/' + encodeURIComponent(sessionId), { method: 'POST', json: { meal_type: mealType, confirmed: true } });
  },
};

const WD_KO = ['일', '월', '화', '수', '목', '금', '토'];
const MEAL_KO = { breakfast: '아침', lunch: '점심', dinner: '저녁', snack: '간식' };

export function dateLabel(iso, mealType, lang) {
  if (!iso) return '';
  const p = String(iso).split('-').map((x) => parseInt(x, 10));
  const wd = new Date(p[0], p[1] - 1, p[2]).getDay();
  if (lang === 'en') return iso + (mealType ? ' ' + mealType : '');
  return p[0] + '년 ' + p[1] + '월 ' + p[2] + '일(' + WD_KO[wd] + ')' + (mealType ? ' ' + MEAL_KO[mealType] : '');
}

export function shiftDate(iso, days) {
  const p = String(iso).split('-').map((x) => parseInt(x, 10));
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2] + days));
  return d.toISOString().slice(0, 10);
}

export function itemLine(i, t) {
  const amount = i.grams !== null && i.grams !== undefined ? Math.round(i.grams) + 'g' : t.gramsUnknown;
  const kcal = i.kcal !== null && i.kcal !== undefined ? Math.round(i.kcal) + 'kcal' : t.kcalUnknown;
  const tag = i.ref_is_demo ? ' [' + t.demo + ']' : (i.nutrition_ref_id ? '' : ' ?');
  return i.food_name + ' · ' + amount + ' · ' + kcal + (i.is_estimate ? ' ' + t.estimate : '') + tag;
}
