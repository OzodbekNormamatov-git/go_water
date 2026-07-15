// Rasmiylashtirish — manzil (saqlangan / xarita / joriy joy), telefon, izoh,
// keshbek, qaytaradigan idishlar va tasdiqlash.

import { api, ApiError } from "../api.js";
import { cart, ensureOrderKey, rotateOrderKey, session } from "../state.js";
import { fmtMoney, escapeHtml, iconFor, normalizePhone } from "../format.js";
import {
  hapticNotification,
  hideBackButton,
  hideMainButton,
  showBackButton,
} from "../telegram.js";
import { back, go } from "../router.js";
import { toast } from "../toast.js";
import { showCTA, hideCTA, setCTALoading } from "../cta.js";
import { openMapPicker } from "../mappicker.js";

export function renderCheckout(root) {
  if (cart.isEmpty()) { back(); return; }

  document.getElementById("screen-title").textContent = "Rasmiylashtirish";
  showBackButton(() => back());
  hideMainButton();

  const me = session.me || {};

  // Sotuv summasi — server-side cart bilan qayta hisoblanadi (idempotency).
  let cartItems = cart.toApi();
  let itemsTotalCached = 0;

  root.innerHTML = `
    <div class="form">
      <label class="label">Yetkazib berish manzili</label>
      <div id="addrArea" class="card" style="padding:12px">
        <div class="muted" id="addrEmpty">Yuklanmoqda…</div>
      </div>

      <div class="bonus-row" id="cashbackArea" hidden></div>

      <label class="label">To'lov usuli</label>
      <div class="card" style="padding:10px">
        <div id="payOptions" style="display:flex;gap:8px"></div>
        <div class="muted" id="payHint" style="font-size:12px;margin-top:6px"></div>
      </div>

      <label class="label" for="c-phone">Telefon (yetkazish uchun)</label>
      <input class="input" id="c-phone" type="tel" placeholder="+998 90 123 45 67 yoki 901234567" inputmode="tel" autocomplete="tel" />

      <label class="label" for="c-note">Izoh (podyezd, kvartira, ko'rsatma)</label>
      <textarea class="input" id="c-note" maxlength="500" placeholder="Masalan: 3-podyezd, 17-kvartira, qo'ng'iroq qilmang"></textarea>

      <div class="card" style="margin-top:14px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span class="muted">Mahsulotlar</span>
          <b id="sumItems">—</b>
        </div>
        <div style="display:flex;justify-content:space-between;margin-bottom:4px" id="rowDiscount" hidden>
          <span class="muted">Keshbek qoplandi</span>
          <b id="sumDiscount" style="color:var(--brand-success)">—</b>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:6px;padding-top:6px;border-top:1px solid var(--divider)">
          <span><b id="payLabel">To'lov (naqd)</b></span>
          <b id="sumTotal" style="color:var(--brand-deep)">—</b>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:6px" id="rowEarn" hidden>
          <span class="muted">Keshbek olasiz</span>
          <b id="sumEarn" style="color:var(--brand-primary)">—</b>
        </div>
      </div>
    </div>
  `;

  const phoneInput = root.querySelector("#c-phone");
  const noteInput = root.querySelector("#c-note");
  const addrArea = root.querySelector("#addrArea");
  const cashbackArea = root.querySelector("#cashbackArea");
  const sumItemsEl = root.querySelector("#sumItems");
  const sumDiscountEl = root.querySelector("#sumDiscount");
  const sumTotalEl = root.querySelector("#sumTotal");
  const sumEarnEl = root.querySelector("#sumEarn");
  const rowDiscount = root.querySelector("#rowDiscount");
  const rowEarn = root.querySelector("#rowEarn");
  const payOptionsEl = root.querySelector("#payOptions");
  const payHintEl = root.querySelector("#payHint");
  const payLabelEl = root.querySelector("#payLabel");

  if (me.phone_number) phoneInput.value = me.phone_number;

  let location = null;
  let addressLabel = "";
  let addressDetails = "";
  let savedAddresses = [];
  let balance = { cashback_balance: 0, bottles_balance: 0, deposit_balance: 0, cashback_enabled: true, cashback_percent: 1.5, max_cashback_usage_ratio: 1.0 };
  let cashbackToUse = 0;
  // To'lov usuli: cash (default) | card | deposit (avans balansi yetarli bo'lsa).
  let paymentMethod = "cash";
  // Bo'sh idishlar — endi mijoz kiritmaydi, kuryer yetkazganda hisoblaydi.
  // Order yaratilganda doim 0 — DELIVERED bo'lganda kuryer kiritgan qiymat saqlanadi.

  // Items total'ni bir marta hisoblab keshlaymiz; keyingi recomputeSummary chaqiruvlari sync.
  async function loadItemsTotal() {
    try {
      const products = await api.products();
      let total = 0;
      for (const it of cartItems) {
        const p = products.find((x) => x.id === it.food_id);
        if (p) total += Number(p.price) * it.quantity;
      }
      itemsTotalCached = total;
    } catch (_) {
      // Network xato — UI'da 0 ko'rinishi mumkin, lekin createOrder server-side hisoblaydi.
    }
  }

  const totalDue = () =>
    Math.max(0, itemsTotalCached - Math.min(cashbackToUse, itemsTotalCached));

  const PAY_META = {
    cash:    { label: "💵 Naqd",      sum: "To'lov (naqd)",       hint: "Kuryerga naqd to'laysiz." },
    card:    { label: "💳 Karta",     sum: "To'lov (karta)",      hint: "Karta orqali to'laysiz — kuryerga naqd bermaysiz." },
    deposit: { label: "💰 Balansdan", sum: "To'lov (balansdan)",  hint: "" },
  };

  // To'lov usuli tanlagichi — "Balansdan" faqat avans balansi bor mijozlarga
  // ko'rinadi; balans buyurtmaga yetmasa tugma o'chirilgan holda qoladi.
  const renderPayment = () => {
    const dep = Number(balance.deposit_balance || 0);
    const due = totalDue();
    const opts = [
      { key: "cash", disabled: false },
      { key: "card", disabled: false },
    ];
    if (dep > 0) opts.push({ key: "deposit", disabled: dep < due });
    if (paymentMethod === "deposit" && (dep <= 0 || dep < due)) paymentMethod = "cash";
    payOptionsEl.innerHTML = opts.map((o) => `
      <button type="button" class="btn ${paymentMethod === o.key ? "" : "btn--ghost"}"
              data-pay="${o.key}" ${o.disabled ? "disabled" : ""} style="flex:1">
        ${PAY_META[o.key].label}
      </button>
    `).join("");
    payOptionsEl.querySelectorAll("[data-pay]").forEach((btn) => {
      btn.addEventListener("click", () => {
        paymentMethod = btn.getAttribute("data-pay");
        renderPayment();
        recomputeSummary();
      });
    });
    if (paymentMethod === "deposit") {
      payHintEl.textContent =
        `Balansingizda ${fmtMoney(dep)} bor — buyurtma shundan yechiladi, kuryerga pul bermaysiz.`;
    } else if (dep > 0 && dep < due) {
      payHintEl.textContent =
        `Balansingizda ${fmtMoney(dep)} bor, lekin buyurtmaga yetmaydi (${fmtMoney(due)} kerak).`;
    } else {
      payHintEl.textContent = PAY_META[paymentMethod].hint;
    }
    payLabelEl.textContent = PAY_META[paymentMethod].sum;
  };

  const recomputeSummary = () => {
    sumItemsEl.textContent = fmtMoney(itemsTotalCached);
    const discount = Math.min(cashbackToUse, itemsTotalCached);
    rowDiscount.hidden = !(discount > 0);
    sumDiscountEl.textContent = "−" + fmtMoney(discount);
    sumTotalEl.textContent = fmtMoney(totalDue());
    // Cashback dasturi o'chirilgan bo'lsa "olasiz" satrini ko'rsatmaymiz.
    const earn = balance.cashback_enabled
      ? Math.floor((itemsTotalCached * (balance.cashback_percent || 0)) / 100 / 100) * 100
      : 0;
    rowEarn.hidden = !(earn > 0);
    sumEarnEl.textContent = "+" + fmtMoney(earn);
    payLabelEl.textContent = PAY_META[paymentMethod].sum;
  };

  const renderAddrUI = () => {
    if (location) {
      const niceLabel = addressLabel || "Tanlangan manzil";
      const icon = iconFor(addressLabel);
      addrArea.innerHTML = `
        <div class="addr-summary" id="addrSummary" role="button" tabindex="0">
          <div class="addr-summary__icon">${icon}</div>
          <div class="addr-summary__body">
            <div class="addr-summary__label">${escapeHtml(niceLabel)}</div>
            <div class="addr-summary__sub" style="font-family:ui-monospace,monospace">
              ${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}
            </div>
            ${addressDetails ? `<div class="addr-summary__sub">${escapeHtml(addressDetails)}</div>` : ""}
          </div>
          <div class="addr-summary__action">O'zgartirish ›</div>
        </div>
      `;
    } else {
      addrArea.innerHTML = `
        <div class="addr-summary addr-summary--empty" id="addrSummary" role="button" tabindex="0">
          <div class="addr-summary__icon">📍</div>
          <div class="addr-summary__body">
            <div class="addr-summary__label">Manzilni tanlang</div>
            <div class="addr-summary__sub">Saqlangan, joriy joyim yoki xaritadan</div>
          </div>
          <div class="addr-summary__action">Tanlash ›</div>
        </div>
      `;
    }
    const el = root.querySelector("#addrSummary");
    el.addEventListener("click", openAddressMenu);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openAddressMenu(); }
    });
  };

  function applyAddress(addr, label, details) {
    location = { latitude: Number(addr.latitude), longitude: Number(addr.longitude) };
    addressLabel = label || "";
    addressDetails = details || "";
    if (addressDetails && !noteInput.value.trim()) {
      noteInput.value = addressDetails;
    }
    renderAddrUI();
  }

  async function openAddressMenu() {
    // Saqlanganlardan tanlash YOKI xaritada belgilash. Alohida "GPS" tugmasi
    // yo'q — xarita ochilganda fon'da GPS chaqiriladi va pin avtomatik
    // ko'chadi (Wolt/Yandex pattern). Hech qachon bloklamaydi.
    const choices = [];
    if (savedAddresses.length) {
      for (const a of savedAddresses) {
        choices.push({
          html: `${iconFor(a.label)} <b>${escapeHtml(a.label)}</b>${a.is_default ? " (default)" : ""}`,
          action: () => applyAddress(a, a.label, a.details),
        });
      }
    }
    choices.push({
      html: `🗺 <b>Xaritadan tanlash</b>`,
      action: openMap,
    });
    // Saqlangan manzil bo'lmasa, menyu ko'rsatmaymiz — to'g'ridan-to'g'ri xarita.
    if (choices.length === 1) {
      openMap();
      return;
    }
    showAddressSheet(choices);
  }

  function showAddressSheet(choices) {
    const sheet = document.createElement("div");
    sheet.className = "bottom-sheet";
    sheet.innerHTML = `
      <div class="bottom-sheet__panel">
        <div class="bottom-sheet__head">
          <div class="bottom-sheet__title">Manzil tanlang</div>
          <button class="bottom-sheet__close" type="button" aria-label="Yopish">×</button>
        </div>
        <div class="bottom-sheet__list">
          ${choices.map((c, i) => `
            <button type="button" class="bottom-sheet__item" data-idx="${i}">
              <span class="bottom-sheet__item-body">${c.html}</span>
              <span class="bottom-sheet__item-chev">›</span>
            </button>
          `).join("")}
        </div>
      </div>
    `;
    document.body.appendChild(sheet);
    // Trigger CSS animatsiyasi keyingi frame'da
    requestAnimationFrame(() => sheet.classList.add("bottom-sheet--open"));

    const closeSheet = () => {
      sheet.classList.remove("bottom-sheet--open");
      setTimeout(() => sheet.remove(), 180);
    };
    sheet.querySelector(".bottom-sheet__close").addEventListener("click", closeSheet);
    sheet.addEventListener("click", (e) => { if (e.target === sheet) closeSheet(); });
    sheet.querySelectorAll(".bottom-sheet__item").forEach((el) => {
      el.addEventListener("click", () => {
        const idx = Number(el.getAttribute("data-idx"));
        closeSheet();
        try { choices[idx].action(); } catch (err) { console.error(err); }
      });
    });
  }

  async function openMap() {
    const result = await openMapPicker({
      initial: location || (savedAddresses[0] ? { latitude: savedAddresses[0].latitude, longitude: savedAddresses[0].longitude } : undefined),
      title: "Yetkazib berish nuqtasi",
    });
    if (!result) return;
    // Geocoded ko'cha/uy/mahalla nomi — address_details ga avto-to'ldiriladi
    // (mijoz tahrirlashi/xonadon qo'shishi mumkin). x,y baribir saqlanadi.
    applyAddress(result, "", result.address || "");
  }

  // ----- Cashback widget — admin tomonidan o'chirilgan bo'lsa, butunlay yashiriladi.
  // Qoplash birligi: 1000 so'm (CASHBACK_USE_UNIT). Slider 0, 1000, 2000... qadamlar.
  const renderCashback = () => {
    const enabled = Boolean(balance.cashback_enabled);
    const avail = Number(balance.cashback_balance || 0);
    const maxRatio = Number(balance.max_cashback_usage_ratio || 1.0);
    const UNIT = Number(balance.cashback_use_unit || 1000);
    // FLOOR to UNIT — buyurtmaga va balansga moslab
    const maxByItems = Math.floor((itemsTotalCached * maxRatio) / UNIT) * UNIT;
    const maxByBalance = Math.floor(avail / UNIT) * UNIT;
    const maxAllowed = Math.min(maxByBalance, maxByItems);

    if (!enabled || maxAllowed < UNIT) {
      cashbackArea.hidden = true;
      cashbackToUse = 0;
      return;
    }
    // Eski qiymatni saqlasak ham, slider step bilan moslashtiramiz
    if (cashbackToUse > maxAllowed) cashbackToUse = 0;
    cashbackToUse = Math.floor(cashbackToUse / UNIT) * UNIT;

    const fullCoverPossible = avail >= itemsTotalCached && maxRatio >= 1;
    const fullAmount = Math.floor(itemsTotalCached / UNIT) * UNIT;

    cashbackArea.hidden = false;
    cashbackArea.innerHTML = `
      <div class="bonus-row__head">
        <div>
          <div class="bonus-row__title">💎 Keshbek bilan to'lash</div>
          <div class="bonus-row__hint">
            Mavjud: <b>${fmtMoney(avail)}</b>. Eng ko'pi ${Math.round(maxRatio * 100)}% ulushini qoplaysiz.
          </div>
        </div>
        <div class="bonus-row__value" id="cbVal">−${fmtMoney(cashbackToUse)}</div>
      </div>
      <div class="range-row">
        <input type="range" id="cbSlider" min="0" max="${maxAllowed}" step="${UNIT}" value="${cashbackToUse}" />
        <div class="range-row__display" id="cbAmount">${fmtMoney(cashbackToUse)}</div>
      </div>
      ${fullCoverPossible ? `
        <button class="btn btn--xs btn--ghost" id="useAllCb" type="button" style="margin-top:6px">
          Hammasini ishlatish (${fmtMoney(fullAmount)})
        </button>` : ""}
    `;
    const slider = root.querySelector("#cbSlider");
    const cbVal = root.querySelector("#cbVal");
    const cbAmount = root.querySelector("#cbAmount");
    slider.addEventListener("input", () => {
      // Slider step=UNIT, lekin xavfsizlik uchun yana FLOOR
      const raw = Number(slider.value) || 0;
      cashbackToUse = Math.floor(raw / UNIT) * UNIT;
      cbVal.textContent = "−" + fmtMoney(cashbackToUse);
      cbAmount.textContent = fmtMoney(cashbackToUse);
      recomputeSummary();
      // Yakuniy summa o'zgardi — "Balansdan" tugmasining yetarlilik holati yangilansin.
      renderPayment();
    });
    const fullBtn = root.querySelector("#useAllCb");
    if (fullBtn) {
      fullBtn.addEventListener("click", () => {
        cashbackToUse = Math.min(maxAllowed, fullAmount);
        slider.value = String(cashbackToUse);
        cbVal.textContent = "−" + fmtMoney(cashbackToUse);
        cbAmount.textContent = fmtMoney(cashbackToUse);
        recomputeSummary();
        renderPayment();
      });
    }
  };

  // Bo'sh idishlar widget'i checkout'dan olib tashlangan — yetkazganda kuryer kiritadi.
  // Eski (mijoz tomondan kiritiladigan) UX o'rniga, mijoz checkout'da hech narsa
  // qilmaydi; kuryer ARRIVED holatda confirmation oynasida +/− bilan kiritadi.

  (async () => {
    // Hamma narsa parallel keladi, lekin UI render qilishdan oldin barchasini kutamiz —
    // shunda renderCashback `itemsTotalCached` ni to'g'ri o'qiydi (race yo'q).
    try {
      const [_, addrs, bal] = await Promise.all([
        loadItemsTotal(),
        api.addresses().catch(() => []),
        api.balance().catch(() => null),
      ]);
      savedAddresses = Array.isArray(addrs) ? addrs : [];
      if (bal) balance = bal;
    } catch (_) { /* silent — UI degraded mode'da ishlaydi */ }

    // Default manzil bo'lsa — oldindan tanlaymiz
    const def = savedAddresses.find((a) => a.is_default) || savedAddresses[0];
    if (def) applyAddress(def, def.label, def.details);
    else renderAddrUI();

    // Endi barcha ma'lumotlar tayyor — UI to'liq render qilamiz
    recomputeSummary();
    renderCashback();
    renderPayment();
  })();

  let busy = false;
  const submit = async () => {
    if (busy) return;
    if (!location) {
      toast("Avval manzilni tanlang.", { error: true });
      return openAddressMenu();
    }
    // +998 avto-normalizatsiya: '901234567' ham qabul qilinadi.
    const contact_phone = normalizePhone(phoneInput.value);
    if (!contact_phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", { error: true });
    phoneInput.value = contact_phone;
    const note = noteInput.value.trim();
    if (note.length < 1) return toast("Izoh kiriting.", { error: true });

    busy = true;
    setCTALoading(true);
    try {
      const order = await api.createOrder({
        items: cartItems,
        latitude: location.latitude,
        longitude: location.longitude,
        contact_phone,
        note,
        idempotency_key: ensureOrderKey(),
        address_label: addressLabel || "",
        address_details: addressDetails || "",
        cashback_to_use: cashbackToUse || 0,
        payment_method: paymentMethod,
        // bottles_returned — yetkazganda kuryer kiritadi, yaratishda 0.
      });
      hapticNotification("success");
      cart.clear();
      rotateOrderKey();  // keyingi savatcha uchun yangi key generatsiya qilinsin
      go("success", { order });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Xatolik";
      hapticNotification("error");
      toast(msg, { error: true });
    } finally {
      busy = false;
      setCTALoading(false);
    }
  };

  showCTA("Buyurtmani tasdiqlash", submit);

  return () => {
    hideBackButton();
    hideCTA();
  };
}
