// Safe wrappers over the documented wx storage sync APIs.
// wx.setStorageSync / getStorageSync serialize through JSON and throw when
// storage is unavailable or the stored JSON is corrupt; callers get a result
// object instead of an exception so the UI can show a usable error state.
import wx from 'wx';

export function readJson(key, fallback) {
  try {
    const value = wx.getStorageSync(key);
    return value === undefined || value === null ? fallback : value;
  } catch (error) {
    return fallback;
  }
}

export function writeJson(key, value) {
  try {
    wx.setStorageSync(key, value);
    return { ok: true };
  } catch (error) {
    return { ok: false, error: String((error && error.message) || error) };
  }
}

export function remove(key) {
  try {
    wx.removeStorageSync(key);
    return { ok: true };
  } catch (error) {
    return { ok: false, error: String((error && error.message) || error) };
  }
}
