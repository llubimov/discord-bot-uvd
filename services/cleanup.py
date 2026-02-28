import logging
import asyncio
from datetime import datetime, timedelta

import state
from config import Config
from database import cleanup_old_requests_db, cleanup_old_orls_drafts, cleanup_old_osb_drafts, cleanup_old_grom_drafts, cleanup_old_pps_drafts

logger = logging.getLogger(__name__)


class CleanupManager:

    def __init__(self, bot):
        self.bot = bot
        self.check_interval = 3600  # раз в час

    def _cleanup_store_by_date(self, store: dict, name: str, cutoff: datetime) -> int:
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
        try:
            cutoff = datetime.now() - timedelta(days=Config.REQUEST_EXPIRY_DAYS)

            # Память: заявки, увольнения, повышения, склад, переводы отделов
            self._cleanup_store_by_date(getattr(state, "active_requests", {}), "заявки", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_firing_requests", {}), "увольнения", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_promotion_requests", {}), "повышения", cutoff)
            self._cleanup_store_by_date(getattr(state, "warehouse_requests", {}), "склад", cutoff)
            self._cleanup_store_by_date(getattr(state, "active_department_transfers", {}), "переводы отделов", cutoff)

            # БД: все таблицы (requests, firing_requests, promotion_requests, warehouse_requests, department_transfer_requests)
            await asyncio.to_thread(cleanup_old_requests_db, Config.REQUEST_EXPIRY_DAYS)

            # Черновики рапортов ОРЛС: удалить старше N дней (из конфига)
            orls_days = getattr(Config, "ORLS_DRAFT_EXPIRY_DAYS", 14)
            orls_deleted = await asyncio.to_thread(cleanup_old_orls_drafts, orls_days)
            if orls_deleted:
                logger.info("🧹 Удалено черновиков ОРЛС (старше %s дней): %s", orls_days, orls_deleted)

            # Черновики рапортов ОСБ
            osb_days = getattr(Config, "OSB_DRAFT_EXPIRY_DAYS", 14)
            osb_deleted = await asyncio.to_thread(cleanup_old_osb_drafts, osb_days)
            if osb_deleted:
                logger.info("🧹 Удалено черновиков ОСБ (старше %s дней): %s", osb_days, osb_deleted)

            # Черновики рапортов ГРОМ
            grom_days = getattr(Config, "GROM_DRAFT_EXPIRY_DAYS", 14)
            grom_deleted = await asyncio.to_thread(cleanup_old_grom_drafts, grom_days)
            if grom_deleted:
                logger.info("🧹 Удалено черновиков ГРОМ (старше %s дней): %s", grom_days, grom_deleted)

            # Черновики рапортов ППС
            pps_days = getattr(Config, "PPS_DRAFT_EXPIRY_DAYS", 14)
            pps_deleted = await asyncio.to_thread(cleanup_old_pps_drafts, pps_days)
            if pps_deleted:
                logger.info("🧹 Удалено черновиков ППС (старше %s дней): %s", pps_days, pps_deleted)

            # Просроченные сессии корзины склада (редактирование/выдача)
            try:
                from services.warehouse_session import WarehouseSession
                purged = WarehouseSession.purge_expired(max_age_hours=24)
                if purged:
                    logger.info("🧹 Очищено просроченных сессий склада: %s", purged)
            except Exception as e:
                logger.warning("Очистка сессий склада: %s", e)

            logger.info("🧹 Периодическая очистка завершена")

        except Exception as e:
            logger.error("Ошибка при очистке: %s", e, exc_info=True)

    async def start_cleanup(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            await self.cleanup()
            await asyncio.sleep(self.check_interval)