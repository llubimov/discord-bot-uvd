from typing import Dict, Any, Optional
import discord
from discord.ext import commands

# Глобальные объекты
bot: Optional[commands.Bot] = None  # Теперь с правильным типом
active_requests: Dict[int, Dict] = {}
active_firing_requests: Dict[int, Dict] = {}
active_promotion_requests: Dict[int, Dict] = {}
role_cache = None
channel_cache = None
warehouse_requests: Dict[int, Dict] = {}  # Для заявок склада
active_department_transfers: Dict[int, Dict[str, Any]] = {}  # Заявки на перевод между отделами