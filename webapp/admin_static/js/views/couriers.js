import { api } from "../api.js";
import { fmtCount, fmtMoney, escapeHtml, normalizePhone } from "../format.js";
import { toast } from "../toast.js";

const PAGE_SIZE = 50;

export async function renderCouriers(root) {
  root.innerHTML = `
    <div id="cashSummary"></div>
    <div class="toolbar" style="flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <h2 style="margin:0;font-size:16px">Kuryerlar</h2>
      <div class="muted" id="totalLabel" style="font-size:12px"></div>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th class="hide-narrow">#</th>
            <th>Ism</th>
            <th class="hide-narrow">Username</th>
            <th>Telefon</th>
            <th style="text-align:right">Naqd pul</th>
            <th class="hide-narrow">Bot</th>
            <th class="hide-narrow">Bugun</th>
            <th class="hide-narrow">Oyda</th>
            <th class="hide-narrow">Jami</th>
            <th>Holat</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="tbody"><tr><td colspan="11" class="loading">Yuklanmoqda…</td></tr></tbody>
      </table>
    </div>
    <div id="loadMoreWrap" style="margin-top:12px;text-align:center"></div>
  `;

  const tbody = document.getElementById("tbody");
  const totalLabel = document.getElementById("totalLabel");
  const loadMoreWrap = document.getElementById("loadMoreWrap");
  const cashSummary = document.getElementById("cashSummary");

  // Kuryerlarda jami naqd — yuqorida KPI sifatida
  async function loadCashSummary() {
    try {
      const s = await api.couriersCashSummary();
      cashSummary.innerHTML = `
        <div class="kpi-grid" style="margin-bottom:14px">
          <div class="kpi">
            <div class="kpi__icon">💵</div>
            <div class="kpi__label">Kuryerlarda jami naqd</div>
            <div class="kpi__value">${fmtMoney(s.total_cash)}</div>
            <div class="kpi__sub">${fmtCount(s.couriers_with_cash)} kuryerda · hali topshirilmagan</div>
          </div>
        </div>
      `;
    } catch (_) {
      cashSummary.innerHTML = "";
    }
  }
  loadCashSummary();

  let cache = [];
  let offset = 0;
  let total = 0;
  let loading = false;

  function renderPhoneCell(c) {
    if (c.phone_number) {
      // `tel:` link mobile'da darhol qo'ng'iroq oynasini ochadi (admin
      // operator uchun foydali: kuryerga zudlik bilan tekshirish).
      return `<a href="tel:${escapeHtml(c.phone_number)}">${escapeHtml(c.phone_number)}</a>`;
    }
    return `<span class="muted">— kiritilmagan</span>`;
  }

  function renderCashCell(c) {
    const cash = Number(c.cash_balance || 0);
    if (cash > 0) {
      return `<b style="color:var(--brand-deep)">${fmtMoney(cash)}</b>`;
    }
    return `<span class="muted">—</span>`;
  }

  function renderRows() {
    if (!cache.length) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty"><div class="empty__icon">🚗</div><div class="empty__text">Hozircha kuryer yo'q.</div></td></tr>`;
      loadMoreWrap.innerHTML = "";
      totalLabel.textContent = "";
      return;
    }
    tbody.innerHTML = cache.map((c) => `
      <tr>
        <td class="hide-narrow">${c.id}</td>
        <td><b>${escapeHtml(c.full_name)}</b></td>
        <td class="hide-narrow">${c.username ? '@' + escapeHtml(c.username) : '<span class="muted">—</span>'}</td>
        <td>${renderPhoneCell(c)}</td>
        <td style="text-align:right">${renderCashCell(c)}</td>
        <td class="hide-narrow">${c.has_started_bot ? "✅" : '<span class="muted">❌</span>'}</td>
        <td class="hide-narrow" style="text-align:right">${fmtCount(c.delivered_today)}</td>
        <td class="hide-narrow" style="text-align:right">${fmtCount(c.delivered_month)}</td>
        <td class="hide-narrow" style="text-align:right"><b>${fmtCount(c.delivered_total)}</b></td>
        <td><span class="pill pill--${c.is_active ? 'active' : 'inactive'}">${c.is_active ? "Aktiv" : "Noaktiv"}</span></td>
        <td>
          <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
            <button class="btn btn--xs btn--secondary" data-id="${c.id}" data-act="edit" title="Tahrirlash">✏️</button>
            <button class="btn btn--xs ${c.is_active ? 'btn--danger' : 'btn--success'}" data-id="${c.id}" data-act="${c.is_active ? 'off' : 'on'}">
              ${c.is_active ? "Noaktiv" : "Aktiv"}
            </button>
          </div>
        </td>
      </tr>
    `).join("");
    tbody.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.id);
        const act = btn.dataset.act;
        if (act === "edit") {
          const c = cache.find((x) => x.id === id);
          if (c) openEditModal(c, reload);
          return;
        }
        // on/off toggle
        const active = act === "on";
        try {
          await api.updateCourier(id, { is_active: active });
          toast(active ? "Aktivlashtirildi" : "Noaktiv qilindi", "success");
          reload();
        } catch (e) { toast(e.message, "error"); }
      });
    });
    totalLabel.textContent = `${fmtCount(cache.length)} / ${fmtCount(total)}`;
    if (cache.length < total) {
      const remaining = total - cache.length;
      loadMoreWrap.innerHTML = `
        <button class="btn btn--secondary" id="loadMoreBtn" type="button">
          Yana yuklash (${fmtCount(remaining)} qoldi)
        </button>
      `;
      loadMoreWrap.querySelector("#loadMoreBtn").addEventListener("click", () => loadPage(false));
    } else {
      loadMoreWrap.innerHTML = "";
    }
  }

  async function loadPage(reset) {
    if (loading) return;
    loading = true;
    try {
      const res = await api.couriers({ limit: PAGE_SIZE, offset: reset ? 0 : offset });
      const page = Array.isArray(res) ? { items: res, total: res.length } : res;
      if (reset) {
        cache = page.items || [];
        offset = (page.items || []).length;
      } else {
        cache = cache.concat(page.items || []);
        offset += (page.items || []).length;
      }
      total = Number(page.total || 0);
      renderRows();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></td></tr>`;
    } finally {
      loading = false;
    }
  }

  function reload() {
    loadCashSummary();
    cache = [];
    offset = 0;
    loadPage(true);
  }

  reload();
}

// ---------------------- Edit modal ----------------------

function openEditModal(courier, onSaved) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <div class="modal__head">
        <h3 class="modal__title">Kuryer: ${escapeHtml(courier.full_name)}</h3>
        <button class="modal__close" data-close>×</button>
      </div>
      <div class="modal__body">
        <label class="label">Telefon raqami</label>
        <input class="input" id="cu-phone" type="tel" inputmode="tel"
               placeholder="+998901234567"
               value="${escapeHtml(courier.phone_number || "")}" />
        <div class="muted" style="font-size:12px;margin-top:4px">
          Format: +998901234567. Bo'sh qoldirib tozalash mumkin. Kuryer botda
          o'zining contact'ini ulashganda bu raqam avtomatik to'ladi.
        </div>

        <label class="label" style="margin-top:14px">Holat</label>
        <div class="settings-row" style="border-bottom:0;padding:6px 0">
          <div class="settings-row__label">
            <div class="settings-row__title">${courier.is_active ? "Aktiv" : "Noaktiv"}</div>
            <div class="settings-row__hint">Aktiv kuryer kuryerlar guruhidan zakaz olishi mumkin.</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="cu-active" ${courier.is_active ? "checked" : ""} />
            <span class="switch__slider"></span>
          </label>
        </div>

        <label class="label" style="margin-top:14px">Naqd pul (qo'lida)</label>
        <div class="card" style="background:var(--surface-2);padding:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="muted">Hozir kuryerda</span>
            <b style="font-size:18px;color:var(--brand-deep)" id="cu-cash">${fmtMoney(courier.cash_balance || 0)}</b>
          </div>
          ${Number(courier.cash_balance || 0) > 0 ? `
            <div style="margin-top:10px">
              <label class="label" style="margin-top:0">Qabul qilinadigan summa</label>
              <div style="display:flex;gap:8px;align-items:center">
                <input class="input" id="cu-settle-amount" type="number" min="0" step="1000"
                       value="${Number(courier.cash_balance || 0)}" style="flex:1" />
                <span class="muted">so'm</span>
              </div>
              <div class="muted" style="font-size:12px;margin-top:4px">
                Kuryer pulni topshirganda bosing. To'liq summa yoki qisman.
              </div>
              <button class="btn btn--success" id="cu-settle" type="button" style="width:100%;margin-top:8px">
                ✅ Pulni qabul qildim
              </button>
            </div>
          ` : `
            <div class="muted" style="font-size:12px;margin-top:6px">Kuryerda hozir naqd pul yo'q.</div>
          `}
        </div>
      </div>
      <div class="modal__foot">
        <button class="btn btn--secondary" data-close>Bekor</button>
        <button class="btn btn--success" id="cu-save">Saqlash</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  // ----- Naqd pulni qabul qilish (settle)
  const settleBtn = document.getElementById("cu-settle");
  if (settleBtn) {
    settleBtn.addEventListener("click", async () => {
      const balance = Number(courier.cash_balance || 0);
      const amt = Math.floor(Number(document.getElementById("cu-settle-amount").value) || 0);
      if (amt <= 0) return toast("Summani kiriting", "error");
      if (amt > balance) return toast(`Kuryerda atigi ${fmtMoney(balance)} bor`, "error");
      const full = amt >= balance;
      if (!confirm(`${courier.full_name}dan ${fmtMoney(amt)} naqd qabul qilindimi?`)) return;
      settleBtn.disabled = true;
      settleBtn.textContent = "Saqlanmoqda…";
      try {
        // Full settle → amount yubormaymiz (server hammasini oladi); qisman → amount.
        await api.settleCourierCash(courier.id, full ? null : amt);
        toast(`${fmtMoney(amt)} qabul qilindi`, "success");
        close();
        onSaved && onSaved();
      } catch (e) {
        toast(e.message, "error");
        settleBtn.disabled = false;
        settleBtn.textContent = "✅ Pulni qabul qildim";
      }
    });
  }

  document.getElementById("cu-save").addEventListener("click", async () => {
    let phoneRaw = document.getElementById("cu-phone").value.trim();
    if (phoneRaw) {
      const normalized = normalizePhone(phoneRaw);
      if (!normalized) return toast("Telefon raqam noto'g'ri.", "error");
      phoneRaw = normalized;
    }
    const active = document.getElementById("cu-active").checked;
    // PATCH body — faqat o'zgargan maydonlar (mavjudga teng bo'lsa yubormaymiz).
    const body = {};
    const phoneEq = (phoneRaw || null) === (courier.phone_number || null);
    if (!phoneEq) body.phone_number = phoneRaw;  // bo'sh string — tozalash
    if (active !== courier.is_active) body.is_active = active;
    if (Object.keys(body).length === 0) {
      close();
      return;
    }
    try {
      await api.updateCourier(courier.id, body);
      toast("Saqlandi", "success");
      close();
      onSaved && onSaved();
    } catch (e) { toast(e.message, "error"); }
  });
}
