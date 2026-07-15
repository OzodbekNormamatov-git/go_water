// Mini App entry point — kompozitsiya ildizi.

import { ready, applyTheme, isTelegram, initData } from "./telegram.js";
import { register, reset } from "./router.js";
import { api, ApiError } from "./api.js";
import { cart, session } from "./state.js";
import { setConfig } from "./config.js";
import { toast } from "./toast.js";
import { showTabbar, hideTabbar } from "./tabbar.js";

// Cart'ni server bilan sinxronlash — api.js circular bog'liqlik tug'dirmasligi
// uchun cart shu yerdan API'ga bog'lanadi.
cart.bindSync(
  (food_id, qty) => api.setCartItem(food_id, qty),
  () => api.clearCart(),
);

import { renderRegistration } from "./views/registration.js";
import { renderHome } from "./views/home.js";
import { renderProducts } from "./views/products.js";
import { renderProduct } from "./views/product.js";
import { renderCart } from "./views/cart.js";
import { renderCheckout } from "./views/checkout.js";
import { renderSuccess } from "./views/success.js";
import { renderOrders } from "./views/orders.js";
import { renderOrder } from "./views/order.js";
import { renderReorder } from "./views/reorder.js";
import { renderProfile } from "./views/profile.js";
import { renderAddresses } from "./views/addresses.js";

// Tab view'lar — pastida tab-bar chiqadi.
function withTabbar(name, render) {
  return (root, params) => {
    showTabbar(name);
    return render(root, params);
  };
}

// Detail view'lar — tab-bar yashirin (ekranni to'liq beradi).
function withoutTabbar(render) {
  return (root, params) => {
    hideTabbar();
    return render(root, params);
  };
}

register("home",         withTabbar("home",     renderHome));
register("products",     withTabbar("products", renderProducts));
register("cart",         withTabbar("cart",     renderCart));
register("orders",       withTabbar("orders",   renderOrders));
register("profile",      withTabbar("profile",  renderProfile));

register("registration", withoutTabbar(renderRegistration));
register("product",      withoutTabbar(renderProduct));
register("checkout",     withoutTabbar(renderCheckout));
register("success",      withoutTabbar(renderSuccess));
register("order",        withoutTabbar(renderOrder));
register("reorder",      withoutTabbar(renderReorder));
register("addresses",    withoutTabbar(renderAddresses));

async function bootstrap() {
  applyTheme();
  ready();

  const titleEl = document.getElementById("screen-title");
  const screen = document.getElementById("screen");

  if (!isTelegram || !initData) {
    hideTabbar();
    titleEl.textContent = "Telegram ichida oching";
    screen.innerHTML = `
      <div class="empty">
        <div class="empty__icon">🤖</div>
        <div class="empty__text">
          Bu sahifa faqat Telegram Mini App sifatida ishlaydi. Iltimos, botdan oching.
        </div>
      </div>`;
    return;
  }

  // ----- PARALLEL PREFETCH -----
  // 1) Config birinchi keladi (TTL/brand/status'lar uchun) — uni kutamiz.
  // 2) Me + products + orders parallel; tablar oralig'ida zero-loading.
  try {
    const cfg = await api.config();
    setConfig(cfg);
  } catch (_) {
    // Config xato bo'lsa default'lar bilan davom etamiz — degraded mode.
  }

  const meP = api.me();
  api.products().catch(() => {});
  api.myOrders().catch(() => {});
  // Server-side cart'ni keltirib, mahalliy state bilan birlashtiramiz.
  api.cart().then((view) => cart.hydrateFromServer(view)).catch(() => {});

  try {
    const me = await meP;
    session.set(me);
    if (!me.is_registered) {
      reset("registration");
    } else {
      // Birinchi sahifa = bosh sahifa (mahsulotlar avtomatik chiqmaydi).
      reset("home");
    }
  } catch (e) {
    hideTabbar();
    titleEl.textContent = "Xatolik";
    const msg = e instanceof ApiError ? e.message : "Server bilan bog'lanib bo'lmadi.";
    screen.innerHTML = `
      <div class="empty">
        <div class="empty__icon">⚠️</div>
        <div class="empty__text">${msg}</div>
      </div>`;
    toast(msg, { error: true });
  }
}

bootstrap();
