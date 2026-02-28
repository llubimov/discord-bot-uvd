from typing import Dict, Any, Optional
import discord
from discord.ext import commands

# Глобальные объекты
bot: Optional[commands.Bot] = None  # Теперь с правильным типом
active_requests: Dict[int, Dict] = {}
active_firing_requests: Dict[int, Dict] = {}
active_promotion_requests: Dict[int, Dict] = {}
# Черновики рапортов ОРЛС: user_id -> { channel_id, message_id, promotion_key, full_name, discord_id, passport, requirement_links: {1:[urls]}, bonus_links: {type:[urls]} }
orls_draft_reports: Dict[int, Dict] = {}
# Последние введённые данные по user_id для автоподстановки в следующем рапорте
orls_last_user_data: Dict[int, Dict[str, str]] = {}
# Черновики рапортов ОСБ (то же устройство)
osb_draft_reports: Dict[int, Dict] = {}
osb_last_user_data: Dict[int, Dict[str, str]] = {}
# Черновики рапортов ГРОМ (ОСН "Гром")
grom_draft_reports: Dict[int, Dict] = {}
grom_last_user_data: Dict[int, Dict[str, str]] = {}
# Черновики рапортов ППС
pps_draft_reports: Dict[int, Dict] = {}
pps_last_user_data: Dict[int, Dict[str, str]] = {}
role_cache = None
channel_cache = None
warehouse_requests: Dict[int, Dict] = {}  # Для заявок склада
active_department_transfers: Dict[int, Dict[str, Any]] = {}  # Заявки на перевод между отделами

# Сообщения «подача рапорта» по каналам: channel_id -> [{"message_id", "dept", "content"}, ...]
# Используется, чтобы держать их внизу канала при новом сообщении
promotion_setup_messages: Dict[int, list] = {}
# Кулдаун переноса (секунды), чтобы не спамить при частых сообщениях
promotion_setup_move_cooldown: Dict[int, float] = {}