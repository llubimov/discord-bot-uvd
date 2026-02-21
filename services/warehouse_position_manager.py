"""
=====================================================
МЕНЕДЖЕР ПОЗИЦИИ КНОПОК СКЛАДА
=====================================================
"""

import discord
from config import Config
from views.message_texts import WarehouseMessages
from views.warehouse_start import WarehouseStartView
from .base_position import BasePositionManager

class WarehousePositionManager(BasePositionManager):
    """Менеджер для кнопок склада"""
    
    @property
    def channel_id(self) -> int:
        return Config.WAREHOUSE_REQUEST_CHANNEL_ID
    
    @property
    def check_interval(self) -> int:
        return 30  # Проверка каждые 30 секунд (как и было)
    
    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=WarehouseMessages.START_TITLE,
            description=WarehouseMessages.START_DESCRIPTION,
            color=discord.Color.blue()
        )
        return embed
    
    async def get_view(self) -> discord.ui.View:
        return WarehouseStartView()
    
    async def should_keep_message(self, message: discord.Message) -> bool:
        """Проверяем что это наше сообщение склада"""
        return (message.embeds and 
                message.embeds[0].title == WarehouseMessages.START_TITLE)