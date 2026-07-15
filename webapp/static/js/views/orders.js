// Buyurtmalar — jarayondagi va tarix bo'limlari + "Yana yuklash" (pagination).

import { api, ApiError } from "../api.js";
import { fmtMoney, fmtDate, escapeHtml } from "../format.js";
import { hapticImpact, hideBackButton, hideMainButton } from "../telegram.js";
import { go } from "../router.js";
import { statusOf } from "../config.js";

const ACTIVE_STATUSES = new Set(["NEW", "ACCEPTED", "DELIVERING", "ARRIVED"]);
const PAGE_SIZE = 20;

function statusPill(statusName, label) {
  const s = statusOf(statusName);
  const cls = `status-pill status-pill--${s.token}`;
  return `<span class="${cls}">${s.emoji ? s.emoji + " " : ""}${escapeHtml(label || s.label)}</span>`;
}

function row(o) {
  const items = (o.items || [])
    .map((it) => `${escapeHtml(it.food_name)} × ${it.quantity}`)
    .join(", ");
  return `
    <div class="order-row order-row--clickable" data-id="${o.id}" role="button" tabindex="0">
      <div class="order-row__head">
        <div class="order-row__id">${escapeHtml(o.display_number || ("#" + o.id))}</div>
        ${statusPill(o.status, o.status_label)}
      </div>
      <div class="order-row__total">${fmtMoney(o.total_amount)}</div>
      ${items ? `<div class="order-row__date" style="margin-top:4px">${items}</div>` : ""}
      <div class="order-row__date">${escapeHtml(fmtDate(o.created_at))}</div>
    </div>
  `;
}

function attachOrderRowHandlers(scope) {
  scope.querySelectorAll(".order-row--clickable").forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    const id = Number(el.getAttribute("data-id"));
    el.addEventListener("click", () => {
      hapticImpact("light");
      go("order", { orderId: id });
    });
  });
}

export function renderOrders(root) {
  document.getElementById("screen-title").textContent = "Buyurtmalarim";
  hideBackButton();
  hideMainButton();

  root.innerHTML = `
    <div id="activeBlock"></div>
    <div id="historyBlock"></div>
    <div id="loadMoreWrap" style="margin-top:12px;text-align:center"></div>
  `;

  const activeBlock = root.querySelector("#activeBlock");
  const historyBlock = root.querySelector("#historyBlock");
  const loadMoreWrap = root.querySelector("#loadMoreWrap");

  let allActive = [];
  let allHistory = [];
  let offset = 0;
  let total = 0;
  let loading = false;

  async function fetchPage() {
    if (loading) return;
    loading = true;
    try {
      const res = await api.myOrders({ limit: PAGE_SIZE, offset });
      // Backward-compat: agar BE eski format (array) bersa
      const items = Array.isArray(res) ? res : (res.items || []);
      total = Array.isArray(res) ? items.length : (res.total || items.length);

      const newActive = items.filter((o) => ACTIVE_STATUSES.has(o.status));
      const newHistory = items.filter((o) => !ACTIVE_STATUSES.has(o.status));

      allActive = allActive.concat(newActive);
      allHistory = allHistory.concat(newHistory);

      offset += items.length;
      render();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Yuklab bo'lmadi";
      root.innerHTML = `
        <div class="empty">
          <div class="empty__icon">⚠️</div>
          <div class="empty__text">${escapeHtml(msg)}</div>
        </div>`;
    } finally {
      loading = false;
    }
  }

  function render() {
    if (!allActive.length && !allHistory.length) {
      root.innerHTML = `
        <div class="empty">
          <div class="empty__icon">📦</div>
          <div class="empty__text">Sizda hali buyurtmalar yo'q.</div>
        </div>`;
      return;
    }
    activeBlock.innerHTML = allActive.length
      ? `<div class="section-title">Jarayonda (${allActive.length})</div>${allActive.map(row).join("")}`
      : "";
    historyBlock.innerHTML = allHistory.length
      ? `<div class="section-title" style="margin-top:18px">Tarix (${allHistory.length})</div>${allHistory.map(row).join("")}`
      : "";
    attachOrderRowHandlers(activeBlock);
    attachOrderRowHandlers(historyBlock);

    if (offset < total) {
      loadMoreWrap.innerHTML = `
        <button class="btn btn--ghost" id="loadMoreBtn" type="button">
          Yana yuklash (${total - offset} qoldi)
        </button>
      `;
      loadMoreWrap.querySelector("#loadMoreBtn").addEventListener("click", fetchPage);
    } else {
      loadMoreWrap.innerHTML = "";
    }
  }

  fetchPage();
}
