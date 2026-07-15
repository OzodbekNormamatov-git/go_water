// Mijozlar faolligi va pik vaqtlar tahlili.

import { api } from "../api.js";
import { fmtCount, escapeHtml } from "../format.js";

let _charts = [];
function destroyCharts() {
  for (const c of _charts) { try { c.destroy(); } catch (_) {} }
  _charts = [];
}

const C = {
  blue:    "#0088CC",
  green:   "#27AE60",
  yellow:  "#F39C12",
  blueAlpha: "rgba(0, 136, 204, 0.15)",
};

// PG dow: 0=Yakshanba, 6=Shanba
const WEEKDAY_NAMES = ["Yakshanba", "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"];

export async function renderActivity(root, params) {
  destroyCharts();

  // Lokal state — select o'zgarganda yangilanadi. finance.js bilan bir xil
  // pattern: hashchange'ga umid qilmasdan, lokal reload + replaceState
  // (ba'zi Telegram WebView'larda hashchange ishonchsiz fire qiladi).
  const ALLOWED_DAYS = [7, 14, 30, 60, 90, 180, 365];
  let days = Number(params.days) || 30;
  if (!ALLOWED_DAYS.includes(days)) days = 30;

  root.innerHTML = `
    <div class="toolbar">
      <div class="filters">
        <select class="select" id="rangeSel">
          ${ALLOWED_DAYS.map((d) => `<option value="${d}" ${d === days ? "selected" : ""}>So'nggi ${d} kun</option>`).join("")}
        </select>
      </div>
    </div>

    <div class="kpi-grid" id="kpis"></div>

    <div class="charts-grid" style="grid-template-columns: 1fr">
      <div class="card chart-card">
        <h3 class="card__title">Mijozlar bazasi o'sishi</h3>
        <canvas id="signup-chart"></canvas>
      </div>
    </div>

    <div class="charts-grid" style="grid-template-columns: 1fr 1fr">
      <div class="card chart-card">
        <h3 class="card__title">Pik soatlar (sutka)</h3>
        <canvas id="hour-chart"></canvas>
      </div>
      <div class="card chart-card">
        <h3 class="card__title">Hafta kunlari kesimida</h3>
        <canvas id="weekday-chart"></canvas>
      </div>
    </div>
  `;

  const reload = () => loadAndRender(root, days);

  root.querySelector("#rangeSel").addEventListener("change", (e) => {
    const v = Number(e.target.value) || 30;
    if (!ALLOWED_DAYS.includes(v)) return;
    days = v;
    // URL — bookmark uchun (hashchange fire qilmaymiz)
    try {
      history.replaceState(
        null, "",
        `${location.pathname}${location.search}#/activity?days=${days}`,
      );
    } catch (_) {}
    reload();
  });

  await reload();
  return () => destroyCharts();
}

async function loadAndRender(root, days) {
  destroyCharts();
  const data = await api.activity(days).catch((e) => {
    root.querySelector("#kpis").innerHTML = `<div class="empty"><div class="empty__icon">⚠️</div><div class="empty__text">${escapeHtml(e.message)}</div></div>`;
    return null;
  });
  if (!data) return;

  const newSignups = data.signups_by_day.reduce((a, b) => a + (b.count || 0), 0);
  const peakHourLabel = (data.peak_hour ?? null) !== null ? `${String(data.peak_hour).padStart(2, "0")}:00` : "—";
  const peakWdLabel = (data.peak_weekday_index ?? null) !== null ? WEEKDAY_NAMES[data.peak_weekday_index] : "—";

  root.querySelector("#kpis").innerHTML = `
    <div class="kpi">
      <div class="kpi__icon">👤</div>
      <div class="kpi__label">Yangi mijozlar</div>
      <div class="kpi__value">${fmtCount(newSignups)}</div>
      <div class="kpi__sub">So'nggi ${days} kun</div>
    </div>
    <div class="kpi">
      <div class="kpi__icon">👥</div>
      <div class="kpi__label">Jami mijozlar</div>
      <div class="kpi__value">${fmtCount(data.customers_total)}</div>
      <div class="kpi__sub">Hozirgi baza</div>
    </div>
    <div class="kpi">
      <div class="kpi__icon">⏰</div>
      <div class="kpi__label">Pik soat</div>
      <div class="kpi__value">${escapeHtml(peakHourLabel)}</div>
      <div class="kpi__sub">Eng ko'p buyurtma vaqti</div>
    </div>
    <div class="kpi">
      <div class="kpi__icon">📅</div>
      <div class="kpi__label">Pik kun</div>
      <div class="kpi__value">${escapeHtml(peakWdLabel)}</div>
      <div class="kpi__sub">Eng tig'iz hafta kuni</div>
    </div>
  `;

  const Chart = window.Chart;
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#64748B";

  // Signups
  _charts.push(new Chart(root.querySelector("#signup-chart"), {
    type: "line",
    data: {
      labels: data.signups_by_day.map((p) => p.date.slice(5)),
      datasets: [{
        label: "Yangi mijozlar",
        data: data.signups_by_day.map((p) => p.count),
        borderColor: C.green,
        backgroundColor: "rgba(39, 174, 96, 0.18)",
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 2.5,
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  }));

  // Hours
  _charts.push(new Chart(root.querySelector("#hour-chart"), {
    type: "bar",
    data: {
      labels: data.peak_hours.map((h) => h.hour),
      datasets: [{
        label: "Buyurtmalar",
        data: data.peak_hours.map((h) => h.count),
        backgroundColor: data.peak_hours.map((h) => h.hour === data.peak_hour ? C.yellow : C.blue),
        borderRadius: 6,
        maxBarThickness: 18,
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  }));

  // Weekdays
  _charts.push(new Chart(root.querySelector("#weekday-chart"), {
    type: "bar",
    data: {
      labels: data.peak_weekday.map((w) => WEEKDAY_NAMES[w.weekday].slice(0, 3)),
      datasets: [{
        label: "Buyurtmalar",
        data: data.peak_weekday.map((w) => w.count),
        backgroundColor: data.peak_weekday.map((w) => w.weekday === data.peak_weekday_index ? C.yellow : C.blue),
        borderRadius: 6,
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  }));
}
