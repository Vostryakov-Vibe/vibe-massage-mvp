"""Генерация локальных изображений-заглушек (SVG).

Проект обязан работать без интернета, поэтому фотографии услуг и мастеров
не скачиваются, а генерируются: премиальные градиенты в фирменных цветах
(изумруд + золото) с абстрактными «массажными» мотивами.

Текст в картинки НЕ впечатывается: названия услуг, цены и специализация
мастеров выводятся подписями в HTML. Иначе при обрезке (object-cover в
карточках и в hero-блоке) надписи наезжали на текст интерфейса и резались
по краям.

Если владелец салона положит в static/uploads свои файлы с теми же именами
(или загрузит их через админку), они будут использоваться вместо заглушек:
свои файлы мы не перезаписываем, а только обновляем собственные заглушки.
"""

from __future__ import annotations

import os

import config

EMERALD_DARK = "#022C26"
EMERALD = "#044A42"
EMERALD_LIGHT = "#0B6B5F"
GOLD = "#D4AF37"
GOLD_LIGHT = "#E5C158"

SERVICE_SIZE = (960, 640)
AVATAR_SIZE = (480, 480)

# По этим признакам отличаем свою заглушку от картинки владельца салона.
# Первый маркер ставят новые версии генератора, два других остались в файлах,
# созданных прежними версиями (там были градиенты с такими id).
GENERATED_MARKS = ("<!-- placeholder: assets.py -->", "url(#bg)", "url(#av)")


def _scale_points(points: list[tuple[float, float]], width: int, height: int) -> str:
    """Нормированные координаты (0..1) → строка атрибутов SVG path."""
    return " ".join(f"{x * width:.1f},{y * height:.1f}" for x, y in points)


def _motif_waves(width: int, height: int) -> str:
    """Плавные волны — течение, расслабление."""
    paths = []
    for index in range(5):
        offset = 0.12 * index
        points = [(x / 10, 0.45 + offset + 0.06 * ((x % 3) - 1)) for x in range(0, 11)]
        paths.append(
            f'<polyline points="{_scale_points(points, width, height)}" fill="none" '
            f'stroke="{GOLD}" stroke-width="{2.2 - index * 0.25:.2f}" stroke-opacity="{0.55 - index * 0.08:.2f}" '
            f'stroke-linecap="round"/>'
        )
    return "".join(paths)


def _motif_lotus(width: int, height: int) -> str:
    """Лотос — баланс и оздоровление."""
    cx, cy = width * 0.5, height * 0.52
    petals = []
    for index in range(7):
        angle = -75 + index * 25
        petals.append(
            f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{width * 0.055:.0f}" ry="{height * 0.20:.0f}" '
            f'fill="none" stroke="{GOLD}" stroke-opacity="0.5" stroke-width="2" '
            f'transform="rotate({angle} {cx:.0f} {cy:.0f})"/>'
        )
    return "".join(petals)


def _motif_spine(width: int, height: int) -> str:
    """Линия позвоночника с точками-позвонками."""
    parts = []
    cx = width * 0.5
    for index in range(12):
        y = height * (0.16 + index * 0.06)
        radius = 5 + abs(6 - index) * 0.9
        parts.append(
            f'<circle cx="{cx + (index % 2) * 12:.0f}" cy="{y:.0f}" r="{radius:.1f}" '
            f'fill="{GOLD}" fill-opacity="0.55"/>'
        )
    parts.append(
        f'<path d="M {cx:.0f} {height * 0.12:.0f} Q {cx + 60:.0f} {height * 0.5:.0f} {cx:.0f} {height * 0.90:.0f}" '
        f'fill="none" stroke="{GOLD_LIGHT}" stroke-opacity="0.35" stroke-width="3"/>'
    )
    return "".join(parts)


def _motif_hands(width: int, height: int) -> str:
    """Две дуги-ладони вокруг центра."""
    cx, cy = width * 0.5, height * 0.5
    return (
        f'<path d="M {cx - width * 0.22:.0f} {cy + height * 0.18:.0f} '
        f'A {width * 0.20:.0f} {height * 0.24:.0f} 0 0 1 {cx + width * 0.02:.0f} {cy - height * 0.22:.0f}" '
        f'fill="none" stroke="{GOLD}" stroke-opacity="0.55" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M {cx + width * 0.22:.0f} {cy + height * 0.18:.0f} '
        f'A {width * 0.20:.0f} {height * 0.24:.0f} 0 0 0 {cx - width * 0.02:.0f} {cy - height * 0.22:.0f}" '
        f'fill="none" stroke="{GOLD}" stroke-opacity="0.55" stroke-width="4" stroke-linecap="round"/>'
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{height * 0.045:.0f}" fill="{GOLD}" fill-opacity="0.7"/>'
    )


def _motif_face(width: int, height: int) -> str:
    """Профиль лица — массаж лица."""
    cx, cy = width * 0.5, height * 0.5
    return (
        f'<path d="M {cx + width * 0.06:.0f} {cy - height * 0.26:.0f} '
        f'C {cx + width * 0.20:.0f} {cy - height * 0.10:.0f}, {cx + width * 0.20:.0f} {cy + height * 0.10:.0f}, '
        f'{cx + width * 0.02:.0f} {cy + height * 0.22:.0f}" '
        f'fill="none" stroke="{GOLD}" stroke-opacity="0.6" stroke-width="4" stroke-linecap="round"/>'
        f'<path d="M {cx - width * 0.10:.0f} {cy - height * 0.20:.0f} '
        f'C {cx - width * 0.22:.0f} {cy - height * 0.02:.0f}, {cx - width * 0.20:.0f} {cy + height * 0.16:.0f}, '
        f'{cx - width * 0.02:.0f} {cy + height * 0.22:.0f}" '
        f'fill="none" stroke="{GOLD_LIGHT}" stroke-opacity="0.4" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="{cx + width * 0.07:.0f}" cy="{cy - height * 0.06:.0f}" r="6" fill="{GOLD}"/>'
    )


def _motif_drops(width: int, height: int) -> str:
    """Капли — детокс и лимфодренаж."""
    parts = []
    positions = [(0.30, 0.35), (0.50, 0.26), (0.68, 0.40), (0.40, 0.56), (0.60, 0.62)]
    for index, (x, y) in enumerate(positions):
        radius = 10 + index * 4
        parts.append(
            f'<circle cx="{x * width:.0f}" cy="{y * height:.0f}" r="{radius}" '
            f'fill="{GOLD}" fill-opacity="{0.55 - index * 0.06:.2f}"/>'
        )
    return "".join(parts)


MOTIFS = {
    "waves": _motif_waves,
    "lotus": _motif_lotus,
    "spine": _motif_spine,
    "hands": _motif_hands,
    "face": _motif_face,
    "drops": _motif_drops,
}


def build_service_svg(title: str, motif: str = "waves") -> str:
    """SVG-обложка услуги: градиент и мотив, без подписей.

    ``title`` попадает только в aria-label — он нужен скринридерам и поиску,
    а видимая подпись выводится в HTML поверх или рядом с картинкой.
    """
    width, height = SERVICE_SIZE
    draw = MOTIFS.get(motif, _motif_waves)
    safe_title = _escape(title)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{safe_title}">
  <!-- placeholder: assets.py -->
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{EMERALD_LIGHT}"/>
      <stop offset="55%" stop-color="{EMERALD}"/>
      <stop offset="100%" stop-color="{EMERALD_DARK}"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="35%" r="70%">
      <stop offset="0%" stop-color="{GOLD}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="{GOLD}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <rect width="{width}" height="{height}" fill="url(#glow)"/>
  <circle cx="{width * 0.86:.0f}" cy="{height * 0.18:.0f}" r="{height * 0.22:.0f}" fill="{GOLD}" fill-opacity="0.10"/>
  {draw(width, height)}
</svg>
"""


def build_avatar_svg(full_name: str) -> str:
    """SVG-аватар мастера: инициалы на изумрудном градиенте, без подписей.

    Специализация в картинку не вписывается: в круглом аватаре её края
    обрезались, а в интерфейсе она выводится отдельной строкой.
    """
    width, height = AVATAR_SIZE
    initials = "".join(part[0] for part in full_name.split()[:2]).upper() or "М"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(full_name)}">
  <!-- placeholder: assets.py -->
  <defs>
    <linearGradient id="av" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{EMERALD_LIGHT}"/>
      <stop offset="100%" stop-color="{EMERALD_DARK}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#av)"/>
  <circle cx="{width / 2:.0f}" cy="{height * 0.44:.0f}" r="{height * 0.30:.0f}" fill="none" stroke="{GOLD}" stroke-opacity="0.55" stroke-width="5"/>
  <text x="50%" y="{height * 0.44 + 44:.0f}" text-anchor="middle" font-family="Georgia, serif" font-size="132" fill="{GOLD_LIGHT}">{initials}</text>
</svg>
"""


def _escape(value: str) -> str:
    """Экранирование XML-спецсимволов."""
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_upload(filename: str, content: str) -> str:
    """Сохраняет SVG-заглушку в static/uploads.

    Чужой файл с таким же именем (картинка владельца салона) не трогаем,
    а свою устаревшую заглушку перезаписываем — иначе правки генератора
    не доходили бы до уже запущенных установок.
    """
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = os.path.join(config.UPLOAD_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                existing = handle.read()
        except (OSError, UnicodeDecodeError):
            return filename  # не наш текстовый SVG — считаем чужим
        if existing == content or not any(mark in existing for mark in GENERATED_MARKS):
            return filename
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return filename


def generate_service_image(slug: str, title: str, motif: str) -> str:
    """Создаёт обложку услуги, возвращает имя файла."""
    return write_upload(f"service-{slug}.svg", build_service_svg(title, motif))


def generate_master_avatar(slug: str, full_name: str) -> str:
    """Создаёт аватар мастера, возвращает имя файла."""
    return write_upload(f"master-{slug}.svg", build_avatar_svg(full_name))
