/* =========================================================================
   Услуги: создание, редактирование, мягкое скрытие и жёсткое удаление.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;

  function openModal(data) {
    document.getElementById("serviceModalTitle").textContent = data ? data.title : "Новая услуга";
    document.getElementById("serviceId").value = data ? data.id : "";
    document.getElementById("serviceTitle").value = data ? data.title : "";
    document.getElementById("serviceCategory").value = data ? data.category : "Классический массаж";
    document.getElementById("serviceDuration").value = data ? data.duration_minutes : 60;
    document.getElementById("servicePrice").value = data ? data.price : 3000;
    document.getElementById("serviceShort").value = data ? data.short_description : "";
    document.getElementById("serviceFull").value = data ? data.full_description : "";
    document.getElementById("serviceIndications").value = data ? data.indications : "";
    document.getElementById("serviceContra").value = data ? data.contraindications : "";
    document.getElementById("serviceOrder").value = data ? data.sort_order : 100;
    document.getElementById("serviceActive").checked = data ? data.is_active : true;
    App.Modal.open("serviceModal");
  }

  function collect() {
    return {
      title: document.getElementById("serviceTitle").value.trim(),
      category: document.getElementById("serviceCategory").value,
      duration_minutes: Number(document.getElementById("serviceDuration").value),
      price: Number(document.getElementById("servicePrice").value),
      short_description: document.getElementById("serviceShort").value.trim(),
      full_description: document.getElementById("serviceFull").value.trim(),
      indications: document.getElementById("serviceIndications").value.trim(),
      contraindications: document.getElementById("serviceContra").value.trim(),
      sort_order: Number(document.getElementById("serviceOrder").value),
      is_active: document.getElementById("serviceActive").checked,
    };
  }

  async function save(event) {
    event.preventDefault();
    const id = document.getElementById("serviceId").value;
    try {
      await App.withLoading(event.submitter, async () => {
        if (id) {
          await App.api(`/api/admin/services/${id}`, { method: "PATCH", body: collect() });
        } else {
          await App.api("/api/admin/services", { method: "POST", body: collect() });
        }
        App.toast("Услуга сохранена", "success");
        App.Modal.close("serviceModal");
        setTimeout(() => window.location.reload(), 500);
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  async function toggle(button) {
    const id = button.dataset.id;
    const isActive = button.dataset.active === "1";
    try {
      if (isActive) {
        await App.api(`/api/admin/services/${id}`, { method: "DELETE" });
        App.toast("Услуга скрыта с сайта. История записей сохранена.", "success");
      } else {
        await App.api(`/api/admin/services/${id}/restore`, { method: "POST" });
        App.toast("Услуга снова доступна на сайте", "success");
      }
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  async function hardDelete(button) {
    const id = button.dataset.id;
    const title = button.dataset.title;
    const warning =
      `Удалить услугу «${title}» безвозвратно?\n\n` +
      "Записи останутся в базе, но ссылка на услугу будет очищена " +
      "(название в истории и аналитике сохранится).";
    if (!App.confirmAction(warning)) return;
    try {
      const result = await App.api(`/api/admin/services/${id}/hard`, { method: "DELETE" });
      App.toast(`Услуга удалена. Затронуто записей: ${result.affected_bookings}`, "success", 6000);
      setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("openServiceModal").addEventListener("click", () => openModal(null));
    document.getElementById("serviceForm").addEventListener("submit", save);
    document.querySelectorAll(".js-edit-service").forEach((button) => {
      button.addEventListener("click", () => openModal(JSON.parse(button.dataset.service)));
    });
    document.querySelectorAll(".js-toggle-service").forEach((button) => {
      button.addEventListener("click", () => toggle(button));
    });
    document.querySelectorAll(".js-hard-delete-service").forEach((button) => {
      button.addEventListener("click", () => hardDelete(button));
    });
  });
})();
