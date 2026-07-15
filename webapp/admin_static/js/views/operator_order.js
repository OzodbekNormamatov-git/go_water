// Operator uchun "Yangi buyurtma" sahifasi.
//
// Oqim:
//   1. Operator telefon raqamni kiritadi → tizim mijozni qidiradi
//   2. Topilsa — ism/balans avtomatik ko'rinadi (eski mijoz)
//      Topilmasa — operator ismni qo'shimcha kiritadi (yangi guest mijoz)
//   3. Mahsulot tanlash (cart-like UI: + / −)
//   4. Manzil tanlash (xaritadan yoki saqlangan — hozir faqat xarita)
//   5. Aloqa telefon va izoh
//   6. (Ixtiyoriy) keshbek va idishlar
//   7. "Buyurtmani yuborish" — kuryerlar guruhiga ketadi

import { api, ApiError } from "../api.js";
import { fmtMoney, fmtCount, escapeHtml, normalizePhone, PAYMENT_LABELS } from "../format.js";
import { toast } from "../toast.js";
import { resolveReorderItems } from "../reorder_resolve.js";

// Mini xarita modal — admin paneliga oddiy Leaflet bilan
const LEAFLET_CSS = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS  = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";

let _leafletLoading = null;
function _loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_leafletLoading) return _leafletLoading;
  _leafletLoading = new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
    const s = document.createElement("script");
    s.src = LEAFLET_JS;
    s.onload = () => resolve(window.L);
    s.onerror = () => reject(new Error("Xarita yuklanmadi."));
    document.head.appendChild(s);
  });
  return _leafletLoading;
}

// Manzil qidiruv + teskari geocoding — bizning backend (Photon/OSM) orqali
// (api.geocode / api.reverseGeocode). Ko'cha/uy/mahalla nomlarini topadi.

function openMapPicker(initial) {
  return new Promise(async (resolve) => {
    const L = await _loadLeaflet().catch(() => null);
    if (!L) { resolve(null); return; }
    const start = initial || { latitude: 41.3111, longitude: 69.2797 }; // Tashkent
    const backdrop = document.createElement("div");
    backdrop.className = "map-picker-backdrop";
    backdrop.innerHTML = `
      <div class="map-picker-panel">
        <div class="map-picker-head">
          <b>Manzilni tanlang</b>
          <button class="map-picker-close" type="button" aria-label="Yopish">×</button>
        </div>
        <div class="map-picker-search">
          <input class="input" id="mp-search" type="search" autocomplete="off"
                 placeholder="Ko'cha, mahalla yoki joy (masalan: Chilonzor, Bunyodkor ko'chasi)" />
          <button class="btn btn--secondary" id="mp-search-btn" type="button">🔍</button>
        </div>
        <div class="map-picker-results" id="mp-results" hidden></div>
        <div class="map-picker-map" id="mp-map"></div>
        <div class="map-picker-pin">📍</div>
        <div id="mp-address" style="font-size:13px;font-weight:600;text-align:center;min-height:18px;padding:4px 12px 0"></div>
        <div class="map-picker-coord" id="mp-coord"></div>
        <div class="map-picker-foot">
          <button class="btn btn--secondary" id="mp-locate" type="button">📍 Mening joyim</button>
          <button class="btn" id="mp-ok" type="button">Tanlash</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    const map = L.map(backdrop.querySelector("#mp-map"), { attributionControl: false, zoomControl: true })
      .setView([start.latitude, start.longitude], 14);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);
    const coordEl = backdrop.querySelector("#mp-coord");
    const addressEl = backdrop.querySelector("#mp-address");
    let lastAddress = "";
    const refresh = () => {
      const c = map.getCenter();
      coordEl.textContent = `Lat: ${c.lat.toFixed(5)}, Lon: ${c.lng.toFixed(5)}`;
    };
    refresh(); map.on("move", refresh);

    // Pin to'xtaganda — manzilni teskari aniqlash (ko'cha/uy/mahalla ko'rinsin).
    let revTimer = null;
    const refreshAddress = () => {
      const c = map.getCenter();
      addressEl.textContent = "📍 aniqlanmoqda…";
      clearTimeout(revTimer);
      revTimer = setTimeout(async () => {
        try {
          const r = await api.reverseGeocode(c.lat, c.lng);
          lastAddress = (r && r.address) || "";
          addressEl.textContent = lastAddress || "📍 nom topilmadi (joylashuv saqlanadi)";
        } catch { addressEl.textContent = ""; }
      }, 500);
    };
    refreshAddress(); map.on("moveend", refreshAddress);

    const finish = (r) => { map.remove(); backdrop.remove(); resolve(r); };
    backdrop.querySelector(".map-picker-close").addEventListener("click", () => finish(null));
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) finish(null); });
    backdrop.querySelector("#mp-ok").addEventListener("click", async () => {
      const c = map.getCenter();
      let address = lastAddress;
      if (!address) { try { const r = await api.reverseGeocode(c.lat, c.lng); address = (r && r.address) || ""; } catch { /* x,y baribir */ } }
      finish({ latitude: c.lat, longitude: c.lng, address });
    });
    backdrop.querySelector("#mp-locate").addEventListener("click", () => {
      if (!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition(
        (pos) => map.setView([pos.coords.latitude, pos.coords.longitude], 16),
        () => {}, { enableHighAccuracy: true, timeout: 8000 },
      );
    });

    // ----- Qidiruv (Photon/OSM — ko'cha/uy/mahalla)
    const searchEl = backdrop.querySelector("#mp-search");
    const searchBtn = backdrop.querySelector("#mp-search-btn");
    const resultsEl = backdrop.querySelector("#mp-results");
    let searchTimer = null;

    const doSearch = async () => {
      const q = searchEl.value.trim();
      if (q.length < 2) { resultsEl.hidden = true; return; }
      resultsEl.hidden = false;
      resultsEl.innerHTML = `<div class="map-picker-result-loading">Qidirilmoqda…</div>`;
      try {
        const center = map.getCenter();
        const results = await api.geocode(q, { lat: center.lat, lon: center.lng });
        if (!results || !results.length) {
          resultsEl.innerHTML = `<div class="map-picker-result-empty">Topilmadi. Boshqa nom bilan urinib ko'ring.</div>`;
          return;
        }
        resultsEl.innerHTML = results.map((r, i) => `
            <div class="map-picker-result" data-idx="${i}">
              <div class="map-picker-result-title">${escapeHtml(r.title)}</div>
              <div class="map-picker-result-sub">${escapeHtml(r.subtitle)}</div>
            </div>`).join("");
        resultsEl.querySelectorAll(".map-picker-result").forEach((el) => {
          el.addEventListener("click", () => {
            const r = results[Number(el.dataset.idx)];
            if (!r || !Number.isFinite(r.latitude) || !Number.isFinite(r.longitude)) return;
            map.setView([r.latitude, r.longitude], 17);
            if (r.address) { lastAddress = r.address; addressEl.textContent = r.address; }
            resultsEl.hidden = true;
          });
        });
      } catch (e) {
        resultsEl.innerHTML = `<div class="map-picker-result-empty">Xatolik: ${escapeHtml(e.message || "")}</div>`;
      }
    };

    searchEl.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = searchEl.value.trim();
      if (q.length < 2) { resultsEl.hidden = true; return; }
      searchTimer = setTimeout(doSearch, 350);
    });
    searchBtn.addEventListener("click", doSearch);
    searchEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); clearTimeout(searchTimer); doSearch(); }
    });
    // Xaritani bossa — natijalar yashirinadi (yo'ldan olib tashlash)
    backdrop.querySelector(".map-picker-map").addEventListener("mousedown", () => {
      resultsEl.hidden = true;
    }, true);
  });
}

export async function renderOperatorOrder(root) {
  // State
  let products = [];
  const cart = new Map();        // food_id -> quantity
  let customer = null;            // { id, full_name, has_started_bot, cashback_balance, bottles_balance } | null
  let customerSearched = false;   // birinchi qidiruv qilinganmi
  let orderLocation = null;       // { latitude, longitude } | null
  let paymentMethod = "cash";     // "cash" | "card" | "deposit"
  let busy = false;
  // Idempotensiya kaliti — har form render'da BIR marta yaratiladi: tarmoq
  // xatosidan keyin qayta bosilsa ham buyurtma dublikat bo'lmaydi.
  const idemKey = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

  root.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <h3 class="card__title">1. Mijoz</h3>
      <div class="form-row">
        <label class="label" for="op-search">Mijozni qidirish — ism yoki telefon</label>
        <input class="input" id="op-search" type="search" autocomplete="off"
               placeholder="Masalan: Ali  yoki  1234 (oxirgi raqamlar)" />
        <div class="muted" style="font-size:12px;margin-top:4px">Kamida 2 belgi yozing — mosliklar avtomatik chiqadi.</div>
      </div>
      <div id="op-results"></div>
      <div id="op-selected" hidden></div>
      <div id="op-recent"></div>
      <div id="op-new" hidden>
        <div class="form-row">
          <label class="label" for="op-name">Ism (yangi mijoz)</label>
          <input class="input" id="op-name" type="text" placeholder="Mijozning ismi" />
        </div>
        <div class="form-row">
          <label class="label" for="op-newphone">Telefon</label>
          <input class="input" id="op-newphone" type="tel" inputmode="tel" placeholder="+998901234567" />
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3 class="card__title">2. Mahsulotlar</h3>
      <div id="op-products" class="loading">Yuklanmoqda…</div>
      <div class="op-cart-summary" id="op-cart-summary" hidden>
        <span class="muted">Tanlangan:</span>
        <b id="op-cart-count">0 ta</b>
        <span style="margin-left:auto;font-weight:700;color:var(--brand-deep)" id="op-cart-total">0 so'm</span>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3 class="card__title">3. Yetkazib berish manzili</h3>
      <button class="btn btn--secondary" id="op-pick-addr" type="button">🗺 Xaritadan tanlash</button>
      <div class="muted" id="op-addr-status" style="font-size:12px;margin-top:6px">Belgilanmagan</div>
      <label class="label" for="op-addr-details" style="margin-top:10px">Tafsilot (podyezd, kvartira...)</label>
      <input class="input" id="op-addr-details" type="text" maxlength="200" placeholder="3-podyezd, 17-kvartira" />
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3 class="card__title">4. Aloqa va izoh</h3>
      <label class="label" for="op-contact">Aloqa telefoni (kuryer uchun)</label>
      <input class="input" id="op-contact" type="tel" inputmode="tel" placeholder="+998901234567" />
      <label class="label" for="op-note">Izoh (kuryer va oshpaz uchun)</label>
      <textarea class="textarea" id="op-note" maxlength="500" placeholder="Maxsus ko'rsatma, qo'ng'iroq qilmaslik va h.k."></textarea>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3 class="card__title">5. To'lov usuli</h3>
      <div id="op-payment" style="display:flex;gap:8px"></div>
      <div class="muted" id="op-payment-hint" style="font-size:12px;margin-top:6px"></div>
    </div>

    <div class="card" style="margin-bottom:14px" id="op-bonus-card" hidden>
      <h3 class="card__title">6. Keshbek bilan to'lash</h3>
      <div class="form-row">
        <label class="label" for="op-cashback">Keshbek ishlatish (so'm)</label>
        <input class="input" id="op-cashback" type="number" min="0" step="1000" placeholder="0" />
        <div class="muted" id="op-cashback-hint" style="font-size:12px;margin-top:4px"></div>
      </div>
      <div class="muted" style="font-size:12px;margin-top:8px">
        ℹ️ Bo'sh idishlar — yetkazganda kuryer kiritadi.
      </div>
    </div>

    <div style="display:flex;gap:10px;align-items:center;padding:12px 0">
      <span class="muted" id="op-summary"></span>
      <span style="flex:1"></span>
      <button class="btn" id="op-submit" type="button" style="min-width:180px">📦 Buyurtmani yuborish</button>
    </div>
  `;

  // Refs
  const searchEl = root.querySelector("#op-search");
  const resultsEl = root.querySelector("#op-results");
  const selectedEl = root.querySelector("#op-selected");
  const recentEl = root.querySelector("#op-recent");
  const newWrap = root.querySelector("#op-new");
  const nameEl = root.querySelector("#op-name");
  const newPhoneEl = root.querySelector("#op-newphone");
  const productsEl = root.querySelector("#op-products");
  const cartSummary = root.querySelector("#op-cart-summary");
  const cartCountEl = root.querySelector("#op-cart-count");
  const cartTotalEl = root.querySelector("#op-cart-total");
  const pickAddrBtn = root.querySelector("#op-pick-addr");
  const addrStatus = root.querySelector("#op-addr-status");
  const addrDetailsEl = root.querySelector("#op-addr-details");
  const contactEl = root.querySelector("#op-contact");
  const noteEl = root.querySelector("#op-note");
  const paymentEl = root.querySelector("#op-payment");
  const paymentHint = root.querySelector("#op-payment-hint");
  const bonusCard = root.querySelector("#op-bonus-card");
  const cashbackEl = root.querySelector("#op-cashback");
  const cashbackHint = root.querySelector("#op-cashback-hint");
  // Bo'sh idishlar (op-bottles) — UI'dan olib tashlangan: kuryer yetkazganda kiritadi.
  const submitBtn = root.querySelector("#op-submit");
  const summaryEl = root.querySelector("#op-summary");

  // ----- 1. Mijoz qidirish (ism yoki telefon, qisman — oxirgi raqamlar ham)
  let searchTimer = null;

  function clearSelection() {
    customer = null;
    customerSearched = false;
    selectedEl.hidden = true;
    selectedEl.innerHTML = "";
    recentEl.innerHTML = "";
    newWrap.hidden = true;
    updateBonusCard();
    renderPayment();
  }

  function renderResults(list, q) {
    const rows = (list || []).map((c, i) => `
      <button type="button" data-pick="${i}"
        style="display:block;width:100%;text-align:left;border:1px solid var(--border,#e5e7eb);border-radius:10px;padding:8px 10px;margin-top:6px;background:var(--surface,#fff);cursor:pointer">
        <b>${escapeHtml(c.full_name)}</b>
        <span class="muted" style="font-size:13px"> · ${escapeHtml(c.phone_number)}</span>
        ${Number(c.cashback_balance) > 0 ? `<span class="muted" style="font-size:12px"> · 💰 ${fmtMoney(c.cashback_balance)}</span>` : ""}
        ${Number(c.deposit_balance) > 0 ? `<span class="muted" style="font-size:12px"> · 💰 ${fmtMoney(c.deposit_balance)}</span>` : ""}
        ${c.has_started_bot ? "" : `<span class="muted" style="font-size:12px"> · botsiz</span>`}
      </button>`).join("");
    const newBtn = `
      <button type="button" data-new="1"
        style="display:block;width:100%;text-align:left;border:1px dashed var(--brand-primary,#3b82f6);border-radius:10px;padding:8px 10px;margin-top:6px;background:var(--brand-tint,#f0f7ff);cursor:pointer;color:var(--brand-deep,#1d4ed8)">
        ➕ Yangi mijoz qo'shish${q ? ` ("${escapeHtml(q)}")` : ""}
      </button>`;
    resultsEl.innerHTML = (rows || `<div class="muted" style="font-size:13px;padding:6px">Mijoz topilmadi.</div>`) + newBtn;
    resultsEl.querySelectorAll("[data-pick]").forEach((b) =>
      b.addEventListener("click", () => selectCustomer(list[Number(b.dataset.pick)])));
    resultsEl.querySelector("[data-new]").addEventListener("click", () => startNewCustomer(q));
  }

  async function doSearch(q) {
    resultsEl.innerHTML = `<div class="muted" style="font-size:13px;padding:6px">Qidirilmoqda…</div>`;
    let list;
    try {
      list = await api.operatorCustomerSearch(q, { limit: 8 });
    } catch (e) {
      resultsEl.innerHTML = `<div class="muted" style="font-size:13px;padding:6px;color:var(--brand-danger)">${escapeHtml(e.message || "Xatolik")}</div>`;
      return;
    }
    renderResults(list, q);
  }

  searchEl.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = searchEl.value.trim();
    if (q.length < 2) { resultsEl.innerHTML = ""; return; }
    searchTimer = setTimeout(() => doSearch(q), 300);
  });

  function selectCustomer(c) {
    if (!c) return;
    customer = c;
    customerSearched = true;
    searchEl.value = "";
    resultsEl.innerHTML = "";
    newWrap.hidden = true;
    selectedEl.hidden = false;
    selectedEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;border:1px solid var(--brand-success,#16a34a);border-radius:10px;padding:8px 10px;background:var(--brand-tint,#f0fff4)">
        <div style="flex:1">
          ✅ <b>${escapeHtml(c.full_name)}</b>
          <span class="muted" style="font-size:13px"> · ${escapeHtml(c.phone_number)}</span>
          ${Number(c.deposit_balance) > 0 ? `<span class="muted" style="font-size:12px"> · 💰 ${fmtMoney(c.deposit_balance)}</span>` : ""}
          ${c.has_started_bot ? "" : `<span class="muted" style="font-size:12px"> · botsiz</span>`}
        </div>
        <button type="button" class="btn btn--xs btn--secondary" data-change>✖ o'zgartirish</button>
      </div>
      <div id="op-phones" style="margin-top:8px"></div>`;
    selectedEl.querySelector("[data-change]").addEventListener("click", () => {
      clearSelection();
      searchEl.focus();
    });
    if (!contactEl.value) contactEl.value = c.phone_number;
    updateBonusCard();
    renderPayment();
    // Mijoz raqamlari — operator yangi raqam biriktira oladi (mijoz boshqa
    // nomerdan qo'ng'iroq qilsa dublikat profil o'rniga shu ishlatiladi).
    loadCustomerPhones(c.id);
    // Oxirgi 3 ta buyurtmasini ko'rsatamiz — operator bittada takrorlay oladi.
    loadRecentOrders(c.id);
  }

  // ----- Mijoz telefon raqamlari (ko'rish + yangi biriktirish)
  async function loadCustomerPhones(customerId) {
    const box = root.querySelector("#op-phones");
    if (!box) return;
    box.innerHTML = `<div class="muted" style="font-size:12px">Raqamlar yuklanmoqda…</div>`;
    let phones = [];
    try {
      phones = await api.customerPhones(customerId);
    } catch (e) {
      box.innerHTML = "";  // jim — raqamlarni ko'rsatolmasak ham buyurtma ishlaydi
      return;
    }
    renderPhonesBox(box, customerId, phones);
  }

  function renderPhonesBox(box, customerId, phones) {
    const chips = (phones || []).map((p) => `
      <span class="phone-chip" style="display:inline-flex;align-items:center;gap:4px;border:1px solid var(--border,#e5e7eb);border-radius:999px;padding:3px 10px;margin:0 4px 4px 0;font-size:13px">
        ${p.is_primary ? "⭐ " : "📞 "}${escapeHtml(p.phone)}${p.label ? ` <span class="muted" style="font-size:11px">(${escapeHtml(p.label)})</span>` : ""}
        <button type="button" data-usecontact="${escapeHtml(p.phone)}" title="Aloqa raqami sifatida ishlatish"
          style="border:none;background:none;cursor:pointer;color:var(--brand-primary,#3b82f6);font-size:12px">↳</button>
      </span>`).join("");
    box.innerHTML = `
      <div class="muted" style="font-size:12px;margin-bottom:4px">📇 Mijoz raqamlari (↳ — aloqa raqami sifatida qo'yish):</div>
      <div style="margin-bottom:6px">${chips || `<span class="muted" style="font-size:12px">Raqam yo'q</span>`}</div>
      <div style="display:flex;gap:6px;align-items:center">
        <input class="input" id="op-newnum" type="tel" inputmode="tel" placeholder="+998901234567 (yangi raqam)" style="flex:1" />
        <input class="input" id="op-newnum-label" type="text" placeholder="izoh (ish, uy...)" style="max-width:120px" />
        <button type="button" class="btn btn--secondary" id="op-addnum">➕ Biriktirish</button>
      </div>
      <div class="muted" id="op-newnum-hint" style="font-size:11px;margin-top:4px">
        Mijoz boshqa raqamdan qo'ng'iroq qilsa — shu yerga qo'shing, keyingi safar avtomatik topiladi.
      </div>`;
    // "↳" — chip raqamini aloqa (kuryer) telefoniga qo'yish.
    box.querySelectorAll("[data-usecontact]").forEach((b) =>
      b.addEventListener("click", () => { contactEl.value = b.dataset.usecontact; toast("Aloqa raqami yangilandi", "success"); }));

    const numEl = box.querySelector("#op-newnum");
    const labelEl = box.querySelector("#op-newnum-label");
    const addBtn = box.querySelector("#op-addnum");
    addBtn.addEventListener("click", async () => {
      const phone = normalizePhone(numEl.value);
      if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
      addBtn.disabled = true;
      try {
        await api.addCustomerPhone(customerId, { phone, label: (labelEl.value || "").trim() });
        toast("Raqam biriktirildi", "success");
        if (!contactEl.value) contactEl.value = phone;
        const fresh = await api.customerPhones(customerId);
        renderPhonesBox(box, customerId, fresh);
      } catch (e) {
        // 409 phone_taken — raqam boshqa mijozniki (backend owner_user_id qaytaradi)
        const msg = e instanceof ApiError
          ? (e.code === "http_409" ? "Bu raqam boshqa mijozga biriktirilgan" : e.message)
          : "Xatolik";
        toast(msg, "error");
        addBtn.disabled = false;
      }
    });
  }

  function startNewCustomer(q) {
    customer = null;
    customerSearched = true;
    resultsEl.innerHTML = "";
    selectedEl.hidden = true;
    recentEl.innerHTML = "";
    newWrap.hidden = false;
    // Qidiruv raqamlardan iborat bo'lsa — telefonni oldindan to'ldiramiz; aks holda ism.
    const digits = (q || "").replace(/\D/g, "");
    if (digits.length >= 4) {
      // normalizePhone to'liq raqamni +998... ga keltiradi; qisman raqam
      // bo'lsa — xom qidiruvni qoldiramiz, operator o'zi to'ldiradi.
      if (!newPhoneEl.value) newPhoneEl.value = normalizePhone(q) || (q || "").trim();
      nameEl.focus();
    } else {
      if (!nameEl.value) nameEl.value = (q || "").trim();
      nameEl.focus();
    }
    if (!contactEl.value && newPhoneEl.value) contactEl.value = newPhoneEl.value;
    updateBonusCard();
    renderPayment();
  }

  // ----- 2. Products
  (async () => {
    try {
      // Operator buyurtma formasi uchun barcha aktiv mahsulotlar kerak (server
      // tomonida hozir li=200 max). Limit yetmasa, kelajakda bu yerni
      // ham `Yana yuklash` bilan paginatsiyalashtirish mumkin — hozircha
      // suv yetkazib berish shopida mahsulotlar soni ko'p emas.
      const res = await api.products({ limit: 200 });
      const items = Array.isArray(res) ? res : (res.items || []);
      products = items.filter((p) => p.is_available && !p.deleted_at);
      if (!products.length) {
        productsEl.innerHTML = `<div class="muted">Mahsulotlar yo'q.</div>`;
        return;
      }
      productsEl.classList.remove("loading");
      productsEl.innerHTML = `
        <div class="op-products-list">
          ${products.map((p) => `
            <div class="op-product-row" data-id="${p.id}">
              <div class="op-product-name">
                <div style="font-weight:600">${escapeHtml(p.name)}</div>
                <div class="muted" style="font-size:12px">${fmtMoney(p.price)}${Number(p.min_quantity || 1) > 1 ? ` · min ${p.min_quantity}` : ""}</div>
              </div>
              <div class="qty-stepper">
                <button type="button" data-act="dec">−</button>
                <div class="qty-stepper__value" data-qty>0</div>
                <button type="button" data-act="inc">+</button>
              </div>
            </div>
          `).join("")}
        </div>
      `;
      productsEl.querySelectorAll(".op-product-row").forEach((row) => {
        const id = Number(row.dataset.id);
        const qtyEl = row.querySelector("[data-qty]");
        row.querySelectorAll("button[data-act]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const act = btn.dataset.act;
            const p = products.find((x) => x.id === id);
            // Per-mahsulot minimal: birinchi "+" 0 → min sakraydi; "−" min
            // ostiga tushsa — 0 (olib tashlash).
            const minQ = Math.max(1, Number((p && p.min_quantity) || 1));
            const cur = cart.get(id) || 0;
            const next = act === "inc"
              ? (cur < minQ ? minQ : Math.min(cur + 1, 999))
              : (cur - 1 < minQ ? 0 : cur - 1);
            if (next === 0) cart.delete(id); else cart.set(id, next);
            qtyEl.textContent = next;
            updateCartSummary();
          });
        });
      });
    } catch (e) {
      productsEl.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    }
  })();

  function cartTotal() {
    let total = 0;
    for (const [id, qty] of cart) {
      const p = products.find((x) => x.id === id);
      if (p) total += Number(p.price) * qty;
    }
    return total;
  }
  function cartCount() {
    let c = 0;
    for (const v of cart.values()) c += v;
    return c;
  }
  function updateCartSummary() {
    const n = cartCount();
    if (n > 0) {
      cartSummary.hidden = false;
      cartCountEl.textContent = `${fmtCount(n)} ta`;
      cartTotalEl.textContent = fmtMoney(cartTotal());
    } else {
      cartSummary.hidden = true;
    }
    updateBonusCard();
    renderPayment();
    updateSummary();
  }

  // ----- Takror buyurtma (reorder)
  // Cart Map o'zgargandan keyin mahsulot ro'yxatidagi qty ko'rsatkichlarini sinxronlaymiz.
  function syncProductRowsFromCart() {
    productsEl.querySelectorAll(".op-product-row").forEach((row) => {
      const id = Number(row.dataset.id);
      const qtyEl = row.querySelector("[data-qty]");
      if (qtyEl) qtyEl.textContent = String(cart.get(id) || 0);
    });
  }

  // O'tgan buyurtmani formaga to'ldiradi (joriy katalogga moslab) — operator
  // tekshirib/o'zgartirib yuboradi. Mavjud create_order quvuridan o'tadi.
  function applyReorder(order) {
    if (!products.length) {
      toast("Mahsulotlar hali yuklanmadi, biroz kuting", "error");
      return;
    }
    const { available, removed, adjusted } = resolveReorderItems(order.items, products);
    cart.clear();
    for (const r of available) cart.set(r.food_id, r.quantity);
    syncProductRowsFromCart();
    updateCartSummary();

    // Manzil
    if (order.latitude && order.longitude) {
      orderLocation = { latitude: Number(order.latitude), longitude: Number(order.longitude) };
      addrStatus.innerHTML = `✅ <code>${orderLocation.latitude.toFixed(5)}, ${orderLocation.longitude.toFixed(5)}</code>`;
    }
    if (order.address_details) addrDetailsEl.value = order.address_details;
    // Aloqa + izoh
    if (order.contact_phone) contactEl.value = order.contact_phone;
    if (order.note) noteEl.value = order.note;

    let msg = "♻️ Takrorlandi — tekshirib, yuboring";
    if (removed.length) msg += ` · ${removed.length} ta mahsulot endi yo'q`;
    if (adjusted.length) msg += ` · ${adjusted.length} ta miqdor minimalga moslandi`;
    toast(msg, removed.length ? "error" : "success");
  }

  async function loadRecentOrders(customerId) {
    recentEl.innerHTML = `<div class="muted" style="font-size:12px;margin-top:8px">Oxirgi buyurtmalar yuklanmoqda…</div>`;
    let list;
    try {
      list = await api.operatorRecentOrders(customerId, { limit: 3 });
    } catch (e) {
      recentEl.innerHTML = "";  // jim — takror buyurtma ixtiyoriy qulaylik
      return;
    }
    if (!list || !list.length) {
      recentEl.innerHTML = `<div class="muted" style="font-size:12px;margin-top:8px">Oldingi buyurtmalar yo'q.</div>`;
      return;
    }
    recentEl.innerHTML = `
      <div class="label" style="margin-top:12px">♻️ Oxirgi buyurtmalar (takrorlash uchun)</div>
      ${list.map((o, i) => `
        <div class="op-recent-order" style="border:1px solid var(--border,#e5e7eb);border-radius:10px;padding:10px;margin-top:8px">
          <div style="display:flex;align-items:center;gap:8px">
            <b>${escapeHtml(o.display_number)}</b>
            <span class="muted" style="font-size:12px">${o.status_label ? escapeHtml(o.status_label) : ""}</span>
            <span style="margin-left:auto;font-weight:700;color:var(--brand-deep)">${fmtMoney(o.total_amount)}</span>
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">
            ${(o.items || []).map((it) => `${escapeHtml(it.food_name)}×${it.quantity}`).join(", ") || "—"}
          </div>
          <button class="btn btn--secondary" data-reorder="${i}" type="button" style="margin-top:8px;padding:4px 10px;font-size:13px">♻️ Takrorlash</button>
        </div>
      `).join("")}
    `;
    recentEl.querySelectorAll("button[data-reorder]").forEach((btn) => {
      btn.addEventListener("click", () => applyReorder(list[Number(btn.dataset.reorder)]));
    });
  }

  // ----- 3. Address
  pickAddrBtn.addEventListener("click", async () => {
    const r = await openMapPicker(orderLocation || undefined);
    if (!r) return;
    orderLocation = r;
    addrStatus.innerHTML = `✅ <code>${r.latitude.toFixed(5)}, ${r.longitude.toFixed(5)}</code>`;
    // Geocoded ko'cha/uy/mahalla — ko'rsatamiz + tafsilot bo'sh bo'lsa to'ldiramiz.
    if (r.address) {
      addrStatus.innerHTML += `<div style="margin-top:2px">📍 ${escapeHtml(r.address)}</div>`;
      if (!addrDetailsEl.value.trim()) addrDetailsEl.value = r.address;
    }
  });

  // ----- 4/5. Bonus card visibility — faqat mijozda keshbek bo'lsa ko'rinadi.
  // Bo'sh idishlar endi alohida widget emas — kuryer yetkazganda kiritadi.
  function updateBonusCard() {
    const cb = Number((customer && customer.cashback_balance) || 0);
    if (cb > 0) {
      bonusCard.hidden = false;
      const itemsTotal = cartTotal();
      cashbackHint.textContent = `Mavjud: ${fmtMoney(cb)} · 1000 so'm qadami bilan, items_total dan oshmasin (${fmtMoney(itemsTotal)})`;
      cashbackEl.max = String(Math.min(cb, itemsTotal));
    } else {
      bonusCard.hidden = true;
      cashbackEl.value = "0";
    }
  }

  // ----- To'lov usuli (segmented control) — "Balansdan" faqat mijoz tanlangan
  // va balansi savat jamidan kam bo'lmaganda yoqiladi.
  function renderPayment() {
    const dep = Number((customer && customer.deposit_balance) || 0);
    const depositOk = !!customer && dep > 0 && dep >= cartTotal();
    if (paymentMethod === "deposit" && !depositOk) paymentMethod = "cash";
    paymentEl.innerHTML = ["cash", "card", "deposit"].map((m) => `
      <button type="button" data-pay="${m}"
        class="${paymentMethod === m ? "btn" : "btn btn--secondary"}"
        style="flex:1" ${m === "deposit" && !depositOk ? "disabled" : ""}>${PAYMENT_LABELS[m]}</button>`).join("");
    paymentEl.querySelectorAll("button[data-pay]").forEach((b) =>
      b.addEventListener("click", () => { paymentMethod = b.dataset.pay; renderPayment(); }));
    const hints = {
      cash: "Kuryer mijozdan naqd oladi.",
      card: "Karta orqali — kuryer naqd olmaydi.",
      deposit: `Mijoz balansida ${fmtMoney(dep)} bor — buyurtma shundan yechiladi, kuryerdan pul so'ralmaydi.`,
    };
    paymentHint.textContent = hints[paymentMethod];
  }
  renderPayment();

  function updateSummary() {
    const n = cartCount();
    if (!n) { summaryEl.textContent = ""; return; }
    const cb = Math.max(0, Math.floor((Number(cashbackEl.value) || 0) / 1000) * 1000);
    const cash = Math.max(0, cartTotal() - cb);
    summaryEl.innerHTML = `Jami: <b>${fmtMoney(cartTotal())}</b> · Naqd: <b style="color:var(--brand-deep)">${fmtMoney(cash)}</b>`;
  }
  cashbackEl.addEventListener("input", updateSummary);

  // ----- 6. Submit
  submitBtn.addEventListener("click", async () => {
    if (busy) return;
    let phone = (customer ? customer.phone_number : newPhoneEl.value).trim();
    const name = (customer ? customer.full_name : nameEl.value).trim();
    if (!customerSearched) return toast("Avval mijozni qidiring va tanlang (yoki yangi qo'shing)", "error");
    if (name.length < 2) return toast("Mijozning ismini kiriting", "error");
    if (phone.length < 4) return toast("Telefon raqamini kiriting", "error");
    if (!customer) {
      // Yangi mijoz — operator terganini +998... ga normalizatsiya qilamiz.
      // Tanlangan mijozning saqlangan raqami esa o'z holicha ketadi.
      phone = normalizePhone(phone);
      if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    }
    if (cart.size === 0) return toast("Hech qaysi mahsulot tanlanmagan", "error");
    if (!orderLocation) return toast("Manzilni xaritadan tanlang", "error");
    const contactRaw = contactEl.value.trim();
    if (contactRaw.length < 4) return toast("Aloqa telefonini kiriting", "error");
    const contact = normalizePhone(contactRaw);
    if (!contact) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    const note = noteEl.value.trim();
    if (note.length < 1) return toast("Izoh kiriting", "error");

    const items = Array.from(cart.entries()).map(([food_id, quantity]) => ({ food_id, quantity }));
    const cashbackToUse = Math.max(0, Math.floor((Number(cashbackEl.value) || 0) / 1000) * 1000);

    busy = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Yuborilmoqda…";
    try {
      const res = await api.operatorCreateOrder({
        customer_phone: phone,
        customer_full_name: name,
        items,
        latitude: orderLocation.latitude,
        longitude: orderLocation.longitude,
        address_label: "",
        address_details: addrDetailsEl.value.trim(),
        contact_phone: contact,
        note,
        cashback_to_use: cashbackToUse,
        payment_method: paymentMethod,
        idempotency_key: idemKey,
        // bottles_returned — yetkazganda kuryer kiritadi
      });
      toast(`✅ Buyurtma ${res.display_number || ("#" + res.id)} yaratildi — kuryerlarga yuborildi`, "success");
      // Formni tozalaymiz, lekin sahifani qaytadan render qilamiz
      // (root DOM'dan uzilgan bo'lsa — masalan boshqa sahifaga o'tilgan — render qilmaymiz)
      setTimeout(() => { if (root.isConnected) renderOperatorOrder(root); }, 800);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Xatolik";
      toast(msg, "error");
    } finally {
      busy = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "📦 Buyurtmani yuborish";
    }
  });
}
