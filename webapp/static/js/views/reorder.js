// Oxirgi buyurtmani takrorlash — bir bosishda yangi buyurtma.
//
// Mijozlar odatda bir xil narsani buyurtma qiladi (suv). Shu sababli oxirgi
// buyurtmani to'liq ko'rsatamiz (mahsulotlar, manzil, telefon, izoh) va bitta
// "Buyurtma berish" tugmasi bilan darhol takror yaratamiz.
//
// Muhim:
//   * Narxlar JORIY narxlardan olinadi (eski snapshot emas) — narx o'zgargan bo'lsa yangisini
//   * Endi mavjud bo'lmagan mahsulotlar avtomatik chiqarib tashlanadi (ogohlantirish bilan)
//   * Yetkazib berish manzili / telefon / izoh — oxirgi buyurtmadan ko'chiriladi
//   * Idempotency key — shu ekran uchun barqaror (retry'da duplikat order yaratmaydi)

import { api, ApiError } from "../api.js";
import { cart } from "../state.js";
import { fmtMoney, escapeHtml, iconFor } from "../format.js";
import {
  hapticNotification,
  hideBackButton,
  hideMainButton,
  showBackButton,
} from "../telegram.js";
import { back, go } from "../router.js";
import { toast } from "../toast.js";
import { showCTA, hideCTA, setCTALoading } from "../cta.js";

export function renderReorder(root, { orderId }) {
  document.getElementById("screen-title").textContent = "Takroriy buyurtma";
  showBackButton(() => back());
  hideMainButton();

  // Shu ekran uchun barqaror idempotency key (retry'da bir xil — duplikat yo'q).
  const idemKey = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));

  root.innerHTML = `<div class="muted center" style="padding:20px">Yuklanmoqda…</div>`;

  let busy = false;

  (async () => {
    // Oxirgi buyurtma detali (lat/lon shu yerda) + joriy mahsulotlar (narx/mavjudlik).
    let order, products;
    try {
      [order, products] = await Promise.all([
        api.order(orderId),
        api.products().catch(() => []),
      ]);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Buyurtmani yuklab bo'lmadi";
      root.innerHTML = `
        <div class="empty">
          <div class="empty__icon">⚠️</div>
          <div class="empty__text">${escapeHtml(msg)}</div>
        </div>`;
      return;
    }

    const productMap = new Map((products || []).map((p) => [p.id, p]));

    // Har bir item uchun: mavjudmi + joriy narx + minimal buyurtma clamp.
    const resolved = (order.items || []).map((it) => {
      const p = productMap.get(it.food_id);
      const available = !!p;
      const price = available ? Number(p.price) : Number(it.unit_price);
      // Per-mahsulot minimal: eski buyurtma miqdori joriy min'dan past bo'lsa,
      // minimalga ko'taramiz (aks holda server item_below_minimum bilan rad etadi).
      const minQ = available ? Math.max(1, Number(p.min_quantity || 1)) : 1;
      // Takrorlashda ASL buyurtma qilingan miqdorni qaytaramiz (kuryer
      // yetkazishда o'zgartirgan bo'lsa ham). `ordered_quantity` — asl niyat;
      // eski buyurtmalar (maydonsiz) uchun `quantity` ga fallback.
      const orderedQ = Number(it.ordered_quantity ?? it.quantity);
      const quantity = available ? Math.max(orderedQ, minQ) : orderedQ;
      return {
        food_id: it.food_id,
        name: it.food_name,
        quantity,
        adjusted: available && quantity !== orderedQ,
        available,
        price,
        line_total: available ? price * quantity : 0,
      };
    });

    const availableItems = resolved.filter((r) => r.available);
    const removedItems = resolved.filter((r) => !r.available);
    const adjustedItems = availableItems.filter((r) => r.adjusted);
    const total = availableItems.reduce((s, r) => s + r.line_total, 0);
    const canOrder = availableItems.length > 0;

    // ----- Render
    const itemsHtml = resolved.map((r) => {
      if (!r.available) {
        return `
          <div class="order-item" style="opacity:0.5">
            <div class="order-item__name"><s>${escapeHtml(r.name)} × ${r.quantity}</s>
              <span class="muted" style="font-size:12px"> · endi mavjud emas</span>
            </div>
            <div class="order-item__total muted">—</div>
          </div>`;
      }
      return `
        <div class="order-item">
          <div class="order-item__name">${escapeHtml(r.name)} × ${r.quantity}</div>
          <div class="order-item__total">${fmtMoney(r.line_total)}</div>
        </div>`;
    }).join("");

    const addrLabel = order.address_label || "Tanlangan manzil";
    const addrIcon = iconFor(order.address_label);

    root.innerHTML = `
      <div class="section-title">Mahsulotlar</div>
      <div class="card">
        ${itemsHtml || `<div class="muted">Mahsulot yo'q</div>`}
        <div class="divider"></div>
        <div class="order-item" style="font-weight:700">
          <div>Jami</div>
          <div style="color:var(--brand-deep)">${fmtMoney(total)}</div>
        </div>
      </div>

      ${removedItems.length ? `
        <div class="card" style="margin-top:10px;border-color:var(--brand-warning)">
          <div style="font-size:13px;color:var(--brand-warning-strong)">
            ⚠️ ${removedItems.length} ta mahsulot endi mavjud emas — ular buyurtmaga kiritilmaydi.
          </div>
        </div>` : ""}

      ${adjustedItems.length ? `
        <div class="card" style="margin-top:10px;border-color:var(--brand-warning)">
          <div style="font-size:13px;color:var(--brand-warning-strong)">
            ⚠️ ${adjustedItems.length} ta mahsulot miqdori minimal buyurtma talabiga moslab oshirildi.
          </div>
        </div>` : ""}

      <div class="section-title">Yetkazib berish manzili</div>
      <div class="card">
        <div class="addr-summary" style="cursor:default">
          <div class="addr-summary__icon">${addrIcon}</div>
          <div class="addr-summary__body">
            <div class="addr-summary__label">${escapeHtml(addrLabel)}</div>
            <div class="addr-summary__sub" style="font-family:ui-monospace,monospace">
              ${Number(order.latitude).toFixed(5)}, ${Number(order.longitude).toFixed(5)}
            </div>
            ${order.address_details ? `<div class="addr-summary__sub">${escapeHtml(order.address_details)}</div>` : ""}
          </div>
        </div>
      </div>

      <div class="section-title">Aloqa</div>
      <div class="list-item">
        <span class="list-item__label">Telefon</span>
        <span class="list-item__value">${escapeHtml(order.contact_phone)}</span>
      </div>

      ${order.note ? `
        <div class="section-title">Izoh</div>
        <div class="card"><div style="white-space:pre-wrap">${escapeHtml(order.note)}</div></div>
      ` : ""}

      <div class="card" style="margin-top:12px;background:var(--brand-tint);border:0">
        <div class="muted" style="font-size:13px">
          💡 Manzil yoki mahsulotni o'zgartirmoqchi bo'lsangiz, oddiy buyurtma berishdan foydalaning.
          Bu yerda oxirgi buyurtmangiz aynan takrorlanadi.
        </div>
      </div>
    `;

    // ----- CTA
    const submit = async () => {
      if (busy) return;
      if (!canOrder) {
        toast("Bu buyurtmadagi mahsulotlar endi mavjud emas.", { error: true });
        return;
      }
      // Telefon/lokatsiya sanity (eski buyurtmada bor edi, lekin himoya)
      if (order.latitude == null || order.longitude == null) {
        toast("Manzil ma'lumoti to'liq emas. Oddiy buyurtma bering.", { error: true });
        return;
      }

      busy = true;
      setCTALoading(true);
      try {
        const newOrder = await api.createOrder({
          items: availableItems.map((r) => ({ food_id: r.food_id, quantity: r.quantity })),
          latitude: Number(order.latitude),
          longitude: Number(order.longitude),
          contact_phone: order.contact_phone,
          note: order.note || "Takroriy buyurtma",
          idempotency_key: idemKey,
          address_label: order.address_label || "",
          address_details: order.address_details || "",
          // cashback_to_use: 0 — tezkor takrorda keshbek ishlatilmaydi (to'liq checkout'da mumkin)
        });
        hapticNotification("success");
        // Server cart'ni tozaladi — mahalliy state'ni sinxronlaymiz.
        cart.clear();
        go("success", { order: newOrder });
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "Xatolik";
        hapticNotification("error");
        toast(msg, { error: true });
      } finally {
        busy = false;
        setCTALoading(false);
      }
    };

    if (canOrder) {
      showCTA(`Buyurtma berish · ${fmtMoney(total)}`, submit);
    } else {
      // Hech qaysi mahsulot mavjud emas — buyurtma berib bo'lmaydi.
      showCTA("Mahsulot tanlashga o'tish", () => go("products"), { variant: "secondary" });
    }
  })();

  return () => {
    hideBackButton();
    hideCTA();
  };
}
