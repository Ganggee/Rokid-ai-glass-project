// Meal before/after API client. Image processing runs on the server only.
import { request, uploadImage } from './api-client.js';
import { readJson, remove, writeJson } from './storage.js';

const base = '/api/v1/meals';
const SESSION_KEY = 'meal.session.v1';

export const GRAM_OPTIONS = [null, 100, 150, 200, 250, 300];

export const mealClient = {
  createSession() { return request(base + '/sessions', { method: 'POST', json: {} }); },
  getSession(sid) { return request(base + '/' + sid); },
  uploadPhoto(sid, kind, photo) { return uploadImage(base + '/' + sid + '/photos/' + kind, photo, kind + '.jpg'); },
  setItems(sid, items) { return request(base + '/' + sid + '/items', { method: 'POST', json: { items } }); },
  analyze(sid, method) { return request(base + '/' + sid + '/analyze', { method: 'POST', json: { method: method || 'auto' }, timeoutMs: 60000 }); },
  results(sid) { return request(base + '/' + sid + '/results'); },
};

export function rememberSession(sid) { return writeJson(SESSION_KEY, { sid, at: new Date().toISOString() }); }
export function recallSession() { const v = readJson(SESSION_KEY, null); return v && v.sid ? v.sid : null; }
export function forgetSession() { return remove(SESSION_KEY); }

const POS_KO = { 'top-left': '좌상', 'top-center': '중상', 'top-right': '우상', 'bottom-left': '좌하', 'bottom-center': '중하', 'bottom-right': '우하' };

export function positionText(position, lang) {
  return lang === 'en' ? String(position || '') : (POS_KO[position] || String(position || ''));
}

// HUD line for one analysed food. Never invents numbers: null stays "n/a".
export function foodLine(f, t) {
  const pct = f.estimated_consumed_ratio === null || f.estimated_consumed_ratio === undefined
    ? t.notComputable : Math.round(f.estimated_consumed_ratio * 100) + '%';
  let tail;
  if (f.estimated_consumed_grams === null || f.estimated_consumed_grams === undefined) {
    tail = f.estimated_consumed_ratio === null ? '' : ' · ' + t.gramsNone;
  } else {
    tail = ' · ' + Math.round(f.estimated_consumed_grams) + 'g';
    if (f.kcal !== null && f.kcal !== undefined) tail += ' · ' + Math.round(f.kcal) + 'kcal';
  }
  return f.label + ' ' + t.consumed + ' ' + pct + tail + (f.is_demo ? ' [' + t.demo + ']' : '') + (f.warnings && f.warnings.length ? ' !' : '');
}
