import { api, ApiError } from "../api.js";
import { fmtMoney, fmtCount, escapeHtml } from "../format.js";

let _charts = [];
function destroyCharts() {
  for (const c of _charts) { try { c.destroy(); } catch (_) {} }
  _charts = [];
}

// Dizayn tizimi: 4 funksional rang (CSS palitra'si bilan moslangan).
// Chart.js hex string kutadi — shu sababli inline. CSS var'lardan o'qish
// uchun getComputedStyle kerak edi, lekin Chart.js qayta-init paytida
// jonli o'qishi murakkab. Hex'lar barbar `admin.css :root` bilan moslangan.
const C = {
  blue:      "#0088CC",   // brand-primary    — aktiv statuslar (accepted/delivering/arrived)
  blueDark:  "#003F7F",   // brand-deep       — aksent, gradient end
  green:     "#27AE60",   // brand-success    — DELIVERED, daromad
  red:       "#E74C3C",   // brand-danger     — CANCELLED, xato
  yellow:    "#F39C12",   // brand-warning    — NEW, diqqat
  gray:      "#94A3B8",   // text-muted       — neutral
  blueAlpha: "rgba(0, 136, 204, 0.15)",
};

export async function renderDashboard(root) {
  destroyCharts();

  let data;
  try {
    data = await api.stats();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    return;
  }

  const t = data.today;
  const statusCounts = data.active_orders_by_status;
  const cashbackUsedToday = Number(t.cashback_used || 0);

  // Tushum: total_revenue = naqd + karta + avans (server DELIVERED bo'yicha
  // hisoblaydi). Eski backend'da total_revenue bo'lmasa — cash_revenue fallback.
  const totalRevenue = t.total_revenue !== undefined ? Number(t.total_revenue || 0) : Number(t.cash_revenue || 0);
  const cardRevenue = Number(t.card_revenue || 0);
  const depositRevenue = Number(t.deposit_revenue || 0);
  const revenueSub = (cardRevenue > 0 || depositRevenue > 0)
    ? `💵 ${fmtMoney(t.cash_revenue)} · 💳 ${fmtMoney(cardRevenue)} · 💰 ${fmtMoney(depositRevenue)}`
    : (cashbackUsedToday > 0 ? "Keshbeksiz qism" : "Faqat naqd");

  const cashbackBadge = data.cashback_enabled ? "" : `
    <div class="alert alert--danger">
      <div class="alert__icon">⛔️</div>
      <div class="alert__body">
        <div class="alert__title">Cashback dasturi o'chirilgan</div>
        <div class="alert__hint">Mijozlar yangi keshbek olmayapti va eski balansini ishlatolmayapti.</div>
      </div>
      <a href="#/settings" class="btn btn--xs btn--secondary">Sozlamalar</a>
    </div>
  `;

  root.innerHTML = `
    ${cashbackBadge}

    <div class="section-title">Bugungi moliya</div>
    <div class="kpi-grid kpi-grid--4">
      <div class="kpi">
        <div class="kpi__icon">💵</div>
        <div class="kpi__label">Bugungi tushum</div>
        <div class="kpi__value">${fmtMoney(totalRevenue)}</div>
        <div class="kpi__sub">${revenueSub}</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">💎</div>
        <div class="kpi__label">Keshbek aylanmasi</div>
        <div class="kpi__value">${fmtMoney(t.cashback_used)}</div>
        <div class="kpi__sub">+${fmtMoney(t.cashback_earned)} yangi liability</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">📊</div>
        <div class="kpi__label">Jami sotuv (gross)</div>
        <div class="kpi__value">${fmtMoney(t.gross_sale)}</div>
        <div class="kpi__sub">Naqd + keshbek</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">💼</div>
        <div class="kpi__label">Cashback qarz</div>
        <div class="kpi__value">${fmtMoney(data.cashback_liability_total || 0)}</div>
        <div class="kpi__sub">Mijozlar qo'lidagi keshbek</div>
      </div>
    </div>

    <div class="section-title">Bugungi operatsion</div>
    <div class="kpi-grid kpi-grid--4">
      <div class="kpi">
        <div class="kpi__icon">📦</div>
        <div class="kpi__label">Buyurtmalar</div>
        <div class="kpi__value">${fmtCount(t.orders_count)}</div>
        <div class="kpi__sub">Bugun yaratilgan</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">✅</div>
        <div class="kpi__label">Yetkazilgan</div>
        <div class="kpi__value">${fmtCount(t.delivered)}</div>
        <div class="kpi__sub">Bugun tugatilgan</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">👤</div>
        <div class="kpi__label">Yangi mijozlar</div>
        <div class="kpi__value">${fmtCount(t.new_customers)}</div>
        <div class="kpi__sub">Jami: ${fmtCount(data.customers_total)}</div>
      </div>
      <div class="kpi">
        <div class="kpi__icon">🚗</div>
        <div class="kpi__label">Kuryerlar</div>
        <div class="kpi__value">${fmtCount(data.couriers_active)} / ${fmtCount(data.couriers_total)}</div>
        <div class="kpi__sub">Aktiv / jami</div>
      </div>
    </div>

    ${statusCounts.length ? `
      <div class="section-title">Faol buyurtmalar holati</div>
      <div class="status-strip">
        ${statusCounts.map((s) => `
          <div class="status-strip__item status-strip__item--${s.color_token}">
            <div class="status-strip__count">${fmtCount(s.count)}</div>
            <div class="status-strip__label">${escapeHtml(s.label)}</div>
          </div>
        `).join("")}
      </div>
    ` : ""}

    <div class="section-title">Daromad trendi</div>
    <div class="charts-grid">
      <div class="card chart-card">
        <h3 class="card__title">So'nggi 30 kun</h3>
        <canvas id="revenue-chart"></canvas>
      </div>
      <div class="card chart-card">
        <h3 class="card__title">Top mahsulotlar (30 kun)</h3>
        <div class="tops" id="top-products"></div>
      </div>
    </div>

    <div class="section-title">Soatlik faollik</div>
    <div class="charts-grid" style="grid-template-columns: 1fr 1fr">
      <div class="card chart-card">
        <h3 class="card__title">Bugungi soatlik</h3>
        <canvas id="hour-chart"></canvas>
      </div>
      <div class="card chart-card">
        <h3 class="card__title">Status taqsimoti (faol)</h3>
        <canvas id="status-chart"></canvas>
      </div>
    </div>
  `;

  // --- Top products list
  const topEl = document.getElementById("top-products");
  if (!data.top_products.length) {
    topEl.innerHTML = `<div class="empty" style="padding:20px"><div class="empty__text">Hozircha sotuv yo'q.</div></div>`;
  } else {
    topEl.innerHTML = data.top_products.map((p, i) => `
      <div class="top-row">
        <div class="top-row__rank">${i + 1}</div>
        <div class="top-row__main">
          <div class="top-row__name">${escapeHtml(p.name)}</div>
          <div class="top-row__sub">${fmtCount(p.quantity_sold)} dona sotildi</div>
        </div>
        <div class="top-row__value">${fmtMoney(p.revenue)}</div>
      </div>
    `).join("");
  }

  // --- Charts
  const Chart = window.Chart;
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#64748B";

  const rev = data.revenue_last_30_days;
  const labels = rev.map((p) => p.date.slice(5));
  _charts.push(new Chart(document.getElementById("revenue-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Naqd",
          data: rev.map((p) => p.cash_revenue ?? p.revenue ?? 0),
          borderColor: C.blue,
          backgroundColor: C.blueAlpha,
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 2.5,
        },
        {
          label: "Keshbek aylanmasi",
          data: rev.map((p) => p.cashback_used ?? 0),
          borderColor: C.green,
          backgroundColor: "rgba(39, 174, 96, 0.10)",
          fill: false,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 2,
          borderDash: [4, 3],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: "bottom", labels: { boxWidth: 12, padding: 12 } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y)}` } },
      },
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => v >= 1000 ? (v / 1000) + "k" : v }, grid: { color: "rgba(15,23,42,0.05)" } },
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
      },
    },
  }));

  const hourly = data.orders_by_hour_today;
  _charts.push(new Chart(document.getElementById("hour-chart"), {
    type: "bar",
    data: {
      labels: hourly.map((h) => h.hour),
      datasets: [{
        label: "Buyurtmalar",
        data: hourly.map((h) => h.count),
        backgroundColor: C.blue,
        borderRadius: 6,
        maxBarThickness: 18,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(15,23,42,0.05)" } },
        x: { grid: { display: false } },
      },
    },
  }));

  // Status doughnut rangi — B sxemasi (4 funksional rang).
  // Aktiv 3 ta status (accepted/delivering/arrived) doughnut'da vizual
  // ajratish uchun brand-blue ning 3 shade variantida (deepening = oqim
  // bosqichi). Ranglar palitra'dan: brand-primary, primary-hover, brand-deep.
  const statusColors = {
    new:        C.yellow,
    accepted:   C.blue,        // #0088CC — sayoz aktiv
    delivering: "#006BA1",      // primary-hover — o'rta aktiv
    arrived:    C.blueDark,    // #003F7F — chuqur aktiv (deyarli yakun)
    delivered:  C.green,
    cancelled:  C.red,
  };
  _charts.push(new Chart(document.getElementById("status-chart"), {
    type: "doughnut",
    data: {
      labels: statusCounts.map((s) => s.label),
      datasets: [{
        data: statusCounts.map((s) => s.count),
        backgroundColor: statusCounts.map((s) => statusColors[s.color_token] || C.blue),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12, padding: 12 } } },
    },
  }));

  return () => destroyCharts();
}
