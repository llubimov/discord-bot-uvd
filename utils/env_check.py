# -*- coding: utf-8 -*-
"""
Проверка переменных окружения до запуска бота.
Вызывать после load_dotenv() и до импорта config.
"""
import os
import sys


def _has_promotion_channels() -> bool:
    """Есть ли хотя бы один канал повышений (PROMOTION_CH_* или PROMOTION_CHANNELS)."""
    for key, value in os.environ.items():
        if key.startswith("PROMOTION_CH_") and value and ":" in str(value).strip():
            return True
    raw = os.getenv("PROMOTION_CHANNELS", "")
    if raw and ":" in raw:
        return True
    return False


def _has_rank_role_mapping() -> bool:
    """Есть ли хотя бы один маппинг звание->роль (RANKMAP_* или RANK_ROLE_MAPPING)."""
    for key, value in os.environ.items():
        if key.startswith("RANKMAP_") and value and ":" in str(value).strip():
            return True
    raw = os.getenv("RANK_ROLE_MAPPING", "")
    if raw and ":" in raw:
        return True
    return False


def validate_env() -> None:
    """
    Проверяет обязательные переменные окружения.
    При отсутствии обязательных переменных выводит список и завершает работу (sys.exit(1)).
    Опциональные переменные только предупреждает в stderr.
    """
    missing: list[str] = []
    warnings: list[str] = []

    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        missing.append("DISCORD_BOT_TOKEN — токен бота из Discord Developer Portal")

    try:
        guild_id = int((os.getenv("GUILD_ID") or "0").strip())
    except ValueError:
        guild_id = 0
    if not guild_id:
        missing.append("GUILD_ID — ID сервера (число)")

    if not _has_promotion_channels():
        missing.append(
            "PROMOTION_CHANNELS или PROMOTION_CH_01, PROMOTION_CH_02, ... — "
            "каналы повышений и роли кадровика (формат channel_id:role_id)"
        )

    if not _has_rank_role_mapping():
        missing.append(
            "RANK_ROLE_MAPPING или RANKMAP_01, RANKMAP_02, ... — "
            "соответствие формулировки повышения и ID роли (формат Текст:role_id)"
        )

    # Опциональные, но важные для базовых фич — только предупреждение
    if not (os.getenv("START_CHANNEL_ID") or "").strip():
        warnings.append("START_CHANNEL_ID не задан — канал заявок «Курсант/Перевод/Гос» может быть недоступен")
    if not (os.getenv("REQUEST_CHANNEL_ID") or "").strip():
        warnings.append("REQUEST_CHANNEL_ID не задан — канал приёма заявок может быть недоступен")
    if not (os.getenv("STAFF_ROLE_ID") or "").strip():
        warnings.append("STAFF_ROLE_ID не задан — кнопки «Принять/Отклонить» могут быть недоступны")

    for w in warnings:
        print(f"⚠️ {w}", file=sys.stderr)

    if missing:
        print("❌ Отсутствуют обязательные переменные окружения (.env):", file=sys.stderr)
        for m in missing:
            print(f"   • {m}", file=sys.stderr)
        print("   Скопируйте .env.example в .env и заполните значения.", file=sys.stderr)
        sys.exit(1)
