/* =========================================================================
   Клиенты: поиск, редактирование карточки, рейтинг, заметки, согласие 152-ФЗ.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const isSuperadmin = window.CLIENTS_IS_SUPERADMIN === true;

  function openModal(row) {
    const data = row ? JSON.parse(row.dataset.client) : null;
    document.getElementById("clientModalTitle").textContent = data ? data.full_name : "Новый клиент";
    document.getElementById("clientId").value = data ? data.id : "";
    document.getElementById("clientName").value = data ? data.full_name : "";
    document.getElementById("clientPhone").value = data ? data.phone : "";
    document.getElementById("clientContact").value = data ? data.contact : "";
    document.getElementById("clientRating").value = data ? data.rating : 5;
    document.getElementById("clientNotes").value = data ? data.admin_notes : "";

    const consentBox = document.getElementById("clientConsentBox");
    if (data && data.consent) {
      consentBox.classList.remove("hidden");
      consentBox.innerHTML = `Согласие на обработку персональных данных получено ${App.escape(data.consent_date)}<br>IP: ${App.escape(data.consent_ip || "—")}`;
    } else if (data) {
      consentBox.classList.remove("hidden");
      consentBox.innerHTML = "Отметка о согласии отсутствует. Зафиксируйте письменное согласие перед процедурой.";
    } else {
      consentBox.classList.add("hidden");
    }

    const deleteButton = document.getElementById("deleteClient");
    if (deleteButton) deleteButton.classList.toggle("hidden", !data);

    App.Modal.open("clientModal");
  }

  async function save(event) {
    event.preventDefault();
    const id = document.getElementById("clientId").value;
    const payload = {
      full_name: document.getElementById("clientName").value.trim(),
      phone: document.getElementById("clientPhone").value.trim(),
      telegram_vk_contact: document.getElementById("clientContact").value.trim(),
      rating: Number(document.getElementById("clientRating").value),
      admin_notes: document.getElementById("clientNotes").value.trim(),
    };
    try {
      await App.withLoading(event.submitter, async () => {
        if (id) {
          await App.api(`/api/admin/clients/${id}`, { method: "PATCH", body: payload });
        } else {
          await App.api("/api/admin/clients", { method: "POST", body: payload });
        }
        App.toast("Данные клиента сохранены", "success");
        App.Modal.close("clientModal");
        setTimeout(() => window.location.reload(), 500);
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  async function remove() {
    const id = document.getElementById("clientId").value;
    const name = document.getElementById("clientName").value;
    if (!id) return;
    if (!App.confirmAction(`Удалить клиента «${name}» вместе со всеми его записями?`)) return;
    try {
      await App.api(`/api/admin/clients/${id}`, { method: "DELETE" });
      App.toast("Клиент удалён", "success");
      App.Modal.close("clientModal");
      setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  /** Поиск по таблице (клиентский фильтр). */
  function search(value) {
    const query = value.trim().toLowerCase();
    let visible = 0;
    document.querySelectorAll("#clientsTable tr").forEach((row) => {
      const match = !query || row.textContent.toLowerCase().includes(query);
      row.classList.toggle("hidden", !match);
      if (match) visible += 1;
    });
    document.getElementById("clientsCount").textContent = `Показано: ${visible}`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("openClientModal").addEventListener("click", () => openModal(null));
    document.getElementById("clientForm").addEventListener("submit", save);
    document.getElementById("clientSearch").addEventListener("input", (event) => search(event.target.value));

    document.querySelectorAll(".js-edit-client").forEach((button) => {
      button.addEventListener("click", () => openModal(button.closest("tr")));
    });

    const deleteButton = document.getElementById("deleteClient");
    if (deleteButton && isSuperadmin) deleteButton.addEventListener("click", remove);

    search("");
  });
})();
