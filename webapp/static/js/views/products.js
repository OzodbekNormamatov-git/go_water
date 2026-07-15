import { api, ApiError } from "../api.js";
import { cart } from "../state.js";
import { fmtMoney, escapeHtml } from "../format.js";
import { hapticImpact, hideBackButton, hideMainButton } from "../telegram.js";
import { go } from "../router.js";

export function renderProducts(root) {
  document.getElementById("screen-title").textContent = "Mahsulotlar";
  hideBackButton();
  hideMainButton();

  // Skeleton
  root.innerHTML = `
    <div class="product-grid" id="grid">
      ${Array.from({ length: 6 }).map(() => `
        <div class="product-card">
          <div class="product-card__img-wrap"><div class="skeleton" style="width:100%;height:100%"></div></div>
          <div class="product-card__body">
            <div class="skeleton" style="height:14px;width:80%"></div>
            <div class="skeleton" style="height:12px;width:50%;margin-top:6px"></div>
          </div>
        </div>`).join("")}
    </div>
  `;

  const grid = root.querySelector("#grid");

  const renderGrid = (products) => {
    if (!products.length) {
      grid.outerHTML = `
        <div class="empty">
          <div class="empty__icon">📭</div>
          <div class="empty__text">Hozircha mahsulotlar yo'q.</div>
        </div>`;
      return;
    }
    grid.innerHTML = products.map((p) => {
      const qty = cart.qty(p.id);
      const img = p.image_url
        ? `<img class="product-card__img" src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.name)}" loading="lazy" />`
        : `<div class="product-card__placeholder">💧</div>`;
      const pill = qty > 0 ? `<div class="product-card__qty-pill">${qty}</div>` : "";
      return `
        <div class="product-card" data-id="${p.id}" role="button" tabindex="0">
          <div class="product-card__img-wrap">${img}${pill}</div>
          <div class="product-card__body">
            <div class="product-card__name">${escapeHtml(p.name)}</div>
            <div class="product-card__price">${fmtMoney(p.price)}</div>
            ${Number(p.min_quantity || 1) > 1 ? `<div class="muted" style="font-size:11px">min ${p.min_quantity} dona</div>` : ""}
          </div>
        </div>`;
    }).join("");

    grid.querySelectorAll(".product-card").forEach((card) => {
      card.addEventListener("click", () => {
        hapticImpact("light");
        const id = Number(card.getAttribute("data-id"));
        const product = products.find((p) => p.id === id);
        go("product", { product });
      });
    });
  };

  let unsubscribe = null;
  let products = [];

  (async () => {
    try {
      products = await api.products();
      renderGrid(products);
      unsubscribe = cart.subscribe(() => {
        // qty pill larni yangilash uchun grid'ni qayta chizamiz
        renderGrid(products);
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Yuklab bo'lmadi";
      grid.outerHTML = `
        <div class="empty">
          <div class="empty__icon">⚠️</div>
          <div class="empty__text">${escapeHtml(msg)}</div>
        </div>`;
    }
  })();

  return () => {
    if (unsubscribe) unsubscribe();
  };
}
