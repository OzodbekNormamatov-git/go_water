export function fmtMoney(value, currency = "so'm") {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${Math.round(n).toLocaleString("ru-RU").replace(/,/g, " ")} ${currency}`;
}

export function fmtCount(value) {
  return Number(value || 0).toLocaleString("ru-RU").replace(/,/g, " ");
}

export function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("uz-UZ", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function statusPill(code, label) {
  const key = (code || "").toLowerCase();
  return `<span class="pill pill--${key}">${escapeHtml(label || code)}</span>`;
}

// Telefon +998-normalizatsiya — Service/phone.py bilan BIR XIL qoidalar
// (o'zgartirsangiz, ikkalasini ham yangilang; static/js/format.js'da nusxasi bor —
// ikki bundle alohida, cross-import yo'q):
//   '901234567' -> '+998901234567'; '998...' -> '+998...'; noto'g'ri -> null.
export function normalizePhone(raw) {
  const s = String(raw ?? "").trim().replace(/[\s\-().]/g, "");
  if (!s) return null;
  const hadPlus = s.startsWith("+");
  const digits = s.replace(/\D/g, "");
  if (!digits) return null;
  if (digits.length === 9 && !hadPlus) return "+998" + digits;
  if (digits.length === 12 && digits.startsWith("998")) return "+" + digits;
  if (digits.length === 13 && digits.startsWith("8998")) return "+" + digits.slice(1);
  if (hadPlus && /^\d{9,15}$/.test(digits)) return "+" + digits;
  return null;
}

// To'lov usuli belgilari — backend PaymentMethod bilan mos.
export const PAYMENT_LABELS = {
  cash: "💵 Naqd",
  card: "💳 Karta",
  deposit: "💰 Balansdan",
};
