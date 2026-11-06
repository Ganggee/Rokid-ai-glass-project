<script def>
{
  "navigationBarTitleText": "Meal Diary",
  "description": "Voice meal diary: say a date and a meal to record what was eaten (confirmed before saving), or to view or hear the log of a date. Nutrition values are estimates from public reference data."
}
</script>

<script setup>
import { describeError, isServerConfigured } from '../../lib/api-client.js';
import { CONFIG } from '../../lib/config.js';
import { recognizeOnce, speakText, speechAvailable } from '../../lib/device.js';
import { dateLabel, diaryClient, itemLine, shiftDate } from '../../lib/diary-client.js';
import { strings } from '../../lib/i18n.js';
import { newIdempotencyKey } from '../../lib/ids.js';

export default {
  data: {
    t: {},
    view: 'home', // home | confirm | ask | view | busy | noserver
    heading: '',
    lines: [],
    items: [],
    question: '',
    message: '',
    busyText: '',
    lastHeard: '',
  },

  onLoad() {
    this.pending = null;
    this.summaryData = null;
    this.busy = false;
    this.setData({ t: strings() });
  },

  onShow() {
    if (!isServerConfigured()) this.setData({ view: 'noserver' });
  },

  onKeyUp(event) {
    if (event && event.code === 'Backspace' && this.data.view !== 'home') {
      if (event.preventDefault) event.preventDefault();
      if (this.data.view === 'confirm') this.cancelLog(); else this.goHome();
    }
  },

  goHome() {
    if (this.busy) return;
    this.setData({ view: 'home', lines: [], items: [], question: '' });
  },

  // ---------------------------------------------------------------- voice
  async voice() {
    const { t } = this.data;
    if (this.busy) return;
    if (!speechAvailable()) { this.setData({ message: t.noSpeech }); return; }
    this.setData({ busyText: t.listening, message: '' });
    let text = '';
    try {
      text = await recognizeOnce(CONFIG.SPEECH_LANG, 10000);
    } catch (error) {
      this.setData({ busyText: '', message: t.noSpeech + ' (' + String(error && error.message) + ')' });
      return;
    }
    this.setData({ busyText: '', lastHeard: text });
    return this.handleText(text);
  },

  // Also used for typed text (Simulator) and tests.
  async handleText(text) {
    const { t } = this.data;
    if (!text) { this.setData({ message: t.noSpeech }); return; }
    if (this.busy) return;
    const inConfirm = this.data.view === 'confirm';
    this.busy = true;
    const r = await diaryClient.parse(text);
    this.busy = false;
    if (!r.ok) { this.setData({ message: describeError(r, t) }); return; }
    const cmd = r.data;
    const heard = t.heard + ': ' + text;
    if (cmd.intent === 'confirm') { if (inConfirm) return this.saveLog(); this.setData({ message: heard }); return; }
    if (cmd.intent === 'cancel') { if (inConfirm) return this.cancelLog(); return this.goHome(); }
    if (cmd.questions && cmd.questions.length) {
      this.setData({ view: 'ask', question: cmd.questions[0], message: heard });
      return;
    }
    if (cmd.intent === 'record') {
      // date was fixed by the server at parse time; it is sent back unchanged on save
      this.pending = { date: cmd.date, meal_type: cmd.meal_type, items: cmd.items, utterance: text,
        key: newIdempotencyKey('diary'), choice: cmd.items.map(() => 0) };
      this.renderPending();
      this.setData({ view: 'confirm', message: heard + (cmd.warnings && cmd.warnings.length ? ' / ' + cmd.warnings[0] : '') });
      return;
    }
    if (cmd.intent === 'view' || cmd.intent === 'read') {
      await this.loadSummary(cmd.date, cmd.meal_type, cmd.intent === 'read');
      return;
    }
    this.setData({ message: heard + ' / ' + t.unrecognized });
  },

  renderPending() {
    const { t } = this.data;
    const p = this.pending;
    const items = p.items.map((i, idx) => ({ id: String(idx), line: itemLine(i, t) + (i.candidates && i.candidates.length ? ' >' : '') }));
    this.setData({ heading: t.confirmLog + ' ' + dateLabel(p.date, p.meal_type, CONFIG.UI_LANG), items });
  },

  // Cycle an unmatched item through the server's candidates (nutrition recomputed server-side on save).
  switchCandidate(event) {
    if (!this.pending) return;
    const ds = (event && event.currentTarget && event.currentTarget.dataset) || (event && event.target && event.target.dataset) || {};
    const idx = event && typeof event.index === 'number' ? event.index : parseInt(ds.index, 10);
    const item = this.pending.items[idx];
    if (!item || !item.candidates || !item.candidates.length) return;
    const n = item.candidates.length + 1;
    this.pending.choice[idx] = (this.pending.choice[idx] + 1) % n;
    const c = this.pending.choice[idx];
    if (!item.original) item.original = { food_name: item.food_name, nutrition_ref_id: item.nutrition_ref_id };
    if (c === 0) Object.assign(item, item.original);
    else Object.assign(item, { food_name: item.candidates[c - 1].food_name, nutrition_ref_id: item.candidates[c - 1].id });
    item.kcal = null;
    item.grams = item.grams_basis === 'stated' ? item.grams : null;
    this.renderPending();
  },

  cancelLog() {
    if (this.busy) return;
    this.pending = null;
    this.setData({ view: 'home', items: [], message: this.data.t.cancelled });
  },

  async saveLog() {
    const { t } = this.data;
    if (this.busy || !this.pending || this.data.view !== 'confirm') return;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.saving });
    const r = await diaryClient.save(this.pending); // same key on retry -> server applies once
    this.busy = false;
    if (!r.ok) {
      this.setData({ view: 'confirm', busyText: '', message: describeError(r, t) });
      return;
    }
    const saved = this.pending;
    this.pending = null;
    this.setData({ message: t.saved + ': ' + dateLabel(saved.date, saved.meal_type, CONFIG.UI_LANG) });
    await this.loadSummary(saved.date, null, false);
  },

  // ---------------------------------------------------------------- view / read
  async loadSummary(date, mealType, readAloud) {
    const { t } = this.data;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.loading });
    const r = await diaryClient.summary(date, mealType);
    this.busy = false;
    if (!r.ok) { this.setData({ view: 'home', busyText: '', message: describeError(r, t) }); return; }
    this.summaryData = r.data;
    const lines = (r.data.display_lines || []).slice(0, 6).map((l, i) => ({ id: String(i), line: l }));
    const totals = r.data.totals && r.data.totals.kcal !== null && r.data.totals.kcal !== undefined
      ? Math.round(r.data.totals.kcal) + 'kcal' + (r.data.totals_complete ? '' : '+?') + ' ' + t.estimate : '';
    if (totals) lines.push({ id: 'total', line: totals + (r.data.has_demo ? ' [' + t.demo + ']' : '') });
    this.setData({ view: 'view', busyText: '', heading: dateLabel(r.data.date, r.data.meal_type, CONFIG.UI_LANG), lines });
    if (readAloud) this.readAloud();
  },

  readAloud() {
    const { t } = this.data;
    if (!this.summaryData) return;
    if (!speakText(this.summaryData.speech_text)) this.setData({ message: t.ttsUnavailable });
  },

  showToday() { return this.loadSummary(null, null, false); },

  showYesterday() {
    const base = this.summaryData ? this.summaryData.date : null;
    if (base) return this.loadSummary(shiftDate(base, -1), null, false);
    return this.handleText('어제 기록 보여줘');
  },

  prevDay() { if (this.summaryData) return this.loadSummary(shiftDate(this.summaryData.date, -1), null, false); },

  nextDay() { if (this.summaryData) return this.loadSummary(shiftDate(this.summaryData.date, 1), null, false); },
};
</script>

<page>
  <view class="screen">
    <view class="top">
      <text class="title">{{t.diary}}</text>
      <text class="mode">{{lastHeard}}</text>
    </view>

    <view class="body" ink:if="{{view === 'home'}}">
      <view class="actions">
        <button class="act primary" bindtap="voice">{{t.voiceLog}}</button>
        <button class="act" bindtap="showToday">{{t.today}}</button>
        <button class="act" bindtap="showYesterday">{{t.yesterday}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'confirm'}}">
      <text class="name">{{heading}}</text>
      <scroll-view class="list" scroll-y="true">
        <button ink:for="{{items}}" class="row" data-index="{{index}}" bindtap="switchCandidate">{{item.line}}</button>
      </scroll-view>
      <view class="actions">
        <button class="act primary" bindtap="saveLog">{{t.save}}</button>
        <button class="act" bindtap="cancelLog">{{t.cancel}}</button>
        <button class="act" bindtap="voice">{{t.voice}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'ask'}}">
      <text class="name">{{question}}</text>
      <view class="actions">
        <button class="act primary" bindtap="voice">{{t.voice}}</button>
        <button class="act" bindtap="goHome">{{t.back}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'view'}}">
      <text class="name">{{heading}}</text>
      <scroll-view class="list" scroll-y="true">
        <text ink:for="{{lines}}" class="line">{{item.line}}</text>
      </scroll-view>
      <view class="actions">
        <button class="act primary" bindtap="readAloud">{{t.readAloud}}</button>
        <button class="act" bindtap="prevDay">{{t.prevDay}}</button>
        <button class="act" bindtap="nextDay">{{t.nextDay}}</button>
        <button class="act" bindtap="voice">{{t.voice}}</button>
        <button class="act" bindtap="goHome">{{t.back}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'noserver'}}">
      <text class="name">{{t.needServer}}</text>
    </view>

    <view class="body" ink:else>
      <text class="name">{{busyText}}</text>
    </view>

    <text class="status" ink:if="{{busyText && view !== 'busy'}}">{{busyText}}</text>
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
  font-size: 11px;
  line-height: 14px;
}
.body {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 6px;
}
.name {
  color: #40ff5e;
  font-size: 17px;
  line-height: 22px;
  font-weight: 500;
}
.list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row {
  color: rgba(64, 255, 94, 0.72);
  font-size: 13px;
  line-height: 18px;
  padding: 4px 8px;
  border: 1px solid rgba(64, 255, 94, 0.24);
  border-radius: 4px;
  text-align: left;
}
.row:focus {
  color: #40ff5e;
  border: 2px solid #40ff5e;
  background-color: rgba(64, 255, 94, 0.12);
}
.line {
  color: rgba(64, 255, 94, 0.72);
  font-size: 13px;
  line-height: 18px;
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
.primary {
  border: 1px solid rgba(64, 255, 94, 0.72);
}
.status {
  color: #40ff5e;
  font-size: 13px;
  line-height: 18px;
}
</style>
