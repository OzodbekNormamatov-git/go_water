import { api, ApiError, tgApp } from "../api.js";
import { fmtMoney, fmtCount, fmtDate, escapeHtml, normalizePhone } from "../format.js";
import { toast } from "../toast.js";
import { renderPagination, bindPagination } from "../pagination.js";

const PAGE_SIZE = 20;

// ---------------------- Telefon raqamlar API ----------------------
// api.js dagi `request` pattern'ining lokal nusxasi (o'sha auth header,
// o'sha xato shakli) — mijoz raqamlari endpointlari uchun.

const _initData = tgApp ? tgApp.initData : "";

async function phonesRequest(path, { method = "GET", body } = {}) {
  const headers = {
    "Authorization": `tma ${_initData}`,
    "Accept": "application/json",
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, {
      method, headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
    // api.js kanonik xulqi bilan bir xil kod mapping (drift bo'lmasin).
    if (res.status === 401) throw new ApiError("unauthorized", message);
    if (res.status === 403) throw new ApiError("forbidden", message);
    throw new ApiError(`http_${res.status}`, message);
  }
  return data;
}

const phonesApi = {
  list:       (customerId) => phonesRequest(`/api/admin/customers/${customerId}/phones`),
  add:        (customerId, body) => phonesRequest(`/api/admin/customers/${customerId}/phones`, { method: "POST", body }),
  remove:     (customerId, phoneId) => phonesRequest(`/api/admin/customers/${customerId}/phones/${phoneId}`, { method: "DELETE" }),
  setPrimary: (customerId, phoneId) => phonesRequest(`/api/admin/customers/${customerId}/phones/${phoneId}/primary`, { method: "POST" }),
};

// Telefon 409 javobi {error: <kod>, message: <tarjima>} shaklida keladi —
// odatda message'ning o'zi yetarli; map faqat kod kelib qolgan holat uchun
// zaxira (backend str(e) o'rniga kod yuborsa ham UI tushunarli qoladi).
const PHONE_ERR_TEXT = {
  "phone_taken":               "Bu raqam boshqa mijozga biriktirilgan",
  "phone_primary_undeletable": "Asosiy raqam o'chirilmaydi — avval boshqa raqamni asosiy qiling",
  "phone_limit_reached":       "Raqamlar soni cheklovga yetdi",
  "phone_invalid":             "Telefon raqam noto'g'ri formatda. Masalan: +998901234567",
};

function phoneErrMsg(e) {
  return PHONE_ERR_TEXT[e.message] || e.message || "Xatolik";
}

// ---------------------- Rol (admin | operator) ----------------------
// api.me() ni bir marta chaqirib modul ichida saqlaymiz. Operatorga balans
// tahrirlash (keshbek/idish/depozit), ledger va telefon o'chirish/asosiy
// qilish YOPIQ — faqat ro'yxat, qidiruv, mijoz qo'shish, telefon ko'rish+qo'shish.
let _role = null;

async function loadRole() {
  if (_role) return _role;
  try {
    const me = await api.me();
    _role = (me && me.role) || "operator";
    return _role;
  } catch {
    // Vaqtinchalik xato — natijani KESHLAMAYMIZ: keyingi renderда qayta
    // urinadi (aks holda admin sessiya oxirigacha operator rejimida qolardi).
    return "operator";  // shu render uchun cheklangan (xavfsiz) rejim
  }
}

export async function renderCustomers(root) {
  const role = await loadRole();
  const isAdmin = role === "admin";
  root.innerHTML = `
    <div class="filters" style="justify-content:space-between;gap:10px;flex-wrap:wrap">
      <input class="input" id="search" placeholder="Ism yoki telefon bo'yicha izlash…" style="flex:1;min-width:180px" />
      <button class="btn btn--primary" id="newCustomerBtn" type="button">➕ Yangi mijoz</button>
      <div class="muted" id="totalLabel" style="font-size:12px"></div>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th class="hide-narrow">#</th>
            <th>Ism</th>
            <th>Telefon</th>
            <th class="hide-narrow">Telegram ID</th>
            <th class="hide-narrow">Ro'yxatdan</th>
            <th style="text-align:right">Buyurtmalar</th>
            <th style="text-align:right">Jami</th>
            <th style="text-align:right">Keshbek</th>
            <th style="text-align:right">Balans</th>
            <th style="text-align:right">Idishlar</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="tbody"><tr><td colspan="11" class="loading">Yuklanmoqda…</td></tr></tbody>
      </table>
    </div>
    <div id="paginationWrap"></div>
  `;

  const tbody = document.getElementById("tbody");
  const search = document.getElementById("search");
  const totalLabel = document.getElementById("totalLabel");
  const paginationWrap = document.getElementById("paginationWrap");
  const newCustomerBtn = document.getElementById("newCustomerBtn");

  let timer = null;
  let cache = [];           // joriy sahifadagi mijozlar
  let total = 0;
  let currentQuery = "";
  let page = 1;             // 1-based
  let loading = false;

  function rowHtml(u) {
    return `
      <tr data-id="${u.id}">
        <td class="hide-narrow">${u.id}</td>
        <td><b>${escapeHtml(u.full_name)}</b></td>
        <td>${escapeHtml(u.phone_number)}</td>
        <td class="hide-narrow"><code>${u.telegram_id}</code></td>
        <td class="hide-narrow muted">${escapeHtml(fmtDate(u.created_at))}</td>
        <td style="text-align:right">${fmtCount(u.orders_count)}</td>
        <td style="text-align:right;font-weight:700">${fmtMoney(u.total_spent)}</td>
        <td style="text-align:right;color:var(--brand-primary);font-weight:600">${fmtMoney(u.cashback_balance)}</td>
        <td style="text-align:right;color:var(--brand-deep);font-weight:600">${fmtMoney(u.deposit_balance)}</td>
        <td style="text-align:right;font-weight:600">${fmtCount(u.bottles_balance)}</td>
        <td style="text-align:right">
          <button class="btn btn--xs btn--secondary js-edit" type="button">⚙️</button>
        </td>
      </tr>
    `;
  }

  function bindRowHandlers() {
    tbody.querySelectorAll(".js-edit").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const tr = e.target.closest("tr");
        const id = Number(tr.getAttribute("data-id"));
        const u = cache.find((x) => x.id === id);
        if (u) openAdjust(u, () => loadPage(), isAdmin);
      });
    });
  }

  function renderRows() {
    if (!cache.length) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty"><div class="empty__icon">👤</div><div class="empty__text">Mijoz topilmadi.</div></td></tr>`;
      paginationWrap.innerHTML = "";
      totalLabel.textContent = "";
      return;
    }
    tbody.innerHTML = cache.map(rowHtml).join("");
    bindRowHandlers();

    totalLabel.textContent = `${fmtCount(total)} ta mijoz`;
    paginationWrap.innerHTML = renderPagination({ page, pageSize: PAGE_SIZE, total });
    bindPagination(paginationWrap, (newPage) => {
      page = newPage;
      loadPage();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  async function loadPage() {
    if (loading) return;
    loading = true;
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const res = await api.customers(currentQuery, { limit: PAGE_SIZE, offset });
      const pageData = Array.isArray(res) ? { items: res, total: res.length } : res;
      cache = pageData.items || [];
      total = Number(pageData.total || 0);

      // Search filter o'zgartirilsa — joriy sahifa mavjud bo'lmasligi mumkin.
      // Oxirgi mavjud sahifaga qaytaramiz (UX'da "bo'sh sahifa" ko'rsatish o'rniga).
      if (cache.length === 0 && total > 0 && page > 1) {
        page = Math.max(1, Math.ceil(total / PAGE_SIZE));
        await loadPage();
        return;
      }
      renderRows();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
      paginationWrap.innerHTML = "";
    } finally {
      loading = false;
    }
  }

  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      currentQuery = search.value.trim();
      page = 1;  // search o'zgartirilsa — 1-sahifaga qaytamiz
      loadPage();
    }, 280);
  });

  // Yangi mijoz qo'shish — operator ham qo'sha oladi (backend operator_required).
  newCustomerBtn.addEventListener("click", () => {
    openCreateCustomer(() => {
      // Yangi mijoz qo'shilgach — ro'yxatni yangilaymiz (1-sahifadan).
      page = 1;
      currentQuery = "";
      search.value = "";
      loadPage();
    });
  });

  loadPage();
}

// ---------------------- Yangi mijoz modali ----------------------
// api.createCustomer({full_name, phone}) → {id, full_name, phone_number,
// has_started_bot, created}. created===false bo'lsa telefon allaqachon
// mavjud mijozniki edi (dublikat yaratilmadi).
function openCreateCustomer(onCreated) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">➕ Yangi mijoz</h3>
        <button class="modal__close" type="button">×</button>
      </div>
      <div class="modal__body">
        <label class="label">Ism</label>
        <input class="input" id="ncName" placeholder="Mijoz ismi" maxlength="120" />

        <label class="label" style="margin-top:14px">Telefon</label>
        <input class="input" id="ncPhone" type="tel" placeholder="+998901234567" />
        <p class="muted" style="font-size:11px;margin-top:4px">Masalan: 901234567 yoki +998901234567</p>

        <label class="label" style="margin-top:14px">Mijozda nechta idish bor</label>
        <input class="input" id="ncBottles" type="number" inputmode="numeric" min="0" max="500" step="1" value="0" />
        <p class="muted" style="font-size:11px;margin-top:4px">
          Mijozda hozir yig'ilgan (qaytariladigan) idishlar soni — kuryer keyin
          shu chegaragacha qaytarib oladi. Bilmasangiz 0 qoldiring.
        </p>
      </div>
      <div class="modal__foot">
        <button class="btn" id="ncCancel" type="button">Bekor qilish</button>
        <button class="btn btn--primary" id="ncSave" type="button">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector(".modal__close").addEventListener("click", close);
  backdrop.querySelector("#ncCancel").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  const nameEl = backdrop.querySelector("#ncName");
  const phoneEl = backdrop.querySelector("#ncPhone");
  const bottlesEl = backdrop.querySelector("#ncBottles");
  const saveBtn = backdrop.querySelector("#ncSave");
  nameEl.focus();

  saveBtn.addEventListener("click", async () => {
    const fullName = nameEl.value.trim();
    const phoneRaw = phoneEl.value.trim();
    if (fullName.length < 2) return toast("Ism juda qisqa", "error");
    if (phoneRaw.length < 4) return toast("Telefon raqam kiriting", "error");
    const phone = normalizePhone(phoneRaw);
    if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    const bottles = Math.max(0, Math.min(500, Math.floor(Number(bottlesEl.value) || 0)));

    saveBtn.disabled = true;
    try {
      const r = await api.createCustomer({ full_name: fullName, phone, bottles });
      if (r && r.created === false) {
        // Server mavjud mijozga TEGMAYDI (rename_existing=false, idish ham
        // yozilmaydi) — operator kimniki ekanini ko'rsin va ro'yxatdan topsin.
        toast(`Bu raqam mavjud mijozniki: ${r.full_name} — ro'yxatdan toping (kiritilgan ism/idish saqlanmadi)`, "error");
      } else {
        toast("Mijoz qo'shildi", "success");
        close();
        onCreated && onCreated();
      }
    } catch (e) {
      // 400 (name_too_short, phone_invalid, ...) — o'zbekcha tarjima bo'lsa ishlatamiz.
      toast(phoneErrMsg(e), "error");
    } finally {
      saveBtn.disabled = false;
    }
  });
}


function openAdjust(u, onSaved, isAdmin) {
  // Balans tahrirlash (keshbek/idish/depozit) + ledger faqat ADMIN uchun.
  // Operator faqat mijoz telefon raqamlarini ko'radi va qo'sha oladi.
  const adminSectionsHtml = isAdmin ? `
        <div class="balance-grid" style="margin-bottom:14px;grid-template-columns:1fr 1fr 1fr">
          <div class="balance-card">
            <div class="balance-card__label">Keshbek</div>
            <div class="balance-card__value" id="cbView">${fmtMoney(u.cashback_balance)}</div>
          </div>
          <div class="balance-card">
            <div class="balance-card__label">Bo'sh idishlar</div>
            <div class="balance-card__value" id="btView">${fmtCount(u.bottles_balance)}</div>
          </div>
          <div class="balance-card">
            <div class="balance-card__label">Balans (avans)</div>
            <div class="balance-card__value" id="depView">${fmtMoney(u.deposit_balance)}</div>
          </div>
        </div>

        <label class="label">Keshbekka qo'shish / ayirish (so'm)</label>
        <div style="display:flex;gap:8px">
          <input class="input" id="cbDelta" type="number" step="100" placeholder="Misol: 5000 yoki -1000" />
          <button class="btn btn--secondary" id="cbApply" type="button">Qo'llash</button>
        </div>
        <p class="muted" style="font-size:11px;margin-top:4px">Manfiy qiymat — ayirish. Yakuniy balans manfiy bo'lib qola olmaydi.</p>

        <label class="label" style="margin-top:14px">Idishlar (+/−)</label>
        <div style="display:flex;gap:8px">
          <input class="input" id="btDelta" type="number" step="1" placeholder="Misol: 3 yoki -2" />
          <button class="btn btn--secondary" id="btApply" type="button">Qo'llash</button>
        </div>
        <p class="muted" style="font-size:11px;margin-top:4px">Mijoz idish qaytarib oldi — manfiy; qo'shimcha berdi — musbat.</p>

        <label class="label" style="margin-top:14px">Balans (avans) o'zgartirish</label>
        <div style="display:flex;gap:8px">
          <input class="input" id="depDelta" type="number" step="1000" placeholder="Misol: 500000 yoki -100000" />
          <button class="btn btn--secondary" id="depApply" type="button">Qo'llash</button>
        </div>
        <p class="muted" style="font-size:11px;margin-top:4px">Musbat = mijoz pul o'tkazdi (to'ldirish). Manfiy = tuzatish.</p>
  ` : "";

  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">${escapeHtml(u.full_name)}</h3>
        <button class="modal__close" type="button">×</button>
      </div>
      <div class="modal__body">
        ${adminSectionsHtml}
        <label class="label"${isAdmin ? ` style="margin-top:16px"` : ""}>📞 Telefon raqamlar</label>
        <div id="phList"><div class="muted" style="font-size:12px">Yuklanmoqda…</div></div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <input class="input" id="phNew" type="tel" placeholder="+998901234567" style="flex:2;min-width:150px" />
          <input class="input" id="phLabel" placeholder="Izoh (ish, uy…)" maxlength="40" style="flex:1;min-width:110px" />
        </div>
        <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
          ${isAdmin ? `<label class="muted" style="font-size:12px;display:flex;align-items:center;gap:6px;cursor:pointer;margin:0">
            <input type="checkbox" id="phPrimary" /> Asosiy qilish
          </label>` : ""}
          <div style="flex:1"></div>
          <button class="btn btn--secondary" id="phAdd" type="button">+ Raqam qo'shish</button>
        </div>
      </div>
      <div class="modal__foot">
        <button class="btn" id="closeBtn" type="button">Yopish</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector(".modal__close").addEventListener("click", close);
  backdrop.querySelector("#closeBtn").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  // Balans tahrirlash handlerlari — faqat admin (inputlar operatorda render
  // qilinmaydi, shu sabab handlerlarni ham faqat admin uchun ulaymiz).
  if (isAdmin) {
    backdrop.querySelector("#cbApply").addEventListener("click", async () => {
      const delta = Number(backdrop.querySelector("#cbDelta").value);
      if (!Number.isFinite(delta) || delta === 0) {
        return toast("Qiymat kiriting", "error");
      }
      try {
        const r = await api.adjustCashback(u.id, { delta, reason: "admin manual" });
        backdrop.querySelector("#cbView").textContent = fmtMoney(r.cashback_balance);
        backdrop.querySelector("#cbDelta").value = "";
        toast("Keshbek yangilandi", "success");
        onSaved && onSaved();
      } catch (e) {
        toast(e.message || "Xatolik", "error");
      }
    });

    backdrop.querySelector("#btApply").addEventListener("click", async () => {
      const delta = Number(backdrop.querySelector("#btDelta").value);
      if (!Number.isFinite(delta) || delta === 0) {
        return toast("Qiymat kiriting", "error");
      }
      try {
        const r = await api.adjustBottles(u.id, { delta, reason: "admin manual" });
        backdrop.querySelector("#btView").textContent = fmtCount(r.bottles_balance);
        backdrop.querySelector("#btDelta").value = "";
        toast("Idishlar balansi yangilandi", "success");
        onSaved && onSaved();
      } catch (e) {
        toast(e.message || "Xatolik", "error");
      }
    });

    backdrop.querySelector("#depApply").addEventListener("click", async () => {
      const delta = Number(backdrop.querySelector("#depDelta").value);
      if (!Number.isFinite(delta) || delta === 0) {
        return toast("Qiymat kiriting", "error");
      }
      try {
        const r = await api.adjustDeposit(u.id, { delta, reason: "admin manual" });
        backdrop.querySelector("#depView").textContent = fmtMoney(r.deposit_balance);
        backdrop.querySelector("#depDelta").value = "";
        toast("Balans (avans) yangilandi", "success");
        onSaved && onSaved();
      } catch (e) {
        toast(e.message || "Xatolik", "error");
      }
    });
  }

  // ---------------------- Telefon raqamlar bo'limi ----------------------

  const phList = backdrop.querySelector("#phList");

  function phoneRowHtml(p) {
    return `
      <div data-pid="${p.id}" style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px dashed rgba(128,128,128,.25)">
        <div style="flex:1;min-width:0">
          <div style="font-weight:600">${p.is_primary ? "⭐ " : ""}${escapeHtml(p.phone)}</div>
          ${p.label ? `<div class="muted" style="font-size:11px">${escapeHtml(p.label)}</div>` : ""}
        </div>
        ${p.is_primary
          ? `<span class="muted" style="font-size:11px">asosiy</span>`
          : (isAdmin
              ? `<button class="btn btn--xs btn--secondary" data-act="primary" type="button">Asosiy qilish</button>
                 <button class="btn btn--xs btn--danger" data-act="del" type="button">O'chirish</button>`
              : "")}
      </div>
    `;
  }

  function bindPhoneActions(rows) {
    phList.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const holder = btn.closest("[data-pid]");
        const pid = Number(holder && holder.getAttribute("data-pid"));
        const row = rows.find((x) => x.id === pid);
        if (!row) return;
        if (btn.dataset.act === "primary") {
          try {
            await phonesApi.setPrimary(u.id, pid);
            toast("Asosiy raqam yangilandi", "success");
            await loadPhones();
            onSaved && onSaved();  // jadvaldagi "Telefon" ustuni yangilansin
          } catch (e) { toast(phoneErrMsg(e), "error"); }
        } else if (btn.dataset.act === "del") {
          if (!confirm(`${row.phone} raqamini o'chiramizmi?`)) return;
          try {
            await phonesApi.remove(u.id, pid);
            toast("Raqam o'chirildi", "success");
            await loadPhones();
          } catch (e) { toast(phoneErrMsg(e), "error"); }
        }
      });
    });
  }

  async function loadPhones() {
    try {
      const rows = (await phonesApi.list(u.id)) || [];
      if (!rows.length) {
        phList.innerHTML = `<div class="muted" style="font-size:12px">Raqam yo'q.</div>`;
        return;
      }
      phList.innerHTML = rows.map(phoneRowHtml).join("");
      bindPhoneActions(rows);
    } catch (e) {
      phList.innerHTML = `<div class="muted" style="font-size:12px">⚠️ ${escapeHtml(phoneErrMsg(e))}</div>`;
    }
  }

  backdrop.querySelector("#phAdd").addEventListener("click", async () => {
    const phoneEl = backdrop.querySelector("#phNew");
    const labelEl = backdrop.querySelector("#phLabel");
    const primaryEl = backdrop.querySelector("#phPrimary");
    const phoneRaw = phoneEl.value.trim();
    if (phoneRaw.length < 4) return toast("Telefon raqam kiriting", "error");
    const phone = normalizePhone(phoneRaw);
    if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    // Operatorda "Asosiy qilish" checkbox'i yo'q (backend ham e'tiborsiz qoldiradi).
    const makePrimary = !!(primaryEl && primaryEl.checked);
    const addBtn = backdrop.querySelector("#phAdd");
    addBtn.disabled = true;
    try {
      await phonesApi.add(u.id, {
        phone,
        label: labelEl.value.trim(),
        make_primary: makePrimary,
      });
      toast("Raqam qo'shildi", "success");
      phoneEl.value = "";
      labelEl.value = "";
      if (primaryEl) primaryEl.checked = false;
      await loadPhones();
      // Asosiy qilingan bo'lsa — jadvaldagi telefon ham o'zgardi.
      if (makePrimary) onSaved && onSaved();
    } catch (e) {
      toast(phoneErrMsg(e), "error");
    } finally {
      addBtn.disabled = false;
    }
  });

  loadPhones();
}
