/* =========================================================================
   Маркетинг: генерация постов, публикация в Telegram/ВК, архив.
   ========================================================================= */

(function () {
  "use strict";

  const App = window.SalonApp;
  const state = { currentPostId: null };

  function setPreview(post) {
    state.currentPostId = post ? post.id : null;
    document.getElementById("postPreview").value = post ? post.content : "";
    const badge = document.getElementById("postSource");
    if (post) {
      badge.classList.remove("hidden");
      badge.textContent =
        post.source === "ai" ? "Сгенерировано ИИ-API" : "Офлайн-шаблон (fallback)";
    } else {
      badge.classList.add("hidden");
    }
    document.getElementById("publishTelegram").disabled = !post;
    document.getElementById("publishVk").disabled = !post;
  }

  /** Генерация поста. */
  async function generate(event) {
    event.preventDefault();
    const payload = {
      topic: document.getElementById("postTopic").value.trim(),
      tone: document.getElementById("postTone").value,
      length: document.getElementById("postLength").value,
      keywords: document.getElementById("postKeywords").value.trim(),
      send_telegram: document.getElementById("sendTelegram").checked,
      send_vk: document.getElementById("sendVk").checked,
    };
    if (!payload.topic) return App.toast("Укажите тему поста", "warning");

    try {
      await App.withLoading(document.getElementById("generatePost"), async () => {
        const data = await App.api("/api/admin/marketing/generate", { method: "POST", body: payload });
        setPreview(data.post);
        App.toast(
          data.post.source === "ai"
            ? "Пост сгенерирован через ИИ-API"
            : "ИИ-API недоступно — использован офлайн-шаблон",
          "success",
          5000
        );
        reportPublish(data.publish);
        setTimeout(() => window.location.reload(), 2500);
      });
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  /** Показывает результат публикации. */
  function reportPublish(publish) {
    const log = document.getElementById("publishLog");
    if (!publish || !Object.keys(publish).length) {
      log.textContent = "";
      return;
    }
    const parts = Object.entries(publish).map(([network, result]) => {
      const name = network === "telegram" ? "Telegram" : "ВК";
      return `${name}: ${result.detail}`;
    });
    log.textContent = parts.join(" · ");
    Object.values(publish).forEach((result) => {
      App.toast(result.detail, result.ok ? "success" : "warning", 6000);
    });
  }

  /** Публикация текущего поста. */
  async function publish(network) {
    if (!state.currentPostId) return;
    try {
      const data = await App.api("/api/admin/marketing/publish", {
        method: "POST",
        body: {
          post_id: state.currentPostId,
          send_telegram: network === "telegram",
          send_vk: network === "vk",
        },
      });
      reportPublish(data.publish);
    } catch (error) {
      App.toast(error.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("marketingForm").addEventListener("submit", generate);
    document.getElementById("copyPost").addEventListener("click", async () => {
      const text = document.getElementById("postPreview").value;
      if (!text) return App.toast("Сначала сгенерируйте пост", "warning");
      try {
        await navigator.clipboard.writeText(text);
        App.toast("Текст скопирован в буфер обмена", "success");
      } catch (error) {
        document.getElementById("postPreview").select();
        App.toast("Скопируйте текст вручную (Ctrl+C)", "info");
      }
    });
    document.getElementById("publishTelegram").addEventListener("click", () => publish("telegram"));
    document.getElementById("publishVk").addEventListener("click", () => publish("vk"));

    document.getElementById("cleanupPosts").addEventListener("click", async () => {
      if (!App.confirmAction("Удалить из архива все посты старше срока хранения?")) return;
      try {
        const data = await App.api("/api/admin/marketing/cleanup", { method: "POST" });
        App.toast(`Удалено записей: ${data.removed}`, "success");
        setTimeout(() => window.location.reload(), 700);
      } catch (error) {
        App.toast(error.message, "error");
      }
    });

    document.querySelectorAll(".js-load-post").forEach((button) => {
      button.addEventListener("click", () => {
        const data = JSON.parse(button.closest("tr").dataset.post);
        setPreview({ id: data.id, content: data.content, source: "template" });
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    });
  });
})();
