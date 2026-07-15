// Narx formati: 22000 -> "22 000 so'm" (tiyinlarsiz, 1000 ajratilgan).

export function fmtMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const rounded = Math.round(n);
  return `${rounded.toLocaleString("ru-RU").replace(/,/g, " ")} so'm`;
}

export function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("uz-UZ", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (s) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[s]));
}

// Butun son: 1234 -> "1 234". Tilim — narx emas, faqat soni.
export function fmtCount(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return Math.round(n).toLocaleString("ru-RU").replace(/,/g, " ");
}

// Telefon +998-normalizatsiya — Service/phone.py bilan BIR XIL qoidalar
// (o'zgartirsangiz, ikkalasini ham yangilang):
//   '901234567'        -> '+998901234567'  (9 raqam — O'zbekiston lokal)
//   '998901234567'     -> '+998901234567'  (998 + 9 raqam)
//   '8998901234567'    -> '+998901234567'  (eski 8-prefiks)
//   '+998 90 123-45-67'-> '+998901234567'  (ajratkichlar tozalanadi)
//   tushunarsiz format -> null (server ham rad etadi — UI xabar ko'rsatadi)
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

// Manzil yorlig'i ("Uy", "Ishxona", ...) uchun emoji ikona.
export function iconFor(label) {
  const l = (label || "").toLowerCase();
  if (l.includes("uy") || l.includes("home")) return "🏠";
  if (l.includes("ish") || l.includes("work") || l.includes("ofis") || l.includes("office")) return "💼";
  if (l.includes("dam") || l.includes("dacha")) return "🌳";
  return "📍";
}
