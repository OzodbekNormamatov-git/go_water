import { api } from "../api.js";
import { fmtMoney, fmtDate, escapeHtml, statusPill } from "../format.js";
import { toast } from "../toast.js";
import { go } from "../router.js";

export async function renderOrderDetail(root, params) {
  const id = Number(params.id);
  if (!id) { go("orders"); return; }

  root.innerHTML = `<div class="loading"><span class="spinner"></span> Yuklanmoqda…</div>`;

  let order;
  try { order = await api.order(id); }
  catch (e) {
    root.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    return;
  }

  const canCancel = !["DELIVERED", "CANCELLED"].includes(order.status);

  const items = (order.items || []).map((it) => `
    <div class="detail-row">
      <span class="detail-row__label">${escapeHtml(it.food_name)} × ${it.quantity}</span>
      <span class="detail-row__value">${fmtMoney(Number(it.unit_price) * it.quantity)}</span>
    </div>
  `).join("");

  root.innerHTML = `
    <div class="toolbar">
      <button class="btn btn--secondary" id="back">← Ro'yxat</button>
      <div style="display:flex;gap:8px;align-items:center">
        ${statusPill(order.status, order.status_label)}
        ${canCancel ? `<button class="btn btn--danger" id="cancel">Bekor qilish</button>` : ""}
      </div>
    </div>

    <div class="detail-grid">
      <div class="card">
        <h3 class="card__title">Buyurtma</h3>
        <div class="detail-row"><span class="detail-row__label">№</span><span class="detail-row__value">${escapeHtml(order.display_number || ("#" + order.id))}</span></div>
        <div class="detail-row"><span class="detail-row__label">Yaratilgan</span><span class="detail-row__value">${escapeHtml(fmtDate(order.created_at))}</span></div>
        <div class="detail-row"><span class="detail-row__label">Qabul qilindi</span><span class="detail-row__value">${escapeHtml(fmtDate(order.accepted_at))}</span></div>
        <div class="detail-row"><span class="detail-row__label">Yo'lda</span><span class="detail-row__value">${escapeHtml(fmtDate(order.delivering_at))}</span></div>
        ${order.arrived_at ? `<div class="detail-row"><span class="detail-row__label">Yetib keldi</span><span class="detail-row__value">${escapeHtml(fmtDate(order.arrived_at))}</span></div>` : ""}
        <div class="detail-row"><span class="detail-row__label">Yetkazildi</span><span class="detail-row__value">${escapeHtml(fmtDate(order.delivered_at))}</span></div>
        ${order.cancelled_at ? `<div class="detail-row"><span class="detail-row__label">Bekor qilingan</span><span class="detail-row__value">${escapeHtml(fmtDate(order.cancelled_at))}</span></div>` : ""}
        <div class="detail-row"><span class="detail-row__label">Jami</span><span class="detail-row__value" style="font-size:18px;color:var(--brand-deep)">${fmtMoney(order.total_amount)}</span></div>
      </div>

      <div class="card">
        <h3 class="card__title">Mijoz</h3>
        <div class="detail-row"><span class="detail-row__label">Ism</span><span class="detail-row__value">${escapeHtml(order.customer.full_name)}</span></div>
        <div class="detail-row"><span class="detail-row__label">Telefon</span><span class="detail-row__value">${escapeHtml(order.customer.phone_number)}</span></div>
        <div class="detail-row"><span class="detail-row__label">Aloqa</span><span class="detail-row__value">${escapeHtml(order.contact_phone)}</span></div>
        <div class="detail-row"><span class="detail-row__label">Telegram ID</span><span class="detail-row__value">${order.customer.telegram_id}</span></div>
      </div>

      <div class="card">
        <h3 class="card__title">Kuryer</h3>
        ${order.courier ? `
          <div class="detail-row"><span class="detail-row__label">Ism</span><span class="detail-row__value">${escapeHtml(order.courier.full_name)}</span></div>
          <div class="detail-row"><span class="detail-row__label">Telefon</span><span class="detail-row__value">${
            order.courier.phone_number
              ? `<a href="tel:${escapeHtml(order.courier.phone_number)}">${escapeHtml(order.courier.phone_number)}</a>`
              : '<span class="muted">— kiritilmagan</span>'
          }</span></div>
          <div class="detail-row"><span class="detail-row__label">Username</span><span class="detail-row__value">${order.courier.username ? '@' + escapeHtml(order.courier.username) : '—'}</span></div>
          <div class="detail-row"><span class="detail-row__label">Telegram ID</span><span class="detail-row__value">${order.courier.telegram_id}</span></div>
        ` : `<div class="empty"><div class="empty__text">Kuryer hali biriktirilmagan.</div></div>`}
      </div>

      <div class="card">
        <h3 class="card__title">Manzil</h3>
        <a class="btn btn--secondary" href="${escapeHtml(order.map_url)}" target="_blank" rel="noopener" style="width:100%">📍 Xaritada ko'rish</a>
        <div class="detail-row" style="margin-top:8px"><span class="detail-row__label">Koordinatalar</span><span class="detail-row__value" style="font-family:monospace">${order.latitude.toFixed(5)}, ${order.longitude.toFixed(5)}</span></div>
        ${order.note ? `<div class="detail-row" style="display:block"><span class="detail-row__label">Izoh</span><div class="detail-row__value" style="text-align:left;margin-top:4px;white-space:pre-wrap">${escapeHtml(order.note)}</div></div>` : ""}
      </div>

      <div class="card" style="grid-column: 1 / -1">
        <h3 class="card__title">Mahsulotlar</h3>
        ${items || `<div class="empty"><div class="empty__text">Mahsulot yo'q.</div></div>`}
      </div>
    </div>
  `;

  document.getElementById("back").addEventListener("click", () => go("orders"));

  const cancelBtn = document.getElementById("cancel");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      if (!confirm(`${order.display_number || ("#" + order.id)} buyurtmasi bekor qilinsinmi?`)) return;
      try {
        await api.cancelOrder(order.id);
        toast("Bekor qilindi", "success");
        renderOrderDetail(root, { id: order.id });
      } catch (e) { toast(e.message, "error"); }
    });
  }
}
