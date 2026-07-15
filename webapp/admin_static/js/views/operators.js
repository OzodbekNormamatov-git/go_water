// Operatorlar — admin botga /start bosganlar (kuryer patterni: aktiv/noaktiv).
// Operator ro'yxatdan o'tgach admin shu yerdan aktivlashtiradi; telefonini
// tahrirlash ham shu yerda. Arxivlash YO'Q — ishdan ketgan operator
// shunchaki noaktiv qilinadi (egasi talabi: ro'yxatdan hech kim yo'qolmasin).

import { api } from "../api.js";
import { fmtCount, escapeHtml, normalizePhone } from "../format.js";
import { toast } from "../toast.js";

export async function renderOperators(root) {
  root.innerHTML = `
    <div class="toolbar" style="flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <h2 style="margin:0;font-size:16px">Operatorlar</h2>
      <div class="muted" id="op-total-label" style="font-size:12px"></div>
    </div>
    <div class="muted" style="font-size:13px;margin-bottom:12px">
      Operatorlar admin botga /start bosib ro'yxatdan o'tadi — bu yerda aktivlashtirasiz.
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Ism</th>
            <th>Telefon</th>
            <th class="hide-narrow">Telegram ID</th>
            <th class="hide-narrow">Botga start bosgan</th>
            <th>Holat</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="op-tbody"><tr><td colspan="6" class="loading">Yuklanmoqda…</td></tr></tbody>
      </table>
    </div>
  `;

  const tbody = root.querySelector("#op-tbody");
  const totalLabel = root.querySelector("#op-total-label");

  let cache = [];
  let total = 0;

  function renderPhoneCell(o) {
    if (o.phone_number) {
      return `<a href="tel:${escapeHtml(o.phone_number)}">${escapeHtml(o.phone_number)}</a>`;
    }
    return `<span class="muted">— kiritilmagan</span>`;
  }

  function renderRows() {
    if (!cache.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">📞</div><div class="empty__text">Hozircha operator yo'q. Operator admin botga /start bossin.</div></td></tr>`;
      totalLabel.textContent = "";
      return;
    }
    tbody.innerHTML = cache.map((o) => `
      <tr>
        <td>
          <b>${escapeHtml(o.full_name)}</b>
          ${o.username ? `<span class="muted" style="font-size:12px"> @${escapeHtml(o.username)}</span>` : ""}
        </td>
        <td>${renderPhoneCell(o)}</td>
        <td class="hide-narrow"><code>${escapeHtml(String(o.telegram_id ?? "—"))}</code></td>
        <td class="hide-narrow">${o.has_started_bot ? "✅" : '<span class="muted">❌</span>'}</td>
        <td><span class="pill pill--${o.is_active ? 'active' : 'inactive'}">${o.is_active ? "Aktiv" : "Noaktiv"}</span></td>
        <td>
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn--xs btn--secondary" data-id="${o.id}" data-act="edit" title="Tahrirlash">✏️</button>
            <button class="btn btn--xs ${o.is_active ? 'btn--danger' : 'btn--success'}" data-id="${o.id}" data-act="toggle">
              ${o.is_active ? "⛔️ To'xtatish" : "✅ Aktivlashtirish"}
            </button>
          </div>
        </td>
      </tr>
    `).join("");
    tbody.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.id);
        const o = cache.find((x) => x.id === id);
        if (!o) return;
        if (btn.dataset.act === "edit") {
          openEditModal(o, reload);
          return;
        }
        // toggle aktiv/noaktiv
        try {
          await api.updateOperator(id, { is_active: !o.is_active });
          toast("Saqlandi", "success");
          reload();
        } catch (e) { toast(e.message, "error"); }
      });
    });
    totalLabel.textContent = `${fmtCount(cache.length)} / ${fmtCount(total)}`;
  }

  async function reload() {
    try {
      const res = await api.operators({ limit: 100 });
      const page = Array.isArray(res) ? { items: res, total: res.length } : res;
      cache = page.items || [];
      total = Number(page.total || cache.length);
      renderRows();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
    }
  }

  reload();
}

// ---------------------- Edit modal ----------------------

function openEditModal(operator, onSaved) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">Operator: ${escapeHtml(operator.full_name)}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        <label class="label">Telefon raqami</label>
        <input class="input" id="opm-phone" type="tel" inputmode="tel"
               placeholder="+998901234567"
               value="${escapeHtml(operator.phone_number || "")}" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Format: +998901234567. Bo'sh qoldirib tozalash mumkin.
        </div>

        <div class="muted" style="font-size:12px;margin-top:14px">
          Ishdan ketgan operatorni ro'yxatdagi «⛔️ To'xtatish» bilan noaktiv
          qiling — u panelga kira olmaydi, lekin ro'yxatda ko'rinib turadi.
        </div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="opm-save">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  backdrop.querySelector("#opm-save").addEventListener("click", async () => {
    const raw = backdrop.querySelector("#opm-phone").value.trim();
    let phone = "";  // bo'sh string — tozalash
    if (raw) {
      phone = normalizePhone(raw);
      if (!phone) return toast("Telefon raqam noto'g'ri. Masalan: 901234567", "error");
    }
    // PATCH body — faqat o'zgargan maydonlar (mavjudga teng bo'lsa yubormaymiz).
    if ((phone || null) === (operator.phone_number || null)) {
      close();
      return;
    }
    try {
      await api.updateOperator(operator.id, { phone_number: phone });
      toast("Saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) { toast(e.message, "error"); }
  });
}
