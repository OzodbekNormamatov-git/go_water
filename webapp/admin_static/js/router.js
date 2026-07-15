// Hash-router — admin SPA uchun.
//
// MUHIM: Telegram WebApp sahifa ochilganda URL'ga `#tgWebAppData=...` hash
// fragmentini joylaydi. Bu bizning route emas — uni e'tiborga olmaymiz
// va default route ("dashboard") ga o'tamiz.

const routes = new Map();
const titles = new Map();

const ROUTE_PREFIX = "#/";
const DEFAULT_ROUTE = "dashboard";

export function register(name, render, { title } = {}) {
  routes.set(name, render);
  if (title) titles.set(name, title);
}

export function go(name, params = {}) {
  const q = new URLSearchParams(params).toString();
  location.hash = `${ROUTE_PREFIX}${name}${q ? "?" + q : ""}`;
}

export function current() {
  const hash = location.hash || "";
  // Bizning route'lar har doim `#/<name>` bilan boshlanadi.
  // Telegram'ning `#tgWebAppData=...` yoki bo'sh hash — default'ga ketadi.
  if (!hash.startsWith(ROUTE_PREFIX)) {
    return { name: DEFAULT_ROUTE, params: {} };
  }
  const path = hash.slice(ROUTE_PREFIX.length);
  const [name, query] = path.split("?");
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  return { name: name || DEFAULT_ROUTE, params };
}

function _setActiveNav(name) {
  document.querySelectorAll(".nav__item").forEach((el) => {
    el.classList.toggle("active", el.dataset.route === name);
  });
  const titleEl = document.getElementById("page-title");
  if (titleEl) {
    titleEl.textContent = titles.get(name) || titles.get(DEFAULT_ROUTE) || "";
  }
}

let _cleanup = null;

async function _render() {
  const { name, params } = current();
  const screen = document.getElementById("screen");
  if (_cleanup) { try { _cleanup(); } catch (_) {} _cleanup = null; }
  screen.innerHTML = `<div class="loading"><span class="spinner"></span> Yuklanmoqda…</div>`;
  _setActiveNav(name);
  const fn = routes.get(name) || routes.get(DEFAULT_ROUTE);
  try {
    const cleanup = await fn(screen, params);
    if (typeof cleanup === "function") _cleanup = cleanup;
  } catch (e) {
    console.error(e);
    screen.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${e.message || "Xatolik"}</div></div>`;
  }
}

export function start() {
  window.addEventListener("hashchange", _render);
  // Telegram `#tgWebAppData=...` qoldirgan bo'lsa, uni tozalab default'ga o'tamiz.
  // `replaceState` — hashchange event'ini ishga tushirmaydi, infinite loop yo'q.
  if (!location.hash.startsWith(ROUTE_PREFIX)) {
    history.replaceState(
      null, "", location.pathname + location.search + `${ROUTE_PREFIX}${DEFAULT_ROUTE}`,
    );
  }
  _render();
}
