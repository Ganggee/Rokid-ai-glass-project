// On-device rule parser for LOCAL mode (SERVER mode uses POST /parse-command).
// Converts recognized text into a structured command. It never changes stock;
// the page must still show the confirmation step.
const KO_NUM = { 한: 1, 하나: 1, 두: 2, 둘: 2, 세: 3, 셋: 3, 네: 4, 넷: 4, 다섯: 5 };
const compact = (s) => String(s || '').toLowerCase().replace(/\s+/g, '');

export function parseCommand(text, products) {
  const t = String(text || '').trim();
  const out = { text: t, intent: 'unknown', quantity: null, product: null, requires_confirmation: false };
  if (/(취소|그만|cancel|abort)/i.test(t) || /^no$/i.test(t)) return Object.assign(out, { intent: 'cancel' });
  if (/^(사용\s*확인|확인|예|네|응|confirm|yes|ok(ay)?)\s*[.!]?$/i.test(t)) return Object.assign(out, { intent: 'confirm' });
  const c = compact(t);
  let best = null;
  let bestLen = 0;
  for (const p of products || []) {
    const names = [p.product_name, p.product_id].concat(p.aliases || []);
    for (const n of names) {
      const a = compact(n);
      if (a.length >= 2 && c.indexOf(a) >= 0 && a.length > bestLen) { best = p; bestLen = a.length; }
    }
  }
  out.product = best;
  if (/(사용|차감|썼|소모|\buse\b|\bused\b)/i.test(t)) {
    let q = 1;
    const m = t.match(/(\d+)\s*(개|ea)?/);
    const k = t.match(/(한|하나|두|둘|세|셋|네|넷|다섯)\s*개/);
    if (m) q = parseInt(m[1], 10); else if (k) q = KO_NUM[k[1]];
    return Object.assign(out, { intent: 'use', quantity: q, requires_confirmation: true });
  }
  if (/(재고|몇\s*개|얼마|남았|조회|알려|stock|how\s+many|check)/i.test(t) || best) {
    return Object.assign(out, { intent: 'query_stock' });
  }
  return out;
}
