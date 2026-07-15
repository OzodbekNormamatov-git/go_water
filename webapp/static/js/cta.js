// In-page CTA bar — Telegram MainButton o'rniga.
// Tab-bar ustida joylashgan, sahifa ichida; mobil saqlash sezgisi tabiiy.

let _onClick = null;
let _busy = false;

function _ensureEl() {
  let el = document.getElementById("cta-bar");
  if (el) return el;
  el = document.createElement("div");
  el.id = "cta-bar";
  el.className = "cta-bar";
  el.hidden = true;
  el.innerHTML = `
    <button class="btn cta-bar__btn" id="cta-btn" type="button">
      <span class="cta-bar__spinner" aria-hidden="true" hidden>
        <span class="spinner"></span>
      </span>
      <span class="cta-bar__label" id="cta-label"></span>
    </button>
  `;
  document.getElementById("app").appendChild(el);
  el.querySelector("#cta-btn").addEventListener("click", () => {
    if (_busy || !_onClick) return;
    try { _onClick(); } catch (e) { console.error(e); }
  });
  return el;
}

export function showCTA(label, onClick, { variant = "primary", loading = false, disabled = false } = {}) {
  const el = _ensureEl();
  _onClick = onClick;
  _busy = !!loading || !!disabled;
  el.querySelector("#cta-label").textContent = label;
  const btn = el.querySelector("#cta-btn");
  btn.classList.toggle("btn--secondary", variant === "secondary");
  btn.classList.toggle("btn--danger", variant === "danger");
  btn.disabled = !!disabled;
  el.querySelector(".cta-bar__spinner").hidden = !loading;
  el.hidden = false;
  document.body.classList.add("has-cta");
}

export function setCTALoading(loading) {
  const el = document.getElementById("cta-bar");
  if (!el) return;
  _busy = !!loading;
  el.querySelector(".cta-bar__spinner").hidden = !loading;
  el.querySelector("#cta-btn").disabled = !!loading;
}

export function hideCTA() {
  const el = document.getElementById("cta-bar");
  if (!el) return;
  el.hidden = true;
  _onClick = null;
  _busy = false;
  document.body.classList.remove("has-cta");
}
