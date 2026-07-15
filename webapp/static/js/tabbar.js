// Pastki tab-bar — 5 ta tab: Bosh sahifa / Mahsulotlar / Savatcha / Buyurtmalar / Profil.
// Tab almashtirish — `router.reset(name)`. Detail view'larda tab-bar yashirinadi.

import { reset, current as currentRoute } from "./router.js";
import { cart } from "./state.js";
import { hapticImpact } from "./telegram.js";

const TABS = [
  { name: "home",     icon: "🏠", label: "Bosh sahifa" },
  { name: "products", icon: "💧", label: "Mahsulotlar" },
  { name: "cart",     icon: "🛒", label: "Savatcha" },
  { name: "orders",   icon: "📦", label: "Buyurtmalar" },
  { name: "profile",  icon: "👤", label: "Profil" },
];

const TAB_NAMES = new Set(TABS.map((t) => t.name));

let _initialized = false;
let _unsubCart = null;

function _render(active) {
  const el = document.getElementById("tabbar");
  if (!el) return;
  const cartCount = cart.totalCount();
  el.innerHTML = TABS.map((t) => {
    const isActive = t.name === active;
    const badge = t.name === "cart" && cartCount > 0
      ? `<span class="tab__badge">${cartCount > 99 ? "99+" : cartCount}</span>`
      : "";
    return `
      <button class="tab ${isActive ? "tab--active" : ""}" data-tab="${t.name}" type="button" aria-label="${t.label}">
        <span class="tab__icon-wrap">
          <span class="tab__icon">${t.icon}</span>
          ${badge}
        </span>
        <span class="tab__label">${t.label}</span>
      </button>
    `;
  }).join("");

  el.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-tab");
      hapticImpact("light");
      if (name === active) return; // shu tabning o'zi
      reset(name);
    });
  });
}

export function showTabbar(activeName) {
  const el = document.getElementById("tabbar");
  if (!el) return;
  el.hidden = false;
  document.body.classList.remove("no-tabbar");
  if (!_initialized) {
    _initialized = true;
    _unsubCart = cart.subscribe(() => {
      // savatcha o'zgarsa — faqat hozirgi tab uchun qayta chizamiz
      const cur = currentRoute();
      const name = cur && TAB_NAMES.has(cur.name) ? cur.name : "";
      _render(name);
    });
  }
  _render(activeName || "");
}

export function hideTabbar() {
  const el = document.getElementById("tabbar");
  if (!el) return;
  el.hidden = true;
  document.body.classList.add("no-tabbar");
}
