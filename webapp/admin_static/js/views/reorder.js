// Aqlli eslatma — suv olish vaqti kelgan mijozlar.
//
// Operator/admin bu sahifada qayta-buyurtma vaqti kelgan (due), kechikkan
// (overdue) va yo'qotilgan (churned) mijozlarni ko'radi, telefon qiladi va
// qo'ng'iroq natijasini qayd qiladi. Backend: webapp/admin/routes_reorder.py.

import { ApiError, tgApp } from "../api.js";
import { fmtCount, fmtDate, escapeHtml } from "../format.js";
import { toast } from "../toast.js";
import { renderPagination, bindPagination } from "../pagination.js";

const PAGE_SIZE = 20;

// ---------------------- Aqlli eslatma API ----------------------
// api.js dagi `request` helper'ining lokal nusxasi (u eksport qilinmaydi).
// Naqsh bir xil: har so'rovga `Authorization: tma <initData>` header.

const initData = tgApp ? tgApp.initData : "";

async function request(path, { method = "GET", body } = {}) {
  const headers = {
    "Authorization": `tma ${initData}`,
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
    if (res.status === 401) throw new ApiError("unauthorized", message);
    if (res.status === 403) throw new ApiError("forbidden", message);
    throw new ApiError(`http_${res.status}`, message);
  }
  return data;
}

const reorderApi = {
  list: (params = {}) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v != null && v !== "") sp.set(k, String(v));
    }
    return request(`/api/admin/reorder${sp.toString() ? "?" + sp : ""}`);
  },
  logCall: (customerId, body) =>
    request(`/api/admin/reorder/${customerId}/calls`, { method: "POST", body }),
  callHistory: (customerId, limit = 10) =>
    request(`/api/admin/reorder/${customerId}/calls?limit=${limit}`),
};

// ---------------------- Konstantalar ----------------------

// Segment filtr chiplari. "all" = harakat talab qiladigan uchala segment
// (due + overdue + churned) — backend shunday qaytaradi, "active" kirmaydi.
const SEGMENTS = [
  { code: "due",     label: "Vaqti keldi" },
  { code: "overdue", label: "Kechikkan" },
  { code: "churned", label: "Yo'qotilgan" },
  { code: "all",     label: "Hammasi" },
];

// Qator ichidagi segment badge'lari: overdue=sariq, churned=qizil.
const SEGMENT_META = {
  active:  { label: "Faol",         cls: "pill--active" },
  due:     { label: "Vaqti keldi",  cls: "pill--due" },
  overdue: { label: "Kechikkan",    cls: "pill--overdue" },
  churned: { label: "Yo'qotilgan",  cls: "pill--churned" },
};

const OUTCOMES = [
  { code: "ordered",   label: "Buyurtma berdi" },
  { code: "no_answer", label: "Javob bermadi" },
  { code: "refused",   label: "Kerak emas" },
  { code: "snoozed",   label: "Keyinroq" },
];
const OUTCOME_LABELS = Object.fromEntries(OUTCOMES.map((o) => [o.code, o.label]));

const DEFAULT_SNOOZE_DAYS = 3;
const MAX_SNOOZE_DAYS = 90;

// ---------------------- Yordamchilar ----------------------

// Faqat sana (vaqtisiz) — bu ro'yxatda soat-daqiqa shart emas.
function fmtDay(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("uz-UZ", {
      day: "2-digit", month: "2-digit", year: "numeric",
    });
  } catch { return iso; }
}

// tel: havola uchun telefonni tozalaymiz (bo'shliq/qavslar URI'da ishlamaydi).
function telHref(phone) {
  return "tel:" + String(phone || "").replace(/[^\d+]/g, "");
}

function segmentBadge(it) {
  const meta = SEGMENT_META[it.segment] || { label: it.segment, cls: "pill--due" };
  const overdue = Number(it.days_overdue) > 0 ? ` +${fmtCount(it.days_overdue)} kun` : "";
  return `<span class="pill ${meta.cls}">${escapeHtml(meta.label)}${overdue}</span>`;
}

// ---------------------- View ----------------------

export async function renderReorder(root, params) {
  let segment = SEGMENTS.some((s) => s.code === params.segment) ? params.segment : "all";
  let page = Math.max(1, Number(params.page) || 1);
  let includeSnoozed = params.snoozed === "1";

  root.innerHTML = `
    <div class="chips" id="segment-chips"></div>
    <div class="filters" style="justify-content:space-between">
      <label class="check-label">
        <input type="checkbox" id="include-snoozed" ${includeSnoozed ? "checked" : ""} />
        <span>💤 Keyinga surilganlarni ham ko'rsatish</span>
      </label>
      <span class="muted" id="count-info"></span>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Mijoz</th>
            <th class="hide-narrow">Oxirgi buyurtma</th>
            <th class="hide-narrow">Sikl</th>
            <th>Holat</th>
            <th class="hide-narrow">Oxirgi qo'ng'iroq</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="reorder-tbody">
          <tr><td colspan="6" class="loading">Yuklanmoqda…</td></tr>
        </tbody>
      </table>
    </div>
    <div id="paginationWrap"></div>
  `;

  const chipsEl = document.getElementById("segment-chips");
  const tbody = document.getElementById("reorder-tbody");
  const countEl = document.getElementById("count-info");
  const paginationWrap = document.getElementById("paginationWrap");
  const snoozedToggle = document.getElementById("include-snoozed");

  let cache = [];
  let total = 0;
  let counts = {};
  let loading = false;

  // URL — bookmark uchun (orders.js naqshi): hashchange fire qilmaymiz.
  function updateUrl() {
    const sp = new URLSearchParams();
    if (segment !== "all") sp.set("segment", segment);
    if (page > 1) sp.set("page", String(page));
    if (includeSnoozed) sp.set("snoozed", "1");
    const q = sp.toString();
    try {
      history.replaceState(
        null, "",
        `${location.pathname}${location.search}#/reorder${q ? "?" + q : ""}`,
      );
    } catch (_) {}
  }

  function chipCount(code) {
    if (code === "all") {
      // "Hammasi" = due + overdue + churned (backend'da "all" shu uchalasi).
      return (counts.due || 0) + (counts.overdue || 0) + (counts.churned || 0);
    }
    return counts[code] || 0;
  }

  function renderChips() {
    chipsEl.innerHTML = SEGMENTS.map((s) => `
      <button type="button" class="chip ${s.code === segment ? "active" : ""}" data-segment="${s.code}">
        ${escapeHtml(s.label)}
        <span class="chip__count">${fmtCount(chipCount(s.code))}</span>
      </button>
    `).join("");
    chipsEl.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.segment === segment) return;
        segment = btn.dataset.segment;
        page = 1;
        updateUrl();
        loadPage();
      });
    });
  }

  function rowHtml(it) {
    const lastCall = it.last_call_outcome
      ? `${escapeHtml(OUTCOME_LABELS[it.last_call_outcome] || it.last_call_outcome)}
         <div class="muted" style="font-size:11px">${escapeHtml(fmtDay(it.last_call_at))}</div>`
      : `<span class="muted">—</span>`;
    const flags = [
      it.has_open_order ? `<div style="margin-top:4px"><span class="pill pill--accepted">Ochiq buyurtma</span></div>` : "",
      it.snoozed_until ? `<div class="muted" style="font-size:11px;margin-top:4px">💤 ${escapeHtml(fmtDay(it.snoozed_until))} gacha</div>` : "",
    ].join("");
    return `
      <tr data-id="${it.customer_id}">
        <td>
          <b>${escapeHtml(it.full_name)}</b>
          <div><a class="tel-link" href="${telHref(it.phone_number)}">📞 ${escapeHtml(it.phone_number)}</a></div>
        </td>
        <td class="hide-narrow">
          ${escapeHtml(fmtDay(it.last_delivered_at))}
          ${it.due_date ? `<div class="muted" style="font-size:11px">Muddat: ${escapeHtml(fmtDay(it.due_date))}</div>` : ""}
        </td>
        <td class="hide-narrow">
          ${it.cycle_days != null ? `~${Math.round(Number(it.cycle_days))} kun` : `<span class="muted">—</span>`}
          <div class="muted" style="font-size:11px">${fmtCount(it.orders_count)} ta buyurtma</div>
        </td>
        <td>${segmentBadge(it)}${flags}</td>
        <td class="hide-narrow" ${it.last_call_note ? `title="${escapeHtml(it.last_call_note)}"` : ""}>${lastCall}</td>
        <td style="text-align:right">
          <button class="btn btn--xs btn--secondary js-call" type="button">Natija</button>
        </td>
      </tr>
    `;
  }

  function bindRowHandlers() {
    tbody.querySelectorAll(".js-call").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const tr = e.target.closest("tr");
        const id = Number(tr.getAttribute("data-id"));
        const it = cache.find((x) => x.customer_id === id);
        if (it) openCallModal(it, () => loadPage());
      });
    });
  }

  async function loadPage() {
    if (loading) return;
    loading = true;
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const res = await reorderApi.list({
        segment,
        include_snoozed: includeSnoozed ? "true" : "false",
        limit: PAGE_SIZE,
        offset,
      });
      cache = res.items || [];
      total = Number(res.total || 0);
      counts = res.counts || {};
      renderChips();

      // Filter o'zgargach joriy sahifa bo'sh qolgan bo'lsa — oxirgi sahifaga.
      if (cache.length === 0 && total > 0 && page > 1) {
        page = Math.max(1, Math.ceil(total / PAGE_SIZE));
        updateUrl();
        loading = false;
        await loadPage();
        return;
      }

      countEl.textContent = total ? `${fmtCount(total)} ta mijoz` : "";
      if (!cache.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">🎉</div><div class="empty__text">Hozircha qo'ng'iroq qilinadigan mijoz yo'q 🎉</div></td></tr>`;
        paginationWrap.innerHTML = "";
        return;
      }
      tbody.innerHTML = cache.map(rowHtml).join("");
      bindRowHandlers();

      paginationWrap.innerHTML = renderPagination({ page, pageSize: PAGE_SIZE, total });
      bindPagination(paginationWrap, (newPage) => {
        page = newPage;
        updateUrl();
        loadPage();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
      paginationWrap.innerHTML = "";
    } finally {
      loading = false;
    }
  }

  snoozedToggle.addEventListener("change", () => {
    includeSnoozed = snoozedToggle.checked;
    page = 1;
    updateUrl();
    loadPage();
  });

  await loadPage();
}

// ---------------------- Qo'ng'iroq natijasi modali ----------------------

function openCallModal(it, onSaved) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">${escapeHtml(it.full_name)}</h3>
        <button class="modal__close" type="button">×</button>
      </div>
      <div class="modal__body">
        <p style="margin:0 0 14px">
          <a class="tel-link" href="${telHref(it.phone_number)}">📞 ${escapeHtml(it.phone_number)}</a>
          <span class="muted" style="font-size:12px;margin-left:8px">Oxirgi buyurtma: ${escapeHtml(fmtDay(it.last_delivered_at))}</span>
        </p>

        <label class="label">Qo'ng'iroq natijasi</label>
        <select class="select" id="call-outcome" style="width:100%">
          ${OUTCOMES.map((o) => `<option value="${o.code}">${escapeHtml(o.label)}</option>`).join("")}
        </select>

        <label class="label" style="margin-top:12px">Izoh (ixtiyoriy)</label>
        <input class="input" id="call-note" maxlength="255" placeholder="Masalan: ertaga o'zi buyurtma beradi" />

        <div id="snooze-row" hidden>
          <label class="label" style="margin-top:12px">Necha kunga keyinga surish</label>
          <input class="input" id="snooze-days" type="number" min="1" max="${MAX_SNOOZE_DAYS}" step="1" value="${DEFAULT_SNOOZE_DAYS}" />
          <p class="muted" style="font-size:11px;margin-top:4px">Mijoz shu muddat davomida ro'yxatda ko'rinmaydi.</p>
        </div>

        <div class="call-history" id="call-history">
          <div class="call-history__title">Qo'ng'iroqlar tarixi</div>
          <span class="muted">Yuklanmoqda…</span>
        </div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" id="cancel-btn" type="button">Bekor qilish</button>
        <button class="btn" id="save-btn" type="button">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector(".modal__close").addEventListener("click", close);
  backdrop.querySelector("#cancel-btn").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  const outcomeSel = backdrop.querySelector("#call-outcome");
  const noteEl = backdrop.querySelector("#call-note");
  const snoozeRow = backdrop.querySelector("#snooze-row");
  const snoozeDaysEl = backdrop.querySelector("#snooze-days");
  const saveBtn = backdrop.querySelector("#save-btn");

  // "Keyinroq" tanlansa — snooze kunlari maydoni ochiladi.
  outcomeSel.addEventListener("change", () => {
    if (outcomeSel.value === "snoozed") snoozeRow.removeAttribute("hidden");
    else snoozeRow.setAttribute("hidden", "");
  });

  // Qo'ng'iroqlar tarixi — modal ochilgach fonda yuklanadi.
  const historyEl = backdrop.querySelector("#call-history");
  reorderApi.callHistory(it.customer_id).then((calls) => {
    if (!backdrop.isConnected) return;  // modal allaqachon yopilgan
    const items = (calls || []).map((c) => `
      <div class="call-history__item">
        <b>${escapeHtml(c.outcome_label || OUTCOME_LABELS[c.outcome] || c.outcome)}</b>
        <span class="muted">· ${escapeHtml(fmtDate(c.called_at))}</span>
        ${c.note ? `<div class="muted">${escapeHtml(c.note)}</div>` : ""}
      </div>
    `).join("");
    historyEl.innerHTML = `
      <div class="call-history__title">Qo'ng'iroqlar tarixi</div>
      ${items || `<span class="muted">Avval qo'ng'iroq qilinmagan.</span>`}
    `;
  }).catch(() => {
    if (!backdrop.isConnected) return;
    historyEl.innerHTML = `
      <div class="call-history__title">Qo'ng'iroqlar tarixi</div>
      <span class="muted">Tarixni yuklab bo'lmadi.</span>
    `;
  });

  saveBtn.addEventListener("click", async () => {
    const outcome = outcomeSel.value;
    const note = noteEl.value.trim();
    let snoozeDays = 0;
    if (outcome === "snoozed") {
      snoozeDays = Math.round(Number(snoozeDaysEl.value));
      if (!Number.isFinite(snoozeDays) || snoozeDays < 1 || snoozeDays > MAX_SNOOZE_DAYS) {
        return toast(`Kunlar 1–${MAX_SNOOZE_DAYS} oralig'ida bo'lsin`, "error");
      }
    }
    saveBtn.disabled = true;
    try {
      await reorderApi.logCall(it.customer_id, { outcome, note, snooze_days: snoozeDays });
      toast("Qo'ng'iroq natijasi saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message || "Xatolik", "error");
      saveBtn.disabled = false;
    }
  });
}
