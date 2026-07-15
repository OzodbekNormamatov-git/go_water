// Tizim sozlamalari — cashback dasturi va moliyaviy ko'rinish.

import { api, ApiError } from "../api.js";
import { fmtMoney, fmtCount, escapeHtml } from "../format.js";
import { toast } from "../toast.js";

export async function renderSettings(root) {
  root.innerHTML = `
    <div class="kpi-grid" id="cashbackKpis"></div>

    <div class="charts-grid" style="grid-template-columns: 1fr">
      <div class="card">
        <h3 class="card__title">Cashback dasturi sozlamalari</h3>
        <form id="cbForm">
          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Cashback yoqilgan</div>
              <div class="settings-row__hint">O'chirilsa: yangi keshbek berilmaydi va mijozlar uni buyurtmada ishlatolmaydi (eski balanslar saqlanadi).</div>
            </div>
            <label class="switch">
              <input type="checkbox" id="cb-enabled" />
              <span class="switch__slider"></span>
            </label>
          </div>

          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Cashback foizi (%)</div>
              <div class="settings-row__hint">Har sotuvdan qancha foiz qaytariladi. 0..50% oralig'ida.</div>
            </div>
            <input class="input" id="cb-percent" type="number" min="0" max="50" step="0.1" style="max-width:120px" />
          </div>

          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Bitta buyurtmada keshbek qoplash chegarasi</div>
              <div class="settings-row__hint">100% = to'liq qoplash mumkin. Misol: 50% — mijoz buyurtmaning yarmigacha keshbek bilan qoplaydi.</div>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <input class="input" id="cb-ratio" type="number" min="0" max="100" step="1" style="max-width:120px" />
              <span class="muted">%</span>
            </div>
          </div>

          <div style="text-align:right;margin-top:12px">
            <button class="btn" id="saveBtn" type="button">Saqlash</button>
          </div>
        </form>
      </div>
    </div>

    <div class="charts-grid" style="grid-template-columns: 1fr">
      <div class="card">
        <h3 class="card__title">💧 Avto-eslatma ("suv kerakmi?")</h3>
        <p class="muted" style="font-size:12px;margin-bottom:8px">
          Tizim har mijozning o'rtacha siklini (necha kunda suv olishini, idish soniga qarab) hisoblab boradi.
          Sikl tugayotganda mijozga <b>ertalab</b> "suv kerakmi?" eslatmasi yuboriladi.
        </p>
        <form id="remForm">
          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Avto-eslatma yoqilgan</div>
              <div class="settings-row__hint">O'chirilsa: hech qanday eslatma yuborilmaydi.</div>
            </div>
            <label class="switch">
              <input type="checkbox" id="rem-enabled" />
              <span class="switch__slider"></span>
            </label>
          </div>

          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Necha kun OLDIN eslatilsin</div>
              <div class="settings-row__hint">Sikl tugashidan necha kun oldin eslatma borsin. <b>0</b> = aynan tugash kuni, <b>1</b> = 1 kun oldin. (Faqat kunlarda — eslatma doim ertalab boradi.)</div>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <input class="input" id="rem-lead" type="number" min="0" max="30" step="1" style="max-width:120px" />
              <span class="muted">kun</span>
            </div>
          </div>

          <div style="text-align:right;margin-top:12px">
            <button class="btn" id="saveRemBtn" type="button">Saqlash</button>
          </div>
        </form>
      </div>
    </div>

    <div class="charts-grid" style="grid-template-columns: 1fr">
      <div class="card">
        <h3 class="card__title">🚶 Promouterlar (uyma-uy ishchilar)</h3>
        <p class="muted" style="font-size:12px;margin-bottom:8px">
          Ishchilar mijozlarga borib botni tushuntiradi va manzil saqlashga o'rgatadi,
          so'ng mijozning telefonida o'z promokodini kiritadi. Keyingi zakazlar o'sha
          ishchiga yozilib, bonus hisoblanadi. Ishchilar «Promouterlar» bo'limida.
        </p>
        <form id="promForm">
          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Promokod dasturi yoqilgan</div>
              <div class="settings-row__hint">
                O'chirilsa: yangi kodlar qabul qilinmaydi va yangi zakazlarga bonus
                yozilmaydi. Mavjud bog'lanishlar va o'tmish hisoboti saqlanadi.
              </div>
            </div>
            <label class="switch">
              <input type="checkbox" id="prom-enabled" />
              <span class="switch__slider"></span>
            </label>
          </div>

          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Har zakaz uchun bonus</div>
              <div class="settings-row__hint">
                Bonus davri ichidagi har bir <b>yetkazilgan</b> zakaz uchun ishchiga
                yoziladigan summa. <b>0</b> = bonus yozilmaydi (faqat statistika yig'iladi).
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <input class="input" id="prom-bonus" type="number" min="0" step="500" style="max-width:140px" />
              <span class="muted">so'm</span>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-row__label">
              <div class="settings-row__title">Bonus davri</div>
              <div class="settings-row__hint">
                Mijoz kod kiritganidan keyin necha kun davomida uning zakazlari
                ishchiga bonus keltiradi. Davr tugagach, mijoz baribir ishchiga
                <b>biriktirilgan bo'lib qoladi</b> (statistika uchun) — faqat bonus to'xtaydi.
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <input class="input" id="prom-window" type="number" min="1" max="3650" step="1" style="max-width:120px" />
              <span class="muted">kun</span>
            </div>
          </div>

          <p class="muted" style="font-size:12px;margin-top:10px">
            ℹ️ Bu yerdagi o'zgarish <b>orqaga qarab ta'sir qilmaydi</b>: bonus summasi har
            zakazga yaratilganda, davr esa kod kiritilganda muhrlanadi — o'tgan oylarning
            hisoboti o'zgarmaydi.
          </p>

          <div style="text-align:right;margin-top:12px">
            <button class="btn" id="savePromBtn" type="button">Saqlash</button>
          </div>
        </form>
      </div>
    </div>

    <div class="charts-grid" style="grid-template-columns: 1fr 1fr">
      <div class="card">
        <h3 class="card__title">Tarixiy keshbek aylanmasi</h3>
        <div id="historyBox"></div>
      </div>
      <div class="card">
        <h3 class="card__title">Idishlar (bo'sh baklashka)</h3>
        <div id="bottlesBox"></div>
      </div>
    </div>
  `;

  await reload();

  async function reload() {
    let cfg, overview, rem, prom;
    try {
      [cfg, overview, rem, prom] = await Promise.all([
        api.settings(), api.cashbackOverview(), api.reminders(), api.promoterSettings(),
      ]);
    } catch (e) {
      toast(e.message || "Yuklab bo'lmadi", "error");
      return;
    }

    // Form values
    root.querySelector("#cb-enabled").checked = !!cfg.cashback_enabled;
    root.querySelector("#cb-percent").value = Number(cfg.cashback_percent);
    root.querySelector("#cb-ratio").value = Math.round(Number(cfg.max_cashback_usage_ratio) * 100);

    // Avto-eslatma form
    root.querySelector("#rem-enabled").checked = !!rem.reminders_enabled;
    root.querySelector("#rem-lead").value = Number(rem.reminder_lead_days);

    // Promouter form
    root.querySelector("#prom-enabled").checked = !!prom.promoter_program_enabled;
    root.querySelector("#prom-bonus").value = Number(prom.promoter_bonus_per_order);
    root.querySelector("#prom-window").value = Number(prom.promoter_bonus_window_days);

    // KPIs — moliyaviy ko'rinish
    root.querySelector("#cashbackKpis").innerHTML = `
      <div class="kpi">
        <div class="kpi__icon">💼</div>
        <div class="kpi__label">Cashback qarz (liability)</div>
        <div class="kpi__value">${fmtMoney(overview.liability_total)}</div>
        <div class="kpi__sub">${fmtCount(overview.customers_with_balance)} mijozda</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">📤</div>
        <div class="kpi__label">Tarixiy ishlatilgan</div>
        <div class="kpi__value">${fmtMoney(overview.cashback_used_all_time)}</div>
        <div class="kpi__sub">Mijozlar to'lov sifatida ishlatdi</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">🎁</div>
        <div class="kpi__label">Tarixiy berilgan</div>
        <div class="kpi__value">${fmtMoney(overview.cashback_earned_all_time)}</div>
        <div class="kpi__sub">DELIVERED bo'lganlardan jami</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">${overview.config_enabled ? "✅" : "⛔️"}</div>
        <div class="kpi__label">Holati</div>
        <div class="kpi__value" style="color:${overview.config_enabled ? "var(--brand-success)" : "var(--brand-danger)"}">
          ${overview.config_enabled ? "YOQILGAN" : "O'CHIRILGAN"}
        </div>
        <div class="kpi__sub">${overview.config_percent}% qaytaradi</div>
      </div>
    `;

    // History summary
    const net = overview.cashback_earned_all_time - overview.cashback_used_all_time;
    root.querySelector("#historyBox").innerHTML = `
      <div class="detail-row">
        <span class="detail-row__label">Jami berilgan</span>
        <span class="detail-row__value" style="color:var(--brand-success)">+${fmtMoney(overview.cashback_earned_all_time)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-row__label">Jami ishlatilgan</span>
        <span class="detail-row__value">−${fmtMoney(overview.cashback_used_all_time)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-row__label"><b>Hozirgi qarz</b></span>
        <span class="detail-row__value" style="color:var(--brand-deep);font-weight:800">${fmtMoney(overview.liability_total)}</span>
      </div>
      <p class="muted" style="font-size:12px;margin-top:8px">
        <b>Eslatma:</b> "Hozirgi qarz" = mijozlar qo'lidagi keshbek balansi. Mijozlar buni keyingi buyurtmada ishlatishadi.
        Jami berilgan − ishlatilgan = hozirgi qarz (approximately, manual ajustmentlar farq qilishi mumkin).
      </p>
    `;

    root.querySelector("#bottlesBox").innerHTML = `
      <div class="detail-row">
        <span class="detail-row__label">Jami idishlar qaytarilmagan</span>
        <span class="detail-row__value" style="font-weight:700;font-size:18px">${fmtCount(overview.bottles_outstanding_total)} ta</span>
      </div>
      <div class="detail-row">
        <span class="detail-row__label">Mijozlar soni</span>
        <span class="detail-row__value">${fmtCount(overview.customers_with_bottles)} ta</span>
      </div>
      <p class="muted" style="font-size:12px;margin-top:8px">
        Mijozlarga yetkazib berilgan, lekin hali qaytarib olinmagan bo'sh idishlar.
      </p>
    `;
  }

  root.querySelector("#saveBtn").addEventListener("click", async (e) => {
    e.preventDefault();
    const enabled = root.querySelector("#cb-enabled").checked;
    const percent = Number(root.querySelector("#cb-percent").value);
    const ratio = Number(root.querySelector("#cb-ratio").value) / 100;
    if (!Number.isFinite(percent) || percent < 0 || percent > 50) {
      return toast("Foiz 0..50% oralig'ida bo'lishi shart", "error");
    }
    if (!Number.isFinite(ratio) || ratio < 0 || ratio > 1) {
      return toast("Qoplash chegarasi 0..100% oralig'ida bo'lishi shart", "error");
    }
    try {
      await api.updateSettings({
        cashback_enabled: enabled,
        cashback_percent: percent,
        max_cashback_usage_ratio: ratio,
      });
      toast("Sozlamalar saqlandi", "success");
      await reload();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Xatolik";
      toast(msg, "error");
    }
  });

  root.querySelector("#saveRemBtn").addEventListener("click", async (e) => {
    e.preventDefault();
    const enabled = root.querySelector("#rem-enabled").checked;
    const lead = Math.floor(Number(root.querySelector("#rem-lead").value));
    if (!Number.isFinite(lead) || lead < 0 || lead > 30) {
      return toast("Eslatma kuni 0..30 oralig'ida bo'lishi shart", "error");
    }
    try {
      await api.updateReminders({ reminders_enabled: enabled, reminder_lead_days: lead });
      toast("Avto-eslatma sozlamasi saqlandi", "success");
      await reload();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Xatolik";
      toast(msg, "error");
    }
  });

  root.querySelector("#savePromBtn").addEventListener("click", async (e) => {
    e.preventDefault();
    const enabled = root.querySelector("#prom-enabled").checked;
    const bonus = Number(root.querySelector("#prom-bonus").value);
    const days = Math.floor(Number(root.querySelector("#prom-window").value));
    if (!Number.isFinite(bonus) || bonus < 0) {
      return toast("Bonus summasi manfiy bo'la olmaydi", "error");
    }
    if (!Number.isFinite(days) || days < 1 || days > 3650) {
      return toast("Bonus davri 1..3650 kun oralig'ida bo'lishi shart", "error");
    }
    try {
      await api.updatePromoterSettings({
        promoter_program_enabled: enabled,
        promoter_bonus_per_order: bonus,
        promoter_bonus_window_days: days,
      });
      toast("Promouter sozlamasi saqlandi", "success");
      await reload();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Xatolik";
      toast(msg, "error");
    }
  });

}
