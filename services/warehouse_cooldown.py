from datetime import datetime, timedelta
import logging
from typing import Dict, Optional
from config import Config

logger = logging.getLogger(__name__)


class WarehouseCooldown:

    def __init__(self):
        self.last_issue: Dict[int, datetime] = {}
        self.cooldown_hours = Config.WAREHOUSE_COOLDOWN_HOURS

    async def load_from_db(self) -> None:
        try:
            from database import warehouse_cooldown_get_all
            self.last_issue = await warehouse_cooldown_get_all()
            if self.last_issue:
                logger.info("WarehouseCooldown: загружено %s записей из БД", len(self.last_issue))
        except Exception as e:
            logger.warning("WarehouseCooldown load_from_db: %s", e)

    def can_issue(self, user_id: int) -> tuple[bool, Optional[str]]:
        if user_id not in self.last_issue:
            return True, None

        last_time = self.last_issue[user_id]
        next_available = last_time + timedelta(hours=self.cooldown_hours)

        if datetime.now() >= next_available:
            return True, None

        wait_time = next_available - datetime.now()
        hours = int(wait_time.total_seconds() // 3600)
        minutes = int((wait_time.total_seconds() % 3600) // 60)

        if hours > 0:
            return False, f"⏰ Следующая выдача возможна через **{hours} ч {minutes} мин**"
        else:
            return False, f"⏰ Следующая выдача возможна через **{minutes} мин**"

    def register_issue(self, user_id: int):
        self.last_issue[user_id] = datetime.now()
        logger.info("✅ Кулдаун установлен для %s до %s", user_id, self.last_issue[user_id] + timedelta(hours=self.cooldown_hours))
        try:
            from services.worker_queue import get_worker
            from database import warehouse_cooldown_set
            get_worker().submit_fire(warehouse_cooldown_set(user_id, self.last_issue[user_id]))
        except Exception as e:
            logger.debug("WarehouseCooldown persist: %s", e)

    def get_remaining_time(self, user_id: int) -> Optional[str]:
        if user_id not in self.last_issue:
            return None

        next_available = self.last_issue[user_id] + timedelta(hours=self.cooldown_hours)
        if datetime.now() >= next_available:
            return None

        wait_time = next_available - datetime.now()
        hours = int(wait_time.total_seconds() // 3600)
        minutes = int((wait_time.total_seconds() % 3600) // 60)

        if hours > 0:
            return f"{hours} ч {minutes} мин"
        else:
            return f"{minutes} мин"

    def clear_user(self, user_id: int):
        if user_id in self.last_issue:
            del self.last_issue[user_id]
            logger.info("🔄 Кулдаун сброшен для %s", user_id)
        try:
            from services.worker_queue import get_worker
            from database import warehouse_cooldown_clear
            get_worker().submit_fire(warehouse_cooldown_clear(user_id))
        except Exception as e:
            logger.debug("WarehouseCooldown clear persist: %s", e)