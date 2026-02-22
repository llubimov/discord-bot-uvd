import logging
import asyncio
import discord

import state
from config import Config
from database import (
    load_all_requests,
    load_all_firing_requests,
    load_all_promotion_requests,
    load_all_warehouse_requests,
    delete_request,
)

logger = logging.getLogger(__name__)


def log_memory_state():
    """Короткая сводка по состоянию памяти (state)."""
    try:
        logger.info(
            "📊 ПАМЯТЬ | заявки=%s | увольнения=%s | повышения=%s | склад=%s",
            len(getattr(state, "active_requests", {}) or {}),
            len(getattr(state, "active_firing_requests", {}) or {}),
            len(getattr(state, "active_promotion_requests", {}) or {}),
            len(getattr(state, "warehouse_requests", {}) or {}),
        )
    except Exception as e:
        logger.error("Отчёт состояния: ошибка чтения памяти (state): %s", e, exc_info=True)


def _load_all_tables_for_report():
    """Синхронная загрузка таблиц БД для отчёта (вызывается в отдельном потоке)."""
    req = load_all_requests()
    fir = load_all_firing_requests()
    pro = load_all_promotion_requests()
    wh = load_all_warehouse_requests()
    return req, fir, pro, wh


async def log_db_state():
    """Короткая сводка по БД (не блокирует event loop)."""
    try:
        req, fir, pro, wh = await asyncio.to_thread(_load_all_tables_for_report)

        logger.info(
            "🗄️ БАЗА   | заявки=%s | увольнения=%s | повышения=%s | склад=%s",
            len(req),
            len(fir),
            len(pro),
            len(wh),
        )
    except Exception as e:
        logger.error("Отчёт состояния: ошибка чтения БД: %s", e, exc_info=True)


async def _validate_message_exists(channel: discord.TextChannel, message_id: int) -> bool:
    try:
        await channel.fetch_message(int(message_id))
        return True
    except discord.NotFound:
        return False
    except Exception:
        return True  # не считаем это удалением, чтобы случайно не снести запись из БД


async def cleanup_orphan_records(bot: discord.Client, dry_run: bool = True):
    """
    Проверка 'осиротевших' записей:
    - запись есть в БД
    - сообщения в канале уже нет

    dry_run=True  -> только логируем
    dry_run=False -> удаляем из БД
    """
    logger.info("🧹 Проверка осиротевших записей (только проверка=%s)...", dry_run)

    try:
        def _load_orphans():
            return (
                load_all_firing_requests(),
                load_all_promotion_requests(),
                load_all_warehouse_requests(),
            )

        firing, promotion, warehouse = await asyncio.to_thread(_load_orphans)

        firing_channel = bot.get_channel(Config.FIRING_CHANNEL_ID)
        warehouse_channel = bot.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)

        promo_channels = []
        for cid in (getattr(Config, "PROMOTION_CHANNELS", {}) or {}).keys():
            ch = bot.get_channel(int(cid))
            if ch:
                promo_channels.append(ch)

        # Увольнения
        if firing_channel:
            for msg_id in list(firing.keys()):
                exists = await _validate_message_exists(firing_channel, int(msg_id))
                if not exists:
                    logger.warning("🧹 ЛИШНЯЯ ЗАПИСЬ (увольнение): message_id=%s (сообщение удалено)", msg_id)
                    if not dry_run:
                        await asyncio.to_thread(delete_request, "firing_requests", int(msg_id))

        # Склад
        if warehouse_channel:
            for msg_id in list(warehouse.keys()):
                exists = await _validate_message_exists(warehouse_channel, int(msg_id))
                if not exists:
                    logger.warning("🧹 ЛИШНЯЯ ЗАПИСЬ (склад): message_id=%s (сообщение удалено)", msg_id)
                    if not dry_run:
                        await asyncio.to_thread(delete_request, "warehouse_requests", int(msg_id))

        # Повышения
        for msg_id in list(promotion.keys()):
            found = False
            for ch in promo_channels:
                try:
                    ok = await _validate_message_exists(ch, int(msg_id))
                    if ok:
                        found = True
                        break
                except Exception:
                    continue

            if not found:
                logger.warning("🧹 ЛИШНЯЯ ЗАПИСЬ (повышение): message_id=%s (сообщение удалено)", msg_id)
                if not dry_run:
                    await asyncio.to_thread(delete_request, "promotion_requests", int(msg_id))

        logger.info("🧹 Проверка лишних записей завершена")

    except Exception as e:
        logger.error("Отчёт состояния: ошибка проверки лишних записей: %s", e, exc_info=True)


async def run_health_report(bot: discord.Client):
    """
    Запуск краткого отчёта о состоянии:
    1) Память (state)
    2) БД
    3) Проверка лишних записей (только лог)
    """
    logger.info("========== ОТЧЁТ О СОСТОЯНИИ ==========")
    log_memory_state()
    await log_db_state()
    await cleanup_orphan_records(bot, dry_run=True)
    logger.info("======== ОТЧЁТ О СОСТОЯНИИ ГОТОВ ========")