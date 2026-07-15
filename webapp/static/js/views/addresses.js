// Manzillar — saqlangan manzillarni boshqarish (CRUD).

import { api, ApiError } from "../api.js";
import { escapeHtml, iconFor } from "../format.js";
import { hapticImpact, hideMainButton, showBackButton, hideBackButton, showConfirm } from "../telegram.js";
import { back, go } from "../router.js";
import { openMapPicker } from "../mappicker.js";
import { toast } from "../toast.js";

export function renderAddresses(root) {
  document.getElementById("screen-title").textContent = "Manzillarim";
  showBackButton(() => back());
  hideMainButton();

  root.innerHTML = `<div class="muted center" style="padding:20px">Yuklanmoqda…</div>`;

  let items = [];

  const reload = async () => {
    try {
      items = await api.addresses();
      render();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Yuklab bo'lmadi";
      root.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(msg)}</div></div>`;
    }
  };

  const render = () => {
    if (!items.length) {
      root.innerHTML = `
        <div class="empty">
          <div class="empty__icon">📍</div>
          <div class="empty__text">Sizda hali saqlangan manzil yo'q. "Uy", "Ish" kabi manzillarni qo'shib qo'ying — keyingi safar bir bosishda tanlaysiz.</div>
        </div>
        <button class="btn" id="addBtn" type="button" style="margin-top:14px">➕ Yangi manzil qo'shish</button>
      `;
      root.querySelector("#addBtn").addEventListener("click", () => openEditor(null));
      return;
    }
    const rows = items.map((a) => `
      <div class="address-card ${a.is_default ? "address-card--active" : ""}" data-id="${a.id}">
        <div class="address-card__icon">${iconFor(a.label)}</div>
        <div class="address-card__body">
          <div class="address-card__label">
            ${escapeHtml(a.label)}${a.is_default ? `<span class="address-card__badge">Default</span>` : ""}
          </div>
          ${a.details ? `<div class="address-card__sub">${escapeHtml(a.details)}</div>` : ""}
          <div class="address-card__sub">${a.latitude.toFixed(5)}, ${a.longitude.toFixed(5)}</div>
        </div>
        <div class="address-card__actions">
          <button class="js-default" type="button" ${a.is_default ? "disabled" : ""} title="Default qilish">⭐</button>
          <button class="js-edit" type="button" title="Tahrirlash">✏️</button>
          <button class="js-delete" type="button" title="O'chirish">🗑</button>
        </div>
      </div>
    `).join("");
    root.innerHTML = `
      ${rows}
      <button class="btn" id="addBtn" type="button" style="margin-top:14px">➕ Yangi manzil qo'shish</button>
    `;

    root.querySelectorAll(".address-card").forEach((card) => {
      const id = Number(card.getAttribute("data-id"));
      card.querySelector(".js-default").addEventListener("click", async () => {
        try {
          await api.setDefaultAddress(id);
          hapticImpact("light");
          toast("Default manzil yangilandi");
          await reload();
        } catch (e) {
          toast(e.message || "Xatolik", { error: true });
        }
      });
      card.querySelector(".js-edit").addEventListener("click", () => {
        const item = items.find((x) => x.id === id);
        openEditor(item);
      });
      card.querySelector(".js-delete").addEventListener("click", async () => {
        const ok = await showConfirm("Bu manzilni o'chirishni tasdiqlaysizmi?");
        if (!ok) return;
        try {
          await api.deleteAddress(id);
          toast("O'chirildi");
          await reload();
        } catch (e) {
          toast(e.message || "Xatolik", { error: true });
        }
      });
    });
    root.querySelector("#addBtn").addEventListener("click", () => openEditor(null));
  };

  function openEditor(existing) {
    const isEdit = !!existing;
    const initial = existing
      ? { latitude: existing.latitude, longitude: existing.longitude }
      : null;
    document.getElementById("screen-title").textContent = isEdit ? "Manzilni tahrirlash" : "Yangi manzil";
    root.innerHTML = `
      <div class="form">
        <label class="label" for="a-label">Yorlig'i (masalan, "Uy", "Ish")</label>
        <input class="input" id="a-label" type="text" maxlength="40" />

        <label class="label">Xaritadagi nuqta</label>
        <div class="card" style="padding:12px">
          <div id="a-coord" class="muted" style="font-family:ui-monospace,monospace;font-size:12px">Belgilanmagan</div>
          <button class="btn btn--secondary" id="pickBtn" type="button" style="margin-top:8px">🗺 Xaritadan tanlash</button>
        </div>

        <label class="label" for="a-details">Tafsilot (podyezd/kvartira)</label>
        <textarea class="input" id="a-details" maxlength="200" placeholder="Masalan: 3-podyezd, 17-kvartira, eshik kodi 123"></textarea>

        <label class="checkbox" style="margin-top:10px;display:flex;gap:8px;align-items:center;font-size:14px">
          <input type="checkbox" id="a-default" />
          <span>Default sifatida belgilash</span>
        </label>
      </div>
      <div class="spacer"></div>
      <div style="display:flex;gap:10px">
        <button class="btn btn--ghost" id="cancelBtn" type="button">Bekor</button>
        <button class="btn" id="saveBtn" type="button" style="flex:1">${isEdit ? "Saqlash" : "Qo'shish"}</button>
      </div>
    `;
    const labelEl = root.querySelector("#a-label");
    const detailsEl = root.querySelector("#a-details");
    const defaultEl = root.querySelector("#a-default");
    const coordEl = root.querySelector("#a-coord");
    let loc = initial;

    if (existing) {
      labelEl.value = existing.label;
      detailsEl.value = existing.details || "";
      defaultEl.checked = !!existing.is_default;
      coordEl.textContent = `Lat: ${existing.latitude.toFixed(5)}, Lon: ${existing.longitude.toFixed(5)}`;
    }

    root.querySelector("#pickBtn").addEventListener("click", async () => {
      const result = await openMapPicker({
        initial: loc || undefined,
        title: existing ? "Manzilni yangilash" : "Manzilni tanlang",
      });
      if (!result) return;
      loc = result;
      coordEl.textContent = `Lat: ${result.latitude.toFixed(5)}, Lon: ${result.longitude.toFixed(5)}`;
    });

    root.querySelector("#cancelBtn").addEventListener("click", reload);

    root.querySelector("#saveBtn").addEventListener("click", async () => {
      const label = labelEl.value.trim();
      if (!label) return toast("Manzilga nom bering.", { error: true });
      if (!loc) return toast("Avval xaritadan joy tanlang.", { error: true });
      const body = {
        label,
        latitude: loc.latitude,
        longitude: loc.longitude,
        details: detailsEl.value.trim(),
        is_default: defaultEl.checked,
      };
      try {
        if (existing) {
          await api.updateAddress(existing.id, body);
        } else {
          await api.createAddress(body);
        }
        hapticImpact("light");
        toast("Saqlandi");
        await reload();
      } catch (e) {
        toast(e.message || "Xatolik", { error: true });
      }
    });
  }

  reload();

  return () => { hideBackButton(); };
}
