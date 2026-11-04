<script def>
{
  "navigationBarTitleText": "Inventory",
  "description": "Find a product (list, QR/barcode photo, product photo, voice), show its stock and record use after an explicit confirmation. Stock persists on the server (SERVER mode) or in device storage (LOCAL DEMO mode)."
}
</script>

<script setup>
import { describeError, isServerConfigured, serverLabel, uploadImage } from '../../lib/api-client.js';
import { parseCommand } from '../../lib/command-parser.js';
import { capturePhoto, detectCodesOnDevice, recognizeOnce, speechAvailable } from '../../lib/device.js';
import { CONFIG } from '../../lib/config.js';
import { strings } from '../../lib/i18n.js';
import { newIdempotencyKey } from '../../lib/ids.js';
import {
  clearPending, confirmedUse, inventoryBackend, loadPending, reconcilePending,
} from '../../lib/inventory-client.js';

function shortTime(iso) {
  const s = String(iso || '');
  return s.length >= 16 ? s.slice(5, 16).replace('T', ' ') : s;
}

export default {
  data: {
    t: {},
    mode: 'LOCAL',
    modeText: '',
    view: 'list', // list | detail | confirm | busy | pending | candidates | history
    products: [],
    product: null,
    quantity: 1,
    message: '',
    busyText: '',
    candidates: [],
    history: [],
    pendingText: '',
    lastHeard: '',
  },

  onLoad() {
    const t = strings();
    this.backend = inventoryBackend();
    this.busy = false;
    this.pendingKey = '';
    const server = isServerConfigured();
    this.setData({ t, mode: this.backend.mode, modeText: server ? t.modeServer + ' ' + serverLabel() : t.modeLocal });
  },

  onShow() {
    return this.boot();
  },

  async boot() {
    await this.recoverPending();
    await this.loadProducts();
  },

  // ---------------------------------------------------------------- data loading
  async loadProducts() {
    const { t } = this.data;
    this.setData({ busyText: t.loading });
    const r = await this.backend.list();
    if (r.ok) {
      this.setData({ products: r.data.items, busyText: '' });
      if (this.data.product) {
        const fresh = r.data.items.find((p) => p.product_id === this.data.product.product_id);
        if (fresh) this.setData({ product: fresh });
      }
      return;
    }
    const cache = this.backend.cached ? this.backend.cached() : null;
    this.setData({
      busyText: '',
      products: cache ? cache.items : [],
      message: describeError(r, t) + (cache ? ' / ' + t.cached : ''),
    });
  },

  async recoverPending() {
    const { t } = this.data;
    if (!loadPending()) return;
    const result = await reconcilePending(this.backend);
    if (result.state === 'applied') {
      this.setData({ message: t.recovered + ': ' + result.product.product_name + ' ' + result.product.stock_qty + ' ' + result.product.unit });
    } else if (result.state === 'not_applied') {
      this.pendingKey = result.op.key;
      this.setData({ view: 'pending', quantity: result.op.quantity, pendingText: t.notApplied + ': ' + result.op.productId + ' x' + result.op.quantity,
        product: { product_id: result.op.productId, product_name: result.op.productId, stock_qty: '-', unit: '' } });
    } else if (result.state === 'unknown') {
      this.pendingKey = result.op.key;
      this.setData({ view: 'pending', pendingText: t.uncertain, message: describeError(result, t) });
    }
  },

  // ---------------------------------------------------------------- navigation
  selectProduct(event) {
    const id = (event && event.id) || (event && event.currentTarget && event.currentTarget.dataset && event.currentTarget.dataset.id)
      || (event && event.target && event.target.dataset && event.target.dataset.id);
    const product = this.data.products.find((p) => p.product_id === id) || this.data.candidates.find((p) => p.product_id === id);
    if (!product) return;
    this.showProduct(product);
  },

  async showProduct(product) {
    this.setData({ view: 'detail', product, message: '', candidates: [] });
    const r = await this.backend.get(product.product_id);
    if (r.ok) this.setData({ product: r.data });
  },

  goBack() {
    if (this.busy) return;
    this.setData({ view: 'list', message: '', candidates: [] });
    return this.loadProducts();
  },

  onKeyUp(event) {
    if (event && event.code === 'Backspace' && this.data.view !== 'list') {
      if (event.preventDefault) event.preventDefault();
      if (this.data.view === 'confirm') this.cancelUse(); else this.goBack();
    }
  },

  // ---------------------------------------------------------------- use flow
  askUse(quantity) {
    if (!this.data.product || this.busy) return;
    const q = typeof quantity === 'number' && quantity > 0 ? quantity : 1;
    this.pendingKey = newIdempotencyKey('use'); // one key per confirmation screen: double taps reuse it
    this.setData({ view: 'confirm', quantity: q, message: '' });
  },

  askUseOne() {
    this.askUse(1);
  },

  cancelUse() {
    if (this.busy) return;
    this.pendingKey = '';
    this.setData({ view: 'detail', message: this.data.t.cancelled });
  },

  async confirmUse() {
    const { t, product, quantity } = this.data;
    if (this.busy || !product || this.data.view !== 'confirm') return;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.saving });
    const r = await confirmedUse(this.backend, product.product_id, quantity, this.pendingKey);
    this.busy = false;
    if (r.ok) {
      const p = r.data.product;
      this.pendingKey = '';
      this.setData({ view: 'detail', product: p, busyText: '', message: t.done + ': ' + p.stock_qty + ' ' + p.unit + ' ' + t.remaining });
      await this.loadProducts();
      return;
    }
    if (r.uncertain) {
      this.setData({ view: 'pending', busyText: '', pendingText: t.uncertain, message: describeError(r, t) });
      return;
    }
    this.pendingKey = '';
    this.setData({ view: 'detail', busyText: '', message: (r.error && r.error.kind === 'STORAGE') ? t.errStorage : describeError(r, t) });
  },

  async checkPending() {
    const { t } = this.data;
    if (this.busy) return;
    this.busy = true;
    this.setData({ busyText: t.loading });
    const result = await reconcilePending(this.backend);
    this.busy = false;
    if (result.state === 'applied') {
      this.setData({ view: 'detail', product: result.product, busyText: '', message: t.recovered + ': ' + result.product.stock_qty + ' ' + result.product.unit });
    } else if (result.state === 'not_applied') {
      this.setData({ busyText: '', pendingText: t.notApplied });
    } else if (result.state === 'none') {
      this.setData({ view: 'list', busyText: '' });
    } else {
      this.setData({ busyText: '', message: describeError(result, t) });
    }
  },

  async retryPending() {
    const op = loadPending();
    if (!op || this.busy) return;
    this.pendingKey = op.key; // SAME key: the server applies it at most once
    this.setData({ view: 'confirm', quantity: op.quantity,
      product: this.data.products.find((p) => p.product_id === op.productId) || this.data.product });
  },

  discardPending() {
    clearPending();
    this.pendingKey = '';
    return this.goBack();
  },

  // ---------------------------------------------------------------- history
  async showHistory() {
    const { t, product } = this.data;
    this.setData({ view: 'history', busyText: t.loading, history: [] });
    const r = await this.backend.transactions(product ? product.product_id : null);
    if (!r.ok) {
      this.setData({ busyText: '', message: describeError(r, t) });
      return;
    }
    const history = r.data.items.slice(0, 8).map((x) => ({
      id: String(x.id),
      line: shortTime(x.created_at) + '  ' + x.product_id.slice(0, 14) + '  ' + (x.quantity_delta > 0 ? '+' : '') + x.quantity_delta + ' -> ' + x.stock_after,
    }));
    this.setData({ busyText: '', history });
  },

  // ---------------------------------------------------------------- QR / barcode
  async scanQr() {
    const { t } = this.data;
    if (this.busy) return;
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.scanQr + '...', message: '' });
    try {
      const photo = await capturePhoto('wide');
      const codes = await detectCodesOnDevice(photo);
      if (codes && codes.length) {
        for (const code of codes) {
          const r = await this.backend.resolveCode(code);
          if (r.ok && r.data.status === 'matched') { this.busy = false; return this.showProduct(r.data.product); }
        }
        this.busy = false;
        this.setData({ view: 'list', busyText: '', message: t.noCode + ': ' + codes[0] });
        return;
      }
      if (this.backend.mode === 'SERVER') {
        const r = await uploadImage('/api/v1/inventory/resolve-image', photo, 'qr');
        this.busy = false;
        return this.applyResolve(r);
      }
      this.busy = false;
      this.setData({ view: 'list', busyText: '', message: t.noCode });
    } catch (error) {
      this.busy = false;
      this.setData({ view: 'list', busyText: '', message: t.errCamera + ' (' + String(error && error.message) + ')' });
    }
  },

  // ---------------------------------------------------------------- product photo (OCR / candidates)
  async identifyByPhoto() {
    const { t } = this.data;
    if (this.busy) return;
    if (this.backend.mode !== 'SERVER') { this.setData({ message: t.needServer }); return; }
    this.busy = true;
    this.setData({ view: 'busy', busyText: t.photoId + '...', message: '' });
    try {
      const photo = await capturePhoto('telephoto');
      const r = await uploadImage('/api/v1/inventory/resolve-image', photo, 'product');
      this.busy = false;
      return this.applyResolve(r);
    } catch (error) {
      this.busy = false;
      this.setData({ view: 'list', busyText: '', message: t.errCamera + ' (' + String(error && error.message) + ')' });
    }
  },

  applyResolve(r) {
    const { t } = this.data;
    if (!r.ok) { this.setData({ view: 'list', busyText: '', message: describeError(r, t) }); return; }
    if (r.data.status === 'matched') return this.showProduct(r.data.product);
    if (r.data.status === 'candidates' && r.data.candidates.length) {
      this.setData({ view: 'candidates', busyText: '', candidates: r.data.candidates.map((c) => c.product), message: t.candidates });
      return;
    }
    this.setData({ view: 'list', busyText: '', message: t.unrecognized });
  },

  // ---------------------------------------------------------------- voice
  async voiceCommand() {
    const { t } = this.data;
    if (this.busy) return;
    if (!speechAvailable()) { this.setData({ message: t.noSpeech }); return; }
    const returnView = this.data.view;
    this.setData({ busyText: t.listening, message: '' });
    let text = '';
    try {
      text = await recognizeOnce(CONFIG.SPEECH_LANG, 10000);
    } catch (error) {
      this.setData({ busyText: '', message: t.noSpeech + ' (' + String(error && error.message) + ')' });
      return;
    }
    this.setData({ busyText: '', lastHeard: text });
    return this.handleCommandText(text, returnView);
  },

  // Also used for typed text in the Simulator and by tests.
  async handleCommandText(text, returnView) {
    const { t } = this.data;
    if (!text) { this.setData({ message: t.noSpeech }); return; }
    let cmd;
    if (this.backend.mode === 'SERVER' && this.backend.parseCommand) {
      const r = await this.backend.parseCommand(text);
      cmd = r.ok ? r.data : parseCommand(text, this.data.products);
    } else {
      cmd = parseCommand(text, this.data.products);
    }
    const view = returnView || this.data.view;
    if (cmd.intent === 'confirm') { if (view === 'confirm') return this.confirmUse(); this.setData({ message: t.heard + ': ' + text }); return; }
    if (cmd.intent === 'cancel') { if (view === 'confirm') return this.cancelUse(); return this.goBack(); }
    if (cmd.product && cmd.intent === 'use') {
      await this.showProduct(cmd.product);
      this.askUse(cmd.quantity || 1);
      this.setData({ message: t.heard + ': ' + text });
      return;
    }
    if (cmd.product) { await this.showProduct(cmd.product); this.setData({ message: t.heard + ': ' + text }); return; }
    this.setData({ message: t.heard + ': ' + text + ' / ' + t.unrecognized });
  },
};
</script>

<page>
  <view class="screen">
    <view class="top">
      <text class="title">{{t.inventory}}</text>
      <text class="mode">{{modeText}}</text>
    </view>

    <view class="body" ink:if="{{view === 'list'}}">
      <text class="label">{{t.products}}</text>
      <scroll-view class="list" scroll-y="true">
        <button ink:for="{{products}}" class="row" data-id="{{item.product_id}}" bindtap="selectProduct">{{item.product_name}} · {{item.stock_qty}} {{item.unit}}</button>
      </scroll-view>
      <view class="actions">
        <button class="act" bindtap="scanQr">{{t.scanQr}}</button>
        <button class="act" bindtap="identifyByPhoto">{{t.photoId}}</button>
        <button class="act" bindtap="voiceCommand">{{t.voice}}</button>
        <button class="act" bindtap="loadProducts">{{t.refresh}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'detail'}}">
      <text class="name">{{product.product_name}}</text>
      <text class="meta">{{product.product_id}} · LOT {{product.lot_no}}</text>
      <view class="stock">
        <text class="label">{{t.stock}}</text>
        <text class="qty">{{product.stock_qty}}</text>
        <text class="unit">{{product.unit}}</text>
      </view>
      <view class="actions">
        <button class="act primary" bindtap="askUseOne">{{t.useOne}}</button>
        <button class="act" bindtap="voiceCommand">{{t.voice}}</button>
        <button class="act" bindtap="showHistory">{{t.history}}</button>
        <button class="act" bindtap="goBack">{{t.back}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'confirm'}}">
      <text class="name">{{t.confirmQ}}</text>
      <text class="meta">{{product.product_name}} x {{quantity}} {{product.unit}}</text>
      <text class="meta">{{t.stock}} {{product.stock_qty}} {{product.unit}}</text>
      <view class="actions">
        <button class="act primary" bindtap="confirmUse">{{t.confirm}}</button>
        <button class="act" bindtap="cancelUse">{{t.cancel}}</button>
        <button class="act" bindtap="voiceCommand">{{t.voice}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'pending'}}">
      <text class="name">{{pendingText}}</text>
      <view class="actions">
        <button class="act primary" bindtap="checkPending">{{t.checkStatus}}</button>
        <button class="act" bindtap="retryPending">{{t.retry}}</button>
        <button class="act" bindtap="discardPending">{{t.back}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'candidates'}}">
      <scroll-view class="list" scroll-y="true">
        <button ink:for="{{candidates}}" class="row" data-id="{{item.product_id}}" bindtap="selectProduct">{{item.product_name}}</button>
      </scroll-view>
      <view class="actions">
        <button class="act" bindtap="goBack">{{t.back}}</button>
      </view>
    </view>

    <view class="body" ink:elif="{{view === 'history'}}">
      <scroll-view class="list" scroll-y="true">
        <text ink:for="{{history}}" class="line">{{item.line}}</text>
      </scroll-view>
      <view class="actions">
        <button class="act" bindtap="goBack">{{t.back}}</button>
      </view>
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
.list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row {
  color: rgba(64, 255, 94, 0.72);
  font-size: 15px;
  line-height: 20px;
  padding: 6px 10px;
  border: 1px solid rgba(64, 255, 94, 0.24);
  border-radius: 4px;
  text-align: left;
}
.row:focus {
  color: #40ff5e;
  border: 2px solid #40ff5e;
  background-color: rgba(64, 255, 94, 0.12);
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
  font-size: 13px;
  line-height: 18px;
}
.stock {
  display: flex;
  flex-direction: row;
  align-items: flex-end;
  gap: 8px;
}
.qty {
  color: #40ff5e;
  font-family: monospace;
  font-size: 44px;
  line-height: 48px;
  font-weight: 500;
}
.unit {
  color: rgba(64, 255, 94, 0.72);
  font-size: 16px;
  line-height: 24px;
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
.line {
  color: rgba(64, 255, 94, 0.72);
  font-family: monospace;
  font-size: 11px;
  line-height: 16px;
}
.status {
  color: #40ff5e;
  font-size: 13px;
  line-height: 18px;
}
</style>
