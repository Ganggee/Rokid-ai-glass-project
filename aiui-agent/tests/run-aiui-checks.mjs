#!/usr/bin/env node
// AIUI agent checks that run without glasses or AIUI Studio.
//
// 1. Static: the official AIUI benchmark validator (yodaos-project/AIUI bench/src/validator.js)
//    checks manifest/source rules, built-in tags, permissions, handlers and styles.
// 2. Behavior: page logic is executed with the official bench loader (bench/src/behavior.js)
//    and mocked AIUI runtime objects (wx storage/camera, SpeechRecognition). In --with-server
//    mode the page talks to a REAL FastAPI backend over HTTP (node fetch).
//
// These are NOT Simulator or device results. Report them as "AIUI logic harness PASS".
//
// Usage:
//   git clone --depth 1 https://github.com/yodaos-project/AIUI ../AIUI
//   node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo ../AIUI --with-server --python python
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';

const here = path.dirname(fileURLToPath(import.meta.url));
const AGENT = path.resolve(here, '..');
const ROOT = path.resolve(AGENT, '..');
const argv = process.argv.slice(2);
const arg = (name, fallback) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : fallback; };
const AIUI_REPO = path.resolve(arg('--aiui-repo', process.env.AIUI_REPO || path.join(ROOT, '..', 'AIUI')));
const WITH_SERVER = argv.includes('--with-server');
const PYTHON = arg('--python', process.env.PYTHON || 'python3');
const TOKEN = 'aiui-harness-token-123456';

const { validateWorkspace } = await import(pathToFileURL(path.join(AIUI_REPO, 'bench/src/validator.js')));
const { loadLogic } = await import(pathToFileURL(path.join(AIUI_REPO, 'bench/src/behavior.js')));

const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push({ name, status: 'PASS' });
    console.log('PASS ', name);
  } catch (error) {
    results.push({ name, status: 'FAIL', error: String(error && error.stack || error) });
    console.log('FAIL ', name, '\n     ', String(error && error.message || error));
  }
}
function assert(cond, message) { if (!cond) throw new Error(message || 'assertion failed'); }
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ runtime mocks
function makeRuntime(opts = {}) {
  const storage = opts.storage || new Map();
  const state = { storageFailure: false, navigation: [], photo: opts.photo || null, speech: opts.speech || [] };
  const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
  const wx = {
    setStorageSync(k, v) { if (state.storageFailure) throw new Error('storage unavailable'); storage.set(k, clone(v)); },
    getStorageSync(k) { if (state.storageFailure) throw new Error('storage unavailable'); return clone(storage.get(k)); },
    removeStorageSync(k) { storage.delete(k); },
    navigateTo(o) { state.navigation.push(o.url); o.success && o.success({ errMsg: 'navigateTo:ok' }); },
    navigateBack() {},
    exitMiniProgram() {},
    arrayBufferToBase64(buf) { return Buffer.from(buf).toString('base64'); },
    media: {
      createCameraContext() {
        return { async takePhoto() { if (!state.photo) throw new Error('no photo'); return clone2(state.photo); } };
      },
    },
  };
  function clone2(p) { return { data: p.data.slice(0), mimeType: p.mimeType }; }
  class SpeechRecognition {
    start() {
      const text = state.speech.shift();
      setTimeout(() => {
        if (text === undefined) { this.onerror && this.onerror({ error: 'no-speech' }); return; }
        this.onresult && this.onresult({ results: [[{ transcript: text }]] });
        this.onend && this.onend();
      }, 1);
    }
    stop() {}
    abort() {}
  }
  const globals = {
    wx, fetch: opts.fetch || fetch, FormData, Blob, URL, URLSearchParams, encodeURIComponent, decodeURIComponent,
    AbortController, setTimeout, clearTimeout, crypto: webcrypto, console: { log() {}, error() {}, warn() {} },
  };
  if (opts.speechEnabled) globals.SpeechRecognition = SpeechRecognition;
  return { storage, state, globals };
}

async function openPage(workspace, relative, rt) {
  const logic = await loadLogic(workspace, relative, rt.globals);
  const page = {
    async call(method, a) { const r = logic.call(method, a); if (r && r.then) await r; await tick(5); return r; },
    data() { return JSON.parse(logic.snapshot()).data; },
  };
  await page.call('onLoad', {});
  await page.call('onShow');
  return page;
}

function prepareWorkspace(baseUrl, token) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aiui-ws-'));
  fs.cpSync(AGENT, dir, { recursive: true });
  const cfg = path.join(dir, 'lib/config.js');
  let src = fs.readFileSync(cfg, 'utf8');
  src = src.replace("API_BASE_URL: ''", `API_BASE_URL: '${baseUrl}'`).replace("API_TOKEN: ''", `API_TOKEN: '${token}'`);
  fs.writeFileSync(cfg, src);
  return dir;
}

// ------------------------------------------------------------------ backend process
function freePort() {
  return new Promise((resolve) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
}
class Backend {
  constructor(dir) { this.dir = dir; this.db = path.join(dir, 'harness.sqlite3'); this.proc = null; }
  env() { return { ...process.env, API_TOKEN: TOKEN, DATABASE_PATH: this.db, UPLOAD_DIR: path.join(this.dir, 'uploads'), NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost' }; }
  seed() { execFileSync(PYTHON, ['scripts/seed_demo_data.py', '--reset'], { cwd: ROOT, env: this.env(), stdio: 'pipe' }); }
  async start() {
    this.port = this.port || await freePort();
    this.base = `http://127.0.0.1:${this.port}`;
    this.proc = spawn(PYTHON, ['-m', 'uvicorn', 'backend.app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', String(this.port), '--log-level', 'warning'],
      { cwd: ROOT, env: this.env(), stdio: 'ignore' });
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(this.base + '/health')).ok) return; } catch (e) { /* not up yet */ }
      await tick(200);
    }
    throw new Error('backend did not start');
  }
  async stop() { if (this.proc) { this.proc.kill('SIGTERM'); await new Promise((r) => this.proc.once('exit', r)); this.proc = null; } }
  async api(p, init = {}) {
    const r = await fetch(this.base + p, { ...init, headers: { Authorization: 'Bearer ' + TOKEN, 'Content-Type': 'application/json', ...(init.headers || {}) } });
    return r.json();
  }
  async stock(id) { return (await this.api('/api/v1/inventory/products/' + id)).stock_qty; }
  async uses() { return (await this.api('/api/v1/inventory/transactions?limit=500')).items.filter((t) => t.tx_type === 'use').length; }
}

function makeImage(kind, outPath, extra = '') {
  execFileSync(PYTHON, [path.join(here, 'make_test_image.py'), kind, outPath, extra], { cwd: ROOT, stdio: 'pipe' });
  const buf = fs.readFileSync(outPath);
  return { data: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), mimeType: kind.startsWith('meal') ? 'image/jpeg' : 'image/png' };
}

const SENSOR = 'CARE-SENS-AIR-SENSOR';
const INV = 'pages/inventory/inventory.ink';

// ------------------------------------------------------------------ 1. static validation
await check('static: official AIUI bench validator has no issues', async () => {
  const { issues } = await validateWorkspace(AGENT);
  if (issues.length) throw new Error(JSON.stringify(issues, null, 2));
});

await check('static: app.json valid, every page has one .ink source, permissions declared', async () => {
  const app = JSON.parse(fs.readFileSync(path.join(AGENT, 'app.json'), 'utf8'));
  for (const route of app.pages) assert(fs.existsSync(path.join(AGENT, route + '.ink')), 'missing ' + route);
  assert(app.permissions.includes('CAMERA'), 'CAMERA permission');
  for (const route of app.pages) {
    const src = fs.readFileSync(path.join(AGENT, route + '.ink'), 'utf8');
    const def = src.match(/<script def>([\s\S]*?)<\/script>/);
    if (def) JSON.parse(def[1]);
    assert(!/\b(Page|App|Widget)\s*\(/.test(src), 'legacy registration in ' + route);
  }
});

await check('static: committed config.js has no server URL or token', async () => {
  const src = fs.readFileSync(path.join(AGENT, 'lib/config.js'), 'utf8');
  assert(/API_BASE_URL: ''/.test(src) && /API_TOKEN: ''/.test(src), 'config.js must be committed empty');
});

// ------------------------------------------------------------------ 2. LOCAL mode behavior
await check('LOCAL: 20 -> use 1 -> 19 -> page reopened -> still 19 (the reported bug)', async () => {
  const rt = makeRuntime();
  const p1 = await openPage(AGENT, INV, rt);
  assert(p1.data().mode === 'LOCAL', 'expected LOCAL mode');
  assert(p1.data().products.find((p) => p.product_id === SENSOR).stock_qty === 20, 'initial 20');
  await p1.call('selectProduct', { id: SENSOR });
  await p1.call('askUseOne');
  assert(p1.data().view === 'confirm', 'confirmation screen shown before any write');
  assert(rt.storage.get('inv.local.v1').products.find((p) => p.product_id === SENSOR).stock_qty === 20, 'no write before confirm');
  await p1.call('confirmUse');
  assert(p1.data().product.stock_qty === 19, 'after confirm 19, got ' + p1.data().product.stock_qty);
  const p2 = await openPage(AGENT, INV, rt); // agent exit + re-entry: new page instance, same device storage
  assert(p2.data().products.find((p) => p.product_id === SENSOR).stock_qty === 19, 'persisted 19');
});

await check('LOCAL: cancel writes nothing; double confirm applies once', async () => {
  const rt = makeRuntime();
  const p = await openPage(AGENT, INV, rt);
  await p.call('selectProduct', { id: SENSOR });
  await p.call('askUseOne');
  await p.call('cancelUse');
  assert(p.data().view === 'detail' && rt.storage.get('inv.local.v1').transactions.length === 0, 'cancel must not write');
  await p.call('askUseOne');
  await Promise.all([p.call('confirmUse'), p.call('confirmUse')]);
  const st = rt.storage.get('inv.local.v1');
  assert(st.transactions.length === 1 && st.products.find((x) => x.product_id === SENSOR).stock_qty === 19, 'exactly one decrement');
});

await check('LOCAL: storage write failure is reported and not shown as success', async () => {
  const rt = makeRuntime();
  const p = await openPage(AGENT, INV, rt);
  await p.call('selectProduct', { id: SENSOR });
  await p.call('askUseOne');
  rt.state.storageFailure = true;
  await p.call('confirmUse');
  rt.state.storageFailure = false;
  assert(p.data().product.stock_qty === 20, 'UI must keep 20');
  assert(/저장 실패|Save failed/.test(p.data().message), 'storage error message, got ' + p.data().message);
  const p2 = await openPage(AGENT, INV, rt);
  assert(p2.data().products.find((x) => x.product_id === SENSOR).stock_qty === 20, 'still 20 after reopen');
});

await check('LOCAL: voice "케어센스 센서 한 개 사용" -> confirm screen, "취소" -> no change', async () => {
  const rt = makeRuntime({ speechEnabled: true, speech: ['케어센스 센서 한 개 사용', '취소'] });
  const p = await openPage(AGENT, INV, rt);
  await p.call('voiceCommand');
  await tick(20);
  let d = p.data();
  assert(d.view === 'confirm' && d.product.product_id === SENSOR && d.quantity === 1, 'confirm view, got ' + d.view);
  await p.call('voiceCommand');
  await tick(20);
  d = p.data();
  assert(d.view === 'detail' && rt.storage.get('inv.local.v1').transactions.length === 0, 'cancel by voice writes nothing');
});

{
  const { mealLocalScenarios } = await import(pathToFileURL(path.join(here, 'meal-scenarios.mjs')));
  await mealLocalScenarios({ check, assert, openPage, makeRuntime, AGENT });
}

// ------------------------------------------------------------------ 3. SERVER mode behavior (real backend)
if (WITH_SERVER) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'aiui-backend-'));
  const backend = new Backend(tmp);
  backend.seed();
  await backend.start();
  const ws = prepareWorkspace(backend.base, TOKEN);
  try {
    await check('SERVER: 20 -> 19 via page, page reopened -> 19, backend restarted -> 19', async () => {
      const rt = makeRuntime();
      const p1 = await openPage(ws, INV, rt);
      assert(p1.data().mode === 'SERVER', 'SERVER mode');
      assert(p1.data().products.find((x) => x.product_id === SENSOR).stock_qty === 20, 'initial 20 from server');
      await p1.call('selectProduct', { id: SENSOR });
      await p1.call('askUseOne');
      await p1.call('confirmUse');
      assert(p1.data().product.stock_qty === 19 && await backend.stock(SENSOR) === 19, 'server 19');
      assert(rt.storage.get('inv.pendingOp.v1') === undefined, 'pending journal cleared after success');
      const p2 = await openPage(ws, INV, makeRuntime());
      assert(p2.data().products.find((x) => x.product_id === SENSOR).stock_qty === 19, 'reopen shows 19');
      await backend.stop();
      await backend.start();
      const p3 = await openPage(ws, INV, makeRuntime());
      assert(p3.data().products.find((x) => x.product_id === SENSOR).stock_qty === 19, 'after backend restart 19');
      assert(await backend.uses() === 1, 'exactly one use transaction');
    });

    await check('SERVER: response lost after server applied -> pending -> reopen reconciles without 2nd decrement', async () => {
      const before = await backend.stock(SENSOR);
      const usesBefore = await backend.uses();
      const lossyFetch = async (url, init) => {
        const r = await fetch(url, init);
        if (String(url).endsWith('/api/v1/inventory/use')) throw new Error('connection reset (simulated)');
        return r;
      };
      const rt = makeRuntime({ fetch: lossyFetch });
      const p = await openPage(ws, INV, rt);
      await p.call('selectProduct', { id: SENSOR });
      await p.call('askUseOne');
      await p.call('confirmUse');
      assert(p.data().view === 'pending', 'uncertain result must not be shown as success, view=' + p.data().view);
      assert(rt.storage.get('inv.pendingOp.v1'), 'pending journal kept');
      // user exits and re-enters the agent (same device storage, network back)
      const rt2 = makeRuntime({ storage: rt.storage });
      const p2 = await openPage(ws, INV, rt2);
      assert(/반영 확인|applied/.test(p2.data().message), 'recovered message, got ' + p2.data().message);
      assert(rt2.storage.get('inv.pendingOp.v1') === undefined, 'journal cleared');
      assert(await backend.stock(SENSOR) === before - 1 && await backend.uses() === usesBefore + 1, 'applied exactly once');
    });

    await check('SERVER: request never reached server -> pending -> retry with SAME key applies once', async () => {
      const before = await backend.stock('HICARDI-PATCH');
      const deadFetch = async (url, init) => {
        if (String(url).endsWith('/api/v1/inventory/use')) throw new Error('offline (simulated)');
        return fetch(url, init);
      };
      const rt = makeRuntime({ fetch: deadFetch });
      const p = await openPage(ws, INV, rt);
      await p.call('selectProduct', { id: 'HICARDI-PATCH' });
      await p.call('askUseOne');
      await p.call('confirmUse');
      const key = rt.storage.get('inv.pendingOp.v1').key;
      const rt2 = makeRuntime({ storage: rt.storage });
      const p2 = await openPage(ws, INV, rt2);
      assert(p2.data().view === 'pending', 'not applied -> pending view, got ' + p2.data().view);
      await p2.call('retryPending');
      assert(p2.data().view === 'confirm', 'retry asks confirmation again');
      await p2.call('confirmUse');
      assert(await backend.stock('HICARDI-PATCH') === before - 1, 'applied once');
      const op = await backend.api('/api/v1/inventory/operations/' + key);
      assert(op.applied === true, 'same idempotency key used for retry');
    });

    await check('SERVER: insufficient stock is an error, not a success', async () => {
      const rt = makeRuntime();
      const p = await openPage(ws, INV, rt);
      await p.call('handleCommandText', '어플리케이터 11개 사용');
      assert(p.data().view === 'confirm' && p.data().quantity === 11, 'confirm 11');
      await p.call('confirmUse');
      assert(/재고 부족|Insufficient/.test(p.data().message), 'insufficient message, got ' + p.data().message);
      assert(await backend.stock('CARE-SENS-AIR-APPLICATOR') === 10, 'unchanged 10');
    });

    await check('SERVER: QR photo (camera mock) -> server decode -> product shown', async () => {
      const photo = makeImage('qr', path.join(tmp, 'qr.png'), 'HICARDI-PATCH');
      const rt = makeRuntime({ photo });
      const p = await openPage(ws, INV, rt);
      await p.call('scanQr');
      assert(p.data().view === 'detail' && p.data().product.product_id === 'HICARDI-PATCH', 'QR matched, view=' + p.data().view + ' msg=' + p.data().message);
    });

    await check('SERVER: unknown QR -> unrecognized, falls back to list', async () => {
      const photo = makeImage('qr', path.join(tmp, 'qr2.png'), 'UNKNOWN-LOT-123');
      const p = await openPage(ws, INV, makeRuntime({ photo }));
      await p.call('scanQr');
      assert(p.data().view === 'list' && /인식 실패|Not recognized/.test(p.data().message), 'fallback, msg=' + p.data().message);
    });

    await check('SERVER: wrong token -> auth error message, no crash', async () => {
      const ws2 = prepareWorkspace(backend.base, 'wrong-token-xxxxxxxx');
      const p = await openPage(ws2, INV, makeRuntime());
      assert(/인증 실패|Auth failed/.test(p.data().message), 'auth message, got ' + p.data().message);
    });

    if (fs.existsSync(path.join(AGENT, 'pages/meal/meal.ink'))) {
      const { mealScenarios } = await import(pathToFileURL(path.join(here, 'meal-scenarios.mjs')));
      await mealScenarios({ check, assert, tick, openPage, makeRuntime, makeImage, ws, tmp, backend });
    }
  } finally {
    await backend.stop();
  }
} else {
  console.log('SKIP  SERVER scenarios (pass --with-server)');
}

const failed = results.filter((r) => r.status === 'FAIL');
const report = { generated_at: new Date().toISOString(), aiui_repo: AIUI_REPO, level: 'AIUI logic harness (not Simulator, not device)', results };
const out = arg('--report', '');
if (out) fs.writeFileSync(out, JSON.stringify(report, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
