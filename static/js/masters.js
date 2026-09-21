/* =========================================================================
   Мастера: карточки, мягкое/жёсткое удаление, заполнение графика смен.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;

  function openMasterModal(data) {
    document.getElementById("masterModalTitle").textContent = data ? data.full_name : "Новый мастер";
    document.getElementById("masterId").value = data ? data.id : "";
    document.getElementById("masterName").value = data ? data.full_name : "";
    document.getElementById("masterSpec").value = data ? data.specialization : "";
    document.getElementById("masterExp").value = data ? data.experience_years : 5;
    document.getElementById("masterBio").value = data ? data.bio : "";
    document.getElementById("masterActive").checked = data ? data.is_active : true;
    App.Modal.open("masterModal");
  }

  async function saveMaster(event) {
    event.preventDefault();
    const id = document.getElementById("masterId").value;
    const payload = {
      full_name: document.getElementById("masterName").value.trim(),
      specialization: document.getElementById("masterSpec").value.trim(),
      experience_years: Number(document.getElementById("masterExp").value),
      bio: document.getElementById("masterBio").value.trim(),
      is_active: document.getElementById("masterActive").checked,
    };
    try {
      await App.withLoading(event.submitter, async () => {
        if (id) {
          await App.api(`/api/admin/masters/${id}`, { method: "PATCH", body: payload });
        } else {
          await App.api("/api/admin/masters", { method: "POST", body: payload });
        }
        App.toast("Мастер сохранён", "success");
        App.Modal.close("masterModal");
        setTimeout(() => window.location.reload(), 500);
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  async function toggleMaster(button) {
    const id = button.dataset.id;
    const isActive = button.dataset.active === "1";
    try {
      if (isActive) {
        await App.api(`/api/admin/masters/${id}`, { method: "DELETE" });
        App.toast("Мастер скрыт с сайта. История записей сохранена.", "success");
      } else {
        await App.api(`/api/admin/masters/${id}/restore`, { method: "POST" });
        App.toast("Мастер снова доступен на сайте", "success");
      }
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  async function hardDeleteMaster(button) {
    const id = button.dataset.id;
    const name = button.dataset.name;
    const warning =
      `Удалить мастера «${name}» безвозвратно?\n\n` +
      "Все его записи будут переведены на системного мастера «Уволенный сотрудник», " +
      "график смен удалён. Аналитика по прошлым периодам сохранится.";
    if (!App.confirmAction(warning)) return;
    try {
      const result = await App.api(`/api/admin/masters/${id}/hard`, { method: "DELETE" });
      App.toast(
        `Мастер удалён. Записи переведены на «${result.reassigned_to}»: ${result.affected_bookings}`,
        "success",
        7000
      );
      setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  function openSchedule(button) {
    document.getElementById("scheduleTitle").textContent = button.dataset.name;
    document.getElementById("scheduleMasterId").value = button.dataset.id;
    const today = new Date();
    const iso = (date) => App.localIsoDate(date);
    document.getElementById("scheduleFrom").value = iso(today);
    const monthLater = new Date(today);
    monthLater.setDate(today.getDate() + 30);
    document.getElementById("scheduleTo").value = iso(monthLater);
    document.querySelectorAll(".js-weekday").forEach((box) => (box.checked = false));
    App.Modal.open("scheduleModal");
  }

  async function saveSchedule(event) {
    event.preventDefault();
    const weekdays = Array.from(document.querySelectorAll(".js-weekday:checked")).map((box) =>
      Number(box.value)
    );
    const payload = {
      master_id: Number(document.getElementById("scheduleMasterId").value),
      date_from: document.getElementById("scheduleFrom").value,
      date_to: document.getElementById("scheduleTo").value,
      weekdays: weekdays,
      start_time: document.getElementById("scheduleStart").value,
      end_time: document.getElementById("scheduleEnd").value,
      replace: document.getElementById("scheduleReplace").checked,
    };
    try {
      await App.withLoading(event.submitter, async () => {
        const result = await App.api("/api/admin/schedules", { method: "POST", body: payload });
        App.toast(`Создано смен: ${result.created}`, "success");
        App.Modal.close("scheduleModal");
        setTimeout(() => window.location.reload(), 600);
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("openMasterModal").addEventListener("click", () => openMasterModal(null));
    document.getElementById("masterForm").addEventListener("submit", saveMaster);
    document.getElementById("scheduleForm").addEventListener("submit", saveSchedule);

    document.querySelectorAll(".js-edit-master").forEach((button) => {
      button.addEventListener("click", () => openMasterModal(JSON.parse(button.dataset.master)));
    });
    document.querySelectorAll(".js-toggle-master").forEach((button) => {
      button.addEventListener("click", () => toggleMaster(button));
    });
    document.querySelectorAll(".js-hard-delete-master").forEach((button) => {
      button.addEventListener("click", () => hardDeleteMaster(button));
    });
    document.querySelectorAll(".js-schedule-master").forEach((button) => {
      button.addEventListener("click", () => openSchedule(button));
    });
  });
})();
