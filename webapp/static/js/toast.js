// Oddiy toast yordamchi.
let timer = null;

export function toast(message, { error = false, duration = 2400 } = {}) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("toast--error", !!error);
  el.classList.add("toast--show");
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("toast--show"), duration);
}
