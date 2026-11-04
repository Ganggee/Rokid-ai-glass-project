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
