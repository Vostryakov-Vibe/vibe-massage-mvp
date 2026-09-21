/* =========================================================================
   Общие помощники фронтенда: тосты, запросы к API, появление блоков,
   звуковое уведомление (синтез через Web Audio — файлы не нужны, офлайн).
   ========================================================================= */

(function () {
  "use strict";

  const SalonApp = {};

  /** Токен CSRF из meta-тега админки (на лендинге отсутствует). */
  SalonApp.csrfToken = function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  };

  /** Всплывающее уведомление. type: success | error | info | warning */
  SalonApp.toast = function (message, type = "info", timeout = 4200) {
    const stack = document.getElementById("toastStack");
    if (!stack) {
      console.log("[toast]", message);
      return;
    }
    const palette = {
      success: "bg-emerald-600 text-white",
      error: "bg-rose-600 text-white",
      warning: "bg-gold-500 text-brand-900",
      info: "bg-brand-700 text-white",
    };
    const node = document.createElement("div");
    node.className =
      "toast rounded-2xl px-4 py-3 text-sm shadow-lg " + (palette[type] || palette.info);
    node.textContent = message;
    stack.appendChild(node);
    setTimeout(() => {
      node.style.transition = "opacity .3s ease, transform .3s ease";
      node.style.opacity = "0";
      node.style.transform = "translateX(20px)";
      setTimeout(() => node.remove(), 320);
    }, timeout);
  };

  /** Запрос к API. Автоматически добавляет CSRF для изменяющих методов. */
  SalonApp.api = async function (url, options = {}) {
    const config = Object.assign({ headers: {} }, options);
    config.headers = Object.assign({}, options.headers);
    if (config.body && typeof config.body !== "string") {
      config.headers["Content-Type"] = "application/json";
      config.body = JSON.stringify(config.body);
    }
    const method = (config.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      config.headers["X-CSRF-Token"] = SalonApp.csrfToken();
    }

    const response = await fetch(url, config);
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json().catch(() => null);
    }
    if (!response.ok) {
      const detail = (payload && (payload.detail || payload.message)) || `Ошибка ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  };

  /** Плавное появление блоков с классом .reveal при скролле. */
  SalonApp.initReveal = function (root = document) {
    const items = root.querySelectorAll(".reveal:not(.is-visible)");
    if (!items.length) return;
    if (!("IntersectionObserver" in window)) {
      items.forEach((item) => item.classList.add("is-visible"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" }
    );
    items.forEach((item) => observer.observe(item));
  };

  /** Короткий звуковой сигнал для новой записи (Web Audio, без файлов). */
  SalonApp.playNotificationSound = function () {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const now = ctx.currentTime;
      [880, 1180].forEach((frequency, index) => {
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        oscillator.type = "sine";
        oscillator.frequency.value = frequency;
        gain.gain.setValueAtTime(0.0001, now + index * 0.18);
        gain.gain.exponentialRampToValueAtTime(0.22, now + index * 0.18 + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + index * 0.18 + 0.3);
        oscillator.connect(gain).connect(ctx.destination);
        oscillator.start(now + index * 0.18);
        oscillator.stop(now + index * 0.18 + 0.32);
      });
      setTimeout(() => ctx.close(), 1200);
    } catch (error) {
      console.warn("Звук недоступен:", error);
    }
  };

  /** Форматирование суммы в рублях. */
  SalonApp.money = function (value) {
    return new Intl.NumberFormat("ru-RU").format(Math.round(value || 0)) + " ₽";
  };

  /** Дата в формате YYYY-MM-DD по локальному времени.

  toISOString() переводит в UTC, поэтому поздним вечером и ночью он отдаёт
  соседний день — а сервер сверяет дату визита со своей локальной датой.
  */
  SalonApp.localIsoDate = function (value) {
    const date = value instanceof Date ? value : new Date();
    const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return shifted.toISOString().slice(0, 10);
  };

  /** Экранирование HTML при вставке пользовательских данных. */
  SalonApp.escape = function (value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  };

  /** Блокировка кнопки на время запроса. */
  SalonApp.withLoading = async function (button, task) {
    if (!button) return task();
    const original = button.innerHTML;
    button.disabled = true;
    button.classList.add("opacity-70", "cursor-wait");
    button.innerHTML = '<span class="inline-block animate-spin">◌</span> Подождите…';
    try {
      return await task();
    } finally {
      button.disabled = false;
      button.classList.remove("opacity-70", "cursor-wait");
      button.innerHTML = original;
    }
  };

  document.addEventListener("DOMContentLoaded", () => SalonApp.initReveal());

  window.SalonApp = SalonApp;
})();
