import os
import logging
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int = 0) -> int:
    """Безопасно читает int из .env"""
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_int_list(raw: str) -> list[int]:
    """Парсит список ID из строки вида 1,2,3"""
    result: list[int] = []
    if not raw:
        return result

    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue

    return result


def _parse_prefixed_int_list(prefix: str) -> list[int]:
    """
    Читает переменные окружения вида PREFIX_01=123, PREFIX_02=456...
    Возвращает список ID, отсортированный по имени переменной.
    """
    pairs: list[tuple[str, int]] = []

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        try:
            pairs.append((key, int(str(value).strip())))
        except ValueError:
            continue

    pairs.sort(key=lambda x: x[0])
    return [value for _, value in pairs]


def _get_list_from_env(prefix: str, legacy_var: str) -> list[int]:
    """
    Сначала пробует новый формат PREFIX_01, PREFIX_02...
    Если не найдено — берёт старый CSV-формат из legacy_var.
    """
    prefixed = _parse_prefixed_int_list(prefix)
    if prefixed:
        return prefixed

    return _parse_int_list(os.getenv(legacy_var, ""))


def _parse_promotion_channels_legacy(raw: str) -> dict[int, int]:
    """
    Старый формат:
    PROMOTION_CHANNELS=channel_id:staff_role_id,channel_id:staff_role_id
    """
    result: dict[int, int] = {}
    if not raw:
        return result

    for part in str(raw).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue

        channel_id_str, role_id_str = part.split(":", 1)
        try:
            result[int(channel_id_str.strip())] = int(role_id_str.strip())
        except ValueError:
            continue

    return result


def _parse_prefixed_channel_role_map(prefix: str) -> dict[int, int]:
    """
    Новый формат:
    PROMOTION_CH_01=channel_id:role_id
    PROMOTION_CH_02=channel_id:role_id
    """
    result: dict[int, int] = {}

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        raw = str(value).strip()
        if ":" not in raw:
            continue

        channel_id_str, role_id_str = raw.split(":", 1)
        try:
            result[int(channel_id_str.strip())] = int(role_id_str.strip())
        except ValueError:
            continue

    return result


def _parse_rank_role_mapping_legacy(raw: str) -> dict[str, int]:
    """
    Старый формат:
    RANK_ROLE_MAPPING=Текст повышения:ID,Текст повышения:ID
    """
    result: dict[str, int] = {}
    if not raw:
        return result

    for part in str(raw).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue

        key, value = part.rsplit(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue

        try:
            role_id = int(value)
        except ValueError:
            continue

        result[key] = role_id

        # Автоматически добавляем вариант со второй стрелкой
        if "->" in key:
            result[key.replace("->", "→")] = role_id
        if "→" in key:
            result[key.replace("→", "->")] = role_id

    return result


def _parse_prefixed_rank_role_mapping(prefix: str) -> dict[str, int]:
    """
    Новый формат:
    RANKMAP_01=Текст повышения:ID
    RANKMAP_02=Текст повышения:ID
    """
    result: dict[str, int] = {}

    for key, value in sorted(os.environ.items()):
        if not key.startswith(prefix):
            continue

        raw = str(value).strip()
        if ":" not in raw:
            continue

        title, role_id_str = raw.rsplit(":", 1)
        title = title.strip()
        role_id_str = role_id_str.strip()
        if not title or not role_id_str:
            continue

        try:
            role_id = int(role_id_str)
        except ValueError:
            continue

        result[title] = role_id

        # Автоматически добавляем вариант со второй стрелкой
        if "->" in title:
            result[title.replace("->", "→")] = role_id
        if "→" in title:
            result[title.replace("→", "->")] = role_id

    return result


class Config:
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ Токен не найден! Создайте файл .env с DISCORD_BOT_TOKEN=ваш_токен")

    GUILD_ID = _env_int("GUILD_ID", 0)
    COMMAND_PREFIX = "!"
    LOG_FILE = "bot.log"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))

    # База данных
    DB_PATH = os.getenv("DB_PATH", "").strip()
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    # Роли staff
    STAFF_ROLE_ID = _env_int("STAFF_ROLE_ID", 0)
    TRANSFER_STAFF_ROLE_ID = _env_int("TRANSFER_STAFF_ROLE_ID", 0)
    GOV_STAFF_ROLE_ID = _env_int("GOV_STAFF_ROLE_ID", 0)
    FIRING_STAFF_ROLE_ID = _env_int("FIRING_STAFF_ROLE_ID", 0)
    WAREHOUSE_STAFF_ROLE_ID = _env_int("WAREHOUSE_STAFF_ROLE_ID", 0)

    # Роли выдачи (новый формат в .env: *_ROLE_01, *_ROLE_02...; старый CSV тоже поддерживается)
    CADET_ROLES_TO_GIVE = _get_list_from_env("CADET_ROLE_", "CADET_ROLES_TO_GIVE")
    TRANSFER_ROLES_TO_GIVE = _get_list_from_env("TRANSFER_ROLE_", "TRANSFER_ROLES_TO_GIVE")
    GOV_ROLE_TO_GIVE = _env_int("GOV_ROLE_TO_GIVE", 0)

    # Роли увольнения
    FIRED_ROLE_ID = _env_int("FIRED_ROLE_ID", 0)
    ROLES_TO_KEEP_ON_FIRE = _get_list_from_env("KEEP_ON_FIRE_ROLE_", "ROLES_TO_KEEP_ON_FIRE")

    # Роли званий
    ALL_RANK_ROLE_IDS = _get_list_from_env("ALL_RANK_ROLE_", "ALL_RANK_ROLE_IDS")
    ROLES_TO_KEEP_ON_PROMOTION = ROLES_TO_KEEP_ON_FIRE

    # Роли ППС
    PPS_ROLE_IDS = _get_list_from_env("PPS_ROLE_", "PPS_ROLE_IDS")
    DEPARTMENT_ROLES_PPS = PPS_ROLE_IDS

    # Каналы
    REQUEST_CHANNEL_ID = _env_int("REQUEST_CHANNEL_ID", 0)
    START_CHANNEL_ID = _env_int("START_CHANNEL_ID", 0)
    FIRING_CHANNEL_ID = _env_int("FIRING_CHANNEL_ID", 0)
    WAREHOUSE_REQUEST_CHANNEL_ID = _env_int("WAREHOUSE_REQUEST_CHANNEL_ID", 0)
    WAREHOUSE_AUDIT_CHANNEL_ID = _env_int("WAREHOUSE_AUDIT_CHANNEL_ID", 0)
    ACADEMY_CHANNEL_ID = _env_int("ACADEMY_CHANNEL_ID", 0)
    EXAM_CHANNEL_ID = _env_int("EXAM_CHANNEL_ID", 0)

    # Каналы повышений (новый формат: PROMOTION_CH_01=channel_id:role_id; старый PROMOTION_CHANNELS тоже поддерживается)
    PROMOTION_CHANNELS = _parse_prefixed_channel_role_map("PROMOTION_CH_")
    if not PROMOTION_CHANNELS:
        PROMOTION_CHANNELS = _parse_promotion_channels_legacy(os.getenv("PROMOTION_CHANNELS", ""))
    if not PROMOTION_CHANNELS:
        raise ValueError(
            "PROMOTION_CHANNELS / PROMOTION_CH_* не заданы в .env. "
            "Укажите каналы повышений и роль для их обработки."
        )

    # Время
    REQUEST_COOLDOWN = _env_int("REQUEST_COOLDOWN", 60)
    REQUEST_EXPIRY_DAYS = _env_int("REQUEST_EXPIRY_DAYS", 7)
    START_MESSAGE_CHECK_INTERVAL = _env_int("START_MESSAGE_CHECK_INTERVAL", 60)
    WAREHOUSE_COOLDOWN_HOURS = _env_int("WAREHOUSE_COOLDOWN_HOURS", 6)
    EXAM_BUTTON_TIMEOUT = _env_int("EXAM_BUTTON_TIMEOUT", 120)

    # Префиксы ников
    CADET_NICKNAME_PREFIX = "Курсант |"
    TRANSFER_NICKNAME_PREFIX = "Переаттестация |"
    GOV_NICKNAME_PREFIX = "Гос. |"
    FIRING_NICKNAME_PREFIX = "Уволен |"
    PPS_NICKNAME_PREFIX = "ППС |"

    # Маппинг текста повышения -> ID роли (новый формат: RANKMAP_01=Текст:ID; старый RANK_ROLE_MAPPING тоже поддерживается)
    RANK_ROLE_MAPPING = _parse_prefixed_rank_role_mapping("RANKMAP_")
    if not RANK_ROLE_MAPPING:
        RANK_ROLE_MAPPING = _parse_rank_role_mapping_legacy(os.getenv("RANK_ROLE_MAPPING", ""))
    if not RANK_ROLE_MAPPING:
        raise ValueError(
            "RANKMAP_* / RANK_ROLE_MAPPING не задан в .env. "
            "Укажите соответствие повышения и ID роли."
        )

    NON_PPS_RANKS = [
        "рядовой -> младший сержант",
        "рядовой → младший сержант",
        "младший сержант",
    ]

    SERGEANT_PROMOTIONS = [
        "младший сержант -> сержант",
        "младший сержант → сержант",
        "Младший Сержант -> Сержант",
        "Младший Сержант → Сержант",
    ]

    # Аудит
    AUDIT_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSf3LdXQWbYj9IEd5lEgoRmN3Hc5bblJSlefnzI8URsfdumapQ/formResponse"
    AUDIT_FIELD_OFFICER = "entry.1074962427"
    AUDIT_FIELD_TARGET_ID = "entry.70770719"
    AUDIT_FIELD_ACTION = "entry.1847499318"
    AUDIT_FIELD_RANK = "entry.1635379052"
    AUDIT_FIELD_REASON_LINK = "entry.268051623"

    ACTION_ACCEPTED = "Принят"
    ACTION_FIRED = "Уволен"
    ACTION_PROMOTED = "Повышен"

    RANK_PRIVATE = "Рядовой полиции"
    RANK_FIRED = "Уволен"

    # Валидация
    MAX_NAME_LENGTH = 30
    MIN_NAME_LENGTH = 2
    MAX_REASON_LENGTH = 500
    MAX_RANK_LENGTH = 30
    STATIC_ID_LENGTH = 6

    NAME_PATTERN = r"^[а-яА-Яa-zA-Z\- ]+$"
    RANK_PATTERN = r"^[а-яА-Яa-zA-Z\s\-\.]+$"
    URL_PATTERN = r"^https?://"
    STATIC_ID_FORMAT = "{}-{}"