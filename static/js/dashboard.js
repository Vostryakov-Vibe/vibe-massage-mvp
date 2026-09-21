/* =========================================================================
   Дашборд: графики на локальном Chart.js + таблицы метрик.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const state = { from: "", to: "", charts: {} };

  const EMERALD = "#044a42";
  const EMERALD_LIGHT = "#0b6b5f";
  const GOLD = "#d4af37";
  const ROSE = "#be123c";
  const PALETTE = ["#044a42", "#0b6b5f", "#d4af37", "#4f9488", "#8f7222", "#7fb8ac", "#e5c158"];

  if (window.Chart) {
    Chart.defaults.font.family = "'Manrope', 'Segoe UI', sans-serif";
    Chart.defaults.color = "#3f5b57";
  }

  /** Пересоздаёт график (уничтожая предыдущий экземпляр). */
  function draw(key, canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    if (state.charts[key]) state.charts[key].destroy();
    state.charts[key] = new Chart(canvas, config);
  }

  const moneyAxis = {
    ticks: {
      callback: (value) => new Intl.NumberFormat("ru-RU").format(value),
    },
  };

  function renderCharts(data) {
    // 1. Выручка по дням + количество записей
    draw("revenue", "revenueChart", {
      data: {
        labels: data.day_series.map((point) => point.label),
        datasets: [
          {
            type: "bar",
            label: "Выручка, ₽",
            data: data.day_series.map((point) => point.revenue),
            backgroundColor: EMERALD,
            borderRadius: 6,
            maxBarThickness: 26,
            yAxisID: "y",
          },
          {
            type: "line",
            label: "Записей",
            data: data.day_series.map((point) => point.bookings),
            borderColor: GOLD,
            backgroundColor: GOLD,
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 3,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" } },
        scales: {
          y: { position: "left", beginAtZero: true, ...moneyAxis },
          y1: {
            position: "right",
            beginAtZero: true,
            grid: { drawOnChartArea: false },
            ticks: { precision: 0 },
          },
        },
      },
    });

    // 2. Популярные услуги
    draw("services", "servicesChart", {
      type: "doughnut",
      data: {
        labels: data.popular_services.map((item) => item.title),
        datasets: [
          {
            data: data.popular_services.map((item) => item.count),
            backgroundColor: PALETTE,
            borderWidth: 2,
            borderColor: "#ffffff",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "58%",
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, padding: 12 } },
        },
      },
    });

    // 3. Упущенная выгода по дням
    draw("lost", "lostChart", {
      type: "bar",
      data: {
        labels: data.lost_series.map((point) => point.label),
        datasets: [
          {
            label: "Упущенная выгода, ₽",
            data: data.lost_series.map((point) => point.lost),
            backgroundColor: ROSE,
            borderRadius: 6,
            maxBarThickness: 24,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ...moneyAxis } },
      },
    });

    // 4. Загруженность мастеров
    draw("workload", "workloadChart", {
      type: "bar",
      data: {
        labels: data.workload.map((item) => item.master),
        datasets: [
          {
            label: "Загруженность, %",
            data: data.workload.map((item) => item.load_percent),
            backgroundColor: data.workload.map((item) =>
              item.load_percent >= 60 ? EMERALD : item.load_percent >= 30 ? GOLD : EMERALD_LIGHT
            ),
            borderRadius: 6,
            maxBarThickness: 28,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (context) =>
                `${context.parsed.x}% (${data.workload[context.dataIndex].booked_hours} из ${data.workload[context.dataIndex].scheduled_hours} ч)`,
            },
          },
        },
        scales: { x: { beginAtZero: true, ticks: { callback: (value) => value + "%" } } },
      },
    });
  }

  function renderTables(data) {
    const workload = document.getElementById("workloadTable");
    workload.innerHTML = data.workload.length
      ? data.workload
          .map(
            (item) => `
        <tr class="border-b border-brand-50">
          <td class="py-3 pr-4">
            <p class="font-medium text-brand-800">${App.escape(item.master)}</p>
            <p class="text-xs text-brand-500">${App.escape(item.specialization)}</p>
          </td>
          <td class="py-3 pr-4">${item.shifts}</td>
          <td class="py-3 pr-4">${item.scheduled_hours}</td>
          <td class="py-3 pr-4">${item.booked_hours}</td>
          <td class="py-3">
            <span class="inline-block rounded-full px-3 py-1 text-xs font-semibold ${
              item.load_percent >= 60
                ? "bg-emerald-100 text-emerald-800"
                : item.load_percent >= 30
                ? "bg-gold-100 text-gold-700"
                : "bg-brand-50 text-brand-600"
            }">${item.load_percent}%</span>
          </td>
        </tr>`
          )
          .join("")
      : '<tr><td colspan="5" class="py-4 text-brand-500">Нет данных за период</td></tr>';

    const lost = document.getElementById("lostTable");
    lost.innerHTML = data.lost_bookings.length
      ? data.lost_bookings
          .map(
            (item) => `
        <tr class="border-b border-brand-50">
          <td class="py-3 pr-4 whitespace-nowrap">${App.escape(item.date_label)}</td>
          <td class="py-3 pr-4">${App.escape(item.client)}</td>
          <td class="py-3 pr-4">${App.escape(item.service)}<span class="block text-xs text-brand-500">${App.escape(item.status)}</span></td>
          <td class="py-3 text-rose-700 font-medium whitespace-nowrap">${App.money(item.cost)}</td>
        </tr>`
          )
          .join("")
      : '<tr><td colspan="4" class="py-4 text-brand-500">Отмен и неявок нет — отличный результат!</td></tr>';
  }

  function renderKpi(data) {
    const kpi = data.kpi;
    document.getElementById("kpiRevenue").textContent = kpi.revenue_label;
    document.getElementById("kpiRevenueNote").textContent =
      `выполнено записей: ${kpi.bookings_done} из ${kpi.bookings_total}`;
    document.getElementById("kpiLost").textContent = kpi.lost_revenue_label;
    document.getElementById("kpiLostNote").textContent =
      `отменено и неявок: ${kpi.bookings_lost}`;
    document.getElementById("kpiConversion").textContent = kpi.conversion + "%";
    document.getElementById("kpiConversionNote").textContent =
      `потенциал периода: ${App.money(kpi.potential_revenue)}`;
    document.getElementById("kpiAvgCheck").textContent = kpi.avg_check_label;
    document.getElementById("kpiClients").textContent =
      `клиентов: ${kpi.clients_total} (новых: ${kpi.clients_new}) · рейтинг ${kpi.avg_rating}`;

    const from = data.period.date_from.split("-").reverse().join(".");
    const to = data.period.date_to.split("-").reverse().join(".");
    document.getElementById("periodLabel").textContent = `Период: ${from} — ${to}`;
  }

  async function load() {
    const params = new URLSearchParams();
    if (state.from) params.set("date_from", state.from);
    if (state.to) params.set("date_to", state.to);
    try {
      const data = await App.api(`/api/admin/analytics?${params.toString()}`);
      renderKpi(data);
      renderCharts(data);
      renderTables(data);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#rangePresets button").forEach((button) => {
      button.addEventListener("click", () => {
        state.from = button.dataset.from;
        state.to = button.dataset.to;
        document.getElementById("rangeFrom").value = state.from;
        document.getElementById("rangeTo").value = state.to;
        load();
      });
    });

    document.getElementById("applyRange").addEventListener("click", () => {
      state.from = document.getElementById("rangeFrom").value;
      state.to = document.getElementById("rangeTo").value;
      load();
    });

    document.getElementById("exportExcel").addEventListener("click", (event) => {
      const params = new URLSearchParams();
      if (state.from) params.set("date_from", state.from);
      if (state.to) params.set("date_to", state.to);
      App.toast("Формируем отчёт…", "info", 2000);
      window.location.href = `/api/admin/analytics/export?${params.toString()}`;
    });

    // По умолчанию — текущий месяц (даты локальные: toISOString() даёт UTC и
    // сдвигает границу периода на соседний день).
    const today = new Date();
    state.from = App.localIsoDate(new Date(today.getFullYear(), today.getMonth(), 1));
    state.to = App.localIsoDate(today);
    document.getElementById("rangeFrom").value = state.from;
    document.getElementById("rangeTo").value = state.to;
    load();
  });
})();
