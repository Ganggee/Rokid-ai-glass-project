// Idempotency keys. AIUI documents crypto.randomUUID(); fall back when absent.
export function newIdempotencyKey(prefix) {
  let core = '';
  try {
    if (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function') {
      core = crypto.randomUUID();
    }
  } catch (error) {
    core = '';
  }
  if (!core) {
    core = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12) + Math.random().toString(36).slice(2, 8);
  }
  return (prefix || 'aiui') + '-' + core;
}
