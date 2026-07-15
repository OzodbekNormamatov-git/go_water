// Yengil in-memory cache (TTL bilan) + in-flight dedupe.
// Tab almashtirgan/orqaga qaytgan navigatsiyalarda yagona joydan instant javob beradi.

const _cache = new Map();   // key -> { value, expires }
const _inflight = new Map(); // key -> Promise (parallel chaqiruvlarni birlashtirish uchun)

const now = () => Date.now();

/** Cache'dan oling; muddati o'tgan bo'lsa null. */
export function get(key) {
  const e = _cache.get(key);
  if (!e) return null;
  if (e.expires < now()) {
    _cache.delete(key);
    return null;
  }
  return e.value;
}

/** Cache'ga yozish. */
export function set(key, value, ttlMs) {
  _cache.set(key, { value, expires: now() + ttlMs });
}

/** Prefix bo'yicha o'chirish (mutation'lardan keyin). */
export function invalidate(prefix) {
  for (const k of [..._cache.keys()]) {
    if (k === prefix || k.startsWith(prefix + ":")) _cache.delete(k);
  }
}

/**
 * Memoize: cache bo'lsa qaytaradi; bo'lmasa fn() chaqiradi va saqlaydi.
 * Parallel bir xil so'rovlarni avtomatik dedupe qiladi (one-flight).
 */
export async function memoize(key, fn, ttlMs) {
  const cached = get(key);
  if (cached !== null) return cached;
  const existing = _inflight.get(key);
  if (existing) return existing;
  const p = (async () => {
    try {
      const value = await fn();
      set(key, value, ttlMs);
      return value;
    } finally {
      _inflight.delete(key);
    }
  })();
  _inflight.set(key, p);
  return p;
}
