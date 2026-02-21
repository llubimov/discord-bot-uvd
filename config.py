#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from dotenv import load_dotenv

load_dotenv()


class Config:
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ Токен не найден! Создайте файл .env с DISCORD_BOT_TOKEN=ваш_токен")

    GUILD_ID = int(os.getenv("GUILD_ID", 0))
    COMMAND_PREFIX = "!"
    LOG_FILE = "bot.log"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))

    # База данных
    DB_PATH = os.getenv("DB_PATH", "").strip()
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    # Роли staff
    STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", 0))
    TRANSFER_STAFF_ROLE_ID = int(os.getenv("TRANSFER_STAFF_ROLE_ID", 0))
    GOV_STAFF_ROLE_ID = int(os.getenv("GOV_STAFF_ROLE_ID", 0))
    FIRING_STAFF_ROLE_ID = int(os.getenv("FIRING_STAFF_ROLE_ID", 0))
    WAREHOUSE_STAFF_ROLE_ID = int(os.getenv("WAREHOUSE_STAFF_ROLE_ID", 0))

    # Роли выдачи
    CADET_ROLES_TO_GIVE = [int(x) for x in os.getenv("CADET_ROLES_TO_GIVE", "").split(",") if x]
    TRANSFER_ROLES_TO_GIVE = [int(x) for x in os.getenv("TRANSFER_ROLES_TO_GIVE", "").split(",") if x]
    GOV_ROLE_TO_GIVE = int(os.getenv("GOV_ROLE_TO_GIVE", 0))

    # Роли увольнения
    FIRED_ROLE_ID = int(os.getenv("FIRED_ROLE_ID", 0))
    ROLES_TO_KEEP_ON_FIRE = [int(x) for x in os.getenv("ROLES_TO_KEEP_ON_FIRE", "").split(",") if x]

    # Роли званий
    ALL_RANK_ROLE_IDS = [int(x) for x in os.getenv("ALL_RANK_ROLE_IDS", "").split(",") if x]
    ROLES_TO_KEEP_ON_PROMOTION = ROLES_TO_KEEP_ON_FIRE

    # Роли ППС
    PPS_ROLE_IDS = [int(x) for x in os.getenv("PPS_ROLE_IDS", "").split(",") if x]
    DEPARTMENT_ROLES_PPS = PPS_ROLE_IDS

    # Каналы
    REQUEST_CHANNEL_ID = int(os.getenv("REQUEST_CHANNEL_ID", 0))
    START_CHANNEL_ID = int(os.getenv("START_CHANNEL_ID", 0))
    FIRING_CHANNEL_ID = int(os.getenv("FIRING_CHANNEL_ID", 0))
    WAREHOUSE_REQUEST_CHANNEL_ID = int(os.getenv("WAREHOUSE_REQUEST_CHANNEL_ID", 0))
    WAREHOUSE_AUDIT_CHANNEL_ID = int(os.getenv("WAREHOUSE_AUDIT_CHANNEL_ID", 0))
    ACADEMY_CHANNEL_ID = int(os.getenv("ACADEMY_CHANNEL_ID", 0))
    EXAM_CHANNEL_ID = int(os.getenv("EXAM_CHANNEL_ID", 0))

    PROMOTION_CHANNELS_RAW = os.getenv("PROMOTION_CHANNELS", "").split(",")
    PROMOTION_CHANNELS = {}
    for item in PROMOTION_CHANNELS_RAW:
        if ":" in item:
            channel, role = item.split(":")
            PROMOTION_CHANNELS[int(channel)] = int(role)

    # Время
    REQUEST_COOLDOWN = int(os.getenv("REQUEST_COOLDOWN", 60))
    REQUEST_EXPIRY_DAYS = int(os.getenv("REQUEST_EXPIRY_DAYS", 7))
    START_MESSAGE_CHECK_INTERVAL = int(os.getenv("START_MESSAGE_CHECK_INTERVAL", 60))
    WAREHOUSE_COOLDOWN_HOURS = int(os.getenv("WAREHOUSE_COOLDOWN_HOURS", 6))
    EXAM_BUTTON_TIMEOUT = int(os.getenv("EXAM_BUTTON_TIMEOUT", 120))

    # Префиксы ников
    CADET_NICKNAME_PREFIX = "Курсант |"
    TRANSFER_NICKNAME_PREFIX = "Переаттестация |"
    GOV_NICKNAME_PREFIX = "Гос. |"
    FIRING_NICKNAME_PREFIX = "Уволен |"
    PPS_NICKNAME_PREFIX = "ППС |"

    # Повышения / роли
    LOG_RANK_MAPPING_CONFLICTS = True

    RANK_ROLE_MAPPING = {
        "Рядовой -> Младший Сержант": 1473503593989406801,
        "Младший Сержант -> Сержант": 1472578761315713106,
        "Сержант -> Старший Сержант": 1473494440743014552,
        "Старший сержант -> Старшина": 1473503677896462387,
        "Старшина -> Прапорщик": 1473503705474273496,
        "Прапорщик -> Старший прапорщик": 1473503732476936373,
        "Старший прапорщик -> Младший лейтенант": 1473503758741934180,
        "Младший лейтенант -> Лейтенант": 1473503807005655133,
        "Лейтенант -> Старший лейтенант": 1473503849397485609,
        "Старший лейтенант -> Капитан": 1473503910013440193,

        "Рядовой → Младший Сержант": 1473503593989406801,
        "Младший Сержант → Сержант": 1472578761315713106,
        "Сержант → Старший Сержант": 1473494440743014552,
        "Старший сержант → Старшина": 1473503677896462387,
        "Старшина → Прапорщик": 1473503705474273496,
        "Прапорщик → Старший прапорщик": 1473503732476936373,
        "Старший прапорщик → Младший лейтенант": 1473503758741934180,
        "Младший лейтенант → Лейтенант": 1473503807005655133,
        "Лейтенант → Старший лейтенант": 1473503849397485609,
        "Старший лейтенант → Капитан": 1473503910013440193,
    }

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