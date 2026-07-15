// Buyurtma batafsil sahifasi — timeline, kuryer ma'lumotlari, joylashuv, mahsulotlar.

import { api, ApiError } from "../api.js";
import { fmtMoney, fmtDate, escapeHtml } from "../format.js";
import { hideBackButton, hideMainButton, showBackButton } from "../telegram.js";
import { back } from "../router.js";
import { hideCTA } from "../cta.js";

const STATUS_FLOW = ["NEW", "ACCEPTED", "DELIVERING", "ARRIVED", "DELIVERED"];

function statusPill(statusName, label) {
  const cls = `status-pill status-pill--${statusName.toLowerCase()}`;
  return `<span class="${cls}">${escapeHtml(label)}</span>`;
}

function initials(name) {
  if (!name) return "🚗";
  return name.trim().split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
}

function timelineStep(icon, label, iso, active = false, done = false) {
  const stateCls = done ? "timeline__step--done" : active ? "timeline__step--active" : "timeline__step--pending";
  const time = iso ? fmtDate(iso) : "";
  return `
    <div class="timeline__step ${stateCls}">
      <div class="timeline__dot">${icon}</div>
      <div class="timeline__body">
        <div class="timeline__label">${escapeHtml(label)}</div>
        ${time ? `<div class="timeline__time">${escapeHtml(time)}</div>` : `<div class="timeline__time muted">—</div>`}
      </div>
    </div>
  `;
}

function renderTimeline(order) {
  const status = order.status;
  const cancelled = status === "CANCELLED";
  const flowIndex = STATUS_FLOW.indexOf(status);

  if (cancelled) {
    return `
      <div class="timeline">
        ${timelineStep("🆕", "Buyurtma qabul qilindi", order.created_at, false, true)}
        ${timelineStep("❌", "Bekor qilindi", order.cancelled_at, false, true)}
      </div>
    `;
  }

  return `
    <div class="timeline">
      ${timelineStep("🆕", "Buyurtma qabul qilindi", order.created_at,    flowIndex === 0, flowIndex > 0)}
      ${timelineStep("👤", "Kuryer biriktirildi",   order.accepted_at,   flowIndex === 1, flowIndex > 1)}
      ${timelineStep("🚗", "Yo'lga chiqdi",         order.delivering_at, flowIndex === 2, flowIndex > 2)}
      ${timelineStep("📍", "Kuryer yetib keldi",    order.arrived_at,    flowIndex === 3, flowIndex > 3)}
      ${timelineStep("✅", "Yetkazib berildi",      order.delivered_at,  flowIndex === 4, flowIndex > 4)}
    </div>
  `;
}

function renderCourier(order) {
  if (!order.courier) {
    return `
      <div class="section-title">Kuryer</div>
      <div class="card">
        <div class="muted">Kuryer hali biriktirilmagan. Tez orada aniqlanadi.</div>
      </div>
    `;
  }
  const c = order.courier;
  // Aloqa tugmalari — telefon ustun (mobile'da tel: link darhol qo'ng'iroq
  // oynasini ochadi). Telegram username — qo'shimcha (chat'da yozish).
  const callBtn = c.phone_number
    ? `<a class="btn btn--success" href="tel:${escapeHtml(c.phone_number)}">📞 Qo'ng'iroq</a>`
    : "";
  const tgBtn = c.username
    ? `<a class="btn btn--secondary" href="https://t.me/${escapeHtml(c.username)}" target="_blank" rel="noopener">💬 Telegram</a>`
    : "";
  const actionsHtml = (callBtn || tgBtn)
    ? `<div class="courier-card__actions">${callBtn}${tgBtn}</div>`
    : "";
  return `
    <div class="section-title">Kuryer</div>
    <div class="courier-card">
      <div class="avatar avatar--sm">${escapeHtml(initials(c.full_name))}</div>
      <div class="courier-card__main">
        <div class="courier-card__name">${escapeHtml(c.full_name)}</div>
        ${c.phone_number
          ? `<div class="courier-card__sub" style="font-family:ui-monospace,monospace">${escapeHtml(c.phone_number)}</div>`
          : ""}
        ${c.username ? `<div class="courier-card__sub">@${escapeHtml(c.username)}</div>` : ""}
      </div>
      ${actionsHtml}
    </div>
  `;
}

export function renderOrder(root, { orderId }) {
  document.getElementById("screen-title").textContent = "Buyurtma";
  showBackButton(() => back());
  hideMainButton();
  hideCTA();

  root.innerHTML = `<div class="muted center" style="padding:20px">Yuklanmoqda…</div>`;

  (async () => {
    try {
      const order = await api.order(orderId);

      // Sarlavhani kunlik raqam bilan yangilaymiz (backend tayyor string beradi).
      const num = order.display_number || `#${order.id}`;
      document.getElementById("screen-title").textContent = `Buyurtma ${num}`;

      const itemsHtml = (order.items || []).map((it) => {
        // Kuryer yetkazishда miqdorni o'zgartirgan bo'lsa — asl buyurtmani ham
        // ko'rsatamiz ("× 6 (buyurtma: 4)"), Telegram/admin display bilan izchil.
        const ordered = it.ordered_quantity;
        const adj = ordered != null && Number(ordered) !== Number(it.quantity);
        const qtyLabel = adj
          ? `× ${it.quantity} <span class="muted" style="font-size:12px">(buyurtma: ${ordered})</span>`
          : `× ${it.quantity}`;
        return `
        <div class="order-item">
          <div class="order-item__name">${escapeHtml(it.food_name)} ${qtyLabel}</div>
          <div class="order-item__total">${fmtMoney(Number(it.unit_price) * it.quantity)}</div>
        </div>
      `;
      }).join("");

      root.innerHTML = `
        <div class="order-detail__head">
          <div>
            <div class="muted" style="font-size:13px">Buyurtma</div>
            <div style="font-size:22px;font-weight:700">${escapeHtml(num)}</div>
          </div>
          ${statusPill(order.status, order.status_label)}
        </div>

        <div class="section-title">Bosqichlar</div>
        ${renderTimeline(order)}

        ${renderCourier(order)}

        <div class="section-title">Manzil</div>
        <a class="tile" href="${escapeHtml(order.map_url)}" target="_blank" rel="noopener">
          <div class="tile__icon">📍</div>
          <div class="tile__main">
            <div class="tile__title">${escapeHtml(order.address_label || "Xaritada ko'rish")}</div>
            <div class="tile__sub">${order.latitude.toFixed(5)}, ${order.longitude.toFixed(5)}</div>
            ${order.address_details ? `<div class="tile__sub">${escapeHtml(order.address_details)}</div>` : ""}
          </div>
          <div class="tile__chev">›</div>
        </a>

        <div class="section-title">Mahsulotlar</div>
        <div class="card">
          ${itemsHtml || `<div class="muted">Mahsulot yo'q</div>`}
          <div class="divider"></div>
          <div class="order-item">
            <div class="muted">Mahsulotlar</div>
            <div>${fmtMoney(order.items_total || order.total_amount)}</div>
          </div>
          ${Number(order.cashback_used || 0) > 0 ? `
            <div class="order-item">
              <div class="muted">Keshbek qoplandi</div>
              <div style="color:var(--brand-success)">−${fmtMoney(order.cashback_used)}</div>
            </div>` : ""}
          <div class="divider"></div>
          <div class="order-item" style="font-weight:700">
            <div>To'lov (naqd)</div>
            <div>${fmtMoney(order.total_amount)}</div>
          </div>
          <div class="order-item">
            <div class="muted">To'lov:</div>
            <div class="muted">${escapeHtml(order.payment_method_label || "💵 Naqd")}</div>
          </div>
          ${Number(order.cashback_earned || 0) > 0 ? `
            <div class="order-item">
              <div class="muted">Keshbek olasiz</div>
              <div style="color:var(--brand-primary)">+${fmtMoney(order.cashback_earned)}</div>
            </div>` : ""}
          ${order.status === "DELIVERED" ? `
            <div class="order-item">
              <div class="muted">Kuryer olgan bo'sh idishlar</div>
              <div>${Number(order.bottles_returned || 0)} ta</div>
            </div>` : ""}
        </div>

        ${order.note ? `
          <div class="section-title">Izoh</div>
          <div class="card">
            <div style="white-space:pre-wrap">${escapeHtml(order.note)}</div>
          </div>
        ` : ""}

        <div class="section-title">To'lov</div>
        <div class="card">
          <div style="font-weight:600">Naqd kuryerga</div>
          <div class="muted" style="font-size:13px;margin-top:4px">
            Buyurtma yetib kelgach kuryerga to'laysiz: <b>${fmtMoney(order.total_amount)}</b>
          </div>
        </div>

        <div class="section-title">Aloqa</div>
        <div class="list-item">
          <span class="list-item__label">Telefon</span>
          <span class="list-item__value">${escapeHtml(order.contact_phone)}</span>
        </div>
      `;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Yuklab bo'lmadi";
      root.innerHTML = `
        <div class="empty">
          <div class="empty__icon">⚠️</div>
          <div class="empty__text">${escapeHtml(msg)}</div>
        </div>`;
    }
  })();

  return () => hideBackButton();
}
