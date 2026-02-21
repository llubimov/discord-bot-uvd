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
        # Важно: SQLite синхронный — выносим в отдельный поток
        state.active_requests = await asyncio.to_thread(load_all_requests)
        state.active_firing_requests = await asyncio.to_thread(load_all_firing_requests)
        state.active_promotion_requests = await asyncio.to_thread(load_all_promotion_requests)
        state.warehouse_requests = await asyncio.to_thread(load_all_warehouse_requests)

        logger.info(
            "📦 Загружено из БД: заявок=%s, увольнений=%s, повышений=%s, склад=%s",
            len(getattr(state, "active_requests", {}) or {}),
            len(getattr(state, "active_firing_requests", {}) or {}),
            len(getattr(state, "active_promotion_requests", {}) or {}),
            len(getattr(state, "warehouse_requests", {}) or {}),
        )

    async def _delete_orphan(self, storage: dict, table_name: str, msg_id, reason: str = ""):
        """Удаляет битую/осиротевшую запись из памяти и БД."""
        try:
            msg_id_int = int(msg_id)
        except (TypeError, ValueError):
            logger.warning("⚠️ Некорректный message_id для удаления (%s): %r", table_name, msg_id)
            return False

        storage.pop(msg_id_int, None)
        try:
            await asyncio.to_thread(delete_request, table_name, msg_id_int)
            logger.info("🧹 Удалена осиротевшая запись %s msg_id=%s %s", table_name, msg_id_int, f"({reason})" if reason else "")
            return True
        except Exception as e:
            logger.error("❌ Не удалось удалить запись %s msg_id=%s: %s", table_name, msg_id_int, e, exc_info=True)
            return False

    async def _restore_request_views(self):
        restored = 0
        skipped = 0

        for msg_id, data in list((getattr(state, "active_requests", {}) or {}).items()):
            try:
                msg_id_int = int(msg_id)
            except (TypeError, ValueError):
                logger.warning("⚠️ Битый message_id в active_requests: %r", msg_id)
                skipped += 1
                continue

            rt_raw = str((data or {}).get("request_type") or "").strip().lower()
            if not rt_raw:
                logger.warning("⚠️ Пустой request_type для msg_id=%s", msg_id_int)
                skipped += 1
                continue

            try:
                request_type = RequestType(rt_raw)
            except ValueError:
                logger.warning("⚠️ Неизвестный request_type='%s' для message_id=%s", rt_raw, msg_id_int)
                skipped += 1
                continue

            try:
                user_id = int((data or {}).get("user_id", 0))
                if not user_id:
                    logger.warning("⚠️ Некорректный user_id для msg_id=%s", msg_id_int)
                    skipped += 1
                    continue

                view = RequestView(
                    user_id=user_id,
                    validated_data=data,
                    request_type=request_type,
                )
                self.bot.add_view(view, message_id=msg_id_int)
                restored += 1

            except (TypeError, ValueError) as e:
                logger.warning("⚠️ Некорректные данные заявки msg_id=%s: %s", msg_id_int, e)
                skipped += 1
            except Exception as e:
                logger.warning("⚠️ Не удалось восстановить заявку msg_id=%s: %s", msg_id_int, e, exc_info=True)
                skipped += 1

        logger.info("🔨 Восстановлено кнопок заявок: %s | пропущено: %s", restored, skipped)

    async def _restore_firing_views(self):
        channel = self.bot.get_channel(Config.FIRING_CHANNEL_ID)
        if not channel:
            logger.warning("⚠️ Канал увольнений не найден: %s", Config.FIRING_CHANNEL_ID)
            return

        restored = 0
        deleted = 0
        skipped = 0

        for msg_id, data in list((getattr(state, "active_firing_requests", {}) or {}).items()):
            try:
                msg_id_int = int(msg_id)
                user_id = int((data or {}).get("discord_id", 0))
            except (TypeError, ValueError):
                logger.warning("⚠️ Битые данные увольнения msg_id=%r", msg_id)
                if await self._delete_orphan(state.active_firing_requests, "firing_requests", msg_id, "битый ID/данные"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            if not user_id:
                logger.warning("⚠️ Пустой discord_id в увольнении msg_id=%s", msg_id_int)
                if await self._delete_orphan(state.active_firing_requests, "firing_requests", msg_id_int, "пустой discord_id"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            try:
                await channel.fetch_message(msg_id_int)
            except discord.NotFound:
                if await self._delete_orphan(state.active_firing_requests, "firing_requests", msg_id_int, "сообщение удалено"):
                    deleted += 1
                else:
                    skipped += 1
                continue
            except discord.Forbidden:
                logger.warning("⚠️ Нет доступа к сообщению увольнения msg_id=%s", msg_id_int)
                skipped += 1
                continue
            except discord.HTTPException as e:
                logger.warning("⚠️ HTTP ошибка при fetch увольнения msg_id=%s: %s", msg_id_int, e)
                skipped += 1
                continue

            try:
                view = FiringView(user_id=user_id)
                self.bot.add_view(view, message_id=msg_id_int)
                restored += 1
            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления увольнения msg_id=%s: %s", msg_id_int, e, exc_info=True)
                skipped += 1

        logger.info(
            "🔨 Восстановлено кнопок увольнений: %s | удалено из БД: %s | пропущено: %s",
            restored, deleted, skipped
        )

    async def _restore_promotion_views(self):
        restored = 0
        deleted = 0
        skipped = 0

        channel_ids = list(Config.PROMOTION_CHANNELS.keys()) if isinstance(Config.PROMOTION_CHANNELS, dict) else []
        channels = {cid: self.bot.get_channel(cid) for cid in channel_ids}

        for msg_id, data in list((getattr(state, "active_promotion_requests", {}) or {}).items()):
            try:
                msg_id_int = int(msg_id)
                discord_id = int((data or {}).get("discord_id", 0))
                new_rank = str((data or {}).get("new_rank") or "").strip()
                full_name = str((data or {}).get("full_name") or "сотрудник").strip() or "сотрудник"
            except (TypeError, ValueError):
                logger.warning("⚠️ Битые данные повышения msg_id=%r", msg_id)
                if await self._delete_orphan(state.active_promotion_requests, "promotion_requests", msg_id, "битый ID/данные"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            if not discord_id or not new_rank:
                logger.warning("⚠️ Некорректные данные повышения msg_id=%s (discord_id/new_rank)", msg_id_int)
                if await self._delete_orphan(state.active_promotion_requests, "promotion_requests", msg_id_int, "нет discord_id/new_rank"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            found = False
            for _, ch in channels.items():
                if not ch:
                    continue
                try:
                    await ch.fetch_message(msg_id_int)
                    found = True
                    break
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    logger.warning("⚠️ Нет доступа к каналу повышения при проверке msg_id=%s", msg_id_int)
                    continue
                except discord.HTTPException:
                    continue

            if not found:
                if await self._delete_orphan(state.active_promotion_requests, "promotion_requests", msg_id_int, "сообщение удалено"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            try:
                view = PromotionView(
                    user_id=discord_id,
                    new_rank=new_rank,
                    full_name=full_name,
                    message_id=msg_id_int,
                )
                self.bot.add_view(view, message_id=msg_id_int)
                restored += 1
            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления повышения msg_id=%s: %s", msg_id_int, e, exc_info=True)
                skipped += 1

        logger.info(
            "🔨 Восстановлено кнопок повышений: %s | удалено из БД: %s | пропущено: %s",
            restored, deleted, skipped
        )

    async def _restore_warehouse_views(self):
        channel = self.bot.get_channel(Config.WAREHOUSE_REQUEST_CHANNEL_ID)
        if not channel:
            logger.warning("⚠️ Канал склада не найден: %s", Config.WAREHOUSE_REQUEST_CHANNEL_ID)
            return

        restored = 0
        deleted = 0
        skipped = 0

        for msg_id, data in list((getattr(state, "warehouse_requests", {}) or {}).items()):
            try:
                msg_id_int = int(msg_id)
                user_id = int((data or {}).get("user_id", 0))
            except (TypeError, ValueError):
                logger.warning("⚠️ Битые данные склада msg_id=%r", msg_id)
                if await self._delete_orphan(state.warehouse_requests, "warehouse_requests", msg_id, "битый ID/данные"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            if not user_id:
                logger.warning("⚠️ Пустой user_id в заявке склада msg_id=%s", msg_id_int)
                if await self._delete_orphan(state.warehouse_requests, "warehouse_requests", msg_id_int, "пустой user_id"):
                    deleted += 1
                else:
                    skipped += 1
                continue

            try:
                await channel.fetch_message(msg_id_int)
            except discord.NotFound:
                if await self._delete_orphan(state.warehouse_requests, "warehouse_requests", msg_id_int, "сообщение удалено"):
                    deleted += 1
                else:
                    skipped += 1
                continue
            except discord.Forbidden:
                logger.warning("⚠️ Нет доступа к сообщению склада msg_id=%s", msg_id_int)
                skipped += 1
                continue
            except discord.HTTPException as e:
                logger.warning("⚠️ HTTP ошибка при fetch склада msg_id=%s: %s", msg_id_int, e)
                skipped += 1
                continue

            try:
                view = WarehouseRequestView(author_id=user_id, message_id=msg_id_int)
                self.bot.add_view(view, message_id=msg_id_int)
                restored += 1
            except Exception as e:
                logger.warning("⚠️ Ошибка восстановления склада msg_id=%s: %s", msg_id_int, e, exc_info=True)
                skipped += 1

        logger.info(
            "🔨 Восстановлено кнопок склада: %s | удалено из БД: %s | пропущено: %s",
            restored, deleted, skipped
        )