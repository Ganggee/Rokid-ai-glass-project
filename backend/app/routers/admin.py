"""PC admin page for meal sessions (Baseline 0 manual regions, manual upload fallback).

The HTML itself contains no data; every request is made by the page with the
bearer token the operator types in (kept in sessionStorage only).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin"])

ADMIN_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Meal PoC admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,sans-serif;margin:16px;background:#0b0f0c;color:#d7f5dc}
 h1{font-size:18px;margin:0 0 8px} h2{font-size:15px;margin:16px 0 6px}
 input,select,button{background:#101a12;color:#d7f5dc;border:1px solid #3c6b45;border-radius:4px;padding:4px 6px}
 button{cursor:pointer} button.on{background:#2d5a36}
 .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0}
 .imgs{display:flex;gap:12px;flex-wrap:wrap} .imgs div{flex:1;min-width:320px}
 canvas{width:100%;border:1px solid #3c6b45;cursor:crosshair}
 table{border-collapse:collapse;font-size:13px} td,th{border:1px solid #2c4a31;padding:3px 6px;text-align:left}
 .warn{color:#ffd27a} .demo{background:#ffd27a;color:#000;padding:0 4px;border-radius:3px;font-size:11px}
 pre{white-space:pre-wrap;font-size:11px;max-height:280px;overflow:auto;background:#101a12;padding:6px}
</style></head><body>
<h1>Meal before/after PoC — admin</h1>
<div class="row">Token <input id="token" type="password" size="28"> <button onclick="saveToken()">Use</button>
 <button onclick="newSession()">New session</button> <select id="sessions" onchange="load(this.value)"></select>
 <button onclick="refreshSessions()">Reload list</button> <button onclick="delSession()">Delete session</button></div>
<div class="row">Upload from PC: before <input type="file" id="fb" accept="image/*"> after <input type="file" id="fa" accept="image/*">
 <button onclick="upload()">Upload</button></div>
<div class="imgs"><div><b>Before</b><canvas id="cb"></canvas></div><div><b>After</b><canvas id="ca"></canvas></div></div>
<h2>Items <small>select a row, then drag a box on Before (required) and optionally After (manual mode)</small></h2>
<table id="items"><thead><tr><th></th><th>Label</th><th>Nutrition ref</th><th>Initial g</th><th>Serving source</th><th>Before box</th><th>After box</th><th></th></tr></thead><tbody></tbody></table>
<div class="row"><button onclick="addItem()">+ item</button> <button onclick="useDetected()">Use detected regions</button>
 <button onclick="saveItems()">Save items</button> <button onclick="analyze('auto')">Analyze (auto)</button>
 <button onclick="analyze('manual')">Analyze (manual boxes only)</button></div>
<h2>Result</h2><div id="result"></div><pre id="raw"></pre>
<script>
let token = sessionStorage.getItem('poc-token') || ''; document.getElementById('token').value = token;
let sid = null, session = null, refs = [], items = [], sel = 0, imgs = {}, drag = null;
const api = async (path, opt = {}) => {
  const r = await fetch(path, {...opt, headers: {...(opt.headers||{}), Authorization: 'Bearer ' + token}});
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.blob();
  if (!r.ok) { alert(JSON.stringify(body.error || body)); throw new Error(r.status); }
  return body;
};
function saveToken(){ token = document.getElementById('token').value.trim(); sessionStorage.setItem('poc-token', token); init(); }
async function init(){ refs = (await api('/api/v1/nutrition/references')).items; await refreshSessions(); }
async function refreshSessions(){
  const list = (await api('/api/v1/meals/sessions')).items, s = document.getElementById('sessions');
  s.innerHTML = list.map(x => `<option value="${x.session_id}">${x.created_at.slice(0,19)} ${x.status} ${x.session_id.slice(0,6)}</option>`).join('');
  if (list.length) load(sid && list.find(x=>x.session_id===sid) ? sid : list[0].session_id);
}
async function newSession(){ const s = await api('/api/v1/meals/sessions', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); sid = s.session_id; await refreshSessions(); }
async function delSession(){ if (sid && confirm('Delete session and photos?')) { await api('/api/v1/meals/' + sid, {method:'DELETE'}); sid = null; refreshSessions(); } }
async function upload(){
  for (const [kind, id] of [['before','fb'],['after','fa']]) {
    const f = document.getElementById(id).files[0]; if (!f) continue;
    const fd = new FormData(); fd.append('file', f); await api(`/api/v1/meals/${sid}/photos/${kind}`, {method:'POST', body: fd});
  }
  load(sid);
}
async function load(id){
  sid = id; session = await api('/api/v1/meals/' + sid);
  items = session.items.map(i => ({label:i.label, nutrition_ref_id:i.nutrition_ref_id||'', initial_serving_grams:i.initial_serving_grams||'', serving_source:i.serving_source||'user', before_region:i.before_region, after_region:i.after_region}));
  if (!items.length) addItem(false);
  for (const k of ['before','after']) {
    imgs[k] = null;
    if (session.photos[k]) { const b = await api(session.photos[k].url); const im = new Image(); im.onload = () => { imgs[k] = im; draw(); }; im.src = URL.createObjectURL(b); }
  }
  renderItems(); draw();
  try { show(await api(`/api/v1/meals/${sid}/results`)); } catch(e) { document.getElementById('result').innerHTML=''; document.getElementById('raw').textContent=''; }
}
function addItem(render = true){ items.push({label:'', nutrition_ref_id:'', initial_serving_grams:'', serving_source:'user', before_region:null, after_region:null}); sel = items.length-1; if (render) renderItems(); }
function useDetected(){ const d = (session.photos.before||{}).detected_regions || []; items = d.map(r => ({label:'', nutrition_ref_id:'', initial_serving_grams:'', serving_source:'user', before_region:r.region, after_region:null})); renderItems(); draw(); }
const fmt = r => r ? `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.w)}x${Math.round(r.h)}` : '-';
function renderItems(){
  const opts = ['<option value="">(match by label)</option>'].concat(refs.map(r => `<option value="${r.id}">${r.food_name}${r.is_demo?' [DEMO]':''}</option>`)).join('');
  document.querySelector('#items tbody').innerHTML = items.map((it,i) => `<tr style="${i===sel?'background:#173a1f':''}">
   <td><button onclick="sel=${i};renderItems();draw()">${i===sel?'&#9679;':'&#9675;'}</button></td>
   <td><input value="${it.label}" oninput="items[${i}].label=this.value"></td>
   <td><select onchange="items[${i}].nutrition_ref_id=this.value">${opts.replace(`value="${it.nutrition_ref_id}"`, `value="${it.nutrition_ref_id}" selected`)}</select></td>
   <td><input size="5" value="${it.initial_serving_grams}" oninput="items[${i}].initial_serving_grams=this.value"></td>
   <td><select onchange="items[${i}].serving_source=this.value"><option value="user" ${it.serving_source==='user'?'selected':''}>user</option><option value="demo_assumption" ${it.serving_source==='demo_assumption'?'selected':''}>DEMO assumption</option></select></td>
   <td>${fmt(it.before_region)}</td><td>${fmt(it.after_region)} <button onclick="items[${i}].after_region=null;renderItems();draw()">x</button></td>
   <td><button onclick="items.splice(${i},1);sel=0;renderItems();draw()">del</button></td></tr>`).join('');
}
function draw(){
  for (const [k, id] of [['before','cb'],['after','ca']]) {
    const c = document.getElementById(id), im = imgs[k], g = c.getContext('2d');
    if (!im) { c.width = 400; c.height = 300; g.fillStyle='#111'; g.fillRect(0,0,400,300); g.fillStyle='#777'; g.fillText('no ' + k + ' photo', 20, 30); continue; }
    c.width = im.naturalWidth; c.height = im.naturalHeight; g.drawImage(im, 0, 0);
    g.lineWidth = Math.max(2, im.naturalWidth/300); g.font = `${Math.max(14, im.naturalWidth/40)}px sans-serif`;
    items.forEach((it, i) => { const r = it[k + '_region']; if (!r) return; g.strokeStyle = i===sel ? '#40ff5e' : '#ffd27a'; g.strokeRect(r.x, r.y, r.w, r.h); g.fillStyle = g.strokeStyle; g.fillText(it.label || ('#'+(i+1)), r.x + 4, r.y + 20); });
  }
}
for (const [k, id] of [['before','cb'],['after','ca']]) {
  const c = document.getElementById(id);
  const pt = e => { const b = c.getBoundingClientRect(); return [(e.clientX - b.left) * c.width / b.width, (e.clientY - b.top) * c.height / b.height]; };
  c.onmousedown = e => { if (imgs[k] && items[sel]) drag = {k, p: pt(e)}; };
  c.onmouseup = e => { if (!drag || drag.k !== k) return; const [x0,y0] = drag.p, [x1,y1] = pt(e); drag = null;
    items[sel][k + '_region'] = {type:'bbox', x:Math.min(x0,x1), y:Math.min(y0,y1), w:Math.abs(x1-x0), h:Math.abs(y1-y0)}; renderItems(); draw(); };
}
async function saveItems(){
  const body = {items: items.filter(i => i.label).map(i => { const o = {label:i.label}; if (i.nutrition_ref_id) o.nutrition_ref_id = i.nutrition_ref_id;
    if (i.initial_serving_grams) { o.initial_serving_grams = parseFloat(i.initial_serving_grams); o.serving_source = i.serving_source; }
    if (i.before_region) o.before_region = i.before_region; if (i.after_region) o.after_region = i.after_region; return o; })};
  await api(`/api/v1/meals/${sid}/items`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}); load(sid);
}
async function analyze(method){ show(await api(`/api/v1/meals/${sid}/analyze`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({method})})); }
const v = x => x === null || x === undefined ? '<i>n/a</i>' : x;
function show(r){
  document.getElementById('result').innerHTML = `<div>${r.is_demo?'<span class="demo">DEMO</span> ':''}method <b>${r.analysis_method}</b> · confidence <b>${r.confidence}</b> · alignment ${r.alignment.status} (${r.alignment.method||''})</div>
   ${r.warnings.map(w=>`<div class="warn">! ${w}</div>`).join('')}
   <table><tr><th>food</th><th>before px</th><th>after px</th><th>eaten ratio</th><th>initial g</th><th>eaten g</th><th>kcal</th><th>C/P/F g</th><th>notes</th></tr>
   ${r.foods.map(f=>`<tr><td>${f.label}${f.is_demo?' <span class="demo">DEMO</span>':''}</td><td>${v(f.before_mask_area_px)}</td><td>${v(f.after_mask_area_px)}</td><td>${f.estimated_consumed_ratio===null?'<i>verify</i>':Math.round(f.estimated_consumed_ratio*100)+'%'}</td><td>${v(f.initial_serving_grams)}</td><td>${v(f.estimated_consumed_grams)}</td><td>${v(f.kcal)}</td><td>${v(f.carbs_g)}/${v(f.protein_g)}/${v(f.fat_g)}</td><td class="warn">${f.warnings.join('; ')}</td></tr>`).join('')}</table>
   <div><small>${r.disclaimer}</small></div>`;
  document.getElementById('raw').textContent = JSON.stringify(r, null, 2);
}
if (token) init();
</script></body></html>"""


@router.get("/admin/meals", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return HTMLResponse(ADMIN_HTML, headers={"Cache-Control": "no-store"})


SYNC_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Inventory Excel sync</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,sans-serif;margin:16px;background:#0b0f0c;color:#d7f5dc}
 h1{font-size:18px;margin:0 0 8px} h2{font-size:15px;margin:16px 0 6px}
 input,button{background:#101a12;color:#d7f5dc;border:1px solid #3c6b45;border-radius:4px;padding:4px 6px}
 button{cursor:pointer} .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0}
 table{border-collapse:collapse;font-size:13px} td,th{border:1px solid #2c4a31;padding:3px 6px;text-align:left}
 .state{font-weight:600;padding:2px 6px;border-radius:3px} .ok{background:#2d5a36} .bad{background:#7a2b2b} .warn{background:#7a6a2b}
 pre{white-space:pre-wrap;font-size:11px;max-height:260px;overflow:auto;background:#101a12;padding:6px}
</style></head><body>
<h1>Inventory ↔ Excel sync <small><a href="/admin/meals" style="color:#9fd">meals</a></small></h1>
<div class="row">Token <input id="token" type="password" size="28"> <button onclick="saveToken()">Use</button>
 <button onclick="refresh()">Refresh status</button> <button onclick="preview()">Preview changes</button>
 <button id="apply" onclick="applyNow()" disabled>Apply valid rows + export</button></div>
<div id="summary"></div>
<div id="resolve" style="display:none"><h2>Resolve (merge stopped)</h2>
 <div class="row"><button onclick="resolveAct('discard_file')" title="action=discard_file">파일 수정 버리고 DB 값으로 다시 내보내기</button>
 <button onclick="resolveAct('apply_file_values')" title="action=apply_file_values">파일 값을 재고에 반영(adjust)</button></div>
 <div id="resolvePlan"></div></div>
<h2>Plan (preview)</h2><div id="plan">Press "Preview changes".</div>
<h2>Recent events</h2><table id="events"><thead><tr><th>time</th><th>kind</th><th>product</th><th>detail</th></tr></thead><tbody></tbody></table>
<pre id="raw"></pre>
<script>
let token = sessionStorage.getItem('poc-token') || ''; document.getElementById('token').value = token;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api = async (path, opt = {}) => {
  const r = await fetch(path, {...opt, headers: {...(opt.headers||{}), 'Content-Type':'application/json', Authorization: 'Bearer ' + token}});
  const body = await r.json();
  if (!r.ok) { alert(JSON.stringify(body.error || body)); throw new Error(r.status); }
  return body;
};
function saveToken(){ token = document.getElementById('token').value.trim(); sessionStorage.setItem('poc-token', token); refresh(); }
async function refresh(){
  const s = await api('/api/v1/inventory/excel-sync/status');
  if (!s.enabled) { document.getElementById('summary').innerHTML = 'Disabled: ' + esc(s.reason); return; }
  const cls = s.state.startsWith('ok') ? 'ok' : (['error','blocked','needs_review'].includes(s.state) ? 'bad' : 'warn');
  document.getElementById('resolve').style.display = ['blocked','needs_review'].includes(s.state) ? 'block' : 'none';
  document.getElementById('summary').innerHTML =
    `<div class="row"><b>${esc(s.reason_text)}</b></div><div class="row">State <span class="state ${cls}">${esc(s.state)}</span> pending export: <b>${s.pending_export}</b>
     ${s.pending_reason ? '(' + esc(s.pending_reason) + ')' : ''} auto-apply: ${s.auto_apply} poll: ${s.poll_seconds}s</div>
     <div class="row">File: ${esc(s.path)} ${s.lock_file_present ? '<b>(open in Excel)</b>' : ''}
     ${s.conflict_copies.length ? ' conflict copies ignored: ' + esc(s.conflict_copies.join(', ')) : ''}</div>
     ${s.last_error ? '<div class="row">Last error: ' + esc(s.last_error.at + ' ' + s.last_error.error) + '</div>' : ''}`;
  document.querySelector('#events tbody').innerHTML = s.recent_events.map(e =>
    `<tr><td>${esc(e.created_at.slice(0,19))}</td><td>${esc(e.kind)}</td><td>${esc(e.product_id)}</td><td>${esc(e.detail)}</td></tr>`).join('');
  document.getElementById('raw').textContent = JSON.stringify(s.last_result, null, 1);
}
function table(title, rows, cols){
  if (!rows || !rows.length) return '';
  return `<h3>${title} (${rows.length})</h3><table><tr>${cols.map(c=>'<th>'+c+'</th>').join('')}</tr>` +
    rows.map(r => '<tr>' + cols.map(c => '<td>' + esc(typeof r[c] === 'object' ? JSON.stringify(r[c]) : r[c]) + '</td>').join('') + '</tr>').join('') + '</table>';
}
async function preview(){
  const r = await api('/api/v1/inventory/excel-sync', {method:'POST', body: JSON.stringify({dry_run: true})});
  const p = r.plan;
  document.getElementById('apply').disabled = !p || !!p.blocked;
  if (!p) { document.getElementById('plan').innerHTML = 'No external change to apply. Apply will export pending changes.'; document.getElementById('apply').disabled = false; return; }
  document.getElementById('plan').innerHTML = (p.blocked ? '<p class="state bad">BLOCKED: ' + esc(p.blocked) + '</p>' : '') +
    `<p>safe for auto-apply: <b>${r.safe_for_auto_apply}</b></p>` +
    table('Invalid rows (not applied)', p.invalid, ['row','product_id','message']) +
    table('Conflicts (DB kept unless stated)', p.conflicts, ['product_id','kind','base','db','excel','action']) +
    table('Stock changes', p.stock_changes, ['product_id','from','to','kind']) +
    table('Merged (both sides kept)', p.merges, ['product_id','base','db','excel','action']) +
    table('Metadata changes', p.meta_changes, ['product_id','fields']) +
    table('New products', p.creates, ['product_id','product_name','stock_qty']) +
    table('Warnings', p.warnings, ['product_id','kind']);
}
async function applyNow(){
  if (!confirm('Apply the valid rows to the database and export the current stock to Excel?')) return;
  const r = await api('/api/v1/inventory/excel-sync', {method:'POST', body: JSON.stringify({dry_run: false, confirmed: true})});
  alert('Result: ' + r.status + (r.plan && r.plan.invalid.length ? ' (' + r.plan.invalid.length + ' row(s) rejected)' : ''));
  document.getElementById('apply').disabled = true; refresh(); document.getElementById('plan').innerHTML = '';
}
async function resolveAct(action){
  if (action === 'apply_file_values') {
    const p = (await api('/api/v1/inventory/excel-sync/resolve', {method:'POST', body: JSON.stringify({action, dry_run: true})})).plan;
    document.getElementById('resolvePlan').innerHTML = table('File values that will be applied', p.stock_changes, ['product_id','from','to']) +
      table('Metadata', p.meta_changes, ['product_id','fields']) + table('New products', p.creates, ['product_id','product_name','stock_qty']) +
      table('Invalid rows (skipped)', p.invalid, ['row','product_id','message']);
    if (!confirm('Apply the file values shown above as stock adjustments? Uses recorded after this file was saved may be overwritten.')) return;
  } else if (!confirm('Back up the current file and replace it with the database values? Edits in the file are dropped.')) return;
  const r = await api('/api/v1/inventory/excel-sync/resolve', {method:'POST', body: JSON.stringify({action, confirmed: true})});
  alert('Result: ' + r.status + (r.backup ? ' (backup: ' + r.backup + ')' : ''));
  document.getElementById('resolvePlan').innerHTML = ''; refresh();
}
if (token) refresh();
</script></body></html>"""


@router.get("/admin/inventory-sync", response_class=HTMLResponse, include_in_schema=False)
def inventory_sync_page():
    return HTMLResponse(SYNC_HTML, headers={"Cache-Control": "no-store"})
