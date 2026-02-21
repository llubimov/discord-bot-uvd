#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
import logging
import asyncio
from datetime import datetime, timedelta

import state
from config import Config

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format=Config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding="utf-8"),
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

# Если где-то в проекте используется state.warehouse_cooldown — сохраним единый экземпляр
try:
    from services.warehouse_cooldown import WarehouseCooldown
    state.warehouse_cooldown = WarehouseCooldown()
except Exception as e:
    logger.warning("⚠️ Не удалось инициализировать WarehouseCooldown: %s", e)


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
                # Если даты нет — считаем запись подозрительной и тоже удаляем
                to_delete.append(msg_id)
                continue

            try:
                if datetime.fromisoformat(created_at) < cutoff_date:
                    to_delete.append(msg_id)
            except Exception:
                to_delete.append(msg_id)

        # Удаляем из памяти и БД
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
    """Выполняется при запуске бота"""

    logger.info("=" * 60)
    logger.info("🤖 БОТ ЗАПУЩЕН: %s", bot.user)
    logger.info("=" * 60)

    # 1) База данных
    init_db()
    logger.info("✅ База данных подключена")

    # 2) Синхронизация команд
    try:
        synced = await bot.tree.sync()
        logger.info("✅ Синхронизировано %s команд: %s", len(synced), [cmd.name for cmd in synced])
    except Exception as e:
        logger.error("❌ Ошибка синхронизации команд: %s", e)

    # 3) Восстановление view
    await view_restorer.restore_all()

    # 4) Диагностика при запуске (русские логи)
    await run_startup_checks(bot)
    await run_health_report(bot)

    # 5) Фоновые задачи
    bot.loop.create_task(start_manager.start_checking())
    bot.loop.create_task(warehouse_position_manager.start_checking())
    bot.loop.create_task(cleanup_manager.start_cleanup())

    logger.info("=" * 60)
    logger.info("✅ БОТ ПОЛНОСТЬЮ ГОТОВ К РАБОТЕ")
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

    # Вебхуки (увольнения / повышения)
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