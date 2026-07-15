import { fmtMoney, escapeHtml } from "../format.js";
import { hideBackButton, hideMainButton } from "../telegram.js";
import { reset } from "../router.js";
import { showCTA, hideCTA } from "../cta.js";

export function renderSuccess(root, { order }) {
  document.getElementById("screen-title").textContent = "Buyurtma qabul qilindi";
  hideBackButton();
  hideMainButton();

  root.innerHTML = `
    <div class="success">
      <div class="success__icon">✓</div>
      <div class="success__title">Buyurtma ${escapeHtml(order.display_number || ("#" + order.id))} qabul qilindi!</div>
      <div class="success__sub">Tez orada kuryer aniqlanadi va siz bilan bog'lanadi.</div>
      <div class="card" style="text-align:left">
        <div style="font-weight:600;margin-bottom:6px">Tarkibi</div>
        ${order.items.map((it) => `
          <div style="display:flex;justify-content:space-between;font-size:14px;padding:2px 0">
            <span>${escapeHtml(it.food_name)} × ${it.quantity}</span>
            <span>${fmtMoney(Number(it.unit_price) * it.quantity)}</span>
          </div>`).join("")}
        <div class="divider"></div>
        <div style="display:flex;justify-content:space-between;font-weight:700">
          <span>Jami</span>
          <span>${fmtMoney(order.total_amount)}</span>
        </div>
      </div>
    </div>
  `;

  showCTA("Bosh sahifaga qaytish", () => reset("home"), { variant: "secondary" });

  return () => hideCTA();
}
