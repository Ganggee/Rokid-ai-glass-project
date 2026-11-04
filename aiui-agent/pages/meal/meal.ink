<script def>
{
  "navigationBarTitleText": "Meal Analysis",
  "description": "Before/after meal photos: start a meal, take a before photo, label detected food regions and optional serving grams, take an after photo, and show the estimated eaten share and, when grams are known, estimated nutrients. Results are estimates, not measurements."
}
</script>

<script setup>
import { describeError, isServerConfigured } from '../../lib/api-client.js';
import { CONFIG } from '../../lib/config.js';
import { capturePhoto } from '../../lib/device.js';
import { strings } from '../../lib/i18n.js';
import {
  GRAM_OPTIONS, foodLine, forgetSession, mealClient, positionText, recallSession, rememberSession,
} from '../../lib/meal-client.js';

export default {
  data: {
    t: {},
    view: 'start', // start | before | label | after | busy | result | noserver
    sessionShort: '',
    regions: [],
    message: '',
    busyText: '',
    resultLines: [],
    resultSummary: '',
    resultWarnings: [],
    isDemo: false,
    canAnalyze: false,
  },

  onLoad() {
    this.sid = null;
    this.busy = false;
    this.labelOptions = [];
    this.setData({ t: strings() });
  },

  onShow() {
    if (!isServerConfigured()) { this.setData({ view: 'noserver' }); return; }
    if (this.sid) return;
    const sid = recallSession();
    if (sid) return this.resume(sid);
  },

  onKeyUp(event) {
    if (event && event.code === 'Backspace' && this.data.view === 'label') {
      if (event.preventDefault) event.preventDefault();
      this.setData({ view: 'before' });
    }
  },

  // ---------------------------------------------------------------- session
  async startMeal() {
    const { t } = this.data;
    if (this.busy) return;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.loading, message: '' });
    const r = await mealClient.createSession();
    this.busy = false;
    if (!r.ok) { this.setData({ view: 'start', busyText: '', message: describeError(r, t) }); return; }
    this.sid = r.data.session_id;
    rememberSession(this.sid);
    this.setData({ view: 'before', busyText: '', sessionShort: this.sid.slice(0, 6), regions: [], resultLines: [] });
  },

  async resume(sid) {
    const { t } = this.data;
    const r = await mealClient.getSession(sid);
    if (!r.ok) { forgetSession(); this.setData({ view: 'start', message: r.status === 404 ? '' : describeError(r, t) }); return; }
    this.sid = sid;
    const s = r.data;
    this.setData({ sessionShort: sid.slice(0, 6) });
    if (s.status === 'created') { this.setData({ view: 'before' }); return; }
    if (s.status === 'before_captured') {
      const detected = (s.photos.before && s.photos.before.detected_regions) || [];
      this.buildRegions(detected, null);
      this.setData({ view: 'label' });
      return;
    }
    if (s.status === 'after_captured') { this.setData({ view: 'after', canAnalyze: true }); return; }
    const res = await mealClient.results(sid);
    if (res.ok) this.showResult(res.data); else this.setData({ view: 'after', canAnalyze: true });
  },

  restart() {
    forgetSession();
    this.sid = null;
    this.setData({ view: 'start', message: '', regions: [], resultLines: [], resultWarnings: [], canAnalyze: false });
  },

  // ---------------------------------------------------------------- photos
  async captureBefore() { return this.capture('before'); },

  async captureAfter() { return this.capture('after'); },

  async capture(kind) {
    const { t } = this.data;
    if (this.busy || !this.sid) return;
    this.busy = true;
    const backView = kind === 'before' ? 'before' : 'after';
    let photo;
    try {
      photo = await capturePhoto('telephoto'); // interactive call site: invoked from a tap
    } catch (error) {
      this.busy = false;
      this.setData({ view: backView, message: t.errCamera + ' (' + String(error && error.message) + ')' });
      return;
    }
    this.setData({ view: 'busy', busyText: t.uploading, message: '' });
    const r = await mealClient.uploadPhoto(this.sid, kind, photo);
    this.busy = false;
    if (!r.ok) { this.setData({ view: backView, busyText: '', message: describeError(r, t) }); return; }
    if (kind === 'before') {
      this.buildRegions(r.data.detected_regions || [], r.data.label_options || []);
      this.setData({ view: 'label', busyText: '' });
      return;
    }
    this.setData({ view: 'after', busyText: '', canAnalyze: true });
    return this.analyze();
  },

  // ---------------------------------------------------------------- labelling
  buildRegions(detected, labelOptions) {
    const { t } = this.data;
    if (labelOptions) this.labelOptions = [{ id: null, food_name: '-' }].concat(labelOptions);
    if (!this.labelOptions.length) this.labelOptions = [{ id: null, food_name: '-' }];
    const regions = detected.map((d) => ({
      id: d.id, region: d.region, labelIndex: 0, gramsIndex: 0,
      text: this.regionText(d.id, d.position, 0, 0),
      position: d.position,
    }));
    this.setData({ regions, message: regions.length ? '' : t.unrecognized });
  },

  regionText(id, position, labelIndex, gramsIndex) {
    const { t } = this.data;
    const label = this.labelOptions[labelIndex] ? this.labelOptions[labelIndex].food_name : '-';
    const g = GRAM_OPTIONS[gramsIndex];
    return id + ' ' + positionText(position, CONFIG.UI_LANG) + '  ' + t.label + ': ' + label + '  ' + t.grams + ': ' + (g ? g + 'g' : t.gramsNone);
  },

  _idx(event) {
    if (event && typeof event.index === 'number') return event.index;
    const ds = (event && event.currentTarget && event.currentTarget.dataset) || (event && event.target && event.target.dataset) || {};
    return parseInt(ds.index, 10);
  },

  _updateRegion(i, patch) {
    const regions = this.data.regions.slice();
    const r = Object.assign({}, regions[i], patch);
    r.text = this.regionText(r.id, r.position, r.labelIndex, r.gramsIndex);
    regions[i] = r;
    this.setData({ regions });
  },

  cycleLabel(event) {
    const i = this._idx(event);
    if (!(i >= 0) || !this.data.regions[i]) return;
    this._updateRegion(i, { labelIndex: (this.data.regions[i].labelIndex + 1) % this.labelOptions.length });
  },

  cycleGrams(event) {
    const i = this._idx(event);
    if (!(i >= 0) || !this.data.regions[i]) return;
    this._updateRegion(i, { gramsIndex: (this.data.regions[i].gramsIndex + 1) % GRAM_OPTIONS.length });
  },

  async saveItems() {
    const { t } = this.data;
    if (this.busy) return;
    const items = this.data.regions.filter((r) => r.labelIndex > 0).map((r) => {
      const opt = this.labelOptions[r.labelIndex];
      const item = { label: opt.food_name, nutrition_ref_id: opt.id, before_region: r.region };
      const g = GRAM_OPTIONS[r.gramsIndex];
      if (g) { item.initial_serving_grams = g; item.serving_source = 'user'; }
      return item;
    });
    if (!items.length) { this.setData({ view: 'after', message: t.skipLabels }); return; }
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.saving });
    const r = await mealClient.setItems(this.sid, items);
    this.busy = false;
    if (!r.ok) { this.setData({ view: 'label', busyText: '', message: describeError(r, t) }); return; }
    this.setData({ view: 'after', busyText: '', message: '' });
  },

  skipLabels() {
    this.setData({ view: 'after', message: this.data.t.skipLabels });
  },

  // ---------------------------------------------------------------- analysis
  async analyze() {
    const { t } = this.data;
    if (this.busy || !this.sid) return;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.analyzing });
    const r = await mealClient.analyze(this.sid, 'auto');
    this.busy = false;
    if (!r.ok) { this.setData({ view: 'after', busyText: '', canAnalyze: true, message: describeError(r, t) }); return; }
    this.showResult(r.data);
  },

  showResult(res) {
    const { t } = this.data;
    const lines = (res.foods || []).slice(0, 6).map((f, i) => ({ id: String(i), line: foodLine(f, t) }));
    let summary = t.estimate + ' · ' + res.confidence;
    if (res.totals && res.totals.kcal !== null && res.totals.kcal !== undefined) {
      summary += ' · ' + Math.round(res.totals.kcal) + 'kcal' + (res.totals_complete ? '' : '+?');
    }
    const warnings = (res.warnings || []).slice(0, 3).map((w, i) => ({ id: String(i), line: '! ' + String(w).slice(0, 60) }));
    this.setData({ view: 'result', busyText: '', resultLines: lines, resultSummary: summary, resultWarnings: warnings, isDemo: Boolean(res.is_demo) });
  },
};
</script>

<page>
  <view class="screen">
    <view class="top">
      <text class="title">{{t.meal}}</text>
      <text class="mode">{{sessionShort}}</text>
    </view>

    <view class="body" ink:if="{{view === 'start'}}">
      <view class="actions">
        <button class="act primary" bindtap="startMeal">{{t.newMeal}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'before'}}">
      <text class="name">{{t.before}}</text>
      <view class="actions">
        <button class="act primary" bindtap="captureBefore">{{t.before}}</button>
        <button class="act" bindtap="restart">{{t.restart}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'label'}}">
      <text class="label">{{t.regions}}</text>
      <scroll-view class="list" scroll-y="true">
        <view ink:for="{{regions}}" class="region">
          <text class="line">{{item.text}}</text>
          <view class="actions">
            <button class="act small" data-index="{{index}}" bindtap="cycleLabel">{{t.label}}</button>
            <button class="act small" data-index="{{index}}" bindtap="cycleGrams">{{t.grams}}</button>
          </view>
        </view>
      </scroll-view>
      <view class="actions">
        <button class="act primary" bindtap="saveItems">{{t.saveItems}}</button>
        <button class="act" bindtap="skipLabels">{{t.skipLabels}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'after'}}">
      <text class="name">{{t.after}}</text>
      <view class="actions">
        <button class="act primary" bindtap="captureAfter">{{t.after}}</button>
        <button class="act" ink:if="{{canAnalyze}}" bindtap="analyze">{{t.analyze}}</button>
        <button class="act" bindtap="restart">{{t.restart}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'result'}}">
      <text class="name">{{t.resultTitle}}</text>
      <text class="meta">{{resultSummary}}</text>
      <text class="badge" ink:if="{{isDemo}}">{{t.demo}}</text>
      <scroll-view class="list" scroll-y="true">
        <text ink:for="{{resultLines}}" class="line">{{item.line}}</text>
        <text ink:for="{{resultWarnings}}" class="warn">{{item.line}}</text>
      </scroll-view>
      <view class="actions">
        <button class="act" bindtap="analyze">{{t.analyze}}</button>
        <button class="act primary" bindtap="restart">{{t.newMeal}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'noserver'}}">
      <text class="name">{{t.needServer}}</text>
      <text class="meta">{{t.errNotConfigured}}</text>
    </view>

    <view class="body" ink:else>
      <text class="name">{{busyText}}</text>
    </view>

    <text class="status" ink:if="{{message}}">{{message}}</text>
  </view>
</page>

<style>
.screen {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 12px 16px;
  box-sizing: border-box;
  background-color: #000000;
  gap: 6px;
}
.top {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}
.title {
  color: #40ff5e;
  font-size: 16px;
  line-height: 20px;
  font-weight: 500;
}
.mode {
  color: rgba(64, 255, 94, 0.48);
  font-family: monospace;
  font-size: 11px;
  line-height: 14px;
}
.body {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 6px;
}
.label {
  color: rgba(64, 255, 94, 0.48);
  font-size: 12px;
  line-height: 16px;
}
.name {
  color: #40ff5e;
  font-size: 20px;
  line-height: 26px;
  font-weight: 500;
}
.meta {
  color: rgba(64, 255, 94, 0.72);
  font-family: monospace;
  font-size: 12px;
  line-height: 16px;
}
.badge {
  color: #40ff5e;
  font-size: 11px;
  line-height: 14px;
  letter-spacing: 0.08em;
  border: 1px solid #40ff5e;
  border-radius: 2px;
  padding: 0 4px;
}
.list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.region {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  border-bottom: 1px solid rgba(64, 255, 94, 0.24);
}
.line {
  color: rgba(64, 255, 94, 0.72);
  font-size: 13px;
  line-height: 18px;
}
.warn {
  color: rgba(64, 255, 94, 0.48);
  font-size: 11px;
  line-height: 15px;
}
.actions {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 6px;
}
.act {
  color: rgba(64, 255, 94, 0.72);
  font-size: 14px;
  line-height: 18px;
  padding: 6px 10px;
  border: 1px solid rgba(64, 255, 94, 0.48);
  border-radius: 4px;
}
.act:focus {
  color: #40ff5e;
  border: 2px solid #40ff5e;
  background-color: rgba(64, 255, 94, 0.12);
}
.small {
  font-size: 12px;
  line-height: 16px;
  padding: 3px 8px;
}
.primary {
  border: 1px solid rgba(64, 255, 94, 0.72);
}
.status {
  color: #40ff5e;
  font-size: 13px;
  line-height: 18px;
}
</style>
