import { api } from "../api.js";
import { fmtMoney, fmtCount, fmtDate, escapeHtml, statusPill } from "../format.js";
import { go } from "../router.js";
import { renderPagination, bindPagination } from "../pagination.js";

const STATUSES = [
  { code: "",          label: "Barchasi" },
  { code: "NEW",        label: "Yangi" },
  { code: "ACCEPTED",   label: "Qabul qilindi" },
  { code: "DELIVERING", label: "Yo'lda" },
  { code: "ARRIVED",    label: "Yetib keldi" },
  { code: "DELIVERED",  label: "Yetkazildi" },
  { code: "CANCELLED",  label: "Bekor qilindi" },
];

const PAGE_SIZE = 20;

export async function renderOrders(root, params) {
  // Status filter URL'dan keladi. Status o'zgartirilsa — sahifa 1'ga qaytadi.
  let status = params.status || "";
  let page = Math.max(1, Number(params.page) || 1);

  root.innerHTML = `
    <div class="filters" style="justify-content:space-between">
      <select class="select" id="status-filter">
        ${STATUSES.map((s) => `
          <option value="${s.code}" ${s.code === status ? "selected" : ""}>${escapeHtml(s.label)}</option>
        `).join("")}
      </select>
      <span class="muted" id="count-info"></span>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>#</th>
            <th class="hide-narrow">Sana</th>
            <th>Mijoz</th>
            <th class="hide-narrow">Kuryer</th>
            <th>Holat</th>
            <th style="text-align:right">Jami</th>
          </tr>
        </thead>
        <tbody id="orders-tbody">
          <tr><td colspan="6" class="loading">Yuklanmoqda…</td></tr>
        </tbody>
      </table>
    </div>
    <div id="paginationWrap"></div>
  `;

  const tbody = document.getElementById("orders-tbody");
  const countEl = document.getElementById("count-info");
  const paginationWrap = document.getElementById("paginationWrap");
  const statusFilter = document.getElementById("status-filter");

  let cache = [];
  let total = 0;
  let loading = false;

  function rowsHtml(rows) {
    return rows.map((o) => `
      <tr class="clickable" data-id="${o.id}">
        <td><b>${escapeHtml(o.display_number || ("#" + o.id))}</b></td>
        <td class="hide-narrow">${escapeHtml(fmtDate(o.created_at))}</td>
        <td>${escapeHtml(o.customer.full_name)}</td>
        <td class="hide-narrow">${o.courier ? escapeHtml(o.courier.full_name) : '<span class="muted">—</span>'}</td>
        <td>${statusPill(o.status, o.status_label)}</td>
        <td style="text-align:right;font-weight:700">${fmtMoney(o.total_amount)}</td>
      </tr>
    `).join("");
  }

  function bindClicks() {
    tbody.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.addEventListener("click", () => go("order", { id: tr.dataset.id }));
    });
  }

  // URL — bookmark uchun. hashchange fire qilmaymiz (router butun sahifani
  // qayta render qilmasligi uchun) — `history.replaceState` ishlatamiz.
  function updateUrl() {
    const sp = new URLSearchParams();
    if (status) sp.set("status", status);
    if (page > 1) sp.set("page", String(page));
    const q = sp.toString();
    try {
      history.replaceState(
        null, "",
        `${location.pathname}${location.search}#/orders${q ? "?" + q : ""}`,
      );
    } catch (_) {}
  }

  async function loadPage() {
    if (loading) return;
    loading = true;
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const apiParams = { limit: PAGE_SIZE, offset };
      if (status) apiParams.status = status;
      const res = await api.orders(apiParams);
      const pageData = Array.isArray(res) ? { items: res, total: res.length } : res;
      cache = pageData.items || [];
      total = Number(pageData.total || 0);

      // Agar joriy sahifa total > 0 lekin items.length === 0 bo'lsa (masalan,
      // foydalanuvchi 5-sahifaga yuborilgan, lekin filter o'zgartirilgach
      // faqat 3 sahifa qoldi) — oxirgi mavjud sahifaga qaytamiz.
      if (cache.length === 0 && total > 0 && page > 1) {
        page = Math.max(1, Math.ceil(total / PAGE_SIZE));
        updateUrl();
        await loadPage();
        return;
      }

      countEl.textContent = total ? `${fmtCount(total)} ta buyurtma` : "";
      if (!cache.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">📦</div><div class="empty__text">Buyurtmalar yo'q.</div></td></tr>`;
        paginationWrap.innerHTML = "";
        return;
      }
      tbody.innerHTML = rowsHtml(cache);
      bindClicks();

      paginationWrap.innerHTML = renderPagination({ page, pageSize: PAGE_SIZE, total });
      bindPagination(paginationWrap, (newPage) => {
        page = newPage;
        updateUrl();
        loadPage();
        // Sahifa boshidan ko'rsatish — UX qulayligi uchun
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
      paginationWrap.innerHTML = "";
    } finally {
      loading = false;
    }
  }

  statusFilter.addEventListener("change", (e) => {
    status = e.target.value;
    page = 1;  // filter o'zgartirilsa — 1-sahifaga qaytamiz
    updateUrl();
    loadPage();
  });

  await loadPage();
}
