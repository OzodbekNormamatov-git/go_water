// Kuryer Mini App — mavjud buyurtmalar (polling), claim (race-safe), transitsiyalar, statistika.

const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try { tg.ready(); tg.expand(); } catch (_) {} }
const initData = tg ? tg.initData : "";

const screen = document.getElementById("screen");
const tabsEl = document.getElementById("tabs");
const toastEl = document.getElementById("toast");
const availBadge = document.getElementById("availBadge");

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (n) => (Math.round(Number(n) || 0)).toLocaleString("ru-RU").replace(/,/g, " ") + " so'm";

// To'lov usuli qatori — kuryer naqd olishi kerakmi-yo'qmi, karta yonida darhol ko'rinsin.
function payLineHtml(o) {
  if (o.collect_cash === false) {
    return `<div style="font-weight:700;color:var(--danger, #b91c1c);background:var(--danger-tint, #fef2f2);border:1px solid var(--danger-border, #fca5a5);border-radius:8px;padding:6px 8px;margin-top:6px">⚠️ ${esc(o.payment_method_label)} — mijozdan NAQD OLINMAYDI</div>`;
  }
  return `<div style="font-weight:700;color:var(--brand-deep);margin-top:6px">${esc(o.payment_method_label || "💵 Naqd")} — mijozdan naqd oling</div>`;
}

let _toastT = null;
function toast(msg, isErr) {
  toastEl.textContent = msg;
  toastEl.className = isErr ? "show err" : "show";
  clearTimeout(_toastT);
  _toastT = setTimeout(() => { toastEl.className = ""; }, 2600);
  if (tg && tg.HapticFeedback) { try { tg.HapticFeedback.notificationOccurred(isErr ? "error" : "success"); } catch (_) {} }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Authorization": `tma ${initData}`, "Accept": "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (_) {
    throw new Error("Tarmoq xatosi");
  }
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((data && (data.message || data.detail)) || `Xatolik (${res.status})`);
  return data;
}

// ---------------------- State + tabs ----------------------
let tab = "available";
let pollTimer = null;

tabsEl.querySelectorAll("button[data-tab]").forEach((b) => {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
});

function switchTab(next) {
  tab = next;
  tabsEl.querySelectorAll("button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (tab === "available") { renderAvailable(); pollTimer = setInterval(renderAvailable, 5000); }
  else if (tab === "active") { renderActive(); pollTimer = setInterval(renderActive, 5000); }
  else { renderStats(); }
}

function loading() { screen.innerHTML = `<div class="empty"><div class="empty__icon">⏳</div>Yuklanmoqda…</div>`; }
function errorBox(msg) {
  screen.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div>${esc(msg)}</div>`;
}

// ---------------------- Available (NEW orders) ----------------------
let _availFirst = true;
async function renderAvailable() {
  if (_availFirst) loading();
  let list;
  try { list = await api("/api/courier/available"); }
  catch (e) { if (_availFirst) errorBox(e.message); return; }
  _availFirst = false;
  availBadge.hidden = !(list && list.length);
  if (list && list.length) availBadge.textContent = String(list.length);
  if (!list || !list.length) {
    screen.innerHTML = `<div class="empty"><div class="empty__icon">📭</div>Hozircha yangi buyurtma yo'q.<div class="muted" style="margin-top:6px">Yangi buyurtma kelsa shu yerda chiqadi.</div></div>`;
    return;
  }
  screen.innerHTML = list.map((o) => `
    <div class="card">
      <div class="row"><span class="pill pill--new">🆕 ${esc(o.display_number)}</span><span style="flex:1"></span><span class="total">${money(o.total_amount)}</span></div>
      ${payLineHtml(o)}
      <div class="items">${o.items.map((it) => `${esc(it.food_name)} × ${it.quantity}`).join(", ")}</div>
      ${o.address_details ? `<div class="addr">📍 ${esc(o.address_details)}</div>` : ""}
      <div class="muted">🗺 <a class="tel" href="${esc(o.map_url)}" target="_blank">Xaritada ko'rish</a></div>
      ${o.note ? `<div class="muted">📝 ${esc(o.note)}</div>` : ""}
      <button class="btn btn--claim" data-claim="${o.id}">✅ Men olaman</button>
    </div>`).join("");
  screen.querySelectorAll("[data-claim]").forEach((b) => b.addEventListener("click", () => claim(Number(b.dataset.claim), b)));
}

async function claim(orderId, btn) {
  btn.disabled = true; btn.textContent = "Olinmoqda…";
  try {
    await api(`/api/courier/orders/${orderId}/claim`, { method: "POST" });
    toast("✅ Buyurtma sizniki!");
    switchTab("active");
  } catch (e) {
    // 409 — boshqa kuryer ulgurdi yoki sizda tugallanmagan buyurtma bor.
    toast(e.message, true);
    renderAvailable();  // ro'yxatni yangilaymiz (olingan buyurtma yo'qoladi)
  }
}

// ---------------------- Active (my order) ----------------------
let _bottles = 0;      // mijozdan qaytarib olingan bo'sh idishlar
let _bottlesMax = 0;   // mijozning tarixda yig'ilgan idishlari — qaytarish chegarasi
let _delivered = {};   // { item_id: yetkazilgan_dona } — kuryer haqiqatda bergan son
let _priceById = {};   // { item_id: unit_price } — taxminiy summa uchun
let _activeItems = []; // [{id, quantity}] — kartaga kelgan asl donalar; o'zgargan bo'lsa /delivered-items
let _payMethod = "cash";   // ARRIVED: kuryer tanlagan yakuniy to'lov usuli (cash/card)
let _payOriginal = "cash"; // asl — o'zgargan bo'lsagina serverga yuboriladi
let _payLocked = false;    // deposit buyurtma — to'lov usuli o'zgartirilmaydi
let _editOrderId = null;   // ARRIVED tasdiq kartasi qaysi order uchun ochilgan (poll buzmasin)

async function renderActive() {
  let list;
  try { list = await api("/api/courier/active"); }
  catch (e) {
    // Xatoni faqat ARRIVED tasdiq kartasi HOZIR ekranda bo'lsa jim yutamiz
    // (poll takrori input'ni buzmasin); aks holda ko'rsatamiz — masalan tab
    // qaytishda ekranda eski kontent qolib ketmasin.
    if (!(_editOrderId && document.getElementById("btlVal"))) errorBox(e.message);
    return;
  }
  if (!list || !list.length) {
    _editOrderId = null;
    screen.innerHTML = `<div class="empty"><div class="empty__icon">🚚</div>Sizda hozir faol buyurtma yo'q.<div class="muted" style="margin-top:6px">"Mavjud" bo'limidan buyurtma oling.</div></div>`;
    return;
  }
  const o = list[0];
  const st = o.status;

  // ARRIVED — yakuniy tasdiq kartasi. Kuryer sonlarni tinch kiritishi uchun:
  //   * poll DAVOM etadi (agar admin buyurtmani bekor qilsa yoki olib qo'ysa,
  //     "active" ro'yxati bo'shaydi va kuryer buni ko'radi) — LEKIN tasdiq
  //     kartasi allaqachon ekranda bo'lsa QAYTA CHIZMAYMIZ (input saqlanadi).
  //   * holat (_bottles/_delivered/_payMethod) FAQAT shu orderга birinchi
  //     kirganda init qilinadi; tab almashtirilib qaytilsa — saqlangan holatдан.
  if (st === "ARRIVED") {
    const cardShown = !!document.getElementById("btlVal");  // karta hozir ekrandami
    if (_editOrderId === o.id && cardShown) return;   // poll takrori — input'ga tegmaymiz
    if (_editOrderId !== o.id) {
      _editOrderId = o.id;
      // Cap 500 — server route chegarasi (BottlesIn le=500) bilan mos:
      // juda katta balansda ham 422 o'rniga to'g'ri chegara ko'rsatiladi.
      _bottlesMax = Math.min(500, Math.max(0, Number(o.customer_bottles_balance || 0)));
      _bottles = Math.min(Number(o.bottles_returned || 0), _bottlesMax);
      _delivered = {};
      _priceById = {};
      (o.items || []).forEach((it) => {
        _delivered[it.id] = Number(it.quantity || 0);
        _priceById[it.id] = Number(it.unit_price || 0);
      });
      _activeItems = (o.items || []).map((it) => ({ id: it.id, quantity: Number(it.quantity || 0) }));
      _payLocked = (o.payment_method === "deposit");
      _payMethod = o.payment_method === "card" ? "card" : "cash";
      _payOriginal = o.payment_method;   // deposit bo'lsa ham asl saqlanadi (o'zgarmaydi)
    }
    // else: shu order, lekin karta ekranda yo'q (tab qaytdi) — holat saqlanadi, pastda qayta chizamiz
  } else {
    _editOrderId = null;
  }

  let actions = "";
  if (st === "ACCEPTED") {
    actions = `<button class="btn btn--go" data-act="delivering" data-id="${o.id}">🚗 Yo'lga chiqdim</button>`;
  } else if (st === "DELIVERING") {
    actions = `<button class="btn btn--go" data-act="arrived" data-id="${o.id}">📍 Yetib keldim</button>`;
  } else if (st === "ARRIVED") {
    const itemSteppers = (o.items || []).map((it) => {
      const ordered = Number(it.ordered_quantity || 0);
      // Joriy (saqlangan) kiritilgan qiymat — server emas, kuryer tahriri.
      const cur = Number(_delivered[it.id] != null ? _delivered[it.id] : (it.quantity || 0));
      const orderedNote = ordered !== cur
        ? `<div class="muted" style="font-size:12px;text-align:center">buyurtma: ${ordered}</div>` : "";
      return `
        <div style="margin-top:12px">
          <div style="font-weight:700;text-align:center">${esc(it.food_name)}</div>
          ${orderedNote}
          <div class="stepper">
            <button data-item="dec" data-item-id="${it.id}" type="button">−</button>
            <div class="val" id="dlv_${it.id}">${cur}</div>
            <button data-item="inc" data-item-id="${it.id}" type="button">+</button>
          </div>
        </div>`;
    }).join("");
    // To'lov usuli — mijoz "naqd" degan bo'lsa ham kuryer kartaga o'zgartirishi mumkin.
    // Depozit (balansdan) buyurtma oldindan to'langan — toggle ko'rsatilmaydi.
    const payBlock = _payLocked
      ? `<div style="font-weight:700;margin-top:14px;text-align:center;color:var(--brand-deep)">💰 Balansdan to'langan</div>`
      : `
        <div style="font-weight:700;margin-top:14px;text-align:center">💳 To'lov usuli</div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:6px">
          <button type="button" data-pay="cash" class="paybtn">💵 Naqd</button>
          <button type="button" data-pay="card" class="paybtn">💳 Karta</button>
        </div>`;
    actions = `
      <div style="margin-top:12px;border:1px solid var(--brand);border-radius:12px;padding:12px;background:var(--brand-tint, #eef4fb)">
        <div style="font-weight:700;margin-bottom:2px">📋 Yakuniy tasdiq</div>
        <div class="muted" style="font-size:12px">Har mahsulot uchun haqiqatda yetkazgan donani kiriting</div>
        ${itemSteppers}
        <div style="font-weight:700;margin-top:14px;text-align:center">♻️ Mijozdan nechta bo'sh idish oldingiz?</div>
        <div class="stepper">
          <button data-bottle="dec" type="button">−</button>
          <div class="val" id="btlVal">${_bottles}</div>
          <button data-bottle="inc" type="button">+</button>
        </div>
        <div class="muted" style="text-align:center;font-size:12px">${
          _bottlesMax > 0
            ? `Mijozda jami <b>${_bottlesMax}</b> ta idish bor — bundan ortiq qaytarib bo'lmaydi. Olmagan bo'lsangiz — 0.`
            : `Mijozda yig'ilgan idish yo'q — qaytarib olinmaydi (0 qoladi).`
        }</div>
        ${payBlock}
        <div style="margin-top:12px;text-align:center;font-weight:800;color:var(--brand-deep)" id="dlvSummary"></div>
      </div>
      <button class="btn btn--ok" data-act="delivered" data-id="${o.id}">✅ Yetkazib berildi — yopish</button>
      <div class="muted" style="font-size:12px;text-align:center;margin-top:4px">Bossangiz: pul + idishlar javobgarligi sizda, buyurtma yopiladi.</div>`;
  }
  screen.innerHTML = `
    <div class="card">
      <div class="row"><span class="pill pill--act">${esc(o.status_label)}</span><span style="flex:1"></span><span class="total">${money(o.total_amount)}</span></div>
      ${st === "ARRIVED" ? "" : payLineHtml(o)}
      <div class="muted" style="margin-top:2px">${esc(o.display_number)}</div>
      <div class="items">${o.items.map((it) => `${esc(it.food_name)} × ${it.quantity}`).join(", ")}</div>
      ${o.address_details ? `<div class="addr">📍 ${esc(o.address_details)}</div>` : ""}
      <div class="row" style="gap:14px;margin-top:4px">
        ${o.contact_phone ? `<a class="tel" href="tel:${esc(o.contact_phone)}">📞 ${esc(o.contact_phone)}</a>` : ""}
        <a class="tel" href="${esc(o.map_url)}" target="_blank">🗺 Xarita</a>
      </div>
      ${o.note ? `<div class="muted" style="margin-top:4px">📝 ${esc(o.note)}</div>` : ""}
      ${actions}
    </div>`;
  // Stepper'lar
  const valEl = document.getElementById("btlVal");
  const sumEl = document.getElementById("dlvSummary");
  const syncSummary = () => {
    if (!sumEl) return;
    let est = 0;
    for (const id in _delivered) est += (_priceById[id] || 0) * _delivered[id];
    sumEl.textContent = `Taxminiy summa: ${money(est)}`;
  };
  syncSummary();
  screen.querySelectorAll("[data-bottle]").forEach((b) => b.addEventListener("click", () => {
    // Cheg'ara: mijoz TARIXDA yig'gan idishlaridan oshirib bo'lmaydi —
    // "hozir olib kelingan suv idishini qaytarib oldim" bo'lishi mumkin emas.
    _bottles = b.dataset.bottle === "inc"
      ? Math.min(_bottlesMax, _bottles + 1)
      : Math.max(0, _bottles - 1);
    if (valEl) valEl.textContent = String(_bottles);
  }));
  screen.querySelectorAll("[data-item]").forEach((b) => b.addEventListener("click", () => {
    const id = Number(b.dataset.itemId);
    const cur = Number(_delivered[id] || 0);
    _delivered[id] = b.dataset.item === "inc" ? Math.min(999, cur + 1) : Math.max(0, cur - 1);
    const cell = document.getElementById(`dlv_${id}`);
    if (cell) cell.textContent = String(_delivered[id]);
    syncSummary();
  }));
  // To'lov usuli toggle — tanlangan tugma ajralib turadi (mahalliy holat).
  const paintPay = () => {
    screen.querySelectorAll("[data-pay]").forEach((x) => {
      const on = x.dataset.pay === _payMethod;
      // Ranglar CSS tokenlaridan (index.html belgilaydi) — dizayn tizimi bilan uyg'un.
      x.style.cssText = "flex:1;max-width:130px;padding:9px;border-radius:10px;font-weight:700;cursor:pointer;"
        + (on ? "background:var(--brand);color:#fff;border:1px solid var(--brand)"
              : "background:var(--surface, #fff);color:var(--text, #111);border:1px solid var(--border, #d1d5db)");
    });
  };
  paintPay();
  screen.querySelectorAll("[data-pay]").forEach((b) => b.addEventListener("click", () => {
    _payMethod = b.dataset.pay;
    paintPay();
  }));
  // Actions
  screen.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => doAction(b.dataset.act, Number(b.dataset.id), b)));
}

async function doAction(act, orderId, btn) {
  if (act === "delivered") {
    btn.disabled = true;
    try {
      // Ketma-ketlik: (a) dona o'zgargan → /delivered-items, (b) to'lov o'zgargan →
      // /payment-method, (c) /bottles, (d) /delivered. Har biri xato bersa to'xtaydi.
      // MUHIM: har muvaffaqiyatli POST'dan keyin mahalliy BAZA yangilanadi —
      // aks holda qisman xatodan keyin qayta bosishда "o'zgarmagan" deb hisoblanib,
      // server eski/oshirilgan qiymat bilan yopilardi (pul hisobi buzilardi).
      const changed = _activeItems.some((it) => Number(_delivered[it.id] || 0) !== it.quantity);
      if (changed) {
        const items = _activeItems.map((it) => ({ item_id: it.id, quantity: Number(_delivered[it.id] || 0) }));
        await api(`/api/courier/orders/${orderId}/delivered-items`, { method: "POST", body: { items } });
        _activeItems = _activeItems.map((it) => ({ id: it.id, quantity: Number(_delivered[it.id] || 0) }));
      }
      if (!_payLocked && _payMethod !== _payOriginal) {
        await api(`/api/courier/orders/${orderId}/payment-method`, { method: "POST", body: { method: _payMethod } });
        _payOriginal = _payMethod;
      }
      await api(`/api/courier/orders/${orderId}/bottles`, { method: "POST", body: { value: _bottles } });
      const done = await api(`/api/courier/orders/${orderId}/delivered`, { method: "POST" });
      _editOrderId = null;
      toast(`📦 Yetkazildi — ${money(done && done.total_amount)}. Rahmat!`);
      switchTab("available");
    } catch (e) {
      // Xato — input SAQLANADI (qayta chizmaymiz), kuryer tuzatib qayta uradi.
      btn.disabled = false;
      toast(e.message, true);
    }
    return;
  }
  btn.disabled = true;
  try {
    await api(`/api/courier/orders/${orderId}/${act}`, { method: "POST" });
    toast(act === "arrived" ? "📍 Mijozga xabar yuborildi" : "🚗 Yo'lga chiqdingiz");
  } catch (e) {
    toast(e.message, true);
  }
  _editOrderId = null;
  renderActive();
}

// ---------------------- Stats ----------------------
async function renderStats() {
  loading();
  let s;
  try { s = await api("/api/courier/stats"); }
  catch (e) { errorBox(e.message); return; }
  const cash = Number(s.cash_balance || 0);
  screen.innerHTML = `
    <div class="card">
      <div style="font-weight:700;margin-bottom:8px">📊 Yetkazib berilgan buyurtmalar</div>
      <div class="row"><span class="muted" style="flex:1">Bugun</span><span class="num">${s.today}</span></div>
      <div class="row"><span class="muted" style="flex:1">Shu oyda</span><span class="num">${s.month}</span></div>
      <div class="row"><span class="muted" style="flex:1">Shu yilda</span><span class="num">${s.year}</span></div>
      <div class="row"><span class="muted" style="flex:1">Hammasi</span><span class="num">${s.total}</span></div>
    </div>
    ${cash > 0 ? `
    <div class="card" style="border-color:var(--warning-border, #fcd34d);background:var(--warning-tint, #fffbeb)">
      <div style="font-weight:700">💵 Qo'lingizdagi naqd</div>
      <div class="total" style="margin-top:4px">${money(cash)}</div>
      <div class="muted" style="margin-top:4px">Bu summani kompaniyaga topshirishingiz kerak.</div>
    </div>` : ""}`;
}

// ---------------------- Boot ----------------------
(async () => {
  let me;
  try { me = await api("/api/courier/me"); }
  catch (e) {
    errorBox(e.message + "\nKuryer botiga /start yuborganingizni va admin sizni aktiv qilganini tekshiring.");
    return;
  }
  // Faol buyurtmasi bo'lsa, darhol "Menikim" tabini ochamiz.
  switchTab(me.active_order_id ? "active" : "available");
})();
