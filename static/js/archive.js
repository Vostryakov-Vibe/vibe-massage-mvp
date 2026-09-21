/* =========================================================================
   Архив: возврат из скрытых, жёсткое удаление, модерация отзывов.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;

  async function call(url, options, successMessage) {
    try {
      await App.api(url, options);
      App.toast(successMessage, "success");
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  function openReview(data) {
    document.getElementById("reviewId").value = data ? data.id : "";
    document.getElementById("reviewAuthor").value = data ? data.author_name : "";
    document.getElementById("reviewRating").value = data ? data.rating : 5;
    document.getElementById("reviewService").value = data ? data.service_title : "";
    document.getElementById("reviewText").value = data ? data.text : "";
    document.getElementById("reviewPublished").checked = data ? data.is_published : true;
    App.Modal.open("reviewModal");
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Услуги
    document.querySelectorAll(".js-restore-service").forEach((button) => {
      button.addEventListener("click", () =>
        call(`/api/admin/services/${button.dataset.id}/restore`, { method: "POST" }, "Услуга возвращена на сайт")
      );
    });
    document.querySelectorAll(".js-hard-delete-service").forEach((button) => {
      button.addEventListener("click", () => {
        if (!App.confirmAction(`Удалить услугу «${button.dataset.title}» безвозвратно?`)) return;
        call(`/api/admin/services/${button.dataset.id}/hard`, { method: "DELETE" }, "Услуга удалена навсегда");
      });
    });

    // Мастера
    document.querySelectorAll(".js-restore-master").forEach((button) => {
      button.addEventListener("click", () =>
        call(`/api/admin/masters/${button.dataset.id}/restore`, { method: "POST" }, "Мастер возвращён на сайт")
      );
    });
    document.querySelectorAll(".js-hard-delete-master").forEach((button) => {
      button.addEventListener("click", () => {
        const warning =
          `Удалить мастера «${button.dataset.name}» безвозвратно?\n` +
          "Записи будут переведены на системного мастера «Уволенный сотрудник».";
        if (!App.confirmAction(warning)) return;
        call(`/api/admin/masters/${button.dataset.id}/hard`, { method: "DELETE" }, "Мастер удалён навсегда");
      });
    });

    // Отзывы
    document.getElementById("addReview").addEventListener("click", () => openReview(null));
    document.querySelectorAll(".js-edit-review").forEach((button) => {
      button.addEventListener("click", () => openReview(JSON.parse(button.closest("article").dataset.review)));
    });
    document.querySelectorAll(".js-toggle-review").forEach((button) => {
      button.addEventListener("click", () => {
        const article = button.closest("article");
        const data = JSON.parse(article.dataset.review);
        data.is_published = button.dataset.published !== "1";
        call(
          `/api/admin/reviews/${data.id}`,
          { method: "PATCH", body: data },
          data.is_published ? "Отзыв опубликован" : "Отзыв снят с публикации"
        );
      });
    });
    document.querySelectorAll(".js-delete-review").forEach((button) => {
      button.addEventListener("click", () => {
        if (!App.confirmAction("Удалить отзыв?")) return;
        call(`/api/admin/reviews/${button.dataset.id}`, { method: "DELETE" }, "Отзыв удалён");
      });
    });

    document.getElementById("reviewForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const id = document.getElementById("reviewId").value;
      const payload = {
        author_name: document.getElementById("reviewAuthor").value.trim(),
        rating: Number(document.getElementById("reviewRating").value),
        service_title: document.getElementById("reviewService").value.trim(),
        text: document.getElementById("reviewText").value.trim(),
        is_published: document.getElementById("reviewPublished").checked,
      };
      await call(
        id ? `/api/admin/reviews/${id}` : "/api/admin/reviews",
        { method: id ? "PATCH" : "POST", body: payload },
        "Отзыв сохранён"
      );
    });
  });
})();
