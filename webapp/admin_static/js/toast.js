let timer = null;

export function toast(message, kind = null) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("toast--error", "toast--success");
  if (kind === "error") el.classList.add("toast--error");
  if (kind === "success") el.classList.add("toast--success");
  el.classList.add("toast--show");
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("toast--show"), 2600);
}
