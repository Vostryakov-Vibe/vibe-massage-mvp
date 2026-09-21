"""
Скачивание ВСЕХ внешних ассетов в локальные папки проекта.

Зачем: приложение должно работать полностью офлайн (без интернета).
Этот скрипт выполняется ОДИН РАЗ на машине с интернетом, после чего
проект самодостаточен. Запуск повторно безопасен: файлы просто обновятся.

Использование:
    python scripts/fetch_assets.py
"""

from __future__ import annotations

import os
import re
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(BASE_DIR, "static", "vendor")
FONT_DIR = os.path.join(BASE_DIR, "static", "fonts")

# UA «настоящего» браузера нужен, чтобы Google Fonts отдал woff2, а не ttf.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

VENDOR_FILES = {
    # Tailwind CSS — браузерная (Play CDN) сборка: компилирует утилиты на лету.
    "tailwind.js": "https://cdn.tailwindcss.com/3.4.16",
    # Chart.js — графики аналитического дашборда.
    "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js",
    # Sortable.js — drag&drop Канбан-доски CRM.
    "sortable.min.js": "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js",
}

# Шрифты: заголовки — элегантная антиква, текст — современный гротеск.
# Берём только latin + cyrillic, чтобы не тащить лишние подмножества.
FONT_URLS = {
    "Manrope": "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap",
    "Cormorant+Garamond": (
        "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&display=swap"
    ),
}

WANTED_SUBSETS = ("cyrillic", "latin")


def _download(url: str, destination: str) -> int:
    """Скачивает url в destination. Возвращает размер файла в байтах."""
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as handle:
        handle.write(payload)
    return len(payload)


def fetch_vendor() -> None:
    """Скачивает JS-библиотеки в /static/vendor."""
    for filename, url in VENDOR_FILES.items():
        target = os.path.join(VENDOR_DIR, filename)
        try:
            size = _download(url, target)
        except Exception as error:  # noqa: BLE001 - скрипт утилитарный
            print(f"  [!] {filename}: ошибка загрузки — {error}", file=sys.stderr)
            continue
        print(f"  [ok] {filename} — {size / 1024:.1f} КБ")


def fetch_fonts() -> None:
    """Скачивает woff2-файлы шрифтов и генерирует локальный fonts.css.

    Google Fonts отдаёт CSS с блоками @font-face, каждый со своим
    unicode-range. Мы сохраняем только cyrillic/latin, переписывая
    url(...) на локальные пути.
    """
    css_chunks: list[str] = []
    for family, css_url in FONT_URLS.items():
        try:
            request = urllib.request.Request(css_url, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(request, timeout=60) as response:
                css = response.read().decode("utf-8")
        except Exception as error:  # noqa: BLE001
            print(f"  [!] {family}: не удалось получить CSS — {error}", file=sys.stderr)
            continue

        # Разбираем CSS на блоки @font-face с комментарием-подписью подмножества.
        blocks = re.findall(r"/\*\s*([\w\-\[\]]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", css)
        kept = 0
        for subset, block in blocks:
            if not any(subset.startswith(wanted) for wanted in WANTED_SUBSETS):
                continue
            match = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if not match:
                continue
            source_url = match.group(1)
            filename = f"{family.replace('+', '')}-{subset}-{os.path.basename(source_url)}"
            try:
                _download(source_url, os.path.join(FONT_DIR, filename))
            except Exception as error:  # noqa: BLE001
                print(f"  [!] {filename}: {error}", file=sys.stderr)
                continue
            block = block.replace(source_url, f"/static/fonts/{filename}")
            css_chunks.append(block)
            kept += 1
        print(f"  [ok] {family}: {kept} файлов шрифта")

    if css_chunks:
        header = "/* Сгенерировано scripts/fetch_assets.py — локальные шрифты, офлайн. */\n"
        target = os.path.join(BASE_DIR, "static", "css", "fonts.css")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(header + "\n".join(css_chunks) + "\n")
        print(f"  [ok] static/css/fonts.css — {len(css_chunks)} @font-face")


def main() -> None:
    print("Скачивание JS-библиотек…")
    fetch_vendor()
    print("Скачивание шрифтов…")
    fetch_fonts()
    print("Готово. Проект можно запускать без интернета.")


if __name__ == "__main__":
    main()
