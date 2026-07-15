// Moliyaviy hisobotlar — oylik (kunlar) + yillik (oylar) + rasxodlar boshqaruvi.
//
// Rahbarning kunlik daromad oqimini, tannarx (COGS) / rasxodlar / sof foydani
// ko'ra olishi hamda operatsion rasxodlarni (bir martalik + doimiy shablonlar)
// shu yerning o'zida yuritishi uchun.

import { api, ApiError } from "../api.js";
import { fmtMoney, fmtCount, escapeHtml } from "../format.js";
import { toast } from "../toast.js";

let _charts = [];
function destroyCharts() {
  for (const c of _charts) { try { c.destroy(); } catch (_) {} }
  _charts = [];
}

const C = {
  blue:        "#0088CC",
  blueDark:    "#003F7F",
  green:       "#27AE60",
  yellow:      "#F39C12",
  blueAlpha:   "rgba(0, 136, 204, 0.15)",
};

const MONTH_NAMES = [
  "Yan", "Fev", "Mar", "Apr", "May", "Iyun",
  "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek",
];
const MONTH_NAMES_FULL = [
  "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
  "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
];
const WEEKDAYS = [
  "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba",
];

const EXP_PAGE_SIZE = 50;

function _years(centerYear, span = 4) {
  const arr = [];
  for (let y = centerYear - span; y <= centerYear; y++) arr.push(y);
  return arr;
}

/* =====================================================================
 * Rasxod API — api.js'dagi request() pattern'ining lokal ko'chirmasi.
 * (Bu view'dan boshqa joyda kerak emas, api.js esa bu o'zgarish doirasiga
 * kirmaydi — shu sababli xuddi shu header/xato-qayta ishlash bilan shu
 * yerda mirror qilamiz: `Authorization: tma <initData>`.)
 * =================================================================== */

const _tg = window.Telegram && window.Telegram.WebApp;
const _initData = _tg ? _tg.initData : "";

async function req(path, { method = "GET", body } = {}) {
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
  return data; // 204 No Content bo'lsa null qaytadi — chaqiruvchi uchun OK
}

const expApi = {
  list: ({ year, month, limit, offset } = {}) => {
    const sp = new URLSearchParams();
    if (year   != null) sp.set("year",   String(year));
    if (month  != null) sp.set("month",  String(month));
    if (limit  != null) sp.set("limit",  String(limit));
    if (offset != null) sp.set("offset", String(offset));
    return req(`/api/admin/expenses${sp.toString() ? "?" + sp : ""}`);
  },
  create:  (body)     => req("/api/admin/expenses", { method: "POST", body }),
  update:  (id, body) => req(`/api/admin/expenses/${id}`, { method: "PATCH", body }),
  remove:  (id)       => req(`/api/admin/expenses/${id}`, { method: "DELETE" }),

  categories:     (includeArchived = false) =>
    req(`/api/admin/expenses/categories?include_archived=${includeArchived ? "true" : "false"}`),
  createCategory: (name) =>
    req("/api/admin/expenses/categories", { method: "POST", body: { name } }),

  recurring:       ()         => req("/api/admin/expenses/recurring"),
  createRecurring: (body)     => req("/api/admin/expenses/recurring", { method: "POST", body }),
  updateRecurring: (id, body) => req(`/api/admin/expenses/recurring/${id}`, { method: "PATCH", body }),
  stopRecurring:   (id)       => req(`/api/admin/expenses/recurring/${id}`, { method: "DELETE" }),
};

// Kategoriyalar keshi — bitta mount davomida qayta so'ramaslik uchun.
let _catsCache = null;
async function ensureCategories(force = false) {
  if (!_catsCache || force) {
    _catsCache = await expApi.categories(true); // arxivlanganlar ham (edit'da ko'rsatish uchun)
  }
  return Array.isArray(_catsCache) ? _catsCache : [];
}

/* ---------------------- Kichik format yordamchilar ---------------------- */

// "YYYY-MM-DD" (yoki ISO) → "DD.MM.YYYY"
function fmtDay(s) {
  if (!s) return "—";
  const parts = String(s).split("T")[0].split("-");
  if (parts.length !== 3) return String(s);
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function periodText(r) {
  if (r.period === "monthly") return `Har oy, ${r.anchor_day}-kun`;
  // Backend hafta kuni 0-based (0=Dushanba .. 6=Yakshanba)
  if (r.period === "weekly")  return `Har hafta, ${WEEKDAYS[r.anchor_day] || r.anchor_day}`;
  if (r.period === "yearly")  return `Har yil, ${r.anchor_day}-${MONTH_NAMES_FULL[(r.anchor_month || 1) - 1]}`;
  return escapeHtml(r.period || "—");
}

/* =====================================================================
 * Asosiy view
 * =================================================================== */

export async function renderFinance(root, params) {
  destroyCharts();
  _catsCache = null; // har mount'da kategoriyalar yangidan olinadi

  const now = new Date();
  // Lokal state — filter o'zgarganda o'zgartiriladi (let, not const).
  // Avval bu narsalar URL hash orqali boshqarilardi: handlerlar `location.hash`
  // qo'yib, router `hashchange` event bilan butun sahifani qayta render qilardi.
  // Lekin Telegram WebView (ayniqsa Desktop)'da hashchange ba'zan fire qilmaydi —
  // shu sababli `<select>` o'zgartirilsa ham UI yangilanmasdi. Endi:
  //   * Filter o'zgaradi → lokal state yangilanadi → reload() to'g'ridan-to'g'ri
  //   * URL faqat bookmark/share uchun replaceState bilan yangilanadi
  let year = Number(params.year) || now.getFullYear();
  let month = Number(params.month) || (now.getMonth() + 1);
  let view = params.view === "yearly" ? "yearly" : "monthly";

  // Rasxodlar bo'limi state'i
  let expTab = "list";     // "list" | "recurring"
  let expCache = [];
  let expOffset = 0;
  let expTotal = 0;
  let expLoading = false;

  root.innerHTML = `
    <div class="toolbar">
      <div class="filters">
        <div class="seg" id="seg">
          <button data-v="monthly" class="${view === "monthly" ? "active" : ""}" type="button">Oylik</button>
          <button data-v="yearly"  class="${view === "yearly"  ? "active" : ""}" type="button">Yillik</button>
        </div>
        <select class="select" id="yearSel">
          ${_years(now.getFullYear()).map((y) => `<option value="${y}" ${y === year ? "selected" : ""}>${y}</option>`).join("")}
        </select>
        <select class="select" id="monthSel" ${view === "yearly" ? "disabled" : ""}>
          ${MONTH_NAMES_FULL.map((nm, i) => `<option value="${i + 1}" ${i + 1 === month ? "selected" : ""}>${nm}</option>`).join("")}
        </select>
      </div>
    </div>

    <div class="kpi-grid" id="kpis"></div>

    <div class="charts-grid" style="grid-template-columns: 1fr">
      <div class="card chart-card">
        <h3 class="card__title" id="chartTitle">Yuklanmoqda…</h3>
        <canvas id="rev-chart"></canvas>
      </div>
    </div>

    <div class="section-title">💸 Rasxodlar</div>
    <div class="toolbar" style="flex-wrap:wrap;gap:10px">
      <div class="seg" id="expSeg">
        <button data-t="list"      class="active" type="button">Ro'yxat</button>
        <button data-t="recurring" type="button">🔁 Doimiy</button>
      </div>
      <div class="muted" id="expTitle" style="font-size:12px;color:var(--text-muted)"></div>
      <div style="flex:1"></div>
      <button class="btn" id="expNewBtn" type="button">➕ Rasxod</button>
    </div>
    <div class="card" id="catCard" hidden style="margin-bottom:var(--gap)">
      <h3 class="card__title">Kategoriya bo'yicha taqsimot</h3>
      <div class="tops" id="catList"></div>
    </div>
    <div id="expBody"></div>
    <div id="expMore" style="margin-top:12px;text-align:center"></div>
  `;

  const yearSel = root.querySelector("#yearSel");
  const monthSel = root.querySelector("#monthSel");
  const seg = root.querySelector("#seg");
  const expSeg = root.querySelector("#expSeg");
  const expNewBtn = root.querySelector("#expNewBtn");
  const expTitle = root.querySelector("#expTitle");
  const expBody = root.querySelector("#expBody");
  const expMore = root.querySelector("#expMore");

  const reload = async () => {
    destroyCharts();
    const Chart = window.Chart;
    if (!Chart) {
      root.querySelector("#chartTitle").textContent = "Chart.js yuklanmadi";
      return;
    }

    let data;
    try {
      if (view === "yearly") {
        data = await api.financeYearly(year);
      } else {
        data = await api.financeMonthly(year, month);
      }
    } catch (e) {
      root.querySelector("#chartTitle").textContent = "Xatolik";
      root.querySelector("#kpis").innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
      return;
    }

    // ---- P&L raqamlari (yangi maydonlar; eski backend'da undefined → 0) ----
    const cogs = Number(data.cogs || 0);
    const grossProfit = Number(data.gross_profit || 0);
    const expensesTotal = Number(data.expenses_total || 0);
    const netProfit = Number(data.net_profit || 0);
    const netPos = netProfit >= 0;
    const netColor = netPos ? "var(--brand-success)" : "var(--brand-danger)";
    const netBg = netPos ? "var(--pill-bg-success)" : "var(--pill-bg-danger)";

    const kpis = root.querySelector("#kpis");
    kpis.innerHTML = `
      <div class="kpi">
        <div class="kpi__icon">💵</div>
        <div class="kpi__label">Jami tushum</div>
        <div class="kpi__value">${fmtMoney(data.total_revenue || 0)}</div>
        <div class="kpi__sub">faqat yetkazilgan buyurtmalar</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">🧮</div>
        <div class="kpi__label">To'lov usullari</div>
        <div class="kpi__sub" style="margin-top:4px">💵 Naqd ${fmtMoney(data.cash_revenue || 0)}</div>
        <div class="kpi__sub">💳 Karta ${fmtMoney(data.card_revenue || 0)}</div>
        <div class="kpi__sub">💰 Balansdan ${fmtMoney(data.deposit_revenue || 0)}</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">💎</div>
        <div class="kpi__label">Keshbek aylanmasi</div>
        <div class="kpi__value">${fmtMoney(data.cashback_used)}</div>
        <div class="kpi__sub">+${fmtMoney(data.cashback_earned)} yangi liability</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">📊</div>
        <div class="kpi__label">Jami sotuv (gross)</div>
        <div class="kpi__value">${fmtMoney(data.gross_sale)}</div>
        <div class="kpi__sub">Naqd + keshbek</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">📦</div>
        <div class="kpi__label">Jami buyurtmalar</div>
        <div class="kpi__value">${fmtCount(data.total_orders)}</div>
        <div class="kpi__sub">${view === "yearly" ? "Yil davomida" : MONTH_NAMES_FULL[month - 1] + " " + year}</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">📈</div>
        <div class="kpi__label">O'rtacha buyurtma (naqd)</div>
        <div class="kpi__value">${fmtMoney(data.average_order)}</div>
        <div class="kpi__sub">Bitta buyurtmaga</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">🏭</div>
        <div class="kpi__label">Tannarx (COGS)</div>
        <div class="kpi__value">${fmtMoney(cogs)}</div>
        <div class="kpi__sub">Yalpi foyda: ${fmtMoney(grossProfit)}</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">🧾</div>
        <div class="kpi__label">Rasxodlar</div>
        <div class="kpi__value">${fmtMoney(expensesTotal)}</div>
        <div class="kpi__sub">Operatsion xarajatlar</div>
      </div>
      <div class="kpi" style="border:2px solid ${netColor}">
        <div class="kpi__icon" style="background:${netBg};color:${netColor}">${netPos ? "💰" : "⚠️"}</div>
        <div class="kpi__label" style="color:${netColor}">Sof foyda</div>
        <div class="kpi__value" style="color:${netColor}">${fmtMoney(netProfit)}</div>
        <div class="kpi__sub">Yalpi foyda − rasxodlar${netPos ? "" : " (zarar)"}</div>
      </div>
    `;

    // ---- Rasxodlar taqsimoti (kategoriya bo'yicha) ----
    const cats = Array.isArray(data.expenses_by_category) ? data.expenses_by_category : [];
    const catCard = root.querySelector("#catCard");
    const catList = root.querySelector("#catList");
    if (catCard && catList) {
      if (!cats.length) {
        catCard.hidden = true;
      } else {
        catCard.hidden = false;
        const sorted = [...cats].sort((a, b) => Number(b.total || 0) - Number(a.total || 0));
        catList.innerHTML = sorted.map((c, i) => `
          <div class="top-row">
            <div class="top-row__rank">${i + 1}</div>
            <div class="top-row__main">
              <div class="top-row__name">${escapeHtml(c.name)}</div>
            </div>
            <div class="top-row__value">${fmtMoney(c.total)}</div>
          </div>
        `).join("");
      }
    }

    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = "#64748B";

    if (view === "yearly") {
      root.querySelector("#chartTitle").textContent = `${year}-yil oylik moliyaviy hisobot`;
      const labels = data.months.map((m) => MONTH_NAMES[Number(m.month.split("-")[1]) - 1]);
      _charts.push(new Chart(root.querySelector("#rev-chart"), {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "Tushum",
              data: data.months.map((m) => Number(m.total_revenue || 0)),
              backgroundColor: C.blue,
              borderRadius: 6,
            },
            {
              label: "Keshbek aylanmasi",
              data: data.months.map((m) => m.cashback_used),
              backgroundColor: C.green,
              borderRadius: 6,
            },
          ],
        },
        options: stackedChartOptions(),
      }));
    } else {
      root.querySelector("#chartTitle").textContent = `${MONTH_NAMES_FULL[month - 1]} ${year} — kunlik moliyaviy hisobot`;
      const labels = data.days.map((d) => Number(d.date.split("-")[2]));
      _charts.push(new Chart(root.querySelector("#rev-chart"), {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: "Tushum",
              data: data.days.map((d) => Number(d.total_revenue || 0)),
              borderColor: C.blue,
              backgroundColor: C.blueAlpha,
              fill: true,
              tension: 0.35,
              pointRadius: 0,
              pointHoverRadius: 4,
              borderWidth: 2.5,
            },
            {
              label: "Keshbek",
              data: data.days.map((d) => d.cashback_used),
              borderColor: C.green,
              backgroundColor: "rgba(39, 174, 96, 0.10)",
              fill: false,
              tension: 0.35,
              pointRadius: 0,
              pointHoverRadius: 4,
              borderWidth: 2,
              borderDash: [4, 3],
            },
          ],
        },
        options: chartOptions(),
      }));
    }
  };

  /* ---------------------- Rasxodlar bo'limi ---------------------- */

  function expenseRowHtml(x) {
    const rec = x.recurring_id
      ? ` <span title="Doimiy rasxod (shablondan avtomatik)">🔁</span>`
      : "";
    const period = x.period_start
      ? ` <span class="pill pill--active hide-narrow" title="Davrga taqsimlangan" style="font-size:11px">📅 ${fmtDay(x.period_start)} → ${fmtDay(x.period_end)}</span>`
      : "";
    return `
      <tr>
        <td style="white-space:nowrap">${fmtDay(x.spent_on)}${rec}${period}</td>
        <td>${escapeHtml(x.category_name || "—")}</td>
        <td class="hide-narrow muted">${escapeHtml(x.note || "—")}</td>
        <td style="text-align:right;font-weight:600">${fmtMoney(x.amount)}</td>
        <td style="text-align:right">
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn--xs btn--secondary" data-act="edit" data-id="${x.id}">✏️</button>
            <button class="btn btn--xs btn--danger"    data-act="del"  data-id="${x.id}">🗑</button>
          </div>
        </td>
      </tr>
    `;
  }

  function bindExpenseActions() {
    const tbody = root.querySelector("#expTbody");
    if (!tbody) return;
    tbody.querySelectorAll("button[data-act]").forEach((btn) => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      btn.addEventListener("click", async () => {
        const x = expCache.find((e) => e.id === id);
        if (!x) return;
        if (act === "edit") {
          let cats;
          try { cats = await ensureCategories(); } catch (e) { return toast(e.message, "error"); }
          openExpenseModal({ expense: x, categories: cats, onSaved: afterMutation });
        } else if (act === "del") {
          if (!confirm(`${fmtDay(x.spent_on)} — ${fmtMoney(x.amount)} rasxodni arxivga ko'chiramizmi?\n\nHisobotlardan chiqariladi.`)) return;
          try {
            await expApi.remove(id);
            toast("Rasxod arxivlandi", "success");
            afterMutation();
          } catch (e) { toast(e.message, "error"); }
        }
      });
    });
  }

  function renderExpenseRows() {
    const tbody = root.querySelector("#expTbody");
    if (!tbody) return;
    if (!expCache.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty"><div class="empty__icon">🧾</div><div class="empty__text">Bu davrda rasxod yo'q.</div></td></tr>`;
      expMore.innerHTML = "";
      return;
    }
    tbody.innerHTML = expCache.map(expenseRowHtml).join("");
    bindExpenseActions();
    if (expCache.length < expTotal) {
      const remaining = expTotal - expCache.length;
      expMore.innerHTML = `
        <button class="btn btn--secondary" id="expMoreBtn" type="button">
          Yana yuklash (${fmtCount(remaining)} qoldi)
        </button>
      `;
      expMore.querySelector("#expMoreBtn").addEventListener("click", () => loadExpensesPage(false));
    } else {
      expMore.innerHTML = "";
    }
  }

  async function loadExpensesPage(reset) {
    if (expLoading) return;
    expLoading = true;
    try {
      const res = await expApi.list({
        year,
        month: view === "yearly" ? undefined : month,
        limit: EXP_PAGE_SIZE,
        offset: reset ? 0 : expOffset,
      });
      const items = (res && res.items) || [];
      if (reset) {
        expCache = items;
        expOffset = items.length;
      } else {
        expCache = expCache.concat(items);
        expOffset += items.length;
      }
      expTotal = Number((res && res.total) || 0);
      const periodLabel = view === "yearly"
        ? `${year}-yil`
        : `${MONTH_NAMES_FULL[month - 1]} ${year}`;
      expTitle.textContent = `${periodLabel} — ${fmtCount(expTotal)} ta yozuv`;
      renderExpenseRows();
    } catch (e) {
      const tbody = root.querySelector("#expTbody");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
      }
    } finally {
      expLoading = false;
    }
  }

  function recurringRowHtml(r) {
    const rangeSub = (r.start_date || r.end_date)
      ? `<div class="muted" style="font-size:11px">${r.start_date ? fmtDay(r.start_date) : "…"} → ${r.end_date ? fmtDay(r.end_date) : "∞"}</div>`
      : "";
    const actions = r.archived ? "" : `
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
        <button class="btn btn--xs btn--secondary" data-act="edit" data-id="${r.id}">✏️</button>
        <button class="btn btn--xs btn--danger"    data-act="stop" data-id="${r.id}">⏹ To'xtatish</button>
      </div>
    `;
    return `
      <tr${r.archived ? ' style="opacity:0.65"' : ""}>
        <td>🔁 <b>${escapeHtml(r.label)}</b>
          <div class="muted" style="font-size:11px">${escapeHtml(r.category_name || "—")}</div>
        </td>
        <td class="hide-narrow">${periodText(r)}${rangeSub}</td>
        <td style="text-align:right;font-weight:600">${fmtMoney(r.amount)}</td>
        <td><span class="pill pill--${r.archived ? "inactive" : "active"}">${r.archived ? "To'xtatilgan" : "Aktiv"}</span></td>
        <td style="text-align:right">${actions}</td>
      </tr>
    `;
  }

  function renderRecurring(list) {
    if (!list.length) {
      expBody.innerHTML = `<div class="card"><div class="empty"><div class="empty__icon">🔁</div><div class="empty__text">Doimiy rasxod shabloni yo'q. "➕ Shablon" bilan qo'shing — davrlari avtomatik yoziladi.</div></div></div>`;
      return;
    }
    expBody.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Nomi</th>
              <th class="hide-narrow">Davr</th>
              <th style="text-align:right">Summa</th>
              <th>Holat</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="recTbody">${list.map(recurringRowHtml).join("")}</tbody>
        </table>
      </div>
    `;
    expBody.querySelectorAll("button[data-act]").forEach((btn) => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      btn.addEventListener("click", async () => {
        const r = list.find((x) => x.id === id);
        if (!r) return;
        if (act === "edit") {
          openRecurringEditModal({ rec: r, onSaved: afterMutation });
        } else if (act === "stop") {
          if (!confirm(`"${r.label}" shablonini to'xtatamizmi?\n\nBundan keyin yangi davr yozilmaydi. Yozib bo'lingan rasxodlar joyida qoladi.`)) return;
          try {
            await expApi.stopRecurring(id);
            toast("Shablon to'xtatildi", "success");
            afterMutation();
          } catch (e) { toast(e.message, "error"); }
        }
      });
    });
  }

  async function reloadExpenses() {
    if (expTab === "list") {
      expNewBtn.textContent = "➕ Rasxod";
      expTitle.textContent = "";
      expBody.innerHTML = `
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Sana</th>
                <th>Kategoriya</th>
                <th class="hide-narrow">Izoh</th>
                <th style="text-align:right">Summa</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="expTbody"><tr><td colspan="5" class="loading">Yuklanmoqda…</td></tr></tbody>
          </table>
        </div>
      `;
      expCache = [];
      expOffset = 0;
      await loadExpensesPage(true);
    } else {
      expNewBtn.textContent = "➕ Shablon";
      expTitle.textContent = "Davrlari backend'da avtomatik yoziladi";
      expMore.innerHTML = "";
      expBody.innerHTML = `<div class="loading">Yuklanmoqda…</div>`;
      try {
        const list = await expApi.recurring();
        renderRecurring(Array.isArray(list) ? list : []);
      } catch (e) {
        expBody.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
      }
    }
  }

  // Rasxod o'zgardi → ham ro'yxat, ham KPI (sof foyda) yangilanadi.
  function afterMutation() {
    reload();
    reloadExpenses();
  }

  expSeg.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-t]");
    if (!btn) return;
    const t = btn.dataset.t;
    if (t === expTab) return;
    expTab = t;
    expSeg.querySelectorAll("button[data-t]").forEach((b) => {
      b.classList.toggle("active", b.dataset.t === expTab);
    });
    reloadExpenses();
  });

  expNewBtn.addEventListener("click", async () => {
    let cats;
    try { cats = await ensureCategories(); } catch (e) { return toast(e.message, "error"); }
    if (expTab === "recurring") {
      openRecurringCreateModal({ categories: cats, onSaved: afterMutation });
    } else {
      openExpenseModal({ expense: null, categories: cats, onSaved: afterMutation });
    }
  });

  // URL'ni bookmark uchun yangilash + lokal reload. hashchange fire qilmaymiz —
  // shu sababli router butun sahifani qayta render qilmaydi (toza, tez).
  function updateUrlAndReload() {
    const sp = new URLSearchParams();
    sp.set("view", view);
    sp.set("year", String(year));
    sp.set("month", String(month));
    try {
      history.replaceState(
        null, "",
        `${location.pathname}${location.search}#/finance?${sp}`,
      );
    } catch (_) { /* iframe sandbox xato bersa — silent, reload baribir ishlaydi */ }
    reload();
    // Rasxodlar ro'yxati ham davrga bog'liq — shablonlar esa emas.
    if (expTab === "list") reloadExpenses();
  }

  seg.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-v]");
    if (!btn) return;
    const v = btn.dataset.v;
    if (v === view) return;
    view = v;
    // Segmented control visual state — aktiv tugmani ko'rsatish
    seg.querySelectorAll("button[data-v]").forEach((b) => {
      b.classList.toggle("active", b.dataset.v === view);
    });
    // Yillik rejimda month tanlash mantiqiy emas — disabled
    monthSel.disabled = (view === "yearly");
    updateUrlAndReload();
  });

  yearSel.addEventListener("change", () => {
    year = Number(yearSel.value) || year;
    updateUrlAndReload();
  });

  monthSel.addEventListener("change", () => {
    month = Number(monthSel.value) || month;
    updateUrlAndReload();
  });

  await Promise.all([reload(), reloadExpenses()]);
  return () => destroyCharts();
}

/* =====================================================================
 * Modallar (products.js pattern'i: backdrop + [data-close] + footer)
 * =================================================================== */

function openModal(innerHtml) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = innerHtml;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  return { backdrop, close };
}

function categoryOptionsHtml(cats, selectedId) {
  // Arxivlanganlar faqat tanlab qo'yilgan bo'lsa ko'rinadi (edit holati).
  const opts = cats.filter((c) => !c.archived || c.id === selectedId);
  return `<option value="">— tanlang —</option>` + opts.map((c) => `
    <option value="${c.id}" ${c.id === selectedId ? "selected" : ""}>${escapeHtml(c.name)}${c.archived ? " (arxiv)" : ""}</option>
  `).join("");
}

function categoryFieldHtml(cats, selectedId) {
  return `
    <label class="label">Kategoriya</label>
    <div style="display:flex;gap:8px">
      <select class="select" id="c-sel" style="flex:1">${categoryOptionsHtml(cats, selectedId)}</select>
      <button class="btn btn--secondary" id="c-add" type="button" title="Yangi kategoriya qo'shish">➕</button>
    </div>
    <div id="c-new-row" hidden style="display:flex;gap:8px;margin-top:8px">
      <input class="input" id="c-new-name" placeholder="Yangi kategoriya nomi" style="flex:1" />
      <button class="btn btn--success" id="c-new-save" type="button">Qo'shish</button>
    </div>
  `;
}

// Kategoriya tez qo'shish — modal ichidagi ➕ tugmasi.
function bindCategoryQuickAdd(backdrop) {
  const sel = backdrop.querySelector("#c-sel");
  const addBtn = backdrop.querySelector("#c-add");
  const row = backdrop.querySelector("#c-new-row");
  const nameInput = backdrop.querySelector("#c-new-name");
  const saveBtn = backdrop.querySelector("#c-new-save");
  if (!sel || !addBtn) return;

  addBtn.addEventListener("click", () => {
    row.hidden = !row.hidden;
    if (!row.hidden) nameInput.focus();
  });

  saveBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (name.length < 2) return toast("Kategoriya nomi juda qisqa", "error");
    saveBtn.disabled = true;
    try {
      const created = await expApi.createCategory(name);
      const cats = await ensureCategories(true);
      sel.innerHTML = categoryOptionsHtml(cats, created && created.id);
      row.hidden = true;
      nameInput.value = "";
      toast("Kategoriya qo'shildi", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      saveBtn.disabled = false;
    }
  });
}

/* ---------------------- Rasxod: yaratish / tahrirlash ---------------------- */

function openExpenseModal({ expense, categories, onSaved }) {
  const isEdit = !!expense;
  const isRecurringRow = !!(expense && expense.recurring_id);
  const hadPeriod = !!(expense && expense.period_start);
  const { backdrop, close } = openModal(`
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">${isEdit ? "Rasxodni tahrirlash" : "Yangi rasxod"}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        ${categoryFieldHtml(categories, expense ? expense.category_id : undefined)}
        <label class="label">Summa (so'm)</label>
        <input class="input" id="e-amount" type="number" inputmode="numeric" min="0" step="any"
               placeholder="150000" value="${expense ? Number(expense.amount) : ""}" />
        <label class="label">Sana</label>
        <input class="input" id="e-date" type="date"
               value="${expense ? escapeHtml(String(expense.spent_on || "").split("T")[0]) : todayStr()}"
               ${isRecurringRow ? "disabled" : ""} />
        ${isRecurringRow ? `<div class="muted" style="font-size:12px;margin-top:4px">🔁 Doimiy shablondan yozilgan rasxodda sanani o'zgartirib bo'lmaydi.</div>` : ""}
        <label class="label" style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="e-period-on" ${hadPeriod ? "checked" : ""}/> Davrga taqsimlash (oldindan to'lov)</label>
        <div class="muted" style="font-size:12px;margin-top:4px">Masalan: 6 oylik oylik oldindan to'landi — hisobotlarda har oyga teng taqsimlanadi.</div>
        <div id="e-period-box" ${hadPeriod ? "" : "hidden"}>
          <label class="label">Davr boshi</label>
          <input class="input" id="e-pstart" type="date"
                 value="${hadPeriod ? escapeHtml(String(expense.period_start || "").split("T")[0]) : ""}" />
          <label class="label">Davr oxiri</label>
          <input class="input" id="e-pend" type="date"
                 value="${hadPeriod ? escapeHtml(String(expense.period_end || "").split("T")[0]) : ""}" />
        </div>
        <label class="label">Izoh (ixtiyoriy)</label>
        <textarea class="textarea" id="e-note" placeholder="Masalan: ofis ijarasi">${expense ? escapeHtml(expense.note || "") : ""}</textarea>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="e-save">Saqlash</button>
      </div>
    </div>
  `);

  bindCategoryQuickAdd(backdrop);

  // Davrga taqsimlash — checkbox yoqilsa sana inputlari ko'rinadi.
  const periodCb = backdrop.querySelector("#e-period-on");
  const periodBox = backdrop.querySelector("#e-period-box");
  periodCb.addEventListener("change", () => {
    periodBox.hidden = !periodCb.checked;
  });

  backdrop.querySelector("#e-save").addEventListener("click", async () => {
    const category_id = Number(backdrop.querySelector("#c-sel").value) || 0;
    const amount = Number(backdrop.querySelector("#e-amount").value);
    const spent_on = backdrop.querySelector("#e-date").value;
    const note = backdrop.querySelector("#e-note").value.trim();
    const periodOn = periodCb.checked;
    const period_start = backdrop.querySelector("#e-pstart").value;
    const period_end = backdrop.querySelector("#e-pend").value;
    if (!category_id) return toast("Kategoriya tanlang", "error");
    if (!(amount > 0)) return toast("Summa noto'g'ri", "error");
    if (!isRecurringRow && !spent_on) return toast("Sana tanlang", "error");
    if (periodOn) {
      if (!period_start || !period_end) return toast("Davr boshi va oxirini tanlang", "error");
      if (period_end < period_start) return toast("Davr oxiri boshidan oldin bo'lolmaydi", "error");
    }

    const saveBtn = backdrop.querySelector("#e-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saqlanmoqda…";
    try {
      if (isEdit) {
        // note doim string ("" = izohni tozalash; null yuborilsa o'zgarmaydi)
        const body = { category_id, amount, note };
        // Recurring yozuvda spent_on yuborilmaydi (backend 409 qaytaradi)
        if (!isRecurringRow) body.spent_on = spent_on;
        if (periodOn) {
          body.period_start = period_start;
          body.period_end = period_end;
        } else if (hadPeriod) {
          // Avval davr bor edi, checkbox o'chirildi — davrni olib tashlaymiz.
          body.clear_period = true;
        }
        await expApi.update(expense.id, body);
        toast("Saqlandi", "success");
      } else {
        // note: string — backend ExpenseIn.note str kutadi (null = 422)
        const body = { category_id, amount, spent_on, note };
        if (periodOn) {
          body.period_start = period_start;
          body.period_end = period_end;
        }
        await expApi.create(body);
        toast("Rasxod qo'shildi", "success");
      }
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message, "error");
      saveBtn.disabled = false;
      saveBtn.textContent = "Saqlash";
    }
  });
}

/* ---------------------- Doimiy shablon: yaratish ---------------------- */

function recurringAnchorHtml(period) {
  if (period === "weekly") {
    return `
      <label class="label">Hafta kuni</label>
      <select class="select" id="r-day">
        ${WEEKDAYS.map((w, i) => `<option value="${i}">${w}</option>`).join("")}
      </select>
    `;
  }
  if (period === "yearly") {
    return `
      <label class="label">Oy</label>
      <select class="select" id="r-month">
        ${MONTH_NAMES_FULL.map((nm, i) => `<option value="${i + 1}">${nm}</option>`).join("")}
      </select>
      <label class="label">Oyning kuni (1–31)</label>
      <input class="input" id="r-day" type="number" inputmode="numeric" min="1" max="31" step="1" value="1" />
    `;
  }
  // monthly (default)
  return `
    <label class="label">Oyning kuni (1–31)</label>
    <input class="input" id="r-day" type="number" inputmode="numeric" min="1" max="31" step="1" value="1" />
    <div class="muted" style="font-size:12px;margin-top:4px">Masalan: 1 — har oyning 1-kunida avtomatik yoziladi.</div>
  `;
}

function openRecurringCreateModal({ categories, onSaved }) {
  const { backdrop, close } = openModal(`
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">🔁 Yangi doimiy rasxod</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        ${categoryFieldHtml(categories, undefined)}
        <label class="label">Nomi</label>
        <input class="input" id="r-label" placeholder="Ofis ijarasi" />
        <label class="label">Summa (so'm)</label>
        <input class="input" id="r-amount" type="number" inputmode="numeric" min="0" step="any" placeholder="2000000" />
        <label class="label">Davr</label>
        <select class="select" id="r-period">
          <option value="monthly" selected>Har oy</option>
          <option value="weekly">Har hafta</option>
          <option value="yearly">Har yil</option>
        </select>
        <div id="r-anchor">${recurringAnchorHtml("monthly")}</div>
        <label class="label">Boshlanish sanasi (ixtiyoriy)</label>
        <input class="input" id="r-start" type="date" />
        <label class="label">Tugash sanasi (ixtiyoriy)</label>
        <input class="input" id="r-end" type="date" />
        <div class="muted" style="font-size:12px;margin-top:6px">
          Davrlari backend'da avtomatik yoziladi — bu yerda faqat shablon sozlanadi.
        </div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="r-save">Saqlash</button>
      </div>
    </div>
  `);

  bindCategoryQuickAdd(backdrop);

  const periodSel = backdrop.querySelector("#r-period");
  const anchorBox = backdrop.querySelector("#r-anchor");
  periodSel.addEventListener("change", () => {
    anchorBox.innerHTML = recurringAnchorHtml(periodSel.value);
  });

  backdrop.querySelector("#r-save").addEventListener("click", async () => {
    const category_id = Number(backdrop.querySelector("#c-sel").value) || 0;
    const label = backdrop.querySelector("#r-label").value.trim();
    const amount = Number(backdrop.querySelector("#r-amount").value);
    const period = periodSel.value;
    const anchor_day = Math.floor(Number(backdrop.querySelector("#r-day").value));
    // Backend kodlashi: weekly = 0..6 (0=Dushanba), monthly/yearly = 1..31
    const minDay = period === "weekly" ? 0 : 1;
    const maxDay = period === "weekly" ? 6 : 31;
    if (!category_id) return toast("Kategoriya tanlang", "error");
    if (label.length < 2) return toast("Nomi juda qisqa", "error");
    if (!(amount > 0)) return toast("Summa noto'g'ri", "error");
    if (!(anchor_day >= minDay && anchor_day <= maxDay)) {
      return toast(`Kun ${minDay}..${maxDay} oralig'ida bo'lishi shart`, "error");
    }

    const body = { category_id, label, amount, period, anchor_day };
    if (period === "yearly") {
      body.anchor_month = Number(backdrop.querySelector("#r-month").value) || 1;
    }
    const startDate = backdrop.querySelector("#r-start").value;
    const endDate = backdrop.querySelector("#r-end").value;
    if (startDate) body.start_date = startDate;
    if (endDate) body.end_date = endDate;

    const saveBtn = backdrop.querySelector("#r-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saqlanmoqda…";
    try {
      await expApi.createRecurring(body);
      toast("Shablon yaratildi", "success");
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message, "error");
      saveBtn.disabled = false;
      saveBtn.textContent = "Saqlash";
    }
  });
}

/* ---------------------- Doimiy shablon: tahrirlash ---------------------- */

function openRecurringEditModal({ rec, onSaved }) {
  const { backdrop, close } = openModal(`
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">🔁 Tahrirlash: ${escapeHtml(rec.label)}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        <div class="muted" style="font-size:12px">
          ${escapeHtml(rec.category_name || "—")} · ${periodText(rec)}
        </div>
        <label class="label">Nomi</label>
        <input class="input" id="r-label" value="${escapeHtml(rec.label)}" />
        <label class="label">Summa (so'm)</label>
        <input class="input" id="r-amount" type="number" inputmode="numeric" min="0" step="any" value="${Number(rec.amount)}" />
        <label class="label">Tugash sanasi</label>
        <input class="input" id="r-end" type="date" value="${escapeHtml(String(rec.end_date || "").split("T")[0])}" />
        <label style="display:flex;align-items:center;gap:8px;margin-top:10px;font-size:14px;cursor:pointer">
          <input type="checkbox" id="r-clear" />
          Tugash sanasini olib tashlash (∞ davom etsin)
        </label>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="r-save">Saqlash</button>
      </div>
    </div>
  `);

  const endInput = backdrop.querySelector("#r-end");
  const clearCb = backdrop.querySelector("#r-clear");
  clearCb.addEventListener("change", () => {
    endInput.disabled = clearCb.checked;
  });

  backdrop.querySelector("#r-save").addEventListener("click", async () => {
    const label = backdrop.querySelector("#r-label").value.trim();
    const amount = Number(backdrop.querySelector("#r-amount").value);
    if (label.length < 2) return toast("Nomi juda qisqa", "error");
    if (!(amount > 0)) return toast("Summa noto'g'ri", "error");

    const body = { label, amount };
    if (clearCb.checked) {
      body.clear_end_date = true;
    } else if (endInput.value) {
      body.end_date = endInput.value;
    }

    const saveBtn = backdrop.querySelector("#r-save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saqlanmoqda…";
    try {
      await expApi.updateRecurring(rec.id, body);
      toast("Saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) {
      toast(e.message, "error");
      saveBtn.disabled = false;
      saveBtn.textContent = "Saqlash";
    }
  });
}

/* ---------------------- Chart options ---------------------- */

function chartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, position: "bottom", labels: { boxWidth: 12, padding: 12 } },
      tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatMoneyAxis(ctx.parsed.y)}` } },
    },
    scales: {
      y: {
        beginAtZero: true,
        ticks: { callback: (v) => formatMoneyAxis(v) },
        grid: { color: "rgba(15,23,42,0.05)" },
      },
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
    },
  };
}

function stackedChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, position: "bottom", labels: { boxWidth: 12, padding: 12 } },
      tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatMoneyAxis(ctx.parsed.y)}` } },
    },
    scales: {
      y: {
        beginAtZero: true,
        stacked: true,
        ticks: { callback: (v) => formatMoneyAxis(v) },
        grid: { color: "rgba(15,23,42,0.05)" },
      },
      x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
    },
  };
}

function formatMoneyAxis(v) {
  v = Number(v) || 0;
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return Math.round(v / 1_000) + "k";
  return String(v);
}
