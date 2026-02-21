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

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
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

# ========== НАСТРОЙКИ БОТА ==========
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)
state.bot = bot
# Синхронизацию slash-команд делаем только один раз (не на каждый reconnect)
_tree_synced_once = False

# ========== ИМПОРТ МОДУЛЕЙ ==========
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

# ========== ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ ==========
state.role_cache = RoleCache(bot)
state.channel_cache = ChannelCache(bot)

webhook_handler = WebhookHandler(bot)
start_manager = StartPositionManager(bot)
warehouse_position_manager = WarehousePositionManager(bot)
cleanup_manager = CleanupManager(bot)
view_restorer = ViewRestorer(bot)

# Хранилище фоновых задач (защита от повторного запуска в on_ready)
if not hasattr(state, "background_tasks") or not isinstance(getattr(state, "background_tasks", None), dict):
    state.background_tasks = {}

# Единый экземпляр кулдауна склада: используем singleton из services
try:
    from services import warehouse_cooldown
    state.warehouse_cooldown = warehouse_cooldown
except Exception as e:
    logger.warning("⚠️ Не удалось подключить warehouse_cooldown: %s", e)


def _bg_task_done(task_name: str, task: asyncio.Task) -> None:
    """Логирование завершения фоновой задачи и очистка ссылки из state."""
    try:
        if task.cancelled():
            logger.warning("⚠️ Фоновая задача '%s' была отменена", task_name)
            return

        exc = task.exception()
        if exc is not None:
            logger.error("❌ Фоновая задача '%s' завершилась с ошибкой: %s", task_name, exc, exc_info=exc)
        else:
            logger.warning("⚠️ Фоновая задача '%s' неожиданно завершилась без ошибки", task_name)
    except Exception as callback_error:
        logger.error("❌ Ошибка в callback фоновой задачи '%s': %s", task_name, callback_error, exc_info=True)
    finally:
        current = getattr(state, "background_tasks", {}).get(task_name)
        if current is task:
            state.background_tasks.pop(task_name, None)


def _ensure_background_task(task_name: str, coro_factory: Callable[[], Awaitable]) -> None:
    """Запускает фоновую задачу только один раз (даже если on_ready вызван повторно)."""
    existing = getattr(state, "background_tasks", {}).get(task_name)
    if existing and not existing.done():
        logger.info("ℹ️ Фоновая задача '%s' уже запущена, повторный запуск пропущен", task_name)
        return

    task = asyncio.create_task(coro_factory(), name=f"uvd:{task_name}")
    state.background_tasks[task_name] = task
    task.add_done_callback(lambda t, name=task_name: _bg_task_done(name, t))
    logger.info("▶️ Запущена фоновая задача: %s", task_name)


# ============================================================================
# ТЕКСТОВЫЕ КОМАНДЫ
# ============================================================================

@bot.command(name="ping")
async def ping_text(ctx):
    """!ping - проверить работу бота"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Понг! Задержка: {latency}мс")


@bot.command(name="info")
async def info_text(ctx):
    """!info - информация о боте"""
    embed = discord.Embed(
        title="🤖 Информация о боте",
        description="Бот для автоматизации кадрового учета УВД",
        color=discord.Color.blue()
    )
    embed.add_field(name="Версия", value="2.0.0", inline=True)
    embed.add_field(name="Разработчик", value="llubimov", inline=True)

    total = (
        len(getattr(state, "active_requests", {}) or {}) +
        len(getattr(state, "active_firing_requests", {}) or {}) +
        len(getattr(state, "active_promotion_requests", {}) or {}) +
        len(getattr(state, "warehouse_requests", {}) or {})
    )
    embed.add_field(name="Активных заявок", value=str(total), inline=True)

    await ctx.send(embed=embed)


@bot.command(name="help_uvd")
async def help_uvd(ctx):
    """!help_uvd - справка по боту"""
    embed = discord.Embed(
        title="📚 Помощь по боту УВД",
        description="**Текстовые команды (с префиксом !):**",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="Основные",
        value=(
            "`!ping` - Проверка связи\n"
            "`!info` - Информация о боте\n"
            "`!help_uvd` - Это меню"
        ),
        inline=False
    )

    embed.add_field(
        name="Админские",
        value=(
            "`!clear_firing [дни]` - Очистка старых заявок на увольнение\n"
            "`!diag_clean_orphans` - Очистка записей\n"
            "`!diag` - Диагностика\n"
            "*(только для администраторов)*"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Заявки и склад",
        value=(
            "Используйте **кнопки** в соответствующих каналах:\n"
            "• Канал заявок — для поступления на службу\n"
            "• Канал склада — для получения снаряжения"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# ============================================================================
# АДМИНСКИЕ КОМАНДЫ
# ============================================================================

@bot.command(name="diag_clean_orphans")
@commands.has_permissions(administrator=True)
async def diag_clean_orphans_command(ctx):
    """!diag_clean_orphans - удалить записи из БД, у которых уже нет сообщений"""
    try:
        await ctx.send("🧹 Запускаю проверку и очистку лишних записей...")
        await cleanup_orphan_records(bot, dry_run=False)
        await ctx.send("✅ Очистка лишних записей завершена. Проверь лог/!diag.")
    except Exception as e:
        logger.error("Ошибка команды !diag_clean_orphans: %s", e, exc_info=True)
        await ctx.send("❌ Ошибка при очистке лишних записей.")


@diag_clean_orphans_command.error
async def diag_clean_orphans_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Эта команда доступна только администраторам.")
        return
    logger.error("Ошибка команды !diag_clean_orphans (handler): %s", error, exc_info=True)
    await ctx.send("❌ Ошибка выполнения команды.")


@bot.command(name="diag")
@commands.has_permissions(administrator=True)
async def diag_command(ctx):
    """!diag - диагностика бота (память, БД, каналы, роли, права)"""
    try:
        embed = await build_diag_embed(bot)
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error("Ошибка команды !diag: %s", e, exc_info=True)
        await ctx.send("❌ Ошибка при сборке диагностики.")


@diag_command.error
async def diag_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Эта команда доступна только администраторам.")
        return
    logger.error("Ошибка команды !diag (handler): %s", error, exc_info=True)
    await ctx.send("❌ Ошибка выполнения команды.")


@bot.command(name="clear_firing")
@commands.has_permissions(administrator=True)
async def clear_firing_requests(ctx, days: int = 7):
    """!clear_firing [дни] - очистить старые заявки на увольнение (память + БД)"""
    try:
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

        await ctx.send(f"✅ Удалено {deleted_count} старых заявок на увольнение (память + БД)")
        logger.info("🧹 Админ очистил %s заявок на увольнение (память + БД)", deleted_count)

    except Exception as e:
        logger.error("Ошибка в clear_firing: %s", e, exc_info=True)
        await ctx.send("❌ Ошибка при очистке")


@clear_firing_requests.error
async def clear_firing_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Эта команда доступна только администраторам.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send("❌ Укажи число дней, например: `!clear_firing 7`")
        return

    logger.error("Ошибка команды !clear_firing: %s", error, exc_info=True)
    await ctx.send("❌ Ошибка выполнения команды.")


# ============================================================================
# СОБЫТИЕ ON_READY
# ============================================================================

@bot.event
async def on_ready():
    """Выполняется при запуске бота и при повторных подключениях."""

    logger.info("=" * 60)
    logger.info("🤖 БОТ ЗАПУЩЕН / ПОДКЛЮЧЕН: %s", bot.user)
    logger.info("=" * 60)

    # 1) База данных
    init_db()
    logger.info("✅ База данных подключена")

    # 2) Синхронизация команд (только один раз)
    global _tree_synced_once
    if not _tree_synced_once:
        try:
            synced = await bot.tree.sync()
            _tree_synced_once = True
            logger.info("✅ Синхронизировано %s команд: %s", len(synced), [cmd.name for cmd in synced])
        except Exception as e:
            logger.error("❌ Ошибка синхронизации команд: %s", e, exc_info=True)
    else:
        logger.info("ℹ️ Синхронизация команд пропущена (уже выполнена ранее)")
    
        
        
    
        

    # 3) Восстановление view
    try:
        await view_restorer.restore_all()
        logger.info("✅ Восстановление View завершено")
    except Exception as e:
        logger.error("❌ Ошибка восстановления View: %s", e, exc_info=True)

    # 4) Диагностика при запуске
    try:
        await run_startup_checks(bot)
        await run_health_report(bot)
    except Exception as e:
        logger.error("❌ Ошибка стартовой диагностики: %s", e, exc_info=True)

    # 5) Фоновые задачи (запуск только один раз)
    _ensure_background_task("start_position_checker", start_manager.start_checking)
    _ensure_background_task("warehouse_position_checker", warehouse_position_manager.start_checking)
    _ensure_background_task("cleanup_manager", cleanup_manager.start_cleanup)

    logger.info("=" * 60)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 60)


# ============================================================================
# ОБРАБОТЧИК СООБЩЕНИЙ
# ============================================================================

@bot.event
async def on_message(message):
    """Обрабатывает входящие сообщения"""
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    if message.webhook_id:
        await webhook_handler.process_webhook(message)


# ============================================================================
# ЗАПУСК БОТА
# ============================================================================

if __name__ == "__main__":
    try:
        logger.info("=" * 60)
        logger.info("🚀 ЗАПУСК БОТА...")
        logger.info("=" * 60)
        bot.run(Config.TOKEN, log_handler=None)

    except discord.LoginError:
        logger.critical("❌ Ошибка авторизации! Проверьте токен в .env")

    except Exception as e:
        logger.critical("❌ Критическая ошибка: %s", e, exc_info=True)