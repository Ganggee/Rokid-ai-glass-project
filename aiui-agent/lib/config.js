// Runtime configuration for the AIUI agent.
//
// Keep this file free of real secrets in Git. Fill API_BASE_URL / API_TOKEN locally
// with `python scripts/configure_agent.py --base-url https://... --token ...`
// (or edit in AIUI Studio's Code tab) before packaging the AIX.
//
// API_BASE_URL = ''  -> LOCAL DEMO mode: inventory persists in on-device wx storage
//                       (single device, not authoritative); meal analysis is disabled.
// API_BASE_URL set   -> SERVER mode: SQLite on the FastAPI server is the source of truth.
//                       Must be reachable from the glasses (traffic goes over Bluetooth
//                       through the Hi Rokid phone app) — use HTTPS, not localhost.
export const CONFIG = {
  API_BASE_URL: '',
  API_TOKEN: '',
  UI_LANG: 'ko', // 'ko' | 'en' — switch to 'en' if Korean glyphs do not render on the device
  SPEECH_LANG: '', // '' = host default. 'ko-KR' support is NOT VERIFIED on RV101.
  REQUEST_TIMEOUT_MS: 15000,
  UPLOAD_TIMEOUT_MS: 45000,
  UPLOAD_MODE: 'auto', // 'auto' | 'multipart' | 'base64'
};
