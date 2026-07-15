// Bosh sahifa — greeting, jarayondagi buyurtmalar, savatcha xulosasi, tezkor tugma.

import { api, ApiError, invalidateCache } from "../api.js";
import { cart, session } from "../state.js";
import { fmtMoney, escapeHtml } from "../format.js";
import { hideBackButton, hideMainButton } from "../telegram.js";
import { go, reset } from "../router.js";
import { statusOf } from "../config.js";

const ACTIVE_STATUSES = new Set(["NEW", "ACCEPTED", "DELIVERING", "ARRIVED"]);

function statusPill(statusName, label) {
  const s = statusOf(statusName);
  const cls = `status-pill status-pill--${s.token}`;
  return `<span class="${cls}">${s.emoji ? s.emoji + " " : ""}${escapeHtml(label || s.label)}</span>`;
}

export function renderHome(root) {
  document.getElementById("screen-title").textContent = "Bosh sahifa";
  hideBackButton();
  hideMainButton();

  const me = session.me || {};
  const brand = (me.brand_name || "").trim() || "Delivery";

  // Skeleton avval — keyin ma'lumot yuklangach to'liq render.
  root.innerHTML = `
    <div class="home-hero">
      <div class="home-hero__greeting">Xush kelibsiz!</div>
      <h1 class="home-hero__title">${escapeHtml(brand)}</h1>
      <div class="home-hero__brand">Toza ichimlik suvi yetkazib berish</div>
    </div>

    <div id="active-area"></div>
    <div id="reorder-area"></div>
    <div id="cart-area"></div>

    <div class="section-title">Tezkor</div>
    <div class="tile" id="goShop">
      <div class="tile__icon">💧</div>
      <div class="tile__main">
        <div class="tile__title">Mahsulot tanlash</div>
        <div class="tile__sub">Yangi buyurtma berish</div>
      </div>
      <div class="tile__chev">›</div>
    </div>
    <div class="tile" id="goOrders">
      <div class="tile__icon">📦</div>
      <div class="tile__main">
        <div class="tile__title">Buyurtmalarim</div>
        <div class="tile__sub">Tarix va holat</div>
      </div>
      <div class="tile__chev">›</div>
    </div>
  `;

  root.querySelector("#goShop").addEventListener("click", () => reset("products"));
  root.querySelector("#goOrders").addEventListener("click", () => reset("orders"));

  const activeArea = root.querySelector("#active-area");
  const reorderArea = root.querySelector("#reorder-area");
  const cartArea = root.querySelector("#cart-area");

  // ----- Cart preview
  const renderCartArea = () => {
    const count = cart.totalCount();
    if (!count) { cartArea.innerHTML = ""; return; }
    cartArea.innerHTML = `
      <div class="section-title">Savatcha</div>
      <div class="tile" id="goCart">
        <div class="tile__icon">🛒</div>
        <div class="tile__main">
          <div class="tile__title">${count} ta mahsulot</div>
          <div class="tile__sub">Buyurtmani rasmiylashtirishga tayyor</div>
        </div>
        <div class="tile__chev">›</div>
      </div>
    `;
    cartArea.querySelector("#goCart").addEventListener("click", () => reset("cart"));
  };
  renderCartArea();
  const unsub = cart.subscribe(renderCartArea);

  // Fresh me — fonda yangilash (balansni ham sinxronlash uchun)
  (async () => {
    try {
      invalidateCache("me");
      const fresh = await api.me();
      session.set(fresh);
    } catch (_) { /* silent */ }
  })();

  // ----- Active orders + "oxirgi buyurtmani takrorlash" (bitta fetch)
  (async () => {
    try {
      const ordersRes = await api.myOrders();
      const orders = Array.isArray(ordersRes) ? ordersRes : (ordersRes.items || []);

      // Jarayondagi buyurtmalar
      const active = orders.filter((o) => ACTIVE_STATUSES.has(o.status));
      if (active.length) {
        activeArea.innerHTML = `
          <div class="section-title">Jarayondagi buyurtmalar</div>
          ${active.map((o) => `
            <div class="tile" data-id="${o.id}">
              <div class="tile__icon">🚗</div>
              <div class="tile__main">
                <div class="tile__title">Buyurtma ${escapeHtml(o.display_number || ("#" + o.id))} · ${fmtMoney(o.total_amount)}</div>
                <div class="tile__sub">${statusPill(o.status, o.status_label)}</div>
              </div>
              <div class="tile__chev">›</div>
            </div>
          `).join("")}
        `;
        activeArea.querySelectorAll(".tile").forEach((el) => {
          const orderId = Number(el.getAttribute("data-id"));
          el.addEventListener("click", () => go("order", { orderId }));
        });
      } else {
        activeArea.innerHTML = "";
      }

      // Oxirgi buyurtmani takrorlash — eng so'nggi buyurtma (har qanday holatda)
      renderReorderCard(orders[0]);
    } catch (e) {
      // Sokin xato — bosh sahifani buzmaymiz, faqat sektor bo'sh.
      activeArea.innerHTML = "";
      reorderArea.innerHTML = "";
    }
  })();

  function renderReorderCard(last) {
    if (!last || !Array.isArray(last.items) || !last.items.length) {
      reorderArea.innerHTML = "";
      return;
    }
    // Qisqacha tarkib: "Suv 19L × 2, Stakan × 1" (uzun bo'lsa kesiladi)
    const itemsShort = last.items
      .map((it) => `${it.food_name} × ${it.quantity}`)
      .join(", ");
    reorderArea.innerHTML = `
      <div class="section-title">Tezkor takror</div>
      <div class="tile tile--accent" id="reorderTile">
        <div class="tile__icon">🔁</div>
        <div class="tile__main">
          <div class="tile__title">Oxirgi buyurtmani takrorlash</div>
          <div class="tile__sub">${escapeHtml(itemsShort)} · ${fmtMoney(last.total_amount)}</div>
        </div>
        <div class="tile__chev">›</div>
      </div>
    `;
    reorderArea.querySelector("#reorderTile").addEventListener("click", () => {
      go("reorder", { orderId: last.id });
    });
  }

  return () => { if (unsub) unsub(); };
}
