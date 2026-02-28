#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
from discord import app_commands
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import time
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
from database import init_db, delete_request, delete_orls_draft, delete_osb_draft, delete_grom_draft, delete_pps_draft
from services.webhook_handler import WebhookHandler
from services.cache import RoleCache, ChannelCache
from services.start_position_manager import StartPositionManager
from services.warehouse_position_manager import WarehousePositionManager
from services.cleanup import CleanupManager
from services.worker_queue import init_worker, get_worker
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
from views.orls_promotion_apply_view import OrlsPromotionApplyView
from views.osb_promotion_apply_view import OsbPromotionApplyView
from views.grom_promotion_apply_view import GromPromotionApplyView
from views.pps_promotion_apply_view import PpsPromotionApplyView

# ========== СЕРВИСЫ ==========
state.role_cache = RoleCache(bot)
state.channel_cache = ChannelCache(bot)

webhook_handler = WebhookHandler(bot)
start_manager = StartPositionManager(bot)
warehouse_position_manager = WarehousePositionManager(bot)
cleanup_manager = CleanupManager(bot)
init_worker()
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

    # Сообщения «Подать рапорт» создаются при старте в каналах PROMOTION_APPLY_CHANNEL_*;
    # в конец канала их переносит on_message, отдельный position_checker для них не используется.
    if getattr(Config, "PROMOTION_AUTO_SEND_ON_STARTUP", True):
        try:
            guild = bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None
            if guild:
                await _ensure_promotion_messages_on_startup(guild)
                startup_log.step("Сообщения для рапортов", "проверены/созданы")
        except Exception as e:
            logger.error("Ошибка авто-создания сообщений рапортов: %s", e, exc_info=True)
            startup_log.step("Сообщения для рапортов", "ошибка: %s" % e)

    startup_log.section("Фоновые задачи")
    get_worker().start()
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
    if getattr(Config, "PROMOTION_SETUP_CHECK_INTERVAL", 0):
        _ensure_background_task("promotion_setup_position_check", _promotion_setup_position_check_loop)

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

    # Перенос сообщений «подача рапорта» в конец канала при новом сообщении (не от бота)
    if (not getattr(message.author, "bot", False)) and message.channel.id in state.promotion_setup_messages:
        await _move_promotion_setup_to_bottom(message.channel)

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
    try:
        uid = member.id
        state.orls_draft_reports.pop(uid, None)
        state.orls_last_user_data.pop(uid, None)
        get_worker().submit_fire(delete_orls_draft, uid)
        state.osb_draft_reports.pop(uid, None)
        state.osb_last_user_data.pop(uid, None)
        get_worker().submit_fire(delete_osb_draft, uid)
        state.grom_draft_reports.pop(uid, None)
        state.grom_last_user_data.pop(uid, None)
        get_worker().submit_fire(delete_grom_draft, uid)
        state.pps_draft_reports.pop(uid, None)
        state.pps_last_user_data.pop(uid, None)
        get_worker().submit_fire(delete_pps_draft, uid)
    except Exception as e:
        logger.debug("черновики при выходе: %s", e)


@app_commands.command(
    name="orls_promotion_setup",
    description="Создать сообщение для подачи рапортов на повышение ОРЛС в этом канале",
)
@app_commands.guilds(discord.Object(id=Config.GUILD_ID))
async def orls_promotion_setup_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return

    channel = interaction.channel
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Команду нужно вызывать в текстовом канале сервера.",
            ephemeral=True,
        )
        return

    # Разрешаем создавать сообщение только в каналах, настроенных как каналы повышений
    if not isinstance(Config.PROMOTION_CHANNELS, dict) or channel.id not in Config.PROMOTION_CHANNELS:
        await interaction.response.send_message(
            "❌ Этот канал не настроен как канал рапортов на повышение. "
            "Вызовите команду в нужном канале повышений ОРЛС.",
            ephemeral=True,
        )
        return

    view = OrlsPromotionApplyView()
    content = (
        "📋 **Рапорты на повышение ОРЛС**\n\n"
        "1. Выберите ваше повышение из списка ниже.\n"
        "2. В форме укажите ФИО, Discord ID, паспорт.\n"
        "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
        "4. Дополнительно можете указать ссылки для баллов ОРЛС.\n\n"
        "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
    )
    await _send_promotion_message_at_bottom(channel, content, view, dept="orls")
    await interaction.response.send_message("✅ Сообщение для рапортов ОРЛС создано.", ephemeral=True)


@app_commands.command(
    name="osb_promotion_setup",
    description="Создать сообщение для подачи рапортов на повышение ОСБ в этом канале",
)
@app_commands.guilds(discord.Object(id=Config.GUILD_ID))
async def osb_promotion_setup_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return

    channel = interaction.channel
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Команду нужно вызывать в текстовом канале сервера.",
            ephemeral=True,
        )
        return

    if not isinstance(Config.PROMOTION_CHANNELS, dict) or channel.id not in Config.PROMOTION_CHANNELS:
        await interaction.response.send_message(
            "❌ Этот канал не настроен как канал рапортов на повышение. "
            "Вызовите команду в нужном канале повышений ОСБ.",
            ephemeral=True,
        )
        return

    view = OsbPromotionApplyView()
    content = (
        "📋 **Рапорты на повышение ОСБ (Отдел собственной безопасности)**\n\n"
        "1. Выберите ваше повышение из списка ниже.\n"
        "2. В форме укажите ФИО, Discord ID, паспорт.\n"
        "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
        "4. Дополнительно укажите ссылки для баллов (общие и только ОСБ).\n\n"
        "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
    )
    await _send_promotion_message_at_bottom(channel, content, view, dept="osb")
    await interaction.response.send_message("✅ Сообщение для рапортов ОСБ создано.", ephemeral=True)


@app_commands.command(
    name="grom_promotion_setup",
    description="Создать сообщение для подачи рапортов на повышение ОСН «Гром» в этом канале",
)
@app_commands.guilds(discord.Object(id=Config.GUILD_ID))
async def grom_promotion_setup_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return

    channel = interaction.channel
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Команду нужно вызывать в текстовом канале сервера.",
            ephemeral=True,
        )
        return

    if not isinstance(Config.PROMOTION_CHANNELS, dict) or channel.id not in Config.PROMOTION_CHANNELS:
        await interaction.response.send_message(
            "❌ Этот канал не настроен как канал рапортов на повышение. "
            "Вызовите команду в нужном канале повышений ГРОМ.",
            ephemeral=True,
        )
        return

    view = GromPromotionApplyView()
    content = (
        "📋 **Рапорты на повышение ОСН «Гром» (ГРОМ)**\n\n"
        "1. Выберите ваше повышение из списка ниже.\n"
        "2. В форме укажите ФИО, Discord ID, паспорт.\n"
        "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
        "4. Дополнительно укажите ссылки для баллов (общие, ГРОМ, инструкторы).\n\n"
        "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
    )
    await _send_promotion_message_at_bottom(channel, content, view, dept="grom")
    await interaction.response.send_message("✅ Сообщение для рапортов ГРОМ создано.", ephemeral=True)


@app_commands.command(
    name="pps_promotion_setup",
    description="Создать сообщение для подачи рапортов на повышение ППС в этом канале",
)
@app_commands.guilds(discord.Object(id=Config.GUILD_ID))
async def pps_promotion_setup_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return

    channel = interaction.channel
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Команду нужно вызывать в текстовом канале сервера.",
            ephemeral=True,
        )
        return

    if not isinstance(Config.PROMOTION_CHANNELS, dict) or channel.id not in Config.PROMOTION_CHANNELS:
        await interaction.response.send_message(
            "❌ Этот канал не настроен как канал рапортов на повышение. "
            "Вызовите команду в нужном канале повышений ППС.",
            ephemeral=True,
        )
        return

    view = PpsPromotionApplyView()
    content = (
        "📋 **Рапорты на повышение ППС**\n\n"
        "1. Выберите ваше повышение из списка ниже.\n"
        "2. В форме укажите ФИО, Discord ID, паспорт.\n"
        "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
        "4. Дополнительно укажите ссылки для баллов (общие, ППС, инструкторы).\n\n"
        "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
    )
    await _send_promotion_message_at_bottom(channel, content, view, dept="pps")
    await interaction.response.send_message("✅ Сообщение для рапортов ППС создано.", ephemeral=True)


def _get_promotion_view(dept: str) -> discord.ui.View:
    if dept == "orls":
        return OrlsPromotionApplyView()
    if dept == "osb":
        return OsbPromotionApplyView()
    if dept == "grom":
        return GromPromotionApplyView()
    if dept == "pps":
        return PpsPromotionApplyView()
    return OrlsPromotionApplyView()


async def _move_promotion_setup_to_bottom(channel: discord.TextChannel) -> None:
    """Переносит зарегистрированные сообщения «подача рапорта» в самый низ канала."""
    if not isinstance(channel, discord.TextChannel):
        return
    now = time.time()
    cooldown_sec = 15
    if channel.id in state.promotion_setup_move_cooldown:
        if now - state.promotion_setup_move_cooldown[channel.id] < cooldown_sec:
            return
    state.promotion_setup_move_cooldown[channel.id] = now

    entries = state.promotion_setup_messages.get(channel.id, [])
    if not entries:
        return
    new_entries = []
    for item in entries:
        try:
            msg = await channel.fetch_message(item["message_id"])
            if msg.author != bot.user:
                continue
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass
        try:
            view = _get_promotion_view(item["dept"])
            new_msg = await channel.send(content=item["content"], view=view)
            new_entries.append({"message_id": new_msg.id, "dept": item["dept"], "content": item["content"]})
        except Exception as e:
            logger.debug("Перенос сообщения рапорта %s: %s", item.get("dept"), e)
    if new_entries:
        state.promotion_setup_messages[channel.id] = new_entries


async def _promotion_setup_position_check_loop() -> None:
    """Каждые PROMOTION_SETUP_CHECK_INTERVAL сек проверяет: последнее сообщение в канале — наше; если нет — переносит вниз."""
    interval = getattr(Config, "PROMOTION_SETUP_CHECK_INTERVAL", 90) or 90
    if interval <= 0:
        return
    await asyncio.sleep(interval)
    while True:
        try:
            guild = bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None
            if not guild:
                await asyncio.sleep(interval)
                continue
            for channel_id in list((getattr(state, "promotion_setup_messages", {}) or {}).keys()):
                try:
                    ch = guild.get_channel(channel_id)
                    if not ch or not isinstance(ch, discord.TextChannel):
                        continue
                    last_msg = None
                    async for m in ch.history(limit=1):
                        last_msg = m
                        break
                    if not last_msg:
                        continue
                    # Пропускаем только если последнее сообщение — именно наше «Подать рапорт» (по id)
                    setup_ids = {item["message_id"] for item in (state.promotion_setup_messages.get(channel_id) or [])}
                    if last_msg.id in setup_ids:
                        continue
                    await _move_promotion_setup_to_bottom(ch)
                except Exception as e:
                    logger.debug("Проверка канала рапортов %s: %s", channel_id, e)
        except Exception as e:
            logger.warning("promotion_setup_position_check: %s", e, exc_info=True)
        await asyncio.sleep(interval)


async def _send_promotion_message_at_bottom(
    channel: discord.TextChannel,
    content: str,
    view: discord.ui.View,
    dept: str | None = None,
) -> discord.Message | None:
    msg = await channel.send(content=content, view=view)
    try:
        last_in_channel = None
        async for m in channel.history(limit=1):
            last_in_channel = m
            break
        if last_in_channel and last_in_channel.id != msg.id:
            await msg.delete()
            msg = await channel.send(content=content, view=view)
    except Exception:
        pass
    if dept:
        state.promotion_setup_messages.setdefault(channel.id, []).append(
            {"message_id": msg.id, "dept": dept, "content": content}
        )
    return msg


def _promotion_setup_configs():
    return [
        (getattr(Config, "PROMOTION_APPLY_CHANNEL_ORLS", 0), "ОРЛС", "orls", OrlsPromotionApplyView(), (
            "📋 **Рапорты на повышение ОРЛС**\n\n"
            "1. Выберите ваше повышение из списка ниже.\n"
            "2. В форме укажите ФИО, Discord ID, паспорт.\n"
            "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
            "4. Дополнительно можете указать ссылки для баллов ОРЛС.\n\n"
            "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
        )),
        (getattr(Config, "PROMOTION_APPLY_CHANNEL_OSB", 0), "ОСБ", "osb", OsbPromotionApplyView(), (
            "📋 **Рапорты на повышение ОСБ (Отдел собственной безопасности)**\n\n"
            "1. Выберите ваше повышение из списка ниже.\n"
            "2. В форме укажите ФИО, Discord ID, паспорт.\n"
            "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
            "4. Дополнительно укажите ссылки для баллов (общие и только ОСБ).\n\n"
            "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
        )),
        (getattr(Config, "PROMOTION_APPLY_CHANNEL_GROM", 0), "ГРОМ", "grom", GromPromotionApplyView(), (
            "📋 **Рапорты на повышение ОСН «Гром» (ГРОМ)**\n\n"
            "1. Выберите ваше повышение из списка ниже.\n"
            "2. В форме укажите ФИО, Discord ID, паспорт.\n"
            "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
            "4. Дополнительно укажите ссылки для баллов (общие, ГРОМ, инструкторы).\n\n"
            "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
        )),
        (getattr(Config, "PROMOTION_APPLY_CHANNEL_PPS", 0), "ППС", "pps", PpsPromotionApplyView(), (
            "📋 **Рапорты на повышение ППС**\n\n"
            "1. Выберите ваше повышение из списка ниже.\n"
            "2. В форме укажите ФИО, Discord ID, паспорт.\n"
            "3. Вставьте ссылки по обязательным критериям (по одной в строке).\n"
            "4. Дополнительно укажите ссылки для баллов (общие, ППС, инструкторы).\n\n"
            "Бот создаст рапорт с кнопками для кадровика и отдельную ветку со всеми ссылками и требованиями."
        )),
    ]


async def _ensure_promotion_messages_on_startup(guild: discord.Guild) -> None:
    if not bot.user:
        return
    for channel_id, label, dept, view, content in _promotion_setup_configs():
        if not channel_id:
            continue
        ch = guild.get_channel(channel_id)
        if not ch or not isinstance(ch, discord.TextChannel):
            continue
        try:
            last_in_channel = None
            async for m in ch.history(limit=1):
                last_in_channel = m
                break
            if last_in_channel and last_in_channel.author == bot.user and "Рапорты на повышение" in (last_in_channel.content or ""):
                continue
            await _send_promotion_message_at_bottom(ch, content, view, dept=dept)
            logger.info("При запуске создано сообщение для рапортов: %s (channel_id=%s)", label, channel_id)
        except Exception as e:
            logger.warning("Не создать сообщение для рапортов %s при запуске: %s", label, e)


@app_commands.command(
    name="promotion_setup_all",
    description="Создать сообщения «Подать рапорт» во всех каналах повышения (ОРЛС, ОСБ, ГРОМ, ППС)",
)
@app_commands.guilds(discord.Object(id=Config.GUILD_ID))
async def promotion_setup_all_slash(interaction: discord.Interaction):
    if not _slash_require_role_above_bot(interaction):
        await interaction.response.send_message(NO_ROLE_ABOVE_BOT, ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("❌ Только на сервере.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    results = []
    for channel_id, label, dept, view, content in _promotion_setup_configs():
        if not channel_id:
            continue
        ch = guild.get_channel(channel_id)
        if not ch or not isinstance(ch, discord.TextChannel):
            results.append("❌ %s: канал не найден" % label)
            continue
        try:
            await _send_promotion_message_at_bottom(ch, content, view, dept=dept)
            results.append("✅ %s" % label)
        except Exception as e:
            logger.exception("promotion_setup_all %s", label)
            results.append("❌ %s: %s" % (label, e))

    if not results:
        await interaction.followup.send(
            "Не настроено ни одного канала повышения (PROMOTION_CH_02..05 в .env).",
            ephemeral=True,
        )
        return
    await interaction.followup.send("**Готово:**\n" + "\n".join(results), ephemeral=True)


# Регистрируем команды в дереве
bot.tree.add_command(orls_promotion_setup_slash)
bot.tree.add_command(osb_promotion_setup_slash)
bot.tree.add_command(grom_promotion_setup_slash)
bot.tree.add_command(pps_promotion_setup_slash)
bot.tree.add_command(promotion_setup_all_slash)


if __name__ == "__main__":
    try:
        bot.run(Config.TOKEN, log_handler=None)
    except discord.LoginError:
        logger.critical("Неверный токен в .env")
    except Exception as e:
        logger.critical("Критическая ошибка: %s", e, exc_info=True)