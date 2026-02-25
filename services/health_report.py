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
    load_all_department_transfer_requests,
    delete_request,
    delete_department_transfer_request,
)

logger = logging.getLogger(__name__)


def log_memory_state():
    try:
        logger.info(
            "📊 ПАМЯТЬ | заявки=%s | увольнения=%s | повышения=%s | склад=%s | переводы=%s",
            len(getattr(state, "active_requests", {}) or {}),
            len(getattr(state, "active_firing_requests", {}) or {}),
            len(getattr(state, "active_promotion_requests", {}) or {}),
            len(getattr(state, "warehouse_requests", {}) or {}),
            len(getattr(state, "active_department_transfers", {}) or {}),
        )
    except Exception as e:
        logger.error("Отчёт состояния: ошибка чтения памяти (state): %s", e, exc_info=True)


def _load_all_tables_for_report():
    req = load_all_requests()
    fir = load_all_firing_requests()
    pro = load_all_promotion_requests()
    wh = load_all_warehouse_requests()
    dept = load_all_department_transfer_requests()
    return req, fir, pro, wh, dept


async def log_db_state():
    try:
        req, fir, pro, wh, dept = await asyncio.to_thread(_load_all_tables_for_report)

        logger.info(
            "🗄️ БАЗА   | заявки=%s | увольнения=%s | повышения=%s | склад=%s | переводы=%s",
            len(req),
            len(fir),
            len(pro),
            len(wh),
            len(dept),
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

        # Заявки на перевод между отделами
        apply_channel_ids = [
            getattr(Config, "CHANNEL_APPLY_GROM", 0),
            getattr(Config, "CHANNEL_APPLY_PPS", 0),
            getattr(Config, "CHANNEL_APPLY_OSB", 0),
            getattr(Config, "CHANNEL_APPLY_ORLS", 0),
        ]
        apply_channel_ids = [c for c in apply_channel_ids if c]
        dept_transfers = await asyncio.to_thread(load_all_department_transfer_requests)
        for msg_id in list(dept_transfers.keys()):
            found = False
            for ch_id in apply_channel_ids:
                ch = bot.get_channel(ch_id)
                if ch and await _validate_message_exists(ch, int(msg_id)):
                    found = True
                    break
            if not found:
                logger.warning("🧹 ЛИШНЯЯ ЗАПИСЬ (заявка перевод): message_id=%s (сообщение удалено)", msg_id)
                if not dry_run:
                    await asyncio.to_thread(delete_department_transfer_request, int(msg_id))
                    state.active_department_transfers.pop(int(msg_id), None)

        logger.info("🧹 Проверка лишних записей завершена")

    except Exception as e:
        logger.error("Отчёт состояния: ошибка проверки лишних записей: %s", e, exc_info=True)


async def run_health_report(bot: discord.Client):
    logger.info("========== ОТЧЁТ О СОСТОЯНИИ ==========")
    log_memory_state()
    await log_db_state()
    await cleanup_orphan_records(bot, dry_run=True)
    logger.info("======== ОТЧЁТ О СОСТОЯНИИ ГОТОВ ========")