// Camera, on-device barcode detection and speech, using only documented AIUI APIs:
//   wx.media.createCameraContext().takePhoto(options) -> Promise<{ data: ArrayBuffer, mimeType }>
//   BarcodeDetector (global) .detect(Blob)
//   SpeechRecognition (global) start()/stop() with result/error/end events
// takePhoto() and SpeechRecognition.start() require an interactive call site, so
// call these directly from a tap/key handler.
import wx from 'wx';

export function cameraAvailable() {
  try {
    return Boolean(wx.media && typeof wx.media.createCameraContext === 'function');
  } catch (error) {
    return false;
  }
}

// mode: 'wide' (codes, 2016x2688), 'telephoto' (objects/text, 2016x1512), 'default'
export async function capturePhoto(mode) {
  if (!cameraAvailable()) throw new Error('CAMERA_UNAVAILABLE');
  const camera = wx.media.createCameraContext();
  if (!camera) throw new Error('CAMERA_UNAVAILABLE');
  const photo = await camera.takePhoto({ quality: 'high', mode: mode || 'default', enableSystemPreview: true });
  if (!photo || !photo.data) throw new Error('CAMERA_NO_DATA');
  return { data: photo.data, mimeType: photo.mimeType || 'image/jpeg' };
}

// Returns an array of raw strings, or null when on-device detection is unavailable
// (caller then uploads the photo to the server decoder).
export async function detectCodesOnDevice(photo) {
  if (typeof BarcodeDetector !== 'function' || typeof Blob !== 'function') return null;
  try {
    const detector = new BarcodeDetector();
    const results = await detector.detect(new Blob([photo.data], { type: photo.mimeType }));
    return (results || []).map((r) => String(r.rawValue || '').trim()).filter(Boolean);
  } catch (error) {
    return null; // e.g. WebP/Blob unsupported on this runtime version
  }
}

export function speechAvailable() {
  return typeof SpeechRecognition === 'function';
}

// One-shot recognition. Resolves the transcript ('' on no match); rejects on error.
export function recognizeOnce(lang, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (!speechAvailable()) { reject(new Error('SPEECH_UNAVAILABLE')); return; }
    let done = false;
    const rec = new SpeechRecognition();
    if (lang) rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    const finish = (fn, value) => { if (!done) { done = true; clearTimeout(timer); fn(value); } };
    const timer = setTimeout(() => { try { rec.abort(); } catch (e) { /* ignore */ } finish(reject, new Error('SPEECH_TIMEOUT')); }, timeoutMs || 10000);
    rec.onresult = (event) => {
      let text = '';
      try {
        const results = event.results;
        const last = results[results.length - 1];
        text = String((last && last[0] && last[0].transcript) || '');
      } catch (e) { text = ''; }
      finish(resolve, text.trim());
    };
    rec.onnomatch = () => finish(resolve, '');
    rec.onerror = (event) => finish(reject, new Error('SPEECH_ERROR:' + ((event && event.error) || 'unknown')));
    rec.onend = () => finish(resolve, '');
    rec.start();
  });
}

// Text-to-speech via the documented shared player: speechSynthesis.speak(utterance, 'enqueue').
// Korean output is NOT VERIFIED (utterance.lang is documented as unsupported). Returns false when
// TTS is unavailable so the page keeps the HUD text as the primary output.
export function speakText(text) {
  if (typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance !== 'function' || !text) return false;
  try {
    speechSynthesis.speak(new SpeechSynthesisUtterance(String(text)), 'enqueue');
    return true;
  } catch (error) {
    return false;
  }
}
