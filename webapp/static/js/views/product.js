import { cart } from "../state.js";
import { fmtMoney, escapeHtml } from "../format.js";
import {
  hapticImpact,
  hideBackButton,
  hideMainButton,
  showBackButton,
} from "../telegram.js";
import { back, go } from "../router.js";
import { showCTA, hideCTA } from "../cta.js";

export function renderProduct(root, { product }) {
  if (!product) {
    back();
    return;
  }
  document.getElementById("screen-title").textContent = product.name;
  showBackButton(() => back());
  hideMainButton();

  const desc = (product.description || "").trim();
  const imgHtml = product.image_url
    ? `<img src="${escapeHtml(product.image_url)}" alt="${escapeHtml(product.name)}" />`
    : `<div class="product__hero-fallback">💧</div>`;

  // Per-mahsulot minimal buyurtma — stepper shu chegaradan past tushmaydi.
  const minQ = Math.max(1, Number(product.min_quantity || 1));
  // Savatchadagi eski (stale) qiymat min'dan past bo'lsa ham — minga clamp.
  const initialQty = Math.max(cart.qty(product.id) || minQ, minQ);

  root.innerHTML = `
    <div class="product">
      <div class="product__hero">${imgHtml}</div>
      <h2 class="product__name">${escapeHtml(product.name)}</h2>
      <div class="product__price">${fmtMoney(product.price)}</div>
      ${minQ > 1 ? `<div class="muted" style="font-size:12px;margin-top:2px">Minimal buyurtma: ${minQ} dona</div>` : ""}
      ${desc ? `<div class="product__desc">${escapeHtml(desc)}</div>` : ""}

      <div class="qty">
        <div class="qty__label">Miqdor</div>
        <div class="qty__controls">
          <button class="qty__btn" id="dec" type="button" aria-label="Kamaytirish">−</button>
          <div class="qty__value" id="val">${initialQty}</div>
          <button class="qty__btn" id="inc" type="button" aria-label="Ko'paytirish">+</button>
        </div>
      </div>
    </div>
  `;

  const valEl = root.querySelector("#val");
  const decBtn = root.querySelector("#dec");
  const incBtn = root.querySelector("#inc");

  let qty = initialQty;
  const refresh = () => {
    valEl.textContent = qty;
    decBtn.disabled = qty <= minQ;
    incBtn.disabled = qty >= 999;
    const inCart = cart.qty(product.id) > 0;
    showCTA(
      `${inCart ? "Yangilash" : "Savatchaga qo'shish"} · ${fmtMoney(product.price * qty)}`,
      () => {
        hapticImpact("medium");
        cart.set(product.id, qty);
        go("cart");
      }
    );
  };

  decBtn.addEventListener("click", () => {
    if (qty > minQ) { qty--; hapticImpact("light"); refresh(); }
  });
  incBtn.addEventListener("click", () => {
    if (qty < 999) { qty++; hapticImpact("light"); refresh(); }
  });

  refresh();

  return () => {
    hideBackButton();
    hideCTA();
  };
}
