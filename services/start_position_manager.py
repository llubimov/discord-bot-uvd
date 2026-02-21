"""
=====================================================
МЕНЕДЖЕР ПОЗИЦИИ СТАРТОВОГО СООБЩЕНИЯ (ЗАЯВКИ)
=====================================================
"""

import discord
from config import Config
from views.message_texts import StartMessages
from views.start_view import StartView
from .base_position import BasePositionManager

class StartPositionManager(BasePositionManager):
    """Менеджер для кнопок заявок (Курсант/Перевод/Гос)"""
    
    @property
    def channel_id(self) -> int:
        return Config.START_CHANNEL_ID
    
    @property
    def check_interval(self) -> int:
        return Config.START_MESSAGE_CHECK_INTERVAL
    
    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=StartMessages.TITLE,
            description=StartMessages.DESCRIPTION.format(
                cooldown=Config.REQUEST_COOLDOWN,
                expiry_days=Config.REQUEST_EXPIRY_DAYS
            ),
            color=discord.Color.gold()
        )
        return embed
    
    async def get_view(self) -> discord.ui.View:
        return StartView()
    
    async def should_keep_message(self, message: discord.Message) -> bool:
        """Проверяем что это наше стартовое сообщение"""
        return (message.embeds and 
                message.embeds[0].title == StartMessages.TITLE)