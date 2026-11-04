<script def>
{
  "navigationBarTitleText": "Dual PoC",
  "description": "Home: choose Inventory or Meal Analysis. Shows whether a server is configured."
}
</script>

<script setup>
import wx from 'wx';
import { isServerConfigured, serverLabel } from '../../lib/api-client.js';
import { strings } from '../../lib/i18n.js';

export default {
  data: {
    t: {},
    mode: 'LOCAL',
    modeText: '',
    navError: '',
  },

  onLoad() {
    const server = isServerConfigured();
    const t = strings();
    this.setData({ t, mode: server ? 'SERVER' : 'LOCAL', modeText: server ? t.modeServer + ' ' + serverLabel() : t.modeLocal });
  },

  openInventory() {
    this.go('/pages/inventory/inventory');
  },

  openMeal() {
    this.go('/pages/meal/meal');
  },

  go(url) {
    this.setData({ navError: '' });
    wx.navigateTo({
      url,
      fail: (res) => this.setData({ navError: (res && res.errMsg) || 'navigate failed' }),
    });
  },
};
</script>

<page>
  <view class="screen">
    <text class="title">{{t.appTitle}}</text>
    <text class="mode">{{modeText}}</text>
    <text class="hint" ink:if="{{mode !== 'SERVER'}}">{{t.localHint}}</text>
    <view class="menu">
      <button class="item" bindtap="openInventory">{{t.inventory}}</button>
      <button class="item" bindtap="openMeal">{{t.meal}}</button>
    </view>
    <text class="error" ink:if="{{navError}}">! {{navError}}</text>
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
  gap: 8px;
}
.title {
  color: #40ff5e;
  font-size: 22px;
  line-height: 26px;
  font-weight: 500;
}
.mode {
  color: rgba(64, 255, 94, 0.72);
  font-family: monospace;
  font-size: 13px;
  line-height: 18px;
}
.hint {
  color: rgba(64, 255, 94, 0.48);
  font-size: 12px;
  line-height: 16px;
}
.menu {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}
.item {
  color: rgba(64, 255, 94, 0.72);
  font-size: 18px;
  line-height: 24px;
  padding: 10px 12px;
  border: 1px solid rgba(64, 255, 94, 0.48);
  border-radius: 6px;
  background-color: #000000;
}
.item:focus {
  color: #40ff5e;
  border: 2px solid #40ff5e;
  background-color: rgba(64, 255, 94, 0.12);
}
.error {
  color: #40ff5e;
  font-size: 12px;
  line-height: 16px;
}
</style>
