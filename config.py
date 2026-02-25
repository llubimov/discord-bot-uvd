import os
import logging
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int = 0) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_int_list(raw: str) -> list[int]:
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default

    return raw in {"1", "true", "yes", "y", "on", "да"}


def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, "") or "").strip() or default


def _parse_prefixed_int_list(prefix: str) -> list[int]:
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


def _parse_prefixed_int_list_allow_comma(prefix: str) -> list[int]:
    pairs: list[tuple[str, int]] = []

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        raw = str(value).strip()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                pairs.append((key, int(part)))
            except ValueError:
                continue

    pairs.sort(key=lambda x: x[0])
    return [v for _, v in pairs]


def _get_list_from_env(prefix: str, legacy_var: str) -> list[int]:
    prefixed = _parse_prefixed_int_list(prefix)
    if prefixed:
        return prefixed

    return _parse_int_list(os.getenv(legacy_var, ""))


def _get_rank_list_from_env(prefix: str, legacy_var: str) -> list[int]:
    prefixed = _parse_prefixed_int_list_allow_comma(prefix)
    if prefixed:
        return prefixed
    return _parse_int_list(os.getenv(legacy_var, ""))


def _parse_promotion_channels_legacy(raw: str) -> dict[int, int]:
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
    COMMAND_PREFIX = _env_str("COMMAND_PREFIX", "!")
    ENABLE_MESSAGE_CONTENT_INTENT = _env_bool("ENABLE_MESSAGE_CONTENT_INTENT", True)
    LOG_FILE = _env_str("LOG_FILE", "bot.log")
    LOG_FORMAT = _env_str("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

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

    # Каналы заявок на перевод между отделами и админ-перевод
    CHANNEL_APPLY_GROM = _env_int("CHANNEL_APPLY_GROM", 0)
    CHANNEL_APPLY_PPS = _env_int("CHANNEL_APPLY_PPS", 0)
    CHANNEL_APPLY_OSB = _env_int("CHANNEL_APPLY_OSB", 0)
    CHANNEL_APPLY_ORLS = _env_int("CHANNEL_APPLY_ORLS", 0)
    CHANNEL_ADMIN_TRANSFER = _env_int("CHANNEL_ADMIN_TRANSFER", 0)
    CHANNEL_CADRE_LOG = _env_int("CHANNEL_CADRE_LOG", 0)

    # Роли начальников/замов отделов (для одобрения заявок и админ-перевода)
    ROLE_CHIEF_GROM = _env_int("ROLE_CHIEF_GROM", 0)
    ROLE_DEPUTY_GROM = _env_int("ROLE_DEPUTY_GROM", 0)
    ROLE_CHIEF_PPS = _env_int("ROLE_CHIEF_PPS", 0)
    ROLE_DEPUTY_PPS = _env_int("ROLE_DEPUTY_PPS", 0)
    ROLE_CHIEF_OSB = _env_int("ROLE_CHIEF_OSB", 0)
    ROLE_DEPUTY_OSB = _env_int("ROLE_DEPUTY_OSB", 0)
    ROLE_CHIEF_ORLS = _env_int("ROLE_CHIEF_ORLS", 0)
    ROLE_DEPUTY_ORLS = _env_int("ROLE_DEPUTY_ORLS", 0)

    # Роли отделов (снять/выдать при переводе)
    ROLE_DEPT_GROM = _env_int("ROLE_DEPT_GROM", 0)
    ROLE_DEPT_PPS = _env_int("ROLE_DEPT_PPS", 0)
    ROLE_DEPT_OSB = _env_int("ROLE_DEPT_OSB", 0)
    ROLE_DEPT_ORLS = _env_int("ROLE_DEPT_ORLS", 0)

    # Ранги отделов (списки: ROLE_RANK_GROM_01=id или id1,id2,…, ROLE_RANK_GROM_02=…; допускаются несколько ID через запятую в одном ключе)
    ROLE_RANK_GROM = _get_rank_list_from_env("ROLE_RANK_GROM_", "ROLE_RANK_GROM")
    ROLE_RANK_PPS = _get_rank_list_from_env("ROLE_RANK_PPS_", "ROLE_RANK_PPS")
    ROLE_RANK_OSB = _get_rank_list_from_env("ROLE_RANK_OSB_", "ROLE_RANK_OSB")
    ROLE_RANK_ORLS = _get_rank_list_from_env("ROLE_RANK_ORLS_", "ROLE_RANK_ORLS")

    # Роль Академии (заявка «из Академии» — автодобро ППС, для ГРОМ/ОРЛС/ОСБ можно отклонить)
    ROLE_ACADEMY = _env_int("ROLE_ACADEMY", 0)

    # Роли отдела и рангов Академии (снимаются при переводе из Академии в любой отдел)
    ROLE_DEPT_ACADEMY = _env_int("ROLE_DEPT_ACADEMY", 0)
    ROLE_RANK_ACADEMY = _get_list_from_env("ROLE_RANK_ACADEMY_", "ROLE_RANK_ACADEMY")

    ROLE_PASSED_ACADEMY = _env_int("ROLE_PASSED_ACADEMY", 0) or ROLE_ACADEMY

    # Каналы повышений
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
    CADET_NICKNAME_PREFIX = os.getenv("CADET_NICKNAME_PREFIX", "Курсант |").strip()
    TRANSFER_NICKNAME_PREFIX = os.getenv("TRANSFER_NICKNAME_PREFIX", "Переаттестация |").strip()
    GOV_NICKNAME_PREFIX = os.getenv("GOV_NICKNAME_PREFIX", "Гос. |").strip()
    FIRING_NICKNAME_PREFIX = _env_str("FIRING_NICKNAME_PREFIX", "Уволен |")
    PPS_NICKNAME_PREFIX = _env_str("PPS_NICKNAME_PREFIX", "ППС |")

    # Увольнение: шапка канала и кнопка (из .env)
    FIRING_HEADER_TITLE = _env_str("FIRING_HEADER_TITLE", "РАПОРТ НА УВОЛЬНЕНИЕ")
    FIRING_HEADER_DESC = _env_str("FIRING_HEADER_DESC", "Пожалуйста, подайте заявление о вашем увольнении через эту форму.")
    FIRING_BUTTON_LABEL = _env_str("FIRING_BUTTON_LABEL", "ПОДАТЬ ЗАЯВЛЕНИЕ НА УВОЛЬНЕНИЕ")
    FIRING_MODAL_TITLE = _env_str("FIRING_MODAL_TITLE", "Заявление на увольнение")
    FIRING_AUTO_REASON = _env_str("FIRING_AUTO_REASON", "Автоматический рапорт при выходе с сервера")

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
    AUDIT_FORM_URL = os.getenv("AUDIT_FORM_URL", "").strip()
    AUDIT_FIELD_OFFICER = os.getenv("AUDIT_FIELD_OFFICER", "").strip()
    AUDIT_FIELD_TARGET_ID = os.getenv("AUDIT_FIELD_TARGET_ID", "").strip()
    AUDIT_FIELD_ACTION = os.getenv("AUDIT_FIELD_ACTION", "").strip()
    AUDIT_FIELD_RANK = os.getenv("AUDIT_FIELD_RANK", "").strip()
    AUDIT_FIELD_REASON_LINK = os.getenv("AUDIT_FIELD_REASON_LINK", "").strip()

    ACTION_ACCEPTED = _env_str("AUDIT_ACTION_ACCEPTED", "Принят")
    ACTION_FIRED = _env_str("AUDIT_ACTION_FIRED", "Уволен")
    ACTION_PROMOTED = _env_str("AUDIT_ACTION_PROMOTED", "Повышен")

    RANK_PRIVATE = _env_str("RANK_PRIVATE", "Рядовой полиции")
    RANK_FIRED = _env_str("RANK_FIRED", "Уволен")

    # Валидация (все лимиты из .env)
    MAX_NAME_LENGTH = _env_int("MAX_NAME_LENGTH", 30)
    MIN_NAME_LENGTH = _env_int("MIN_NAME_LENGTH", 2)
    MAX_REASON_LENGTH = _env_int("MAX_REASON_LENGTH", 500)
    MAX_RANK_LENGTH = _env_int("MAX_RANK_LENGTH", 30)
    STATIC_ID_LENGTH = _env_int("STATIC_ID_LENGTH", 6)
    # Возраст в заявках в подразделения (ГРОМ, ППС, ОСБ, ОРЛС)
    DEPT_APPLY_AGE_MIN = _env_int("DEPT_APPLY_AGE_MIN", 10)
    DEPT_APPLY_AGE_MAX = _env_int("DEPT_APPLY_AGE_MAX", 100)
    # Лимит полей в embed (Discord 25)
    MAX_EMBED_FIELDS = _env_int("MAX_EMBED_FIELDS", 25)

    # Webhook allowlist (если пусто — разрешаем все, для обратной совместимости)
    WEBHOOK_ALLOWED_IDS = _parse_int_list(os.getenv("WEBHOOK_ALLOWED_IDS", ""))
    WEBHOOK_ALLOWED_CHANNEL_IDS = _parse_int_list(os.getenv("WEBHOOK_ALLOWED_CHANNEL_IDS", ""))

    # Ссылки на изображения для экзамена/приказа (если пусто — используются дефолты из constants.ExamMessages)
    EXAM_HERB_URL = os.getenv("EXAM_HERB_URL", "").strip()
    EXAM_SEAL_URL = os.getenv("EXAM_SEAL_URL", "").strip()

    NAME_PATTERN = r"^[а-яА-Яa-zA-Z\- ]+$"
    RANK_PATTERN = r"^[а-яА-Яa-zA-Z\s\-\.]+$"
    URL_PATTERN = r"^https?://"
    STATIC_ID_FORMAT = "{}-{}"