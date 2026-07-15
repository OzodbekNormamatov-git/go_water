// Mahalliy state — savatcha (localStorage) + foydalanuvchi cache (observable).

const CART_KEY = "delivery_bot_cart_v1";

function readCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed;
  } catch (_) {}
  return {};
}

function writeCart(cart) {
  try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch (_) {}
}

class Cart {
  constructor() {
    this._items = readCart(); // { food_id: qty }  — optimistik mahalliy cache
    this._listeners = new Set();
    this._syncFn = null;       // server'ga sinxronlash funktsiyasi (api.setCartItem)
  }

  /** API client'ni keyinroq inject qilamiz — bu fayl api.js'ga bog'liq emas. */
  bindSync(syncFn, clearFn) {
    this._syncFn = syncFn;
    this._clearFn = clearFn;
  }

  /** Server'dan kelgan view bilan mahalliy cache'ni almashtiramiz (bootstrap'da). */
  hydrateFromServer(serverView) {
    if (!serverView || !Array.isArray(serverView.items)) return;
    const next = {};
    for (const it of serverView.items) {
      next[String(it.food_id)] = it.quantity;
    }
    this._items = next;
    writeCart(this._items);
    this._emit();
  }

  subscribe(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }
  _emit() { for (const fn of this._listeners) try { fn(this); } catch (_) {} }

  set(foodId, qty) {
    const id = String(foodId);
    const finalQty = (!qty || qty <= 0) ? 0 : Math.min(999, Math.floor(qty));
    if (finalQty === 0) delete this._items[id];
    else this._items[id] = finalQty;
    writeCart(this._items);
    this._emit();
    // Server bilan sinxron (fire-and-forget — UI bloklamaymiz).
    if (this._syncFn) {
      this._syncFn(Number(foodId), finalQty).catch(() => {
        // Server xato bersa, mahalliy UI ishlayveradi; keyingi reload'da fix qiladi.
      });
    }
  }

  inc(foodId, by = 1) { this.set(String(foodId), (this._items[String(foodId)] || 0) + by); }
  dec(foodId, by = 1) { this.set(String(foodId), (this._items[String(foodId)] || 0) - by); }
  remove(foodId) { this.set(foodId, 0); }
  clear() {
    this._items = {};
    writeCart(this._items);
    this._emit();
    if (this._clearFn) this._clearFn().catch(() => {});
  }
  qty(foodId) { return this._items[String(foodId)] || 0; }
  totalCount() { return Object.values(this._items).reduce((a, b) => a + b, 0); }
  isEmpty() { return Object.keys(this._items).length === 0; }
  toApi() {
    return Object.entries(this._items)
      .filter(([_, q]) => q > 0)
      .map(([id, q]) => ({ food_id: Number(id), quantity: q }));
  }
  asObject() { return { ...this._items }; }
}

export const cart = new Cart();


// ---------------------- Foydalanuvchi sessiyasi (observable) ----------------------

class Session {
  constructor() {
    this._me = null;
    this._listeners = new Set();
  }
  get me() { return this._me; }
  set(me) {
    this._me = me;
    for (const fn of this._listeners) try { fn(this._me); } catch (_) {}
  }
  update(patch) {
    this._me = { ...(this._me || {}), ...patch };
    for (const fn of this._listeners) try { fn(this._me); } catch (_) {}
  }
  subscribe(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }
}

export const session = new Session();


// ---------------------- Idempotency key generator ----------------------

let _pendingOrderKey = null;

/**
 * Hozir checkout submit qilinmoqchi bo'lgan savatcha uchun barqaror UUID qaytaradi.
 * Network timeout/retry bo'lsa, bir xil key qayta yuboriladi — backend duplikat order yaratmaydi.
 * Yangi savatcha ochilganda `rotateOrderKey()` chaqirilsin.
 */
export function ensureOrderKey() {
  if (!_pendingOrderKey) {
    _pendingOrderKey = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (
      Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
    );
  }
  return _pendingOrderKey;
}

export function rotateOrderKey() { _pendingOrderKey = null; }
