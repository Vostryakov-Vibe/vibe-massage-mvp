/* =========================================================================
   Лендинг: пошаговая онлайн-запись, расчёт свободных слотов,
   модальное окно-«посадочный талон» с анимированной галочкой.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const state = {
    serviceId: null,
    serviceTitle: "",
    serviceDuration: "",
    servicePrice: 0,
    masterId: null,
    masterName: "",
    date: "",
    time: "",
    formToken: "",
    masters: [],
    submitting: false,
  };

  const el = (id) => document.getElementById(id);

  /** Загружает подписанный токен формы (антиспам по времени заполнения). */
  async function refreshFormToken() {
    try {
      const data = await App.api("/api/public/form-token");
      state.formToken = data.token;
    } catch (error) {
      console.warn("Не удалось получить токен формы:", error);
      state.formToken = "";
    }
  }

  /** Загружает список мастеров. */
  async function loadMasters() {
    try {
      const data = await App.api("/api/public/masters");
      state.masters = data.items || [];
    } catch (error) {
      state.masters = [];
      App.toast("Не удалось загрузить список мастеров", "error");
    }
  }

  /** Заполняет селект мастеров. */
  function fillMasters() {
    const select = el("bookingMaster");
    select.innerHTML = "";
    if (!state.masters.length) {
      select.innerHTML = '<option value="">— нет доступных мастеров —</option>';
      select.disabled = true;
      return;
    }
    select.appendChild(new Option("— выберите мастера —", ""));
    state.masters.forEach((master) => {
      const label = master.experience_years
        ? `${master.full_name} · ${master.specialization} · опыт ${master.experience_years} лет`
        : `${master.full_name} · ${master.specialization}`;
      select.appendChild(new Option(label, String(master.id)));
    });
    select.disabled = false;
  }

  /** Обновляет правую панель-сводку. */
  function updateSummary() {
    el("summaryService").textContent = state.serviceTitle || "—";
    el("summaryMaster").textContent = state.masterName || "—";
    el("summaryDuration").textContent = state.serviceDuration || "—";
    el("summaryPrice").textContent = state.servicePrice ? App.money(state.servicePrice) : "—";

    let dateText = "—";
    if (state.date) {
      const parts = state.date.split("-");
      dateText = `${parts[2]}.${parts[1]}.${parts[0]}`;
      if (state.time) dateText += ` в ${state.time}`;
    }
    el("summaryDateTime").textContent = dateText;
  }

  /** Перерисовывает сетку таймслотов. */
  function renderSlots(slots, message) {
    const area = el("slotArea");
    area.innerHTML = "";
    state.time = "";
    el("bookingTime").value = "";
    updateSummary();

    if (!slots || !slots.length) {
      const note = document.createElement("p");
      note.className = "text-sm text-brand-600 bg-brand-50 border border-brand-100 rounded-2xl px-4 py-3";
      note.textContent = message || "Свободных окон нет — выберите другую дату или мастера.";
      area.appendChild(note);
      return;
    }

    const label = document.createElement("p");
    label.className = "text-xs uppercase tracking-wider text-brand-600 mb-3";
    label.textContent = `Свободное время (${slots.length})`;
    area.appendChild(label);

    const grid = document.createElement("div");
    grid.className = "grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-2.5";
    slots.forEach((slot) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className =
        "slot-btn rounded-full border border-brand-200 px-3 py-2.5 text-sm font-medium text-brand-700 hover:border-gold-400 hover:scale-105 transition-all duration-300";
      button.textContent = slot;
      button.dataset.slot = slot;
      button.addEventListener("click", () => selectSlot(button, slot));
      grid.appendChild(button);
    });
    area.appendChild(grid);
  }

  /** Выбор слота. */
  function selectSlot(button, slot) {
    document.querySelectorAll(".slot-btn").forEach((node) => node.classList.remove("is-selected"));
    button.classList.add("is-selected");
    state.time = slot;
    el("bookingTime").value = slot;
    updateSummary();
  }

  /** Загружает слоты с сервера. */
  async function loadSlots() {
    const area = el("slotArea");
    if (!state.serviceId || !state.masterId || !state.date) {
      area.innerHTML = '<p class="text-sm text-brand-600">Сначала выберите услугу, мастера и дату.</p>';
      return;
    }
    area.innerHTML = '<p class="text-sm text-brand-600">Считаем свободные окна…</p>';
    try {
      const query = new URLSearchParams({
        service_id: state.serviceId,
        master_id: state.masterId,
        date_str: state.date,
      });
      const data = await App.api(`/api/public/slots?${query.toString()}`);
      renderSlots(data.slots, data.message);
    } catch (error) {
      area.innerHTML = "";
      const note = document.createElement("p");
      note.className = "text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl px-4 py-3";
      note.textContent = error.message;
      area.appendChild(note);
    }
  }

  /** Выбор услуги (из селекта или карточки). */
  function applyService(serviceId, optionText) {
    state.serviceId = serviceId;
    const select = el("bookingService");
    select.value = String(serviceId);

    const option = select.options[select.selectedIndex];
    const text = optionText || (option ? option.textContent : "");
    const chunks = text.split("·").map((part) => part.trim());
    state.serviceTitle = chunks[0] || "";
    state.serviceDuration = chunks[1] || "";
    const priceMatch = text.match(/([\d\s]+)\s*₽/);
    state.servicePrice = priceMatch ? parseInt(priceMatch[1].replace(/\s/g, ""), 10) : 0;

    const hint = el("serviceHint");
    hint.textContent = state.servicePrice
      ? `Стоимость сеанса: ${App.money(state.servicePrice)}. Оплата в салоне после процедуры.`
      : "";

    el("bookingMaster").disabled = false;
    el("bookingDate").disabled = false;
    state.time = "";
    updateSummary();
    loadSlots();
  }

  /** Отправка формы. */
  async function submitForm(event) {
    event.preventDefault();
    if (state.submitting) return;

    const name = el("bookingName").value.trim();
    const phone = el("bookingPhone").value.trim();
    const consent = el("bookingConsent").checked;

    if (!state.serviceId) return App.toast("Выберите программу массажа", "warning");
    if (!state.masterId) return App.toast("Выберите мастера", "warning");
    if (!state.date) return App.toast("Выберите дату визита", "warning");
    if (!state.time) return App.toast("Выберите свободное время", "warning");
    if (name.length < 2) return App.toast("Укажите имя", "warning");
    if (phone.replace(/\D/g, "").length < 10) return App.toast("Укажите корректный телефон", "warning");
    if (!consent) return App.toast("Отметьте согласие на обработку персональных данных", "warning");

    const turnstileInput = document.querySelector('[name="cf-turnstile-response"]');
    const payload = {
      service_id: Number(state.serviceId),
      master_id: Number(state.masterId),
      date: state.date,
      time: state.time,
      full_name: name,
      phone: phone,
      contact: el("bookingContact").value.trim(),
      comment: el("bookingComment").value.trim(),
      consent: consent,
      honeypot: el("bookingHoneypot").value,
      form_token: state.formToken,
      turnstile_token: turnstileInput ? turnstileInput.value : "",
    };

    state.submitting = true;
    try {
      await App.withLoading(el("bookingSubmit"), async () => {
        const data = await App.api("/api/public/bookings", { method: "POST", body: payload });
        showTicket(data.ticket);
        resetForm();
      });
    } catch (error) {
      App.toast(error.message, "error", 6000);
    } finally {
      state.submitting = false;
    }
  }

  /** Показывает «посадочный талон». */
  function showTicket(ticket) {
    el("ticketCode").textContent = ticket.code;
    el("ticketClient").textContent = ticket.client;
    el("ticketService").textContent = ticket.service;
    el("ticketMaster").textContent = ticket.master;
    el("ticketDate").textContent = `${ticket.date} (${ticket.weekday})`;
    el("ticketTime").textContent = ticket.time;
    el("ticketDuration").textContent = ticket.duration;
    el("ticketPrice").textContent = ticket.price;
    el("ticketAddress").textContent = ticket.address;
    el("ticketPhone").textContent = ticket.phone;

    const modal = el("ticketModal");
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    document.body.style.overflow = "hidden";

    // Перезапуск анимации галочки при повторном открытии.
    const svg = modal.querySelector(".success-check");
    if (svg) {
      const clone = svg.cloneNode(true);
      svg.replaceWith(clone);
    }
  }

  /** Закрывает модальное окно. */
  function hideTicket() {
    const modal = el("ticketModal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    document.body.style.overflow = "";
  }

  /** Сброс формы после успешной записи. */
  function resetForm() {
    el("bookingForm").reset();
    state.serviceId = null;
    state.masterId = null;
    state.date = "";
    state.time = "";
    state.serviceTitle = "";
    state.serviceDuration = "";
    state.servicePrice = 0;
    state.masterName = "";
    el("slotArea").innerHTML = '<p class="text-sm text-brand-600">Сначала выберите услугу, мастера и дату.</p>';
    el("serviceHint").textContent = "";
    el("bookingMaster").disabled = true;
    el("bookingDate").disabled = true;
    updateSummary();
    refreshFormToken();
  }

  /** Привязка обработчиков. */
  function bind() {
    el("bookingService").addEventListener("change", (event) => {
      const value = event.target.value;
      if (!value) {
        state.serviceId = null;
        state.serviceTitle = "";
        state.serviceDuration = "";
        state.servicePrice = 0;
        updateSummary();
        return;
      }
      applyService(Number(value));
    });

    el("bookingMaster").addEventListener("change", (event) => {
      const value = event.target.value;
      state.masterId = value ? Number(value) : null;
      const option = event.target.options[event.target.selectedIndex];
      state.masterName = value && option ? option.textContent.split("·")[0].trim() : "";
      updateSummary();
      loadSlots();
    });

    el("bookingDate").addEventListener("change", (event) => {
      state.date = event.target.value;
      updateSummary();
      loadSlots();
    });

    el("bookingForm").addEventListener("submit", submitForm);

    document.querySelectorAll(".js-pick-service").forEach((button) => {
      button.addEventListener("click", () => {
        const serviceId = Number(button.dataset.serviceId);
        const select = el("bookingService");
        const option = Array.from(select.options).find((item) => item.value === String(serviceId));
        applyService(serviceId, option ? option.textContent : "");
        document.getElementById("booking").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    el("ticketClose").addEventListener("click", hideTicket);
    el("ticketPrint").addEventListener("click", () => window.print());
    el("ticketModal").addEventListener("click", (event) => {
      if (event.target === el("ticketModal")) hideTicket();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideTicket();
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    updateSummary();
    await Promise.all([refreshFormToken(), loadMasters()]);
    fillMasters();

    // Предзаполнение даты: сегодня по локальному времени (если остались слоты — покажет сервер).
    const dateInput = el("bookingDate");
    const iso = App.localIsoDate();
    dateInput.value = iso;
    state.date = iso;
  });
})();
