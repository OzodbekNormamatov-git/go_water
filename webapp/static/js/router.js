// Eng oddiy hash-router. Tarix stack'ni ham ushlab turadi —
// Telegram BackButton uchun "orqaga" qaerga qaytishni biladi.

const stack = []; // [{ name, params }]
const routes = new Map();

export function register(name, render) {
  routes.set(name, render);
}

export function go(name, params = {}) {
  if (!routes.has(name)) throw new Error(`Route topilmadi: ${name}`);
  stack.push({ name, params });
  _render();
}

export function back() {
  if (stack.length <= 1) return false;
  stack.pop();
  _render();
  return true;
}

export function reset(name, params = {}) {
  stack.length = 0;
  go(name, params);
}

export function current() {
  return stack[stack.length - 1] || null;
}

function _render() {
  const cur = current();
  if (!cur) return;
  const screen = document.getElementById("screen");
  // Cleanup any per-view subscribers/handlers from previous render
  if (screen.__cleanup) {
    try { screen.__cleanup(); } catch (_) {}
    screen.__cleanup = null;
  }
  screen.innerHTML = "";
  const handle = routes.get(cur.name);
  const cleanup = handle(screen, cur.params);
  if (typeof cleanup === "function") screen.__cleanup = cleanup;
}
