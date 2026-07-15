// Server-driven configuration — /api/config dan keladi.
// TTL'lar, currency, brand va status katalogi shu yerda.

let _config = null;

const DEFAULTS = {
  brand_name: "Delivery",
  currency_symbol: "so'm",
  locale: "uz",
  cache_ttl_ms: {
    me:       300_000,
    products: 120_000,
    product:  120_000,
    orders:    15_000,
    order:     10_000,
    config:   600_000,
  },
  max_quantity_per_item: 999,
  max_items_per_order: 50,
  max_note_length: 500,
  statuses: [],
};

export function setConfig(cfg) {
  _config = { ...DEFAULTS, ...cfg };
  // Status katalogini token bilan tezkor lookup uchun map'ga aylantiramiz.
  _config.status_by_code = {};
  for (const s of (cfg && cfg.statuses) || []) {
    _config.status_by_code[s.code] = s;
  }
}

export function getConfig() {
  return _config || DEFAULTS;
}

export function statusOf(code) {
  const cfg = getConfig();
  return (cfg.status_by_code && cfg.status_by_code[code]) || {
    code, token: (code || "").toLowerCase(), label: code, emoji: "",
    is_active: false, is_terminal: false,
  };
}
