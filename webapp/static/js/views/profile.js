// Profil — har bosilganda /api/me yangilanadi (cashback/bottle freshness uchun).

import { api, ApiError, invalidateCache } from "../api.js";
import { session } from "../state.js";
import { escapeHtml, fmtMoney, fmtCount, normalizePhone } from "../format.js";
import {
  hapticImpact,
  hideBackButton,
  hideMainButton,
} from "../telegram.js";
import { toast } from "../toast.js";
import { go } from "../router.js";
import { showCTA, hideCTA, setCTALoading } from "../cta.js";

const ACTIVE_STATUSES = new Set(["NEW", "ACCEPTED", "DELIVERING", "ARRIVED"]);
const DONE_STATUSES = new Set(["DELIVERED"]);

function initials(name) {
  if (!name) return "👤";
  return name.trim().split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
}

function renderHero(me) {
  const fullName = me.full_name || me.tg_first_name || "—";
  const phone = me.phone_number || "—";
  const photo = me.tg_photo_url || null;
  const cashback = Number(me.cashback_balance || 0);
  const bottles = Number(me.bottles_balance || 0);
  const deposit = Number(me.deposit_balance || 0);

  return `
    <div class="profile-hero">
      <div class="avatar">${photo ? `<img src="${escapeHtml(photo)}" alt="" />` : escapeHtml(initials(fullName))}</div>
      <div class="profile-hero__name">${escapeHtml(fullName)}</div>
      <div class="profile-hero__sub">${me.tg_username ? "@" + escapeHtml(me.tg_username) : ""}</div>
    </div>

    <div class="balance-grid">
      <div class="balance-card">
        <div class="balance-card__label">Keshbek</div>
        <div class="balance-card__value" id="b-cb">${fmtMoney(cashback)}</div>
        <div class="balance-card__hint">Keyingi buyurtmada qoplaysiz</div>
      </div>
      <div class="balance-card">
        <div class="balance-card__label">Bo'sh idishlar</div>
        <div class="balance-card__value" id="b-bt">${fmtCount(bottles)}</div>
        <div class="balance-card__hint">Qaytarish uchun tayyor</div>
      </div>
      <div class="balance-card">
        <div class="balance-card__label">Balans (avans)</div>
        <div class="balance-card__value" id="b-dep">${fmtMoney(deposit)}</div>
        <div class="balance-card__hint">Buyurtmalar shundan yechiladi</div>
      </div>
    </div>

    <div class="stat-grid" id="stats">
      <div class="stat"><div class="stat__value" id="s-active">—</div><div class="stat__label">Jarayonda</div></div>
      <div class="stat"><div class="stat__value" id="s-done">—</div><div class="stat__label">Yetkazilgan</div></div>
    </div>

    <div class="section-title">Manzillar</div>
    <div class="tile" id="goAddresses">
      <div class="tile__icon">📍</div>
      <div class="tile__main">
        <div class="tile__title">Mening manzillarim</div>
        <div class="tile__sub">"Uy", "Ish" kabi nomlar bilan saqlash</div>
      </div>
      <div class="tile__chev">›</div>
    </div>

    <!-- Promokod — holatga qarab to'ldiriladi (loadPromo). Bo'sh qolishi ham
         normal: mos kelmasa (masalan, mijoz allaqachon zakaz bergan) umuman
         ko'rsatilmaydi. -->
    <div id="promo-slot"></div>

    <div class="section-title">Ma'lumotlarim</div>
    <div class="list-item">
      <span class="list-item__label">Ism</span>
      <span class="list-item__value">${escapeHtml(fullName)}</span>
    </div>
    <div class="list-item">
      <span class="list-item__label">Telefon</span>
      <span class="list-item__value">${escapeHtml(phone)}</span>
    </div>
    <div class="list-item">
      <span class="list-item__label">Telegram ID</span>
      <span class="list-item__value">${me.telegram_id ?? "—"}</span>
    </div>

    <div class="spacer"></div>
    <button class="btn btn--secondary" id="editBtn" type="button">✏️ Ma'lumotlarni tahrirlash</button>
  `;
}

export function renderProfile(root) {
  document.getElementById("screen-title").textContent = "Profil";
  hideBackButton();
  hideMainButton();
  hideCTA();

  // Birinchi navbatda kesh'dan tezda ko'rsatamiz (instant UI), keyin fresh fetch.
  const cached = session.me || {};
  root.innerHTML = renderHero(cached);
  attachHandlers(root);
  loadStats(root);
  loadPromo(root);

  // Background: fresh fetch — keshni invalidate qilib, /api/me ni qaytadan tortadi.
  // Bu admin balansni o'zgartirgan vaqtda mijoz Profil bosishi bilan yangilanadi.
  let cancelled = false;
  (async () => {
    try {
      invalidateCache("me");
      const fresh = await api.me();
      if (cancelled) return;
      // Sessiya'ni yangilab, faqat o'zgargan KPI'larni jonli yangilaymiz (full re-render emas
      // — editBtn handlerlari uzilmasin, scroll position saqlansin).
      session.set(fresh);
      const cbEl = root.querySelector("#b-cb");
      const btEl = root.querySelector("#b-bt");
      const depEl = root.querySelector("#b-dep");
      if (cbEl) cbEl.textContent = fmtMoney(Number(fresh.cashback_balance || 0));
      if (btEl) btEl.textContent = fmtCount(Number(fresh.bottles_balance || 0));
      if (depEl) depEl.textContent = fmtMoney(Number(fresh.deposit_balance || 0));
    } catch (_) {
      // Network xato — kesh ko'rsatilgan, indikator qo'ymaymiz (silent degraded).
    }
  })();

  return () => { cancelled = true; hideCTA(); };
}

function attachHandlers(root) {
  const goAddrEl = root.querySelector("#goAddresses");
  if (goAddrEl) goAddrEl.addEventListener("click", () => go("addresses"));
  const editBtn = root.querySelector("#editBtn");
  if (editBtn) editBtn.addEventListener("click", () => openEdit(root));
}

// ---------------------- Promokod ----------------------
// Uyma-uy yuruvchi ishchi mijoznikiga boradi, botni tushuntiradi, manzil
// saqlashga o'rgatadi va MIJOZNING TELEFONIDA, uning ruxsati bilan, o'z kodini
// shu yerda kiritadi.
//
// Bo'lim FAQAT kerak bo'lganda ko'rinadi (serverdagi eligibility asosida):
//   * eligible              → kod kiritish formasi
//   * manzil yo'q           → "avval manzil saqlang" yo'riqnomasi (ishchiga
//                             keyingi qadamni aytadi — bu oqimning maqsadi)
//   * allaqachon kiritilgan → tasdiq (kod ko'rinadi)
//   * zakaz bergan / dastur o'chirilgan → umuman ko'rsatilmaydi (chalg'itmasin)
//
// Serverdagi qoidalar bu yerda TAKRORLANMAYDI — yakuniy qaror doim POST'da.

function promoSection(inner) {
  return `<div class="section-title">Promokod</div>${inner}`;
}

async function loadPromo(root) {
  const slot = root.querySelector("#promo-slot");
  if (!slot) return;
  let st;
  try {
    st = await api.promoStatus();
  } catch (_) {
    return;  // Silent: promokod ikkinchi darajali, profil baribir ishlayveradi.
  }
  if (!slot.isConnected) return;

  if (!st.program_enabled || st.has_orders) {
    slot.innerHTML = "";
    return;
  }

  if (st.already_redeemed) {
    slot.innerHTML = promoSection(`
      <div class="list-item">
        <span class="list-item__label">✅ Faollashtirilgan</span>
        <span class="list-item__value"><code>${escapeHtml(st.redeemed_code)}</code></span>
      </div>
    `);
    return;
  }

  if (!st.has_address) {
    slot.innerHTML = promoSection(`
      <div class="tile" id="promoGoAddr">
        <div class="tile__icon">🎁</div>
        <div class="tile__main">
          <div class="tile__title">Avval manzilingizni saqlang</div>
          <div class="tile__sub">Manzil saqlanganidan keyin promokod kiritish mumkin bo'ladi</div>
        </div>
        <div class="tile__chev">›</div>
      </div>
    `);
    const el = slot.querySelector("#promoGoAddr");
    if (el) el.addEventListener("click", () => go("addresses"));
    return;
  }

  // Eligible — kod kiritish formasi.
  slot.innerHTML = promoSection(`
    <div class="card" style="padding:12px">
      <div class="muted" style="font-size:13px;margin-bottom:8px">
        Sizga xizmat ko'rsatgan xodimning promokodi bo'lsa, shu yerga kiriting.
      </div>
      <div style="display:flex;gap:8px">
        <input class="input" id="promoInput" placeholder="Promokod"
               autocomplete="off" autocapitalize="characters" maxlength="16"
               style="text-transform:uppercase;letter-spacing:1px;flex:1" />
        <button class="btn" id="promoBtn" type="button">Faollashtirish</button>
      </div>
      <div id="promoErr" class="muted" style="font-size:12px;margin-top:6px;color:var(--danger,#d93025)"></div>
    </div>
  `);

  const input = slot.querySelector("#promoInput");
  const btn = slot.querySelector("#promoBtn");
  const err = slot.querySelector("#promoErr");

  async function submit() {
    const code = (input.value || "").trim();
    if (!code) return;
    err.textContent = "";
    btn.disabled = true;
    input.disabled = true;
    try {
      const r = await api.redeemPromo(code);
      hapticImpact("medium");
      toast(`Promokod faollashtirildi: ${r.promo_code}`, "success");
      loadPromo(root);  // qayta yuklash → "faollashtirilgan" ko'rinishi
    } catch (e) {
      // Xato matni serverdan (o'zbekcha, i18n) — bu yerda takrorlamaymiz.
      err.textContent = e instanceof ApiError ? e.message : "Xatolik yuz berdi.";
      btn.disabled = false;
      input.disabled = false;
    }
  }

  btn.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
}

async function loadStats(root) {
  try {
    const orders = await api.myOrders();
    const items = Array.isArray(orders) ? orders : (orders.items || []);
    const active = items.filter((o) => ACTIVE_STATUSES.has(o.status)).length;
    const done = items.filter((o) => DONE_STATUSES.has(o.status)).length;
    const a = root.querySelector("#s-active"); if (a) a.textContent = active;
    const d = root.querySelector("#s-done");   if (d) d.textContent = done;
  } catch (_) {
    const a = root.querySelector("#s-active"); if (a) a.textContent = "—";
    const d = root.querySelector("#s-done");   if (d) d.textContent = "—";
  }
}

function openEdit(root) {
  const me = session.me || {};
  document.getElementById("screen-title").textContent = "Tahrirlash";
  root.innerHTML = `
    <div class="form">
      <p class="muted" style="margin-top:0">Ism va telefon raqamingizni yangilang.</p>
      <label class="label" for="e-name">Ismingiz</label>
      <input class="input" id="e-name" type="text" autocomplete="name" />
      <label class="label" for="e-phone">Telefon raqam</label>
      <input class="input" id="e-phone" type="tel" inputmode="tel" autocomplete="tel" />
    </div>
    <div class="spacer"></div>
    <button class="btn btn--ghost" id="cancelBtn" type="button">Bekor qilish</button>
  `;
  const nameEl = root.querySelector("#e-name");
  const phoneEl = root.querySelector("#e-phone");
  nameEl.value = me.full_name || me.tg_first_name || "";
  phoneEl.value = me.phone_number || "";

  let busy = false;
  showCTA("Saqlash", async () => {
    if (busy) return;
    const full_name = nameEl.value.trim();
    const phone_number = normalizePhone(phoneEl.value);
    if (full_name.length < 2) return toast("Ismni to'liq kiriting.", { error: true });
    if (!phone_number) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", { error: true });
    phoneEl.value = phone_number;

    busy = true;
    setCTALoading(true);
    try {
      const updated = await api.register(full_name, phone_number);
      session.set(updated);
      hapticImpact("medium");
      toast("Saqlandi");
      renderProfile(root);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Xatolik";
      toast(msg, { error: true });
    } finally {
      busy = false;
      setCTALoading(false);
    }
  }, { variant: "secondary" });

  root.querySelector("#cancelBtn").addEventListener("click", () => {
    hideCTA();
    renderProfile(root);
  });
}
