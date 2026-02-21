import logging
import asyncio
import discord

from views.firing_view import FiringView
from views.promotion_view import PromotionView
from views.start_view import StartView
from views.warehouse_start import WarehouseStartView
from views.request_view import RequestView
from views.warehouse_request_buttons import WarehouseRequestView

import state
from config import Config
from enums import RequestType
from database import (
    load_all_requests,
    load_all_firing_requests,
    load_all_promotion_requests,
    load_all_warehouse_requests,
    delete_request,
)

logger = logging.getLogger(__name__)


class ViewRestorer:
    def __init__(self, bot):
        self.bot = bot

    async def restore_all(self):
        logger.info("🔄 Начинаем восстановление View...")

        self._restore_start_views()
        await self._load_requests_from_db()

        await self._restore_request_views()
        await self._restore_firing_views()
        await self._restore_promotion_views()
        await self._restore_warehouse_views()

        logger.info("✅ Восстановление View завершено")

    def _restore_start_views(self):
        self.bot.add_view(StartView())
        self.bot.add_view(WarehouseStartView())
        logger.info("🔄 Стартовые View восстановлены")

    async def _load_requests_from_db(self):
        state.active_requests = load_all_requests()
        state.active_firing_requests = load_all_firing_requests()
        state.active_promotion_requests = load_all_promotion_requests()
        state.warehouse_requests = load_all_warehouse_requests()

        logger.info(
            "📦 Загружено из БД: заявок=%s, увольнений=%s, повышений=%s, склад=%s",
            len(state.active_requests),
            len(state.active_firing_requests),
            len(state.active_promotion_requests),
            len(state.warehouse_requests),
        )

    async def _restore_request_views(self):
        restored = 0

        for msg_id, data in list(state.active_requests.items()):
            rt_raw = (data.get("request_type") or "").strip().lower()

            try:
                request_type = RequestType(rt_raw)
            except Exception:
                logger.warning("⚠️ Неизвестный request_type='%s' для message_id=%s", rt_raw, msg_id)
                continue

            try:
                view = RequestView(
                    user_id=int(data["user_id"]),
                    validated_data=data,
                    request_type=request_type,
                )
                self.bot.add_view(view, message_id=int(msg_id))
                restored += 1
            except Exception as e:
                logger.warning("⚠️ Не удалось восстановить заявку msg_id=%s: %s", msg_id, e)

        logger.info("🔨 Восстановлено кнопок заявок: %s", restored)

    async def _restore_firing_views(self):
        channel = self.bot.get_channel(Config.FIRING_CHANNEL_ID)
        if not channel:
            logger.warning("⚠️ Канал увольнений не найден: %s", Config.FIRING_CHANNEL_ID)
            return

        restored = 0
        deleted = 0

        for msg_id, data in list(state.active_firing_requests.items()):
            try:
                user_id = int(data.get("discord_id", 0))
                if not user_id:
                    continue

                try:
                    await channel.fetch_message(int(msg_id))
                except discord.NotFound:
                    state.active_firing_requests.pop(int(msg_id), None)
                    await asyncio.to_thread(delete_request, "firing_requests", int(msg_id))
                    deleted += 1
                    continue
                except Exception as e:
                    logger.warning("⚠️ Не удалось получить сообщение увольнения msg_id=%s: %s", msg_id, e)
                    continue

                view = FiringView(user_id=user_id)
                self.bot.add_view(view, message_id=int(msg_id))
                restored += 1

            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления увольнения msg_id=%s: %s", msg_id, e)

        logger.info("🔨 Восстановлено кнопок увольнений: %s | удалено из БД: %s", restored, deleted)

    async def _restore_promotion_views(self):
        restored = 0
        deleted = 0

        channel_ids = list(Config.PROMOTION_CHANNELS.keys()) if isinstance(Config.PROMOTION_CHANNELS, dict) else []
        channels = {cid: self.bot.get_channel(cid) for cid in channel_ids}

        for msg_id, data in list(state.active_promotion_requests.items()):
            try:
                discord_id = int(data.get("discord_id", 0))
                new_rank = (data.get("new_rank") or "").strip()
                full_name = (data.get("full_name") or "сотрудник").strip()

                if not discord_id or not new_rank:
                    continue

                found = False
                for _, ch in channels.items():
                    if not ch:
                        continue
                    try:
                        await ch.fetch_message(int(msg_id))
                        found = True
                        break
                    except discord.NotFound:
                        continue
                    except Exception:
                        continue

                if not found:
                    state.active_promotion_requests.pop(int(msg_id), None)
                    await asyncio.to_thread(delete_request, "promotion_requests", int(msg_id))
                    deleted += 1
                    continue

                view = PromotionView(
                    user_id=discord_id,
                    new_rank=new_rank,
                    full_name=full_name,
                    message_id=int(msg_id),
                )
                self.bot.add_view(view, message_id=int(msg_id))
                restored += 1

            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления повышения msg_id=%s: %s", msg_id, e)

        logger.info("🔨 Восстановлено кнопок повышений: %s | удалено из БД: %s", restored, deleted)

    async def _restore_warehouse_views(self):
        channel = self.bot.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        if not channel:
            logger.warning("⚠️ Канал склада не найден: %s", Config.WAREHOUSE_REQUEST_CHANNEL_ID)
            return

        restored = 0
        deleted = 0

        for msg_id, data in list(state.warehouse_requests.items()):
            try:
                user_id = int(data.get("user_id", 0))
                if not user_id:
                    continue

                try:
                    await channel.fetch_message(int(msg_id))
                except discord.NotFound:
                    state.warehouse_requests.pop(int(msg_id), None)
                    await asyncio.to_thread(delete_request, "warehouse_requests", int(msg_id))
                    deleted += 1
                    continue
                except Exception as e:
                    logger.warning("⚠️ Не удалось получить сообщение склада msg_id=%s: %s", msg_id, e)
                    continue

                view = WarehouseRequestView(author_id=user_id, message_id=int(msg_id))
                self.bot.add_view(view, message_id=int(msg_id))
                restored += 1

            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления склада msg_id=%s: %s", msg_id, e)

        logger.info("🔨 Восстановлено кнопок склада: %s | удалено из БД: %s", restored, deleted)