// Minimal JSON/HTTPS client over the documented global fetch().
// Every call resolves to { ok, status, data, error } — never throws — so pages
// can render loading / success / failure states deterministically.
//
// error.kind: 'NOT_CONFIGURED' | 'NETWORK' | 'TIMEOUT' | 'HTTP' | 'BAD_RESPONSE'
import wx from 'wx';
import { CONFIG } from './config.js';

export function isServerConfigured() {
  return Boolean(CONFIG.API_BASE_URL && CONFIG.API_TOKEN);
}

export function serverLabel() {
  if (!CONFIG.API_BASE_URL) return '';
  try {
    return new URL(CONFIG.API_BASE_URL).host;
  } catch (error) {
    return CONFIG.API_BASE_URL;
  }
}

function joinUrl(path) {
  return CONFIG.API_BASE_URL.replace(/\/+$/, '') + path;
}

function withTimeout(promise, ms, onTimeout) {
  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => {
      if (onTimeout) onTimeout();
      resolve({ __timeout: true });
    }, ms);
  });
  return Promise.race([promise, timeout]).then((value) => {
    clearTimeout(timer);
    return value;
  }, (error) => {
    clearTimeout(timer);
    throw error;
  });
}

export async function request(path, options) {
  const opts = options || {};
  if (!isServerConfigured()) {
    return { ok: false, status: 0, data: null, error: { kind: 'NOT_CONFIGURED', message: 'API_BASE_URL/API_TOKEN not set' } };
  }
  const headers = { Authorization: 'Bearer ' + CONFIG.API_TOKEN, Accept: 'application/json' };
  let body;
  if (opts.formData) {
    body = opts.formData; // let the runtime set the multipart boundary
  } else if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.json);
  }
  let controller = null;
  try {
    controller = typeof AbortController === 'function' ? new AbortController() : null;
  } catch (error) {
    controller = null;
  }
  const init = { method: opts.method || 'GET', headers };
  if (body !== undefined) init.body = body;
  if (controller) init.signal = controller.signal;
  let response;
  try {
    response = await withTimeout(fetch(joinUrl(path), init), opts.timeoutMs || CONFIG.REQUEST_TIMEOUT_MS,
      () => { if (controller) controller.abort(); });
  } catch (error) {
    return { ok: false, status: 0, data: null, error: { kind: 'NETWORK', message: String((error && error.message) || error) } };
  }
  if (response && response.__timeout) {
    return { ok: false, status: 0, data: null, error: { kind: 'TIMEOUT', message: 'Request timed out' } };
  }
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    return { ok: false, status: response.status, data: null, error: { kind: 'BAD_RESPONSE', message: 'Response is not JSON' } };
  }
  if (!response.ok) {
    const err = (data && data.error) || {};
    return { ok: false, status: response.status, data, error: { kind: 'HTTP', code: err.code || 'HTTP_' + response.status, message: err.message || 'Request failed' } };
  }
  return { ok: true, status: response.status, data, error: null };
}

// Upload one encoded photo ({ data: ArrayBuffer, mimeType }) from CameraContext.takePhoto().
export async function uploadImage(path, photo, filename) {
  const mimeType = photo.mimeType || 'image/jpeg';
  const canMultipart = typeof FormData === 'function' && typeof Blob === 'function';
  const mode = CONFIG.UPLOAD_MODE === 'auto' ? (canMultipart ? 'multipart' : 'base64') : CONFIG.UPLOAD_MODE;
  if (mode === 'multipart') {
    const form = new FormData();
    form.append('file', new Blob([photo.data], { type: mimeType }), filename || 'photo');
    return request(path, { method: 'POST', formData: form, timeoutMs: CONFIG.UPLOAD_TIMEOUT_MS });
  }
  // base64 JSON fallback using the documented wx.arrayBufferToBase64
  const b64 = wx.arrayBufferToBase64(photo.data);
  return request(path, { method: 'POST', json: { image_base64: b64, mime_type: mimeType }, timeoutMs: CONFIG.UPLOAD_TIMEOUT_MS });
}

export function describeError(result, t) {
  const e = (result && result.error) || {};
  if (e.kind === 'NOT_CONFIGURED') return t.errNotConfigured;
  if (e.kind === 'TIMEOUT') return t.errTimeout;
  if (e.kind === 'NETWORK') return t.errNetwork;
  if (e.code === 'INSUFFICIENT_STOCK') return t.errInsufficient;
  if (e.code === 'UNAUTHORIZED') return t.errAuth;
  return (e.code ? e.code + ': ' : '') + (e.message || t.errUnknown);
}
