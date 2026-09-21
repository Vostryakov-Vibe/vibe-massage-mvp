"""Инициализация и наполнение базы данных.

Функция :func:`initialize_database` вызывается при старте приложения:
* создаёт учётные записи по умолчанию (пароли — только в виде bcrypt-хэшей);
* создаёт системного мастера «Уволенный сотрудник»;
* генерирует SVG-заглушки изображений в static/uploads;
* при пустой базе заливает реалистичные демо-данные за последние 30 дней
  (услуги, мастера, графики смен, клиенты, записи, отзывы);
* чистит архив постов старше POSTS_RETENTION_DAYS.

Повторный запуск безопасен: данные не дублируются.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import assets
import config
from models import Booking, Client, Master, Post, Review, Schedule, Service, User
from security import hash_password
from utils import slugify

logger = logging.getLogger("salon.seed")

SYSTEM_MASTER_NAME = "Уволенный сотрудник"

# --- Справочник услуг ------------------------------------------------------

SERVICES = [
    {
        "title": "Классический общий массаж",
        "slug": "classic",
        "category": "Классический массаж",
        "short_description": "Базовая программа для всего тела: снимает напряжение, возвращает лёгкость и глубокий сон.",
        "full_description": (
            "Классический общий массаж — фундамент оздоровительных программ салона. "
            "Мастер последовательно прорабатывает спину, шею, руки, ноги и живот, "
            "подбирая интенсивность под ваше состояние. Сеанс улучшает кровообращение, "
            "снимает мышечные зажимы и помогает восстановиться после рабочей недели."
        ),
        "duration_minutes": 60,
        "price": 3000,
        "indications": "Хроническая усталость, сидячая работа, нарушение сна, мышечное напряжение, восстановление после нагрузок.",
        "contraindications": "Острые воспалительные процессы, высокая температура, онкологические заболевания, тромбоз, кожные инфекции.",
        "motif": "waves",
        "sort_order": 10,
    },
    {
        "title": "Массаж спины и шейно-воротниковой зоны",
        "slug": "back-neck",
        "category": "Лечебный массаж",
        "short_description": "Прицельная работа с самой нагруженной зоной: шея, плечи, лопатки и верх спины.",
        "full_description": (
            "Программа создана для тех, кто много работает за компьютером. Мастер снимает "
            "гипертонус трапециевидных и ромбовидных мышц, прорабатывает воротниковую зону, "
            "улучшает подвижность шейного отдела. Уже после первого сеанса уменьшается "
            "тяжесть в плечах и головная боль напряжения."
        ),
        "duration_minutes": 45,
        "price": 2500,
        "indications": "Боль и скованность в шее, «зажатые» плечи, головные боли напряжения, остеохондроз в стадии ремиссии.",
        "contraindications": "Острые боли неясного происхождения, травмы позвоночника, гипертонический криз, грыжи в стадии обострения.",
        "motif": "spine",
        "sort_order": 20,
    },
    {
        "title": "Спортивный массаж",
        "slug": "sport",
        "category": "Спортивный массаж",
        "short_description": "Восстановление после тренировок, профилактика травм и быстрый возврат в форму.",
        "full_description": (
            "Спортивный массаж сочетает глубокие разминочные и восстановительные техники. "
            "Подходит как перед соревнованием, так и в период интенсивных нагрузок: "
            "ускоряет выведение продуктов распада, снижает крепатуру, возвращает мышцам "
            "эластичность. Интенсивность подбирается индивидуально."
        ),
        "duration_minutes": 75,
        "price": 3800,
        "indications": "Интенсивные тренировки, крепатура, подготовка к стартам, восстановление после растяжений (вне острой фазы).",
        "contraindications": "Свежие травмы и гематомы, острые воспаления, повышенная температура, варикозное расширение вен в зоне воздействия.",
        "motif": "hands",
        "sort_order": 30,
    },
    {
        "title": "Лимфодренажный массаж",
        "slug": "lymph",
        "category": "Детокс и лимфодренаж",
        "short_description": "Мягкая техника против отёчности и тяжести в ногах, заметный результат с первого сеанса.",
        "full_description": (
            "Лимфодренажный массаж выполняется в спокойном темпе по направлению тока лимфы. "
            "Он снимает отёчность, убирает тяжесть в ногах, улучшает тонус кожи и помогает "
            "организму быстрее выводить лишнюю жидкость. Курс из 8–10 сеансов даёт стойкий "
            "визуальный и оздоровительный эффект."
        ),
        "duration_minutes": 60,
        "price": 3400,
        "indications": "Отёчность, тяжесть в ногах, малоподвижный образ жизни, восстановление после перелётов, целлюлит.",
        "contraindications": "Острые тромбозы, сердечная и почечная недостаточность в стадии декомпенсации, лимфаденит, беременность без разрешения врача.",
        "motif": "drops",
        "sort_order": 40,
    },
    {
        "title": "Массаж лица",
        "slug": "face",
        "category": "Эстетический массаж",
        "short_description": "Скульптурная техника: свежий цвет лица, чёткий овал и снятие мимического напряжения.",
        "full_description": (
            "Массаж лица сочетает классические и лимфодренажные приёмы. Работа с мимическими "
            "мышцами снимает напряжение, улучшает микроциркуляцию и придаёт коже отдохнувший вид. "
            "Регулярный курс помогает сохранить чёткость овала лица и уменьшить отёчность "
            "в области глаз."
        ),
        "duration_minutes": 40,
        "price": 2200,
        "indications": "Отёчность лица, усталый вид кожи, мимические морщины, напряжение после рабочего дня.",
        "contraindications": "Гнойничковые заболевания кожи, герпес в активной фазе, свежие инъекции и пилинги, повышенная температура.",
        "motif": "face",
        "sort_order": 50,
    },
]

# --- Справочник мастеров ---------------------------------------------------

MASTERS = [
    {
        "full_name": "Ирина Соколова",
        "specialization": "Лечебный и классический массаж",
        "experience_years": 12,
        "bio": (
            "Сертифицированный массажист с медицинским образованием. Специализируется на работе "
            "с шейно-воротниковой зоной и восстановлении после длительной сидячей работы."
        ),
        "services": ["classic", "back-neck", "lymph"],
        # Пн-Пт 09:00–18:00, Сб 10:00–15:00
        "shifts": {0: ("09:00", "18:00"), 1: ("09:00", "18:00"), 2: ("09:00", "18:00"),
                   3: ("09:00", "18:00"), 4: ("09:00", "18:00"), 5: ("10:00", "15:00")},
    },
    {
        "full_name": "Дмитрий Ковалёв",
        "specialization": "Спортивный массаж и восстановление",
        "experience_years": 9,
        "bio": (
            "Работал с любительскими и профессиональными командами. Знает, как быстро вернуть "
            "мышцы в рабочее состояние и предотвратить типичные травмы."
        ),
        "services": ["sport", "classic", "back-neck"],
        # Пн, Ср, Пт 12:00–21:00; Вт, Чт 14:00–21:00
        "shifts": {0: ("12:00", "21:00"), 1: ("14:00", "21:00"), 2: ("12:00", "21:00"),
                   3: ("14:00", "21:00"), 4: ("12:00", "21:00")},
    },
    {
        "full_name": "Анна Верещагина",
        "specialization": "Лимфодренаж и детокс-программы",
        "experience_years": 7,
        "bio": (
            "Специалист по мягким лимфодренажным техникам. Помогает убрать отёчность и вернуть "
            "лёгкость в теле без агрессивного воздействия на ткани."
        ),
        "services": ["lymph", "classic", "face"],
        # Вт-Сб 10:00–19:00
        "shifts": {1: ("10:00", "19:00"), 2: ("10:00", "19:00"), 3: ("10:00", "19:00"),
                   4: ("10:00", "19:00"), 5: ("10:00", "19:00")},
    },
    {
        "full_name": "Мария Лебедева",
        "specialization": "Массаж лица и релакс-программы",
        "experience_years": 5,
        "bio": (
            "Эстетист и массажист. Сочетает скульптурный массаж лица с мягкими релакс-техниками, "
            "уделяя особое внимание комфорту гостя."
        ),
        "services": ["face", "classic", "lymph"],
        # Пн, Ср, Пт, Сб 11:00–20:00
        "shifts": {0: ("11:00", "20:00"), 2: ("11:00", "20:00"), 4: ("11:00", "20:00"),
                   5: ("11:00", "20:00")},
    },
]

# --- Клиенты ---------------------------------------------------------------

CLIENTS = [
    ("Екатерина Морозова", "+79161234501", "@kate_morozova", 5, "Постоянная гостья, предпочитает утренние слоты. Аллергия на эфирное масло лаванды."),
    ("Алексей Громов", "+79161234502", "@gromov_alex", 5, "Спортсмен-любитель, ходит на спортивный массаж перед забегами."),
    ("Ольга Савельева", "+79161234503", "@olga_sav", 4, "Просит среднюю интенсивность, комфортно при 24 °C в кабинете."),
    ("Сергей Никитин", "+79161234504", "", 3, "Работает за компьютером по 10 часов, жалуется на шею. Нужен контроль осанки."),
    ("Наталья Ким", "+79161234505", "@natalia_kim", 5, "Курс лимфодренажа, 10 сеансов. Оплачивает пакетом."),
    ("Павел Дорохов", "+79161234506", "@pavel_d", 4, "Чувствительная кожа — только гипоаллергенные масла."),
    ("Марина Ильина", "+79161234507", "@marina_il", 5, "Записывается вместе с мужем, часто на соседние слоты."),
    ("Артём Белов", "+79161234508", "", 2, "Дважды не пришёл без предупреждения — предупреждать о предоплате."),
    ("Юлия Романова", "+79161234509", "@yulia_rom", 5, "Любит релакс-программы, приходит по субботам."),
    ("Игорь Тимофеев", "+79161234510", "@igor_tim", 4, "Восстановление после перелома руки, нужна щадящая техника."),
    ("Светлана Гущина", "+79161234511", "@sveta_g", 5, "Массаж лица курсом, интересуется уходом."),
    ("Роман Ефимов", "+79161234512", "", 3, "Новый клиент, пришёл по рекомендации Ольги С."),
]

REVIEWS = [
    ("Екатерина М.", 5, "Хожу к Ирине уже полгода. Шея перестала «заклинивать» к вечеру, сплю без боли. Отдельное спасибо за тишину в кабинете.", "Массаж спины и шейно-воротниковой зоны"),
    ("Алексей Г.", 5, "Дмитрий готовит меня к забегам: после сеанса ноги как новые, крепатура уходит за день. Профессионал.", "Спортивный массаж"),
    ("Наталья К.", 5, "Прошла курс лимфодренажа у Анны. Отёки ушли, обувь стала свободнее. Очень бережные руки.", "Лимфодренажный массаж"),
    ("Светлана Г.", 4, "Массаж лица — отдельное удовольствие. Овал подтянулся, вид отдохнувший. Хотелось бы сеанс подольше.", "Массаж лица"),
    ("Марина И.", 5, "Записываемся с мужем на соседнее время. Удобно, что администратор всё согласует в одном сообщении.", "Классический общий массаж"),
    ("Сергей Н.", 4, "Спина после месяца сеансов чувствует себя иначе. Единственное — хочется слотов попозже вечером.", "Классический общий массаж"),
]


# --- Вспомогательные функции ----------------------------------------------


def _parse_time(value: str) -> time:
    """«09:30» → time(9, 30)."""
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _shift_for_weekday(master_data: dict, weekday: int) -> tuple[time, time] | None:
    """Рабочая смена мастера в конкретный день недели (или None — выходной)."""
    raw = master_data["shifts"].get(weekday)
    if raw is None:
        return None
    return _parse_time(raw[0]), _parse_time(raw[1])


def ensure_users(db: Session) -> None:
    """Создаёт учётные записи по умолчанию, если их ещё нет."""
    defaults = [
        (config.DEFAULT_SUPERADMIN_LOGIN, config.DEFAULT_SUPERADMIN_PASSWORD,
         config.ROLE_SUPERADMIN, "Суперадминистратор"),
        (config.DEFAULT_MANAGER_LOGIN, config.DEFAULT_MANAGER_PASSWORD,
         config.ROLE_MANAGER, "Администратор ресепшена"),
    ]
    created = []
    for username, password, role, full_name in defaults:
        exists = db.scalar(select(User).where(User.username == username))
        if exists:
            continue
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                full_name=full_name,
            )
        )
        created.append(f"{username} / {password} ({role})")
    if created:
        db.commit()
        logger.info("Созданы учётные записи: %s", "; ".join(created))


def ensure_system_master(db: Session) -> Master:
    """Системный мастер, на которого перевешиваются записи при жёстком удалении."""
    master = db.scalar(select(Master).where(Master.is_system.is_(True)))
    if master:
        return master
    master = Master(
        full_name=SYSTEM_MASTER_NAME,
        specialization="Служебная запись архива",
        experience_years=0,
        bio="Техническая запись: на неё переносятся записи удалённых мастеров.",
        avatar_filename="",
        is_active=False,
        is_system=True,
    )
    db.add(master)
    db.commit()
    logger.info("Создан системный мастер «%s».", SYSTEM_MASTER_NAME)
    return master


def ensure_services(db: Session) -> None:
    """Загружает базовый каталог услуг и генерирует для них обложки.

    Обложка обновляется при каждом запуске: если генератор картинок изменился,
    заглушка перерисуется (файлы, положенные владельцем салона, не трогаем).
    """
    for payload in SERVICES:
        image = assets.generate_service_image(payload["slug"], payload["title"], payload["motif"])
        exists = db.scalar(select(Service).where(Service.slug == payload["slug"]))
        if exists:
            continue
        db.add(
            Service(
                title=payload["title"],
                slug=payload["slug"],
                short_description=payload["short_description"],
                full_description=payload["full_description"],
                duration_minutes=payload["duration_minutes"],
                price=payload["price"],
                image_filename=image,
                category=payload["category"],
                indications=payload["indications"],
                contraindications=payload["contraindications"],
                is_active=True,
                sort_order=payload["sort_order"],
            )
        )
    db.commit()


def ensure_masters(db: Session) -> None:
    """Загружает мастеров и генерирует их аватары (обновляются при запуске)."""
    for payload in MASTERS:
        avatar = assets.generate_master_avatar(slugify(payload["full_name"]), payload["full_name"])
        exists = db.scalar(select(Master).where(Master.full_name == payload["full_name"]))
        if exists:
            continue
        db.add(
            Master(
                full_name=payload["full_name"],
                specialization=payload["specialization"],
                experience_years=payload["experience_years"],
                bio=payload["bio"],
                avatar_filename=avatar,
                is_active=True,
            )
        )
    db.commit()


def ensure_schedules(db: Session, days_back: int = 30, days_ahead: int = 45) -> None:
    """Формирует графики смен вокруг текущей даты."""
    masters = db.scalars(select(Master).where(Master.is_system.is_(False))).all()
    by_name = {master.full_name: master for master in masters}
    today = date.today()
    created = 0

    for payload in MASTERS:
        master = by_name.get(payload["full_name"])
        if master is None:
            continue
        for offset in range(-days_back, days_ahead + 1):
            day = today + timedelta(days=offset)
            shift = _shift_for_weekday(payload, day.weekday())
            if shift is None:
                continue
            exists = db.scalar(
                select(Schedule).where(Schedule.master_id == master.id, Schedule.date == day)
            )
            if exists:
                continue
            db.add(Schedule(master_id=master.id, date=day, start_time=shift[0], end_time=shift[1]))
            created += 1

    if created:
        db.commit()
        logger.info("Создано смен в графике: %s", created)


def ensure_reviews(db: Session) -> None:
    """Добавляет отзывы для лендинга."""
    if db.scalar(select(func.count(Review.id))) or 0:
        return
    for index, (author, rating, text, service_title) in enumerate(REVIEWS):
        db.add(
            Review(
                author_name=author,
                rating=rating,
                text=text,
                service_title=service_title,
                is_published=True,
                created_at=datetime.now() - timedelta(days=index * 4 + 2),
            )
        )
    db.commit()


def _free_slot(
    occupied: set[tuple[int, date, int]],
    master_id: int,
    day: date,
    shift: tuple[time, time],
    duration: int,
    rng: random.Random,
    max_start_minutes: int | None = None,
) -> time | None:
    """Подбирает свободное время в смене мастера (сетка 30 минут)."""
    start_minutes = shift[0].hour * 60 + shift[0].minute
    end_minutes = shift[1].hour * 60 + shift[1].minute
    if max_start_minutes is not None:
        end_minutes = min(end_minutes, max_start_minutes + duration)
    candidates = list(range(start_minutes, end_minutes - duration + 1, config.SLOT_STEP_MINUTES))
    rng.shuffle(candidates)
    for start in candidates:
        slots = {(master_id, day, start + step) for step in range(0, duration, config.SLOT_STEP_MINUTES)}
        if slots & occupied:
            continue
        occupied |= slots
        return time(hour=start // 60, minute=start % 60)
    return None


def seed_demo_bookings(db: Session) -> None:
    """Создаёт демонстрационную историю записей за последние 30 дней.

    Состав: 15 выполненных в текущем месяце, 3 выполненных в прошлом месяце
    (для 30-дневного окна), 4 отменённых/не пришедших и 5 активных записей
    на ближайшие дни — итого 27 записей.
    """
    if db.scalar(select(func.count(Booking.id))) or 0:
        return

    rng = random.Random(20260921)
    services = {service.slug: service for service in db.scalars(select(Service)).all()}
    masters = [m for m in db.scalars(select(Master).where(Master.is_system.is_(False))).all()]
    master_data = {payload["full_name"]: payload for payload in MASTERS}

    clients: list[Client] = []
    for full_name, phone, contact, rating, notes in CLIENTS:
        client = db.scalar(select(Client).where(Client.phone == phone))
        if client is None:
            registered = datetime.now() - timedelta(days=rng.randint(35, 320))
            client = Client(
                full_name=full_name,
                phone=phone,
                telegram_vk_contact=contact,
                rating=rating,
                admin_notes=notes,
                consent_given=True,
                consent_date=registered,
                consent_ip=f"192.168.{rng.randint(1, 20)}.{rng.randint(2, 250)}",
                created_at=registered,
            )
            db.add(client)
        clients.append(client)
    db.commit()

    today = date.today()
    month_start = today.replace(day=1)
    now_minutes = datetime.now().hour * 60 + datetime.now().minute
    occupied: set[tuple[int, date, int]] = set()

    def make_booking(
        client: Client,
        service: Service,
        day: date,
        status: str,
        cost: int | None = None,
        comment: str = "",
        master: Master | None = None,
    ) -> bool:
        """Создаёт запись у любого свободного мастера, который работает в этот день.

        Мастер должен оказывать выбранную услугу (как в реальном салоне),
        поэтому кандидаты перебираются в случайном порядке.
        """
        candidates = [master] if master is not None else list(masters)
        rng.shuffle(candidates)

        for candidate in candidates:
            payload = master_data[candidate.full_name]
            if service.slug not in payload["services"]:
                continue
            shift = _shift_for_weekday(payload, day.weekday())
            if shift is None:
                continue
            limit = now_minutes - service.duration_minutes if day == today else None
            slot = _free_slot(
                occupied, candidate.id, day, shift, service.duration_minutes, rng,
                max_start_minutes=limit,
            )
            if slot is None:
                continue

            created_at = datetime.combine(day, slot) - timedelta(
                days=rng.randint(1, 6), hours=rng.randint(0, 5)
            )
            db.add(
                Booking(
                    client_id=client.id,
                    service_id=service.id,
                    master_id=candidate.id,
                    service_title=service.title,
                    master_name=candidate.full_name,
                    visit_date=day,
                    visit_time=slot,
                    status=status,
                    total_cost=service.price if cost is None else cost,
                    comment=comment,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            return True
        return False

    def make_booking_on_nearest_day(
        client: Client,
        service: Service,
        day: date,
        status: str,
        comment: str = "",
        max_shift: int = 3,
    ) -> bool:
        """Пробует поставить запись на дату или ближайший рабочий день рядом.

        Нужно, чтобы демо-набор всегда содержал нужное число записей
        (в салоне есть выходные, когда не работает ни один мастер).
        """
        for shift in range(max_shift + 1):
            for candidate_day in {day + timedelta(days=shift), day - timedelta(days=shift)}:
                if candidate_day < today - timedelta(days=30) or candidate_day > today + timedelta(days=30):
                    continue
                if make_booking(client, service, candidate_day, status, comment=comment):
                    return True
        return False

    # 1. Выполненные записи, равномерно по всем дням текущего месяца.
    completed_current = 0
    days_of_month = [month_start + timedelta(days=offset) for offset in range((today - month_start).days + 1)]
    for index, day in enumerate(days_of_month):
        if completed_current >= 15:
            break
        if index % 3 == 2 and index < len(days_of_month) - 3:
            continue  # пропускаем часть дней, чтобы не было «каждый день по записи»
        master = masters[index % len(masters)]
        service = services[rng.choice(master_data[master.full_name]["services"])]
        client = clients[(index * 3) % len(clients)]
        discount = rng.choice([0, 0, 0, 0, -300, -500, 200])
        if make_booking(client, service, day, config.STATUS_DONE, cost=service.price + discount):
            completed_current += 1

    # 2. Выполненные записи в прошлом месяце — хвост 30-дневного окна.
    for offset in range(4, 12):
        day = month_start - timedelta(days=offset)
        if day < today - timedelta(days=30):
            continue
        master = masters[offset % len(masters)]
        service = services[rng.choice(master_data[master.full_name]["services"])]
        make_booking(clients[(offset * 2) % len(clients)], service, day, config.STATUS_DONE)

    # 3. Отменённые и не пришедшие — «упущенная выгода».
    lost_plan = [
        (config.STATUS_CANCELLED, "Клиент перенёс визит на следующую неделю"),
        (config.STATUS_CANCELLED, "Не смог приехать из-за командировки"),
        (config.STATUS_NO_SHOW, "Не пришёл и не предупредил"),
        (config.STATUS_NO_SHOW, "Дважды переносил, в итоге не явился"),
    ]
    for index, (status, comment) in enumerate(lost_plan):
        day = today - timedelta(days=3 + index * 4)
        service = services[rng.choice(master_data[masters[index % len(masters)].full_name]["services"])]
        make_booking_on_nearest_day(clients[(index * 4 + 1) % len(clients)], service, day, status, comment=comment)

    # 4. Активные записи на ближайшие дни — для Канбан-доски.
    active_plan = [
        (config.STATUS_NEW, 0, "Запись с сайта, просит подтверждение в мессенджере"),
        (config.STATUS_NEW, 1, ""),
        (config.STATUS_INFORMING, 1, "Отправлена памятка о подготовке к сеансу"),
        (config.STATUS_ADJUSTMENT, 2, "Просит сдвинуть время на час позже"),
        (config.STATUS_CONFIRMED, 3, "Подтвердила по телефону"),
    ]
    for index, (status, day_offset, comment) in enumerate(active_plan):
        day = today + timedelta(days=day_offset)
        service = services[rng.choice(master_data[masters[(index + 1) % len(masters)].full_name]["services"])]
        make_booking_on_nearest_day(clients[(index * 5 + 2) % len(clients)], service, day, status, comment=comment)

    db.commit()
    total = db.scalar(select(func.count(Booking.id))) or 0
    logger.info(
        "Демо-данные загружены: %s записей (в текущем месяце выполнено — %s).",
        total,
        completed_current,
    )


def cleanup_old_posts(db: Session, retention_days: int | None = None) -> int:
    """Удаляет посты старше срока хранения. Возвращает число удалённых."""
    days = retention_days or config.POSTS_RETENTION_DAYS
    threshold = datetime.now() - timedelta(days=days)
    old_posts = db.scalars(select(Post).where(Post.created_at < threshold)).all()
    for post in old_posts:
        db.delete(post)
    if old_posts:
        db.commit()
        logger.info("Архив постов: удалено %s записей старше %s дней.", len(old_posts), days)
    return len(old_posts)


def initialize_database(db: Session) -> None:
    """Полная инициализация при старте приложения (идемпотентно)."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ensure_users(db)
    ensure_system_master(db)
    ensure_services(db)
    ensure_masters(db)
    ensure_schedules(db)
    ensure_reviews(db)
    seed_demo_bookings(db)
    cleanup_old_posts(db)
