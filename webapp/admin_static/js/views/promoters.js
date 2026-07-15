// Promouterlar — uyma-uy yuruvchi ishchilar va ularning promokodlari.
//
// Operatorlar/kuryerlardan FARQI: promouterda bot/login yo'q — admin o'zi
// yaratadi va kod beradi. Kod O'ZGARMAS (zakazlarga snapshot bo'lib muhrlangan),
// shuning uchun tahrirlash oynasida kod maydoni YO'Q.
//
// Arxivlash BOR (ishdan ketgan ishchi): qator DB'da qoladi, eski zakazlarning
// bog'lanishi va tarixiy KPI buzilmaydi — arxivlangan ishchi ham o'z natijasi
// bilan ro'yxatda ko'rinaveradi.

import { api } from "../api.js";
import { fmtCount, fmtMoney, fmtDate, escapeHtml, normalizePhone } from "../format.js";
import { toast } from "../toast.js";

export async function renderPromoters(root) {
  root.innerHTML = `
    <div class="toolbar" style="flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <h2 style="margin:0;font-size:16px">Promouterlar</h2>
      <div class="muted" id="pr-total-label" style="font-size:12px"></div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <label class="muted" style="font-size:12px;display:flex;align-items:center;gap:5px;cursor:pointer">
          <input type="checkbox" id="pr-archived" /> Arxivdagilar
        </label>
        <button class="btn btn--success btn--xs" id="pr-new">➕ Yangi promouter</button>
      </div>
    </div>

    <div class="muted" style="font-size:13px;margin-bottom:10px">
      Ishchilar mijozlarga borib botni tushuntiradi va manzil saqlashga o'rgatadi,
      so'ng mijozning telefonida o'z kodini kiritadi. Kod faqat
      <b>hali zakaz bermagan</b> va <b>kamida 1 ta manzili saqlangan</b> mijozda o'tadi.
    </div>

    <div id="pr-cfg" class="muted" style="font-size:12px;margin-bottom:12px"></div>

    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Ism</th>
            <th>Promokod</th>
            <th class="hide-narrow">Telefon</th>
            <th>Mijozlar</th>
            <th>Zakazlar</th>
            <th>Bonus</th>
            <th>Holat</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="pr-tbody"><tr><td colspan="8" class="loading">Yuklanmoqda…</td></tr></tbody>
      </table>
    </div>
  `;

  const tbody = root.querySelector("#pr-tbody");
  const totalLabel = root.querySelector("#pr-total-label");
  const archivedCb = root.querySelector("#pr-archived");
  const cfgEl = root.querySelector("#pr-cfg");

  let cache = [];
  let total = 0;

  async function loadConfig() {
    try {
      const c = await api.promoterSettings();
      cfgEl.innerHTML = c.promoter_program_enabled
        ? `Dastur <b style="color:var(--ok,#137333)">yoqilgan</b> · har yetkazilgan zakaz uchun
           <b>${escapeHtml(fmtMoney(c.promoter_bonus_per_order))}</b> ·
           bonus davri <b>${escapeHtml(String(c.promoter_bonus_window_days))} kun</b>
           <span class="muted">(«Sozlamalar» bo'limidan o'zgartiriladi)</span>`
        : `⚠️ Promokod dasturi <b>o'chirilgan</b> — yangi kodlar qabul qilinmaydi va
           bonus yozilmaydi. «Sozlamalar» bo'limidan yoqing.`;
    } catch (_) { cfgEl.textContent = ""; }
  }

  function renderRows() {
    if (!cache.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">
        <div class="empty__icon">🚶</div>
        <div class="empty__text">Hozircha promouter yo'q. «➕ Yangi promouter» bilan qo'shing.</div>
      </td></tr>`;
      totalLabel.textContent = "";
      return;
    }
    tbody.innerHTML = cache.map((p) => {
      const state = p.is_archived
        ? `<span class="pill pill--cancelled">Arxivda</span>`
        : `<span class="pill pill--${p.is_active ? "active" : "inactive"}">${p.is_active ? "Aktiv" : "To'xtatilgan"}</span>`;
      return `
      <tr${p.is_archived ? ' style="opacity:.6"' : ""}>
        <td><b>${escapeHtml(p.full_name)}</b></td>
        <td>
          <code style="font-size:14px;letter-spacing:1px;font-weight:600">${escapeHtml(p.promo_code)}</code>
          <button class="btn btn--xs btn--secondary" data-id="${p.id}" data-act="copy" title="Nusxalash">📋</button>
        </td>
        <td class="hide-narrow">${
          p.phone_number
            ? `<a href="tel:${escapeHtml(p.phone_number)}">${escapeHtml(p.phone_number)}</a>`
            : `<span class="muted">—</span>`
        }</td>
        <td>${fmtCount(p.customers)}</td>
        <td>${fmtCount(p.delivered_orders)}</td>
        <td><b>${escapeHtml(fmtMoney(p.bonus_total))}</b></td>
        <td>${state}</td>
        <td>
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn--xs btn--secondary" data-id="${p.id}" data-act="customers" title="Jalb qilgan mijozlari">👥</button>
            ${p.is_archived ? "" : `
              <button class="btn btn--xs btn--secondary" data-id="${p.id}" data-act="edit" title="Tahrirlash">✏️</button>
              <button class="btn btn--xs ${p.is_active ? "btn--danger" : "btn--success"}" data-id="${p.id}" data-act="toggle">
                ${p.is_active ? "⛔️ To'xtatish" : "✅ Yoqish"}
              </button>`}
            ${p.is_archived
              ? `<button class="btn btn--xs btn--success" data-id="${p.id}" data-act="restore">♻️ Qaytarish</button>`
              : `<button class="btn btn--xs btn--danger" data-id="${p.id}" data-act="archive" title="Ishdan ketdi">🗄️</button>`}
          </div>
        </td>
      </tr>`;
    }).join("");

    tbody.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", () => onAction(btn.dataset.act, Number(btn.dataset.id)));
    });
    totalLabel.textContent = `${fmtCount(cache.length)} / ${fmtCount(total)}`;
  }

  async function onAction(act, id) {
    const p = cache.find((x) => x.id === id);
    if (!p) return;
    try {
      if (act === "copy") {
        await navigator.clipboard.writeText(p.promo_code);
        return toast(`Kod nusxalandi: ${p.promo_code}`, "success");
      }
      if (act === "edit")      return openEditModal(p, reload);
      if (act === "customers") return openCustomersModal(p);
      if (act === "toggle") {
        await api.updatePromoter(id, { is_active: !p.is_active });
        toast("Saqlandi", "success");
        return reload();
      }
      if (act === "archive") {
        if (!confirm(
          `"${p.full_name}" arxivlansinmi?\n\n` +
          `Kodi endi o'tmaydi va yangi zakazlarga bonus yozilmaydi.\n` +
          `Eski zakazlari va hisoboti SAQLANADI — keyin qaytarish mumkin.`
        )) return;
        await api.archivePromoter(id);
        toast("Arxivlandi", "success");
        return reload();
      }
      if (act === "restore") {
        await api.restorePromoter(id);
        toast("Qaytarildi", "success");
        return reload();
      }
    } catch (e) { toast(e.message, "error"); }
  }

  async function reload() {
    try {
      const res = await api.promoters({ limit: 100, archived: archivedCb.checked });
      const page = Array.isArray(res) ? { items: res, total: res.length } : res;
      cache = page.items || [];
      total = Number(page.total || cache.length);
      renderRows();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
    }
  }

  archivedCb.addEventListener("change", reload);
  root.querySelector("#pr-new").addEventListener("click", () => openCreateModal(reload));

  loadConfig();
  reload();
}

// ---------------------- Modallar ----------------------

function modal(title, bodyHtml, footHtml) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">${title}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">${bodyHtml}</div>
      <div class="modal__foot">${footHtml}</div>
    </div>`;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  return { backdrop, close };
}

function openCreateModal(onSaved) {
  const { backdrop, close } = modal(
    "Yangi promouter",
    `
      <label class="label">Ism familiya *</label>
      <input class="input" id="prm-name" placeholder="Masalan: Ali Valiyev" />

      <label class="label" style="margin-top:12px">Telefon raqami</label>
      <input class="input" id="prm-phone" type="tel" inputmode="tel" placeholder="+998901234567" />

      <label class="label" style="margin-top:12px">Promokod</label>
      <input class="input" id="prm-code" placeholder="Bo'sh qoldiring — avtomatik yaratiladi"
             style="text-transform:uppercase;letter-spacing:1px" maxlength="16" />
      <div class="muted" style="font-size:12px;margin-top:4px">
        4–16 ta belgi: lotin harflari va raqamlar. <b>Kod keyin o'zgartirilmaydi</b> —
        u zakazlarga muhrlanadi. Bo'sh qoldirsangiz, chalkashmaydigan
        (0/O, 1/I siz) kod avtomatik yaratiladi.
      </div>
    `,
    `<button class="btn btn--secondary" data-close>Bekor</button>
     <button class="btn btn--success" id="prm-save">Yaratish</button>`
  );

  backdrop.querySelector("#prm-save").addEventListener("click", async () => {
    const name = backdrop.querySelector("#prm-name").value.trim();
    if (name.length < 2) return toast("Ismni kiriting", "error");

    const rawPhone = backdrop.querySelector("#prm-phone").value.trim();
    let phone = null;
    if (rawPhone) {
      phone = normalizePhone(rawPhone);
      if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    }
    const code = backdrop.querySelector("#prm-code").value.trim().toUpperCase();

    try {
      const p = await api.createPromoter({
        full_name: name,
        phone_number: phone,
        promo_code: code || null,
      });
      toast(`Yaratildi. Kod: ${p.promo_code}`, "success");
      close();
      onSaved && onSaved();
    } catch (e) { toast(e.message, "error"); }
  });
}

function openEditModal(p, onSaved) {
  const { backdrop, close } = modal(
    `Promouter: ${escapeHtml(p.full_name)}`,
    `
      <label class="label">Ism familiya</label>
      <input class="input" id="pre-name" value="${escapeHtml(p.full_name)}" />

      <label class="label" style="margin-top:12px">Telefon raqami</label>
      <input class="input" id="pre-phone" type="tel" inputmode="tel"
             placeholder="+998901234567" value="${escapeHtml(p.phone_number || "")}" />

      <div style="margin-top:14px;padding:10px;background:var(--bg-soft,#f5f5f5);border-radius:8px">
        <div class="muted" style="font-size:12px">Promokod (o'zgarmas)</div>
        <code style="font-size:16px;letter-spacing:1px;font-weight:600">${escapeHtml(p.promo_code)}</code>
        <div class="muted" style="font-size:12px;margin-top:6px">
          Kod zakazlarga muhrlangan va tarqatilgan — shuning uchun o'zgartirilmaydi.
          Kodni almashtirish kerak bo'lsa: bu ishchini to'xtating va yangisini yarating.
        </div>
      </div>
    `,
    `<button class="btn btn--secondary" data-close>Bekor</button>
     <button class="btn btn--success" id="pre-save">Saqlash</button>`
  );

  backdrop.querySelector("#pre-save").addEventListener("click", async () => {
    const name = backdrop.querySelector("#pre-name").value.trim();
    if (name.length < 2) return toast("Ismni kiriting", "error");

    const raw = backdrop.querySelector("#pre-phone").value.trim();
    let phone = "";
    if (raw) {
      phone = normalizePhone(raw);
      if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    }
    const body = {};
    if (name !== p.full_name) body.full_name = name;
    if ((phone || null) !== (p.phone_number || null)) body.phone_number = phone;
    if (!Object.keys(body).length) return close();

    try {
      await api.updatePromoter(p.id, body);
      toast("Saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) { toast(e.message, "error"); }
  });
}

function openCustomersModal(p) {
  const { backdrop } = modal(
    `${escapeHtml(p.full_name)} jalb qilgan mijozlar`,
    `<div id="prc-body"><div class="loading">Yuklanmoqda…</div></div>`,
    `<button class="btn btn--secondary" data-close>Yopish</button>`
  );
  const body = backdrop.querySelector("#prc-body");

  (async () => {
    try {
      const res = await api.promoterCustomers(p.id, { limit: 100 });
      const items = res.items || [];
      if (!items.length) {
        body.innerHTML = `<div class="empty"><div class="empty__icon">👥</div>
          <div class="empty__text">Hali hech kim bu kodni kiritmagan.</div></div>`;
        return;
      }
      const now = Date.now();
      body.innerHTML = `
        <div class="muted" style="font-size:12px;margin-bottom:8px">Jami: ${fmtCount(res.total)}</div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Mijoz</th><th>Telefon</th><th>Kod kiritilgan</th><th>Bonus davri</th></tr></thead>
            <tbody>${items.map((c) => {
              const ended = new Date(c.bonus_window_ends_at).getTime() < now;
              return `<tr>
                <td>${escapeHtml(c.full_name)}</td>
                <td>${c.phone_number ? `<a href="tel:${escapeHtml(c.phone_number)}">${escapeHtml(c.phone_number)}</a>` : `<span class="muted">—</span>`}</td>
                <td>${escapeHtml(fmtDate(c.redeemed_at))}</td>
                <td>${ended
                  ? `<span class="muted">tugagan · ${escapeHtml(fmtDate(c.bonus_window_ends_at))}</span>`
                  : `${escapeHtml(fmtDate(c.bonus_window_ends_at))} gacha`}</td>
              </tr>`;
            }).join("")}</tbody>
          </table>
        </div>`;
    } catch (e) {
      body.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div>
        <div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    }
  })();
}
