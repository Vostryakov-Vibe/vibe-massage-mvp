/* =========================================================================
   Пользователи админки: создание, смена пароля и роли, блокировка.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;

  function openModal(data) {
    const isNew = !data;
    document.getElementById("userModalTitle").textContent = isNew ? "Новый пользователь" : data.username;
    document.getElementById("userId").value = data ? data.id : "";
    document.getElementById("userLogin").value = data ? data.username : "";
    document.getElementById("userLogin").disabled = !isNew;
    document.getElementById("userFullName").value = data ? data.full_name : "";
    document.getElementById("userRole").value = data ? data.role : "Manager";
    document.getElementById("userPassword").value = "";
    document.getElementById("userPasswordLabel").textContent = isNew ? "Пароль *" : "Новый пароль";
    document.getElementById("userPasswordHint").textContent = isNew
      ? "Минимум 6 символов."
      : "Оставьте пустым, чтобы не менять пароль.";
    document.getElementById("userActive").checked = data ? data.is_active : true;
    document.getElementById("userActiveBox").classList.toggle("hidden", isNew);
    App.Modal.open("userModal");
  }

  async function save(event) {
    event.preventDefault();
    const id = document.getElementById("userId").value;
    const password = document.getElementById("userPassword").value;

    try {
      await App.withLoading(event.submitter, async () => {
        if (id) {
          const payload = {
            full_name: document.getElementById("userFullName").value.trim(),
            role: document.getElementById("userRole").value,
            is_active: document.getElementById("userActive").checked,
          };
          if (password) payload.password = password;
          await App.api(`/api/admin/users/${id}`, { method: "PATCH", body: payload });
        } else {
          await App.api("/api/admin/users", {
            method: "POST",
            body: {
              username: document.getElementById("userLogin").value.trim(),
              full_name: document.getElementById("userFullName").value.trim(),
              role: document.getElementById("userRole").value,
              password: password,
            },
          });
        }
        App.toast("Пользователь сохранён", "success");
        App.Modal.close("userModal");
        setTimeout(() => window.location.reload(), 500);
      });
    } catch (error) {
      App.toast(error.message, "error", 6000);
    }
  }

  async function remove(button) {
    if (!App.confirmAction(`Удалить пользователя «${button.dataset.username}»?`)) return;
    try {
      await App.api(`/api/admin/users/${button.dataset.id}`, { method: "DELETE" });
      App.toast("Пользователь удалён", "success");
      setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("openUserModal").addEventListener("click", () => openModal(null));
    document.getElementById("userForm").addEventListener("submit", save);
    document.querySelectorAll(".js-edit-user").forEach((button) => {
      button.addEventListener("click", () => openModal(JSON.parse(button.closest("tr").dataset.user)));
    });
    document.querySelectorAll(".js-delete-user").forEach((button) => {
      button.addEventListener("click", () => remove(button));
    });
  });
})();
