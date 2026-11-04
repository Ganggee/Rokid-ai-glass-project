// Inventory data access with two interchangeable backends.
//
// SERVER mode (API_BASE_URL configured): the FastAPI/SQLite server is the source of
//   truth. A "pending operation" (idempotency key + payload) is written to device
//   storage BEFORE the POST and cleared only after a definitive answer, so a crash,
//   app exit or network drop never causes a blind second decrement: on the next
//   start the client asks GET /operations/{key} whether it was applied.
//
// LOCAL mode (no server): stock and history are persisted in wx storage on the
//   glasses. This fixes "20 -> 19 -> restart -> 20" for a single device but is not
//   multi-user safe; use SERVER mode for real inventory.
import { isServerConfigured, request } from './api-client.js';
import { DEMO_PRODUCTS } from './demo-inventory.js';
import { readJson, remove, writeJson } from './storage.js';

export const KEYS = {
  local: 'inv.local.v1',
  pending: 'inv.pendingOp.v1',
  cache: 'inv.cache.v1',
};

function ok(data) { return { ok: true, data, error: null }; }
function fail(kind, message, extra) { return { ok: false, data: null, error: Object.assign({ kind, message }, extra || {}) }; }

// ------------------------------------------------------------------ LOCAL
function loadLocal() {
  let state = readJson(KEYS.local, null);
  if (!state || !Array.isArray(state.products)) {
    state = { version: 1, products: DEMO_PRODUCTS.map((p) => Object.assign({}, p)), transactions: [], appliedKeys: {} };
    const saved = writeJson(KEYS.local, state);
    if (!saved.ok) return { state, persisted: false, error: saved.error };
  }
  return { state, persisted: true };
}

export const localInventory = {
  mode: 'LOCAL',
  async list() {
    const { state } = loadLocal();
    return ok({ items: state.products, count: state.products.length });
  },
  async get(productId) {
    const { state } = loadLocal();
    const p = state.products.find((x) => x.product_id === productId);
    return p ? ok(p) : fail('HTTP', 'Product not found', { code: 'PRODUCT_NOT_FOUND' });
  },
  async use(productId, quantity, key) {
    const { state } = loadLocal();
    if (state.appliedKeys[key]) {
      const p = state.products.find((x) => x.product_id === productId);
      return ok({ product: p, transaction: state.appliedKeys[key], replayed: true });
    }
    const p = state.products.find((x) => x.product_id === productId);
    if (!p) return fail('HTTP', 'Product not found', { code: 'PRODUCT_NOT_FOUND' });
    if (p.stock_qty < quantity) return fail('HTTP', 'Insufficient stock', { code: 'INSUFFICIENT_STOCK' });
    const tx = { id: state.transactions.length + 1, product_id: productId, tx_type: 'use', quantity_delta: -quantity,
      stock_before: p.stock_qty, stock_after: p.stock_qty - quantity, idempotency_key: key, created_at: new Date().toISOString() };
    const next = JSON.parse(JSON.stringify(state));
    const np = next.products.find((x) => x.product_id === productId);
    np.stock_qty -= quantity;
    next.transactions.push(tx);
    next.appliedKeys[key] = tx;
    if (next.transactions.length > 200) next.transactions = next.transactions.slice(-200);
    const saved = writeJson(KEYS.local, next); // commit point: only a successful write counts
    if (!saved.ok) return fail('STORAGE', 'Could not save to device storage: ' + saved.error);
    return ok({ product: np, transaction: tx, replayed: false });
  },
  async transactions(productId) {
    const { state } = loadLocal();
    const items = state.transactions.filter((t) => !productId || t.product_id === productId).slice(-20).reverse();
    return ok({ items, count: items.length });
  },
  async resolveCode(code) {
    const { state } = loadLocal();
    const v = String(code || '').trim();
    const p = state.products.find((x) => x.qr_value === v || x.barcode === v || x.product_id === v);
    return ok(p ? { status: 'matched', product: p, candidates: [] } : { status: 'unrecognized', product: null, candidates: [] });
  },
  async operationStatus() { return ok({ applied: false }); },
  resetLocal() { return remove(KEYS.local); },
};

// ------------------------------------------------------------------ SERVER
const base = '/api/v1/inventory';

export const serverInventory = {
  mode: 'SERVER',
  async list(query) {
    const r = await request(base + '/products' + (query ? '?query=' + encodeURIComponent(query) : ''));
    if (r.ok) writeJson(KEYS.cache, { at: new Date().toISOString(), items: r.data.items });
    return r;
  },
  async get(productId) { return request(base + '/products/' + encodeURIComponent(productId)); },
  async use(productId, quantity, key) {
    return request(base + '/use', { method: 'POST', json: {
      product_id: productId, quantity, idempotency_key: key, confirmed: true,
      client_timestamp: new Date().toISOString(), source: 'aiui' } });
  },
  async transactions(productId) {
    return request(base + '/transactions?limit=20' + (productId ? '&product_id=' + encodeURIComponent(productId) : ''));
  },
  async resolveCode(code) { return request(base + '/resolve-code', { method: 'POST', json: { code: String(code), code_type: 'auto' } }); },
  async operationStatus(key) { return request(base + '/operations/' + encodeURIComponent(key)); },
  async parseCommand(text) { return request(base + '/parse-command', { method: 'POST', json: { text } }); },
  cached() { return readJson(KEYS.cache, null); },
};

export function inventoryBackend() {
  return isServerConfigured() ? serverInventory : localInventory;
}

// ------------------------------------------------------------------ pending operation journal
export function savePending(op) { return writeJson(KEYS.pending, op); }
export function loadPending() { return readJson(KEYS.pending, null); }
export function clearPending() { return remove(KEYS.pending); }

// Perform a confirmed use with crash/network-safe semantics.
// Returns { ok, data, error, uncertain } — uncertain=true means the server may or
// may not have applied it; the pending journal is kept for a status check.
export async function confirmedUse(backend, productId, quantity, key) {
  const journal = savePending({ key, productId, quantity, at: new Date().toISOString(), mode: backend.mode });
  if (!journal.ok && backend.mode === 'SERVER') {
    return fail('STORAGE', 'Cannot write pending-operation journal: ' + journal.error);
  }
  const r = await backend.use(productId, quantity, key);
  if (r.ok) { clearPending(); return r; }
  const kind = r.error && r.error.kind;
  if (kind === 'NETWORK' || kind === 'TIMEOUT' || kind === 'BAD_RESPONSE' || (r.status >= 500)) {
    return Object.assign({}, r, { uncertain: true });
  }
  clearPending(); // definitive rejection (4xx): nothing was applied
  return r;
}

// On page load / retry: resolve an uncertain operation by asking the server.
export async function reconcilePending(backend) {
  const op = loadPending();
  if (!op) return { state: 'none' };
  if (backend.mode !== 'SERVER') { clearPending(); return { state: 'none' }; }
  const s = await backend.operationStatus(op.key);
  if (!s.ok) return { state: 'unknown', op, error: s.error };
  if (s.data.applied) { clearPending(); return { state: 'applied', op, product: s.data.product }; }
  return { state: 'not_applied', op };
}
