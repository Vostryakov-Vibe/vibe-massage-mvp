/* =========================================================================
   CRM: Канбан-доска записей с drag&drop (локальный Sortable.js),
   редактирование карточки, гибкая цена, создание записи по звонку.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const config = window.CRM_DATA || { statuses: [], lostStatuses: [] };
  const board = document.getElementById("kanbanBoard");
  const state = { from: "", to: "", bookings: {} };

  /** Цвета колонок по статусам. */
  const COLUMN_TONES = {
    "Новая": "from-sky-500 to-sky-700",
    "Информирование клиента": "from-indigo-500 to-indigo-700",
    "Корректировка": "from-amber-500 to-amber-700",
    "Подтверждена": "from-emerald-500 to-emerald-700",
    "Выполнена": "from-teal-600 to-teal-800",
    "Отменена": "from-rose-500 to-rose-700",
    "Не пришел": "from-slate-500 to-slate-700",
  };

  function stars(rating) {
    const value = Math.max(0, Math.min(5, Number(rating) || 0));
    return "★".repeat(value) + "☆".repeat(5 - value);
  }

  /** HTML одной карточки записи. */
  function cardHtml(booking) {
    const isLost = config.lostStatuses.includes(booking.status);
    return `
      <article class="booking-card bg-white rounded-2xl border border-brand-100 p-4 shadow-sm"
               data-id="${booking.id}">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-semibold text-brand-800 truncate">${App.escape(booking.client)}</p>
            <p class="text-xs text-brand-500 mt-0.5">${App.escape(booking.phone || "телефон не указан")}</p>
          </div>
          <span class="text-[11px] text-gold-600 shrink-0" title="Рейтинг клиента">${stars(booking.rating)}</span>
        </div>

        <p class="text-sm text-brand-700 mt-3 truncate">${App.escape(booking.service)}</p>
        <p class="text-xs text-brand-500 mt-1 truncate">Мастер: ${App.escape(booking.master)}</p>

        <div class="flex items-center justify-between mt-3 pt-3 border-t border-brand-50">
          <span class="text-xs font-medium text-brand-700">${App.escape(booking.date_label)} · ${App.escape(booking.time)}</span>
          <span class="text-sm font-semibold ${isLost ? "text-rose-600 line-through" : "text-brand-800"}">${App.escape(booking.cost_label)}</span>
        </div>

        ${booking.comment ? `<p class="text-[11px] text-brand-500 mt-2 line-clamp-2">${App.escape(booking.comment)}</p>` : ""}
      </article>`;
  }

  /** Отрисовка доски. */
  function render(data) {
    state.bookings = {};
    board.innerHTML = "";

    data.columns.forEach((column) => {
      column.bookings.forEach((booking) => {
        state.bookings[booking.id] = booking;
      });

      const wrapper = document.createElement("section");
      wrapper.className = "kanban__column";
      wrapper.innerHTML = `
        <header class="px-4 py-3 border-b border-brand-100 rounded-t-2xl bg-gradient-to-r ${COLUMN_TONES[column.status] || "from-brand-500 to-brand-700"} text-white">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold">${App.escape(column.status)}</h2>
            <span class="text-xs bg-white/20 rounded-full px-2 py-0.5">${column.bookings.length}</span>
          </div>
        </header>
        <div class="kanban__list" data-status="${App.escape(column.status)}">
          ${column.bookings.map(cardHtml).join("")}
        </div>`;

      board.appendChild(wrapper);

      const list = wrapper.querySelector(".kanban__list");
      window.Sortable.create(list, {
        group: "bookings",
        animation: 180,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        draggable: ".booking-card",
        onStart: () => list.classList.add("is-over"),
        onEnd: async (event) => {
          document.querySelectorAll(".kanban__list").forEach((node) => node.classList.remove("is-over"));
          const bookingId = Number(event.item.dataset.id);
          const newStatus = event.to.dataset.status;
          const oldStatus = event.from.dataset.status;
          if (newStatus === oldStatus) return;
          await changeStatus(bookingId, newStatus, event);
        },
      });
    });

    const total = document.getElementById("boardTotal");
    if (total) {
      total.textContent = `Всего записей: ${data.total}`;
    }

    board.querySelectorAll(".booking-card").forEach((card) => {
      card.addEventListener("click", () => openCard(Number(card.dataset.id)));
    });
  }

  /** Смена статуса перетаскиванием. */
  async function changeStatus(bookingId, status, event) {
    try {
      const data = await App.api(`/api/admin/bookings/${bookingId}/status`, {
        method: "POST",
        body: { status },
      });
      App.toast(`Запись №${bookingId}: ${status}`, "success");
      state.bookings[bookingId] = data.booking;
      updateColumnCounters();
    } catch (error) {
      App.toast(error.message, "error");
      load(); // возвращаем карточку на прежнее место
    }
  }

  /** Пересчёт счётчиков в шапках колонок. */
  function updateColumnCounters() {
    board.querySelectorAll(".kanban__column").forEach((column) => {
      const list = column.querySelector(".kanban__list");
      const counter = column.querySelector("header span");
      if (list && counter) counter.textContent = list.querySelectorAll(".booking-card").length;
    });
  }

  /** Загрузка доски с учётом фильтров. */
  async function load() {
    const params = new URLSearchParams();
    if (state.from) params.set("date_from", state.from);
    if (state.to) params.set("date_to", state.to);
    board.innerHTML = '<div class="text-brand-600 text-sm p-6">Загрузка записей…</div>';
    try {
      const data = await App.api(`/api/admin/bookings?${params.toString()}`);
      render(data);
    } catch (error) {
      board.innerHTML = `<div class="text-rose-700 text-sm p-6">${App.escape(error.message)}</div>`;
    }
  }

  /** Открывает карточку записи. */
  function openCard(bookingId) {
    const booking = state.bookings[bookingId];
    if (!booking) return;

    document.getElementById("editBookingId").value = booking.id;
    document.getElementById("modalClient").textContent = booking.client;
    document.getElementById("modalContact").textContent =
      [booking.phone, booking.contact].filter(Boolean).join(" · ");
    document.getElementById("editStatus").value = booking.status;
    document.getElementById("editMaster").value = booking.master_id || "";
    document.getElementById("editDate").value = booking.date;
    document.getElementById("editTime").value = booking.time;
    document.getElementById("editCost").value = booking.cost;
    document.getElementById("editComment").value = booking.comment || "";
    document.getElementById("modalService").textContent = booking.service;
    document.getElementById("modalRating").textContent = stars(booking.rating);
    document.getElementById("modalNotes").textContent = booking.client_notes || "—";
    document.getElementById("modalCreated").textContent = booking.created_at;

    const call = document.getElementById("modalCall");
    call.href = booking.phone ? `tel:${booking.phone.replace(/[^\d+]/g, "")}` : "#";
    call.classList.toggle("opacity-40", !booking.phone);
    call.classList.toggle("pointer-events-none", !booking.phone);

    App.Modal.open("bookingModal");
  }

  /** Сохранение изменений карточки. */
  async function saveCard(event) {
    event.preventDefault();
    const bookingId = Number(document.getElementById("editBookingId").value);
    const payload = {
      status: document.getElementById("editStatus").value,
      master_id: Number(document.getElementById("editMaster").value) || null,
      visit_date: document.getElementById("editDate").value,
      visit_time: document.getElementById("editTime").value,
      total_cost: Number(document.getElementById("editCost").value || 0),
      comment: document.getElementById("editComment").value,
    };
    try {
      await App.withLoading(event.submitter, async () => {
        await App.api(`/api/admin/bookings/${bookingId}`, { method: "PATCH", body: payload });
        App.toast("Карточка сохранена", "success");
        App.Modal.close("bookingModal");
        load();
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  /** Удаление записи (Суперадмин). */
  async function deleteCard() {
    const bookingId = Number(document.getElementById("editBookingId").value);
    if (!App.confirmAction(`Удалить запись №${bookingId} безвозвратно?`)) return;
    try {
      await App.api(`/api/admin/bookings/${bookingId}`, { method: "DELETE" });
      App.toast("Запись удалена", "success");
      App.Modal.close("bookingModal");
      load();
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  /** Создание записи по звонку. */
  async function createBooking(event) {
    event.preventDefault();
    const payload = {
      full_name: document.getElementById("newName").value.trim(),
      phone: document.getElementById("newPhone").value.trim(),
      service_id: Number(document.getElementById("newService").value),
      master_id: Number(document.getElementById("newMaster").value),
      date: document.getElementById("newDate").value,
      time: document.getElementById("newTime").value,
      comment: document.getElementById("newComment").value.trim(),
      force: document.getElementById("newForce").checked,
    };
    try {
      await App.withLoading(event.submitter, async () => {
        await App.api("/api/admin/bookings", { method: "POST", body: payload });
        App.toast("Запись создана", "success");
        App.Modal.close("createModal");
        document.getElementById("createBookingForm").reset();
        load();
      });
    } catch (error) {
      App.toast(error.message, "error", 6000);
    }
  }

  /** Быстрые фильтры периода. */
  function applyRange(range) {
    const today = new Date();
    const iso = (date) => App.localIsoDate(date);
    if (range === "today") {
      state.from = iso(today);
      state.to = iso(today);
    } else if (range === "week") {
      const monday = new Date(today);
      const offset = (today.getDay() + 6) % 7;
      monday.setDate(today.getDate() - offset);
      state.from = iso(monday);
      state.to = iso(today);
    } else if (range === "month") {
      state.from = iso(new Date(today.getFullYear(), today.getMonth(), 1));
      state.to = iso(today);
    } else {
      state.from = "";
      state.to = "";
    }
    document.getElementById("filterFrom").value = state.from;
    document.getElementById("filterTo").value = state.to;
    load();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#quickFilters button").forEach((button) => {
      button.addEventListener("click", () => applyRange(button.dataset.range));
    });
    document.getElementById("applyFilters").addEventListener("click", () => {
      state.from = document.getElementById("filterFrom").value;
      state.to = document.getElementById("filterTo").value;
      load();
    });
    document.getElementById("bookingEditForm").addEventListener("submit", saveCard);
    document.getElementById("createBookingForm").addEventListener("submit", createBooking);
    document.getElementById("openCreateBooking").addEventListener("click", () => {
      const today = App.localIsoDate();
      document.getElementById("newDate").value = today;
      document.getElementById("newTime").value = "10:00";
      App.Modal.open("createModal");
    });
    const deleteButton = document.getElementById("deleteBooking");
    if (deleteButton) deleteButton.addEventListener("click", deleteCard);

    document.addEventListener("salon:bookings-changed", () => load());

    applyRange("month");
  });
})();
