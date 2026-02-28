from typing import Dict, Any, Optional
import discord
from discord.ext import commands

bot: Optional[commands.Bot] = None  # Теперь с правильным типом
active_requests: Dict[int, Dict] = {}
active_firing_requests: Dict[int, Dict] = {}
active_promotion_requests: Dict[int, Dict] = {}
orls_draft_reports: Dict[int, Dict] = {}
orls_last_user_data: Dict[int, Dict[str, str]] = {}
osb_draft_reports: Dict[int, Dict] = {}
osb_last_user_data: Dict[int, Dict[str, str]] = {}
grom_draft_reports: Dict[int, Dict] = {}
grom_last_user_data: Dict[int, Dict[str, str]] = {}
pps_draft_reports: Dict[int, Dict] = {}
pps_last_user_data: Dict[int, Dict[str, str]] = {}
role_cache = None
channel_cache = None
warehouse_requests: Dict[int, Dict] = {}  # Для заявок склада
active_department_transfers: Dict[int, Dict[str, Any]] = {}  # Заявки на перевод между отделами

promotion_setup_messages: Dict[int, list] = {}
promotion_setup_move_cooldown: Dict[int, float] = {}