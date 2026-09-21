/* =========================================================================
   Общая логика админ-панели: опрос новых записей, звуковое уведомление,
   модальные окна, подтверждения.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const POLL_INTERVAL = 20000;

  /** Опрос новых записей: звук + тост + событие для обновления доски. */
  const Notifier = {
    lastId: null,
    timer: null,
    enabled: true,

    start() {
      if (!document.body.dataset.pollBookings) return;
      this.tick();
      this.timer = setInterval(() => this.tick(), POLL_INTERVAL);
      const indicator = document.getElementById("liveIndicator");
      if (indicator) indicator.classList.remove("hidden");
    },

    async tick() {
      try {
        const data = await App.api(`/api/admin/notifications?after_id=${this.lastId || 0}`);
        if (this.lastId === null) {
          // Первый опрос: запоминаем текущий максимум, звук не играем.
          this.lastId = data.max_id || 0;
          return;
        }
        if ((data.max_id || 0) > this.lastId) {
          const fresh = (data.items || []).filter((item) => item.id > this.lastId);
          this.lastId = data.max_id;
          if (fresh.length) {
            App.playNotificationSound();
            fresh
              .slice()
              .reverse()
              .forEach((booking) => {
                App.toast(
                  `Новая запись: ${booking.client}, ${booking.date_label} в ${booking.time}`,
                  "success",
                  7000
                );
              });
            document.dispatchEvent(new CustomEvent("salon:bookings-changed", { detail: fresh }));
          }
        }
      } catch (error) {
        // Молча: сервер может быть перезапущен, следующий тик восстановит связь.
        console.warn("Опрос уведомлений:", error.message);
      }
    },
  };

  /** Модальное окно: open(id) / close(id). */
  const Modal = {
    open(id) {
      const node = document.getElementById(id);
      if (!node) return;
      node.classList.remove("hidden");
      node.classList.add("flex");
      document.body.style.overflow = "hidden";
    },
    close(id) {
      const node = document.getElementById(id);
      if (!node) return;
      node.classList.add("hidden");
      node.classList.remove("flex");
      document.body.style.overflow = "";
    },
  };

  /** Простое подтверждение действия. */
  App.confirmAction = function (message) {
    return window.confirm(message);
  };

  document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-modal-close]");
    if (closer) Modal.close(closer.dataset.modalClose);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll(".js-modal.flex").forEach((node) => Modal.close(node.id));
    }
  });

  document.addEventListener("DOMContentLoaded", () => Notifier.start());

  App.Modal = Modal;
  App.Notifier = Notifier;
  window.SalonApp = App;
})();
