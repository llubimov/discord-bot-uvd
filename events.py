# -*- coding: utf-8 -*-
"""Обработчики событий бота: on_ready, on_message, on_member_remove."""
import asyncio
import logging
from typing import Awaitable, Callable

import discord

import state
from config import Config
from database import (
    delete_grom_draft,
    delete_orls_draft,
    delete_osb_draft,
    delete_pps_draft,
    init_db,
)
from services.health_report import cleanup_orphan_records, run_health_report
from services.startup_checks import run_startup_checks
from services.worker_queue import get_worker
from utils import startup_log
from commands.promotion_setup import (
    ensure_promotion_messages_on_startup,
    move_promotion_setup_to_bottom,
    promotion_setup_position_check_loop,
)

logger = logging.getLogger(__name__)

_tree_synced_once = False


def _bg_task_done(task_name: str, task: asyncio.Task) -> None:
    try:
        if task.cancelled():
            logger.warning("Фоновая задача '%s' отменена", task_name)
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Фоновая задача '%s' упала: %s", task_name, exc, exc_info=exc)
        else:
            logger.warning("Фоновая задача '%s' завершилась", task_name)
    except Exception as e:
        logger.error("Ошибка в callback задачи '%s': %s", task_name, e, exc_info=True)
    finally:
        current = getattr(state, "background_tasks", {}).get(task_name)
        if current is task:
            state.background_tasks.pop(task_name, None)


def _ensure_background_task(bot: discord.Client, task_name: str, coro_factory: Callable[[], Awaitable]) -> None:
    existing = getattr(state, "background_tasks", {}).get(task_name)
    if existing and not existing.done():
        return
    task = asyncio.create_task(coro_factory(), name=f"uvd:{task_name}")
    state.background_tasks[task_name] = task
    task.add_done_callback(lambda t, name=task_name: _bg_task_done(name, t))
    logger.info("Запущена фоновая задача: %s", task_name)


def register_events(bot: discord.ext.commands.Bot) -> None:
    """Регистрирует обработчики on_ready, on_message, on_member_remove."""

    @bot.event
    async def on_ready():
        global _tree_synced_once
        startup_log.banner_start()

        startup_log.section("Подключение")
        startup_log.step("Бот", str(bot.user))
        if bot.user:
            startup_log.step("ID бота", str(bot.user.id))

        startup_log.section("База данных")
        try:
            await init_db()
            startup_log.step("БД подключена", "OK")
            # Загрузка персистентного состояния склада
            try:
                from database import warehouse_session_get_all
                from services.warehouse_session import WarehouseSession
                sessions = await warehouse_session_get_all()
                WarehouseSession.load_sessions_into_memory(sessions)
                startup_log.step("Сессии склада", "загружены из БД" if sessions else "—")
            except Exception as e:
                logger.debug("Загрузка сессий склада: %s", e)
            try:
                wc = getattr(state, "warehouse_cooldown", None)
                if wc and hasattr(wc, "load_from_db"):
                    await wc.load_from_db()
                    startup_log.step("Кулдауны склада", "загружены из БД")
            except Exception as e:
                logger.debug("Загрузка кулдаунов склада: %s", e)
        except Exception as e:
            logger.critical("БД не поднялась: %s", e, exc_info=True)
            raise

        startup_log.section("Слэш-команды")
        if not _tree_synced_once:
            try:
                if Config.GUILD_ID:
                    synced = await bot.tree.sync(guild=discord.Object(id=Config.GUILD_ID))
                else:
                    synced = await bot.tree.sync()
                names = [c.name for c in synced]
                startup_log.step("Синхронизированы", ", ".join(names) if names else "—")
                _tree_synced_once = True
            except Exception as e:
                logger.error("Ошибка синхронизации команд: %s", e, exc_info=True)
                startup_log.step("Ошибка синхронизации", str(e))
        else:
            startup_log.step("Уже синхронизированы", "—")

        startup_log.section("Восстановление View")
        view_restorer = getattr(state, "view_restorer", None)
        if view_restorer:
            try:
                await view_restorer.restore_all()
                startup_log.step("View восстановлены", "OK")
            except Exception as e:
                logger.error("Ошибка восстановления View: %s", e, exc_info=True)
                startup_log.step("Ошибка восстановления", str(e))
        else:
            startup_log.step("View восстановлены", "пропущено (нет view_restorer)")

        startup_log.section("Проверки при запуске")
        try:
            await run_startup_checks(bot)
            startup_log.step("Каналы и роли", "проверены")
        except Exception as e:
            logger.error("Стартовая проверка: %s", e, exc_info=True)
            startup_log.step("Ошибка проверок", str(e))

        startup_log.section("Состояние")
        try:
            await run_health_report(bot)
            startup_log.step("Отчёт состояния", "выведен выше")
        except Exception as e:
            logger.error("Ошибка отчёта состояния: %s", e, exc_info=True)
        if Config.GUILD_ID and not bot.get_guild(Config.GUILD_ID):
            logger.critical("GUILD_ID=%s не найден", Config.GUILD_ID)

        if getattr(Config, "PROMOTION_AUTO_SEND_ON_STARTUP", True):
            try:
                guild = bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None
                if guild:
                    await ensure_promotion_messages_on_startup(bot, guild)
                    startup_log.step("Сообщения для рапортов", "проверены/созданы")
            except Exception as e:
                logger.error("Ошибка авто-создания сообщений рапортов: %s", e, exc_info=True)
                startup_log.step("Сообщения для рапортов", "ошибка: %s" % e)

        startup_log.section("Фоновые задачи")
        get_worker().start()
        start_manager = getattr(state, "start_manager", None)
        warehouse_position_manager = getattr(state, "warehouse_position_manager", None)
        cleanup_manager = getattr(state, "cleanup_manager", None)
        if start_manager:
            _ensure_background_task(bot, "start_position_checker", start_manager.start_checking)
        if warehouse_position_manager:
            _ensure_background_task(bot, "warehouse_position_checker", warehouse_position_manager.start_checking)
        if cleanup_manager:
            _ensure_background_task(bot, "cleanup_manager", cleanup_manager.start_cleanup)

        for name, manager_attr in (
            ("apply_grom_position_checker", "apply_grom_manager"),
            ("apply_pps_position_checker", "apply_pps_manager"),
            ("apply_osb_position_checker", "apply_osb_manager"),
            ("apply_orls_position_checker", "apply_orls_manager"),
        ):
            manager = getattr(state, manager_attr, None)
            ch_attr = "CHANNEL_APPLY_GROM" if "grom" in name else "CHANNEL_APPLY_PPS" if "pps" in name else "CHANNEL_APPLY_OSB" if "osb" in name else "CHANNEL_APPLY_ORLS"
            if manager and getattr(Config, ch_attr, 0):
                _ensure_background_task(bot, name, manager.start_checking)

        if getattr(Config, "ACADEMY_CHANNEL_ID", 0) and getattr(Config, "ROLE_ACADEMY", 0):
            academy_apply_manager = getattr(state, "academy_apply_manager", None)
            if academy_apply_manager:
                _ensure_background_task(bot, "academy_apply_position_checker", academy_apply_manager.start_checking)
        if getattr(Config, "CHANNEL_ADMIN_TRANSFER", 0):
            admin_transfer_manager = getattr(state, "admin_transfer_manager", None)
            if admin_transfer_manager:
                _ensure_background_task(bot, "admin_transfer_position_checker", admin_transfer_manager.start_checking)
        if getattr(Config, "FIRING_CHANNEL_ID", 0):
            firing_position_manager = getattr(state, "firing_position_manager", None)
            if firing_position_manager:
                _ensure_background_task(bot, "firing_position_checker", firing_position_manager.start_checking)
        if getattr(Config, "PROMOTION_SETUP_CHECK_INTERVAL", 0):
            _ensure_background_task(bot, "promotion_setup_position_check", lambda: promotion_setup_position_check_loop(bot))

        guild = bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None
        startup_log.banner_ready(
            str(bot.user),
            guild_name=guild.name if guild else None,
            guild_id=Config.GUILD_ID or None,
        )

    @bot.event
    async def on_message(message: discord.Message):
        if message.author == bot.user:
            return

        if (not getattr(message.author, "bot", False)) and message.channel.id in (getattr(state, "promotion_setup_messages", None) or {}):
            await move_promotion_setup_to_bottom(bot, message.channel)

        if message.webhook_id:
            allowed_ids = getattr(Config, "WEBHOOK_ALLOWED_IDS", None) or []
            allowed_channel_ids = getattr(Config, "WEBHOOK_ALLOWED_CHANNEL_IDS", None) or []
            if allowed_ids and int(message.webhook_id) not in allowed_ids:
                return
            if allowed_channel_ids and message.channel.id not in allowed_channel_ids:
                return
            webhook_handler = getattr(state, "webhook_handler", None)
            if webhook_handler:
                await webhook_handler.process_webhook(message)
            return

        await bot.process_commands(message)

    @bot.event
    async def on_member_remove(member: discord.Member):
        try:
            from modals.firing_apply_modal import post_auto_firing_report
            await post_auto_firing_report(member)
        except Exception as e:
            logger.warning("Ошибка при авто-рапорте увольнения: %s", e, exc_info=True)
        try:
            uid = member.id
            (getattr(state, "orls_draft_reports", None) or {}).pop(uid, None)
            (getattr(state, "orls_last_user_data", None) or {}).pop(uid, None)
            get_worker().submit_fire(delete_orls_draft, uid)
            (getattr(state, "osb_draft_reports", None) or {}).pop(uid, None)
            (getattr(state, "osb_last_user_data", None) or {}).pop(uid, None)
            get_worker().submit_fire(delete_osb_draft, uid)
            (getattr(state, "grom_draft_reports", None) or {}).pop(uid, None)
            (getattr(state, "grom_last_user_data", None) or {}).pop(uid, None)
            get_worker().submit_fire(delete_grom_draft, uid)
            (getattr(state, "pps_draft_reports", None) or {}).pop(uid, None)
            (getattr(state, "pps_last_user_data", None) or {}).pop(uid, None)
            get_worker().submit_fire(delete_pps_draft, uid)
        except Exception as e:
            logger.debug("черновики при выходе: %s", e)
