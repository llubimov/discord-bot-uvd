#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
import logging
from logging.handlers import RotatingFileHandler
import asyncio
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import state
from config import Config

# ========== ЛОГИРОВАНИЕ ==========
file_handler = RotatingFileHandler(
    Config.LOG_FILE,
    maxBytes=2 * 1024 * 1024,  # 2 MB
    backupCount=5,
    encoding="utf-8"
)

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format=Config.LOG_FORMAT,
    handlers=[
        file_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== БОТ ==========
intents = discord.Intents.default()
intents.message_content = Config.ENABLE_MESSAGE_CONTENT_INTENT
intents.members = True

bot = commands.Bot(
    command_prefix=Config.COMMAND_PREFIX,
    intents=intents,
    max_messages=Config.BOT_MAX_MESSAGES if Config.BOT_MAX_MESSAGES > 0 else None,
)
state.bot = bot
_tree_synced_once = False


def _slash_require_role_above_bot(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.user:
        return False
    if not isinstance(interaction.user, discord.Member):
        return False
    me = interaction.guild.me
    if not me:
        return False
    return interaction.user.top_role.position > me.top_role.position


# ========== ИМПОРТЫ ==========
from database import init_db, delete_request
from services.webhook_handler import WebhookHandler
from services.cache import RoleCache, ChannelCache
from services.start_position_manager import StartPositionManager
from services.warehouse_position_manager import WarehousePositionManager
from services.cleanup import CleanupManager
from services.restore_views import ViewRestorer
from services.startup_checks import run_startup_checks
from services.health_report import run_health_report
from services.diag_report import build_diag_embed
from services.health_report import cleanup_orphan_records
from services.position_apply_grom import ApplyGromPositionManager
from services.position_apply_pps import ApplyPpsPositionManager
from services.position_apply_osb import ApplyOsbPositionManager
from services.position_apply_orls import ApplyOrlsPositionManager
from services.position_apply_academy import AcademyApplyPositionManager
from services.position_admin_transfer import AdminTransferPositionManager
from services.firing_position_manager import FiringPositionManager
from utils import startup_log

# ========== СЕРВИСЫ ==========
state.role_cache = RoleCache(bot)
state.channel_cache = ChannelCache(bot)

webhook_handler = WebhookHandler(bot)
start_manager = StartPositionManager(bot)
warehouse_position_manager = WarehousePositionManager(bot)
cleanup_manager = CleanupManager(bot)
view_restorer = ViewRestorer(bot)
apply_grom_manager = ApplyGromPositionManager(bot)
apply_pps_manager = ApplyPpsPositionManager(bot)
apply_osb_manager = ApplyOsbPositionManager(bot)
apply_orls_manager = ApplyOrlsPositionManager(bot)
academy_apply_manager = AcademyApplyPositionManager(bot)
admin_transfer_manager = AdminTransferPositionManager(bot)
firing_position_manager = FiringPositionManager(bot)

if not hasattr(state, "background_tasks") or not isinstance(getattr(state, "background_tasks", None), dict):
    state.background_tasks = {}

try:
    from services import warehouse_cooldown
    state.warehouse_cooldown = warehouse_cooldown
except Exception as e:
    logger.warning("warehouse_cooldown не загружен: %s", e)


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


def _ensure_background_task(task_name: str, coro_factory: Callable[[], Awaitable]) -> None:
    existing = getattr(state, "background_tasks", {}).get(task_name)
    if existing and not existing.done():
        return
    task = asyncio.create_task(coro_factory(), name=f"uvd:{task_name}")
    state.background_tasks[task_name] = task
    task.add_done_callback(lambda t, name=task_name: _bg_task_done(name, t))
    logger.info("Запущена фоновая задача: %s", task_name)


# --- Slash-команды (роль выше роли бота) ---

NO_ROLE_ABOVE_BOT = "❌ Команда доступна только участникам с ролью выше роли бота."


@bot.tree.command(name="ping", description="Задержка бота")
async def ping_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Понг! Задержка: {latency}мс")


@bot.tree.command(name="diag", description="-")
async def diag_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return
    try:
        await interaction.response.defer(ephemeral=True)
        embed = await build_diag_embed(bot)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error("Ошибка /diag: %s", e, exc_info=True)
        await interaction.followup.send("❌ Ошибка при сборке диагностики.", ephemeral=True)


@bot.tree.command(name="diag_clean_orphans", description="-")
async def diag_clean_orphans_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return
    try:
        await interaction.response.defer(ephemeral=True)
        await cleanup_orphan_records(bot, dry_run=False)
        await interaction.followup.send("✅ Очистка лишних записей завершена.", ephemeral=True)
    except Exception as e:
        logger.error("Ошибка /diag_clean_orphans: %s", e, exc_info=True)
        await interaction.followup.send("❌ Ошибка при очистке.", ephemeral=True)


@bot.tree.command(name="clear_firing", description="-")
async def clear_firing_slash(interaction: discord.Interaction, days: int = 7):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return
    try:
        await interaction.response.defer(ephemeral=True)
        cutoff_date = datetime.now() - timedelta(days=days)
        to_delete = []
        for msg_id, request in (getattr(state, "active_firing_requests", {}) or {}).items():
            created_at = request.get("created_at")
            if not created_at:
                to_delete.append(msg_id)
                continue
            try:
                if datetime.fromisoformat(created_at) < cutoff_date:
                    to_delete.append(msg_id)
            except Exception:
                to_delete.append(msg_id)
        deleted_count = 0
        for msg_id in to_delete:
            state.active_firing_requests.pop(msg_id, None)
            await asyncio.to_thread(delete_request, "firing_requests", int(msg_id))
            deleted_count += 1
        await interaction.followup.send(
            f"✅ Удалено {deleted_count} старых заявок на увольнение (память + БД)",
            ephemeral=True,
        )
        logger.info("Очистка заявок на увольнение /clear_firing: %s", deleted_count)
    except Exception as e:
        logger.error("Ошибка /clear_firing: %s", e, exc_info=True)
        await interaction.followup.send("❌ Ошибка при очистке.", ephemeral=True)


# --- ON_READY ---

@bot.event
async def on_ready():
    startup_log.banner_start()

    startup_log.section("Подключение")
    startup_log.step("Бот", str(bot.user))
    if bot.user:
        startup_log.step("ID бота", str(bot.user.id))

    startup_log.section("База данных")
    try:
        await asyncio.to_thread(init_db)
        startup_log.step("БД подключена", "OK")
    except Exception as e:
        logger.critical("БД не поднялась: %s", e, exc_info=True)
        raise

    startup_log.section("Слэш-команды")
    global _tree_synced_once
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
    try:
        await view_restorer.restore_all()
        startup_log.step("View восстановлены", "OK")
    except Exception as e:
        logger.error("Ошибка восстановления View: %s", e, exc_info=True)
        startup_log.step("Ошибка восстановления", str(e))

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

    startup_log.section("Фоновые задачи")
    _ensure_background_task("start_position_checker", start_manager.start_checking)
    _ensure_background_task("warehouse_position_checker", warehouse_position_manager.start_checking)
    _ensure_background_task("cleanup_manager", cleanup_manager.start_cleanup)
    if getattr(Config, "CHANNEL_APPLY_GROM", 0):
        _ensure_background_task("apply_grom_position_checker", apply_grom_manager.start_checking)
    if getattr(Config, "CHANNEL_APPLY_PPS", 0):
        _ensure_background_task("apply_pps_position_checker", apply_pps_manager.start_checking)
    if getattr(Config, "CHANNEL_APPLY_OSB", 0):
        _ensure_background_task("apply_osb_position_checker", apply_osb_manager.start_checking)
    if getattr(Config, "CHANNEL_APPLY_ORLS", 0):
        _ensure_background_task("apply_orls_position_checker", apply_orls_manager.start_checking)
    if getattr(Config, "ACADEMY_CHANNEL_ID", 0) and getattr(Config, "ROLE_ACADEMY", 0):
        _ensure_background_task("academy_apply_position_checker", academy_apply_manager.start_checking)
    if getattr(Config, "CHANNEL_ADMIN_TRANSFER", 0):
        _ensure_background_task("admin_transfer_position_checker", admin_transfer_manager.start_checking)
    if getattr(Config, "FIRING_CHANNEL_ID", 0):
        _ensure_background_task("firing_position_checker", firing_position_manager.start_checking)

    guild = bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None
    startup_log.banner_ready(
        str(bot.user),
        guild_name=guild.name if guild else None,
        guild_id=Config.GUILD_ID or None,
    )


# --- Сообщения ---

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.webhook_id:
        if Config.WEBHOOK_ALLOWED_IDS and int(message.webhook_id) not in Config.WEBHOOK_ALLOWED_IDS:
            return
        if Config.WEBHOOK_ALLOWED_CHANNEL_IDS and message.channel.id not in Config.WEBHOOK_ALLOWED_CHANNEL_IDS:
            return
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


if __name__ == "__main__":
    try:
        bot.run(Config.TOKEN, log_handler=None)
    except discord.LoginError:
        logger.critical("Неверный токен в .env")
    except Exception as e:
        logger.critical("Критическая ошибка: %s", e, exc_info=True)