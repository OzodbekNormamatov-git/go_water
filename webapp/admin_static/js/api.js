// Admin API client — Telegram WebApp initData orqali auth (huddi user mini-app kabi).
// Har so'rovga `Authorization: tma <initData>` header qo'shiladi.

const tg = window.Telegram && window.Telegram.WebApp;
const initData = tg ? tg.initData : "";

const BASE = "";

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {
    "Authorization": `tma ${initData}`,
    "Accept": "application/json",
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
    throw new ApiError("network_error", "Tarmoq xatosi.");
  }

  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try { data = await res.json(); } catch { data = null; }
  }

  if (!res.ok) {
    const detail = (data && (data.detail || data.message || data.error)) || `HTTP ${res.status}`;
    const message = typeof detail === "string" ? detail : "Xatolik";
    if (res.status === 401) throw new ApiError("unauthorized", message);
    if (res.status === 403) throw new ApiError("forbidden", message);
    throw new ApiError(`http_${res.status}`, message);
  }
  return data;
}

export class ApiError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

export const api = {
  me:           () => request("/api/admin/auth/me"),
  stats:        () => request("/api/admin/stats"),

  // Moliyaviy hisobotlar (oylik / yillik)
  financeMonthly: (year, month) => {
    const q = new URLSearchParams();
    if (year)  q.set("year",  String(year));
    if (month) q.set("month", String(month));
    return request(`/api/admin/finance/monthly${q.toString() ? "?" + q : ""}`);
  },
  financeYearly: (year) => {
    const q = new URLSearchParams();
    if (year) q.set("year", String(year));
    return request(`/api/admin/finance/yearly${q.toString() ? "?" + q : ""}`);
  },

  // Mijozlar faolligi + pik vaqtlar
  activity: (days = 30) => request(`/api/admin/activity?days=${days}`),

  // Tizim sozlamalari (cashback toggle/percent)
  settings:          () => request("/api/admin/settings"),
  updateSettings:    (body) => request("/api/admin/settings", { method: "PATCH", body }),
  cashbackOverview:  () => request("/api/admin/settings/cashback"),
  // Avto-eslatma sozlamasi
  reminders:         () => request("/api/admin/settings/reminders"),
  updateReminders:   (body) => request("/api/admin/settings/reminders", { method: "PATCH", body }),

  // Broadcasts
  broadcasts:       ({ limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/broadcasts${sp.toString() ? "?" + sp : ""}`);
  },
  cancelBroadcast:  (id) => request(`/api/admin/broadcasts/${id}/cancel`, { method: "POST" }),
  // Broadcast yaratish: multipart/form-data (matn + ixtiyoriy rasm bitta xabar).
  createBroadcast:  async (formData) => {
    const headers = { "Authorization": `tma ${initData}` };
    // FormData uchun Content-Type'ni brauzer o'zi o'rnatadi (boundary bilan).
    let res;
    try {
      res = await fetch("/api/admin/broadcasts", { method: "POST", headers, body: formData });
    } catch (e) {
      throw new ApiError("network_error", "Tarmoq xatosi.");
    }
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
      throw new ApiError(`http_${res.status}`, typeof detail === "string" ? detail : "Xatolik");
    }
    return data;
  },

  orders: (params = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v != null && v !== "") q.set(k, String(v));
    }
    return request(`/api/admin/orders${q.toString() ? "?" + q : ""}`);
  },
  order:        (id) => request(`/api/admin/orders/${id}`),
  cancelOrder:  (id) => request(`/api/admin/orders/${id}/cancel`, { method: "POST" }),

  products:        ({ archived, limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (archived) sp.set("archived", "true");
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/products${sp.toString() ? "?" + sp : ""}`);
  },
  createProduct:   (body) => request("/api/admin/products", { method: "POST", body }),
  updateProduct:   (id, body) => request(`/api/admin/products/${id}`, { method: "PATCH", body }),
  deleteProduct:   (id) => request(`/api/admin/products/${id}`, { method: "DELETE" }),
  restoreProduct:  (id) => request(`/api/admin/products/${id}/restore`, { method: "POST" }),

  // Mahsulot rasmini yuklash — multipart/form-data, broadcast pattern bilan bir xil.
  uploadProductImage: async (id, file) => {
    const fd = new FormData();
    fd.append("photo", file);
    const headers = { "Authorization": `tma ${initData}` };
    let res;
    try {
      res = await fetch(`/api/admin/products/${id}/image`, { method: "POST", headers, body: fd });
    } catch (e) {
      throw new ApiError("network_error", "Tarmoq xatosi.");
    }
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || `HTTP ${res.status}`;
      throw new ApiError(`http_${res.status}`, typeof detail === "string" ? detail : "Xatolik");
    }
    return data;
  },
  deleteProductImage: (id) => request(`/api/admin/products/${id}/image`, { method: "DELETE" }),

  couriers:        ({ archived, limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (archived) sp.set("archived", "true");
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/couriers${sp.toString() ? "?" + sp : ""}`);
  },
  // Kuryer maydonlarini yangilash — phone_number va/yoki is_active.
  // body: { phone_number?: string|null, is_active?: boolean }
  updateCourier:   (id, body) => request(`/api/admin/couriers/${id}`, { method: "PATCH", body }),
  // Kuryerlarda jami naqd pul (admin nazorati)
  couriersCashSummary: () => request("/api/admin/couriers/cash-summary"),
  // Kuryer naqd topshirdi — qabul qilish. amount berilmasa hammasi.
  // body: { amount?: number }
  settleCourierCash: (id, amount) =>
    request(`/api/admin/couriers/${id}/settle-cash`, {
      method: "POST",
      body: amount != null ? { amount } : {},
    }),

  // Geocoding (manzil qidiruv + teskari) — operator xaritasi uchun
  geocode: (q, { lat, lon } = {}) => {
    const sp = new URLSearchParams({ q });
    if (lat != null) sp.set("lat", String(lat));
    if (lon != null) sp.set("lon", String(lon));
    return request(`/api/geocode?${sp}`);
  },
  reverseGeocode: (lat, lon) =>
    request(`/api/reverse-geocode?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`),

  // Operator endpointlari (admin OR operator kira oladi)
  // Ism yoki telefon (qisman) bo'yicha mijoz qidirish — bir nechta moslik.
  operatorCustomerSearch: (q, { limit } = {}) => {
    const sp = new URLSearchParams({ q });
    if (limit != null) sp.set("limit", String(limit));
    return request(`/api/admin/operator/customer-search?${sp}`);
  },
  operatorCreateOrder: (body) =>
    request("/api/admin/operator/orders", { method: "POST", body }),
  // Mijoz telefon raqamlari — operator ham ko'ra/qo'sha oladi (mijoz yangi
  // raqamdan qo'ng'iroq qilsa dublikat profil o'rniga shu ishlatiladi).
  // "Asosiy qilish"/"o'chirish" faqat admin (alohida endpoint) — bu yerda yo'q.
  customerPhones:    (id) => request(`/api/admin/customers/${id}/phones`),
  addCustomerPhone:  (id, body) =>
    request(`/api/admin/customers/${id}/phones`, { method: "POST", body }),
  // Mijozning oxirgi buyurtmalari — "takrorlash" uchun (items snapshot bilan).
  operatorRecentOrders: (customerId, { limit } = {}) => {
    const sp = new URLSearchParams();
    if (limit != null) sp.set("limit", String(limit));
    return request(`/api/admin/operator/customers/${customerId}/recent-orders${sp.toString() ? "?" + sp : ""}`);
  },

  customers: (q = "", { limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (q) sp.set("q", q);
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/customers${sp.toString() ? "?" + sp : ""}`);
  },
  // Yangi mijoz qo'shish (operator ham) — {full_name, phone}.
  // created=false bo'lsa telefon mavjud mijozniki edi (dublikat yaratilmadi).
  createCustomer: (body) => request("/api/admin/customers", { method: "POST", body }),
  adjustCashback: (id, body) => request(`/api/admin/customers/${id}/cashback`, { method: "POST", body }),
  adjustBottles:  (id, body) => request(`/api/admin/customers/${id}/bottles`, { method: "POST", body }),
  // Depozit (avans) balansi — MChJ mijozlar oldindan pul o'tkazganda admin
  // shu orqali kiritadi. body: { delta: number, reason: string }
  adjustDeposit:  (id, body) => request(`/api/admin/customers/${id}/deposit`, { method: "POST", body }),

  // Operatorlar — admin botga /start bosganlar. Faqat aktiv/noaktiv
  // boshqaruvi (arxivlash yo'q — ishdan ketgan operator noaktiv qilinadi).
  operators: ({ limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/operators${sp.toString() ? "?" + sp : ""}`);
  },
  // body: { is_active?: boolean, phone_number?: string }
  updateOperator:  (id, body) => request(`/api/admin/operators/${id}`, { method: "PATCH", body }),

  // Promouterlar — uyma-uy yuruvchi ishchilar (promokod egalari).
  // Operatorlardan farqli: bot/login yo'q, admin o'zi yaratadi. Arxivlash BOR
  // (ishdan ketgan ishchi) — qatori qoladi, tarixiy KPI ko'rinaveradi.
  promoters: ({ limit, offset, archived } = {}) => {
    const sp = new URLSearchParams();
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    if (archived) sp.set("include_archived", "true");
    return request(`/api/admin/promoters${sp.toString() ? "?" + sp : ""}`);
  },
  // body: { full_name, phone_number?, promo_code? } — kod bo'sh bo'lsa avto-generatsiya
  createPromoter:  (body) => request("/api/admin/promoters", { method: "POST", body }),
  // body: { full_name?, phone_number?, is_active? } — promo_code YO'Q (o'zgarmas)
  updatePromoter:  (id, body) => request(`/api/admin/promoters/${id}`, { method: "PATCH", body }),
  archivePromoter: (id) => request(`/api/admin/promoters/${id}`, { method: "DELETE" }),
  restorePromoter: (id) => request(`/api/admin/promoters/${id}/restore`, { method: "POST" }),
  promoterCustomers: (id, { limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return request(`/api/admin/promoters/${id}/customers${sp.toString() ? "?" + sp : ""}`);
  },
  promoterSettings:       () => request("/api/admin/settings/promoter"),
  updatePromoterSettings: (body) =>
    request("/api/admin/settings/promoter", { method: "PATCH", body }),
};

export const isTelegram = !!tg;
export const tgApp = tg;
