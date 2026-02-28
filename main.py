#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dotenv import load_dotenv
load_dotenv()

from utils.env_check import validate_env
validate_env()

import discord
from discord.ext import commands
import logging
from logging.handlers import RotatingFileHandler

import state
from config import Config

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

intents = discord.Intents.default()
intents.message_content = Config.ENABLE_MESSAGE_CONTENT_INTENT
intents.members = True

bot = commands.Bot(
    command_prefix=Config.COMMAND_PREFIX,
    intents=intents,
    max_messages=Config.BOT_MAX_MESSAGES if Config.BOT_MAX_MESSAGES > 0 else None,
)
state.bot = bot

from services.cache import ChannelCache, RoleCache
from services.cleanup import CleanupManager
from services.firing_position_manager import FiringPositionManager
from services.position_apply_academy import AcademyApplyPositionManager
from services.position_apply_grom import ApplyGromPositionManager
from services.position_apply_orls import ApplyOrlsPositionManager
from services.position_apply_osb import ApplyOsbPositionManager
from services.position_apply_pps import ApplyPpsPositionManager
from services.position_admin_transfer import AdminTransferPositionManager
from services.restore_views import ViewRestorer
from services.start_position_manager import StartPositionManager
from services.warehouse_position_manager import WarehousePositionManager
from services.webhook_handler import WebhookHandler
from services.worker_queue import get_worker, init_worker

state.role_cache = RoleCache(bot)
state.channel_cache = ChannelCache(bot)
state.webhook_handler = WebhookHandler(bot)
state.start_manager = StartPositionManager(bot)
state.warehouse_position_manager = WarehousePositionManager(bot)
state.cleanup_manager = CleanupManager(bot)
init_worker()
state.view_restorer = ViewRestorer(bot)
state.apply_grom_manager = ApplyGromPositionManager(bot)
state.apply_pps_manager = ApplyPpsPositionManager(bot)
state.apply_osb_manager = ApplyOsbPositionManager(bot)
state.apply_orls_manager = ApplyOrlsPositionManager(bot)
state.academy_apply_manager = AcademyApplyPositionManager(bot)
state.admin_transfer_manager = AdminTransferPositionManager(bot)
state.firing_position_manager = FiringPositionManager(bot)

if not hasattr(state, "background_tasks") or not isinstance(getattr(state, "background_tasks", None), dict):
    state.background_tasks = {}

try:
    from services import warehouse_cooldown
    state.warehouse_cooldown = warehouse_cooldown
except Exception as e:
    logger.warning("warehouse_cooldown не загружен: %s", e)

from events import register_events
from commands.admin import register_admin_commands
from commands.promotion_setup import register_promotion_setup_commands

register_events(bot)
register_admin_commands(bot)
register_promotion_setup_commands(bot)

if __name__ == "__main__":
    try:
        bot.run(Config.TOKEN, log_handler=None)
    except discord.LoginError:
        logger.critical("Неверный токен в .env")
    except Exception as e:
        logger.critical("Критическая ошибка: %s", e, exc_info=True)
