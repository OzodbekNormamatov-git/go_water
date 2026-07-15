// API client.
//   - Authorization: tma <initData> har so'rovga avtomatik
//   - X-Request-ID FE da generate, BE javobida qaytadi → console'ga
//   - GET so'rovlar `cache.js` orqali memoize (TTL `config.js` dan keladi)

import { initData } from "./telegram.js";
import { memoize, invalidate } from "./cache.js";
import { getConfig } from "./config.js";

const BASE = ""; // bir xil origin

function _rid() {
  // 8 belgili kalit — frontend log'da request topib olish uchun
  if (window.crypto && crypto.randomUUID) {
    return crypto.randomUUID().slice(0, 8);
  }
  return Math.random().toString(36).slice(2, 10);
}

async function request(path, { method = "GET", body, signal } = {}) {
  const rid = _rid();
  const headers = {
    "Authorization": `tma ${initData}`,
    "Accept": "application/json",
    "X-Request-ID": rid,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method, headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    throw new ApiError("network_error", "Tarmoq xatosi. Internet aloqasini tekshiring.", rid);
  }

  // BE qaytargan request_id'ni ustun bilamiz (auth/limiter tarafdan tug'ilgan bo'lishi mumkin).
  const serverRid = res.headers.get("X-Request-ID") || rid;

  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try { data = await res.json(); } catch { data = null; }
  }

  if (!res.ok) {
    const detail = (data && (data.detail || data.message || data.error)) || `HTTP ${res.status}`;
    const message = typeof detail === "string" ? detail : "Xatolik yuz berdi.";
    if (res.status >= 500) {
      console.error(`[${serverRid}] ${method} ${path} -> ${res.status}: ${message}`);
    }
    throw new ApiError(`http_${res.status}`, message, serverRid);
  }
  return data;
}

export class ApiError extends Error {
  constructor(code, message, requestId) {
    super(message);
    this.code = code;
    this.requestId = requestId;
  }
}

const _ttl = (key) => (getConfig().cache_ttl_ms || {})[key] || 60_000;

export const api = {
  config:    () => memoize("config", () => request("/api/config"), _ttl("config")),
  me:        () => memoize("me",     () => request("/api/me"),      _ttl("me")),
  balance:   () => request("/api/me/balance"),  // har gal fresh — checkout uchun

  register: async (full_name, phone_number) => {
    const r = await request("/api/me/register", { method: "POST", body: { full_name, phone_number } });
    invalidate("me");
    return r;
  },

  products:  () => memoize("products",          () => request("/api/products"),          _ttl("products")),
  product:   (id) => memoize(`product:${id}`,   () => request(`/api/products/${id}`),    _ttl("product")),

  myOrders:  ({ limit, offset } = {}) => {
    const q = new URLSearchParams();
    if (limit  != null) q.set("limit",  String(limit));
    if (offset != null) q.set("offset", String(offset));
    const path = `/api/orders${q.toString() ? "?" + q : ""}`;
    // Birinchi (offset=0) sahifa kesh'lanadi; load-more sahifalari yo'q (har gal fresh).
    const isFirst = !offset;
    return isFirst
      ? memoize("orders", () => request(path), _ttl("orders"))
      : request(path);
  },
  order:     (id) => memoize(`order:${id}`,     () => request(`/api/orders/${id}`),      _ttl("order")),

  createOrder: async (payload) => {
    const r = await request("/api/orders", { method: "POST", body: payload });
    invalidate("orders");
    invalidate("cart");
    invalidate("me");
    invalidate("addresses");
    return r;
  },

  // ----- Geocoding (manzil qidiruv + teskari) -----
  geocode: (q, { lat, lon } = {}) => {
    const sp = new URLSearchParams({ q });
    if (lat != null) sp.set("lat", String(lat));
    if (lon != null) sp.set("lon", String(lon));
    return request(`/api/geocode?${sp}`);
  },
  reverseGeocode: (lat, lon) =>
    request(`/api/reverse-geocode?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`),

  cart:        () => request("/api/cart"),  // sync — har gal fresh
  setCartItem: async (food_id, quantity) => {
    const r = await request("/api/cart/items", { method: "POST", body: { food_id, quantity } });
    return r;
  },
  clearCart:   () => request("/api/cart", { method: "DELETE" }),

  // ----- Address book -----
  addresses:        () => memoize("addresses",   () => request("/api/me/addresses"), 60_000),
  createAddress:    async (body) => {
    const r = await request("/api/me/addresses", { method: "POST", body });
    invalidate("addresses");
    return r;
  },
  updateAddress:    async (id, body) => {
    const r = await request(`/api/me/addresses/${id}`, { method: "PATCH", body });
    invalidate("addresses");
    return r;
  },
  setDefaultAddress: async (id) => {
    const r = await request(`/api/me/addresses/${id}/default`, { method: "POST" });
    invalidate("addresses");
    return r;
  },
  deleteAddress:    async (id) => {
    const r = await request(`/api/me/addresses/${id}`, { method: "DELETE" });
    invalidate("addresses");
    return r;
  },
};

export { invalidate as invalidateCache };
