from datetime import datetime, timedelta
import logging
from typing import Dict, Optional
from config import Config

logger = logging.getLogger(__name__)

class WarehouseCooldown:

    def __init__(self):
        # {user_id: datetime последней выдачи}
        self.last_issue: Dict[int, datetime] = {}
        self.cooldown_hours = Config.WAREHOUSE_COOLDOWN_HOURS
    
    def can_issue(self, user_id: int) -> tuple[bool, Optional[str]]:
        if user_id not in self.last_issue:
            return True, None
        
        last_time = self.last_issue[user_id]
        next_available = last_time + timedelta(hours=self.cooldown_hours)
        
        if datetime.now() >= next_available:
            return True, None
        
        # Сколько осталось ждать
        wait_time = next_available - datetime.now()
        hours = int(wait_time.total_seconds() // 3600)
        minutes = int((wait_time.total_seconds() % 3600) // 60)
        
        if hours > 0:
            return False, f"⏰ Следующая выдача возможна через **{hours} ч {minutes} мин**"
        else:
            return False, f"⏰ Следующая выдача возможна через **{minutes} мин**"
    
    def register_issue(self, user_id: int):
        self.last_issue[user_id] = datetime.now()
        logger.info(f"✅ Кулдаун установлен для {user_id} до {self.last_issue[user_id] + timedelta(hours=self.cooldown_hours)}")
    
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
            logger.info(f"🔄 Кулдаун сброшен для {user_id}")