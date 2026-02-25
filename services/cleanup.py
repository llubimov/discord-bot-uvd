"""
Очистка старых заявок.
Удаляет заявки старше REQUEST_EXPIRY_DAYS из памяти и БД.
"""

import logging
import asyncio
from datetime import datetime, timedelta

import state
from config import Config
from database import cleanup_old_requests_db

logger = logging.getLogger(__name__)


class CleanupManager:
    """Менеджер периодической очистки старых заявок"""

    def __init__(self, bot):
        self.bot = bot
        self.check_interval = 3600  # раз в час

    def _cleanup_store_by_date(self, store: dict, name: str, cutoff: datetime) -> int:
        """Очистка словаря в памяти по created_at"""
        if not store:
            return 0

        to_delete = []
        for mid, data in list(store.items()):
            created = (data or {}).get("created_at")
            if not created:
                to_delete.append(mid)
                continue

            try:
                if datetime.fromisoformat(created) < cutoff:
                    to_delete.append(mid)
            except (ValueError, TypeError):
                to_delete.append(mid)

        for mid in to_delete:
            store.pop(mid, None)

        if to_delete:
            logger.info("🧹 Очищено %s старых записей: %s", len(to_delete), name)

        return len(to_delete)

    async def cleanup(self):
        """Выполняет очистку памяти + БД"""
        try:
            cutoff = datetime.now() - timedelta(days=Config.REQUEST_EXPIRY_DAYS)

            # Очистка памяти
            self._cleanup_store_by_date(getattr(state, "active_requests", {}), "заявки", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_firing_requests", {}), "увольнения", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_promotion_requests", {}), "повышения", cutoff)
            self._cleanup_store_by_date(getattr(state, "warehouse_requests", {}), "склад", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_department_transfers", {}), "переводы отделов", cutoff)

            # Очистка БД (все таблицы, включая department_transfer_requests)
            await asyncio.to_thread(cleanup_old_requests_db, Config.REQUEST_EXPIRY_DAYS)

            logger.info("🧹 Периодическая очистка завершена")

        except Exception as e:
            logger.error("Ошибка при очистке: %s", e, exc_info=True)

    async def start_cleanup(self):
        """Запускает периодическую очистку"""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            await self.cleanup()
            await asyncio.sleep(self.check_interval)