// Admin SPA entry point — Telegram WebApp Mini App sifatida ishlaydi.

import { api, ApiError, isTelegram, tgApp } from "./api.js";
import { register, start, go } from "./router.js";
import { toast } from "./toast.js";
import { escapeHtml } from "./format.js";
import { renderDashboard } from "./views/dashboard.js";
import { renderOrders } from "./views/orders.js";
import { renderOrderDetail } from "./views/order_detail.js";
import { renderProducts } from "./views/products.js";
import { renderCouriers } from "./views/couriers.js";
import { renderCustomers } from "./views/customers.js";
import { renderFinance } from "./views/finance.js";
import { renderActivity } from "./views/activity.js";
import { renderBroadcasts } from "./views/broadcasts.js";
import { renderSettings } from "./views/settings.js";
import { renderOperatorOrder } from "./views/operator_order.js";
import { renderOperators } from "./views/operators.js";
import { renderPromoters } from "./views/promoters.js";
import { renderReorder } from "./views/reorder.js";

register("dashboard", renderDashboard, { title: "Dashboard" });
register("orders",    renderOrders,    { title: "Buyurtmalar" });
register("reorder",   renderReorder,   { title: "Aqlli eslatma" });
register("order",     renderOrderDetail, { title: "Buyurtma" });
register("products",  renderProducts,  { title: "Mahsulotlar" });
register("couriers",  renderCouriers,  { title: "Kuryerlar" });
register("operators", renderOperators, { title: "Operatorlar" });
register("promoters", renderPromoters, { title: "Promouterlar" });
register("customers", renderCustomers, { title: "Mijozlar" });
register("finance",   renderFinance,   { title: "Moliyaviy hisobot" });
register("activity",  renderActivity,  { title: "Mijozlar faolligi" });
register("broadcasts", renderBroadcasts, { title: "Rassilka" });
register("settings",  renderSettings,  { title: "Sozlamalar" });
register("operator_new_order", renderOperatorOrder, { title: "Yangi buyurtma" });

// ----- Telegram WebApp boot -----
const MOBILE_PLATFORMS = new Set(["android", "android_x", "ios"]);

if (isTelegram) {
  try {
    tgApp.ready();
    tgApp.expand();
    const platform = (tgApp.platform || "").toLowerCase();
    const isMobile = MOBILE_PLATFORMS.has(platform);
    document.body.classList.toggle("tg-mobile", isMobile);
    document.body.classList.toggle("tg-desktop", !isMobile);
    // Fullscreen FAQAT desktop'da — mobile'da Telegram o'zi optimal ko'rinadi.
    if (!isMobile && typeof tgApp.requestFullscreen === "function") {
      try { tgApp.requestFullscreen(); } catch (_) {}
    }
    if (typeof tgApp.disableVerticalSwipes === "function") {
      tgApp.disableVerticalSwipes();
    }
    if (typeof tgApp.setHeaderColor === "function") {
      try { tgApp.setHeaderColor("#003F7F"); } catch (_) {}
    }
  } catch (e) {
    console.warn("Telegram boot failed", e);
  }
} else {
  document.body.classList.add(window.innerWidth < 600 ? "tg-mobile" : "tg-desktop");
}

// ----- Nav -----
const appEl = document.getElementById("app");
const backdropEl = document.getElementById("sidebar-backdrop");

function closeSidebar() {
  appEl.classList.remove("sidebar-open");
  if (backdropEl) backdropEl.setAttribute("hidden", "");
}
function openSidebar() {
  appEl.classList.add("sidebar-open");
  if (backdropEl) backdropEl.removeAttribute("hidden");
}
function toggleSidebar() {
  if (appEl.classList.contains("sidebar-open")) closeSidebar();
  else openSidebar();
}

document.querySelectorAll(".nav__item").forEach((el) => {
  el.addEventListener("click", (e) => {
    e.preventDefault();
    go(el.dataset.route);
    closeSidebar();
  });
});

document.getElementById("hamburger").addEventListener("click", toggleSidebar);

// Backdrop bosilsa — sidebar yopiladi (Material/iOS pattern).
if (backdropEl) {
  backdropEl.addEventListener("click", closeSidebar);
}

// ESC bilan ham yopish (qulaylik uchun)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && appEl.classList.contains("sidebar-open")) {
    closeSidebar();
  }
});

// ----- Role-based menu filter -----
// Operator ko'radi: "Yangi buyurtma" + "Buyurtmalar" + "Aqlli eslatma" + "Mijozlar"
// (mijoz qidirish/qo'shish uchun; balans tahrirlash faqat adminda).
const OPERATOR_ROUTES = new Set(["operator_new_order", "orders", "order", "reorder", "customers"]);

function applyRoleVisibility(role) {
  if (role === "admin") return;  // admin barchasini ko'radi
  // Operator — admin sahifalarini sidebar'dan yashiramiz
  document.querySelectorAll(".nav__item").forEach((el) => {
    if (!OPERATOR_ROUTES.has(el.dataset.route)) {
      el.style.display = "none";
    }
  });
}

// ----- Bootstrap -----
function showFatal(text) {
  document.getElementById("screen").innerHTML = `
    <div class="empty">
      <div class="empty__icon">🔒</div>
      <div class="empty__text">${text}</div>
    </div>`;
  document.getElementById("sidebar").style.display = "none";
  document.querySelector(".topbar").style.display = "none";
}

(async () => {
  if (!isTelegram) {
    showFatal(
      "Bu sahifa faqat <b>Telegram ichida</b> ochiladi. Admin botga kiring va " +
      "<b>/start</b> yuborib, tepada chiqqan <b>🌐 Admin paneli</b> tugmasini bosing."
    );
    return;
  }
  if (!tgApp.initData) {
    const host = location.host;
    const hashRaw = location.hash || "(empty)";
    // XSS himoyasi: hash foydalanuvchi boshqara oladigan qiymat — innerHTML'ga
    // qo'yishdan oldin escape qilamiz.
    const hashShort = escapeHtml(hashRaw.length > 140 ? hashRaw.slice(0, 140) + "…" : hashRaw);
    const hasTgData = hashRaw.includes("tgWebAppData=");
    const platform = tgApp.platform || "?";
    const version = tgApp.version || "?";
    const initUnsafe = tgApp.initDataUnsafe || {};
    const userId = (initUnsafe.user && initUnsafe.user.id) || "(yo'q)";

    showFatal(
      `<b>Telegram initData yetishmayapti</b><br><br>` +
      `<div style="text-align:left;background:#f5f5f5;padding:12px;border-radius:8px;font-family:monospace;font-size:11px;margin-bottom:14px">` +
      `<b>Diagnostika:</b><br>` +
      `host: ${host}<br>` +
      `platform: ${platform}<br>` +
      `version: ${version}<br>` +
      `hash bor: ${hasTgData ? "✅ ha" : "❌ yo'q"}<br>` +
      `user.id: ${userId}<br>` +
      `hash: ${hashShort}` +
      `</div>` +
      (hasTgData
        ? `Hash bor — lekin Telegram SDK uni parse qila olmadi. Telegram'ni yangilang (eski versiya).`
        : `<b>Sabab:</b> Telegram bu sahifani WebApp sifatida ochmagan (faqat URL kabi). ` +
          `<b>Tuzatish:</b><br>` +
          `1. @BotFather → /mybots → <b>admin bot</b> tanlang<br>` +
          `2. <b>Bot Settings → Menu Button</b> → "Configure menu button"<br>` +
          `3. Button text: <i>Admin paneli</i><br>` +
          `4. URL: <code>https://${host}/admin/</code><br><br>` +
          `<b>VA</b> /setdomain ham:<br>` +
          `5. /setdomain → admin bot → <code>${host}</code><br><br>` +
          `So'ngra botda /start yuborib, <b>YANGI</b> tugmani bosing (eski xabardagi emas).`
      )
    );
    return;
  }
  try {
    const me = await api.me();
    const userEl = document.getElementById("user-info");
    if (userEl) {
      const name = me.first_name + (me.last_name ? " " + me.last_name : "");
      const roleSuffix = me.role === "operator" ? " · 📞 Operator" : "";
      userEl.textContent = `${name}${me.username ? " @" + me.username : ""}${roleSuffix}`;
    }
    // Role'ga qarab brand nomini ham yangilash
    const brandNameEl = document.getElementById("brand-name");
    if (brandNameEl && me.role === "operator") {
      brandNameEl.textContent = "Operator";
    }
    // Operator faqat "Yangi buyurtma" + "Buyurtmalar"ni ko'radi
    applyRoleVisibility(me.role || "operator");
    // Operator default sahifasi — "Yangi buyurtma"
    if (me.role === "operator" && !location.hash.startsWith("#/")) {
      location.hash = "#/operator_new_order";
    }
    start();
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.code === "unauthorized") {
        showFatal("Sessiya yaroqsiz. Mini App'ni qaytadan oching.");
        return;
      }
      if (e.code === "forbidden") {
        showFatal("Sizga admin paneliga kirish ruxsati berilmagan.");
        return;
      }
    }
    showFatal(e.message || "Server bilan bog'lanib bo'lmadi.");
  }
})();
