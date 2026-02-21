"""
====
УПРАВЛЕНИЕ ПОЗИЦИЕЙ СТАРТОВОГО СООБЩЕНИЯ
Следит чтобы кнопки "Курсант/Перевод/Гос" были внизу
====
"""

import logging
import asyncio
from datetime import datetime, timedelta
import discord
from config import Config
from views.message_texts import StartMessages
from views.start_view import StartView
import state

logger = logging.getLogger(__name__)

class StartPositionManager:
    """Менеджер позиции стартового сообщения с кнопками"""
    
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = Config.START_CHANNEL_ID
        self.message_id = None
        self.is_updating = False
        self.check_interval = Config.START_MESSAGE_CHECK_INTERVAL
    
    async def ensure_position(self):
        """Проверяет и перемещает сообщение если нужно"""
        if self.is_updating:
            return
        
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return
        
        try:
            self.is_updating = True
            
            # Находим текущее сообщение
            current_message = None
            if self.message_id:
                try:
                    current_message = await channel.fetch_message(self.message_id)
                except:
                    self.message_id = None
            
            # Находим последнее сообщение
            last_message = None
            async for msg in channel.history(limit=1):
                last_message = msg
                break
            
            # Проверяем нужно ли обновлять
            need_update = False
            if not current_message:
                need_update = True
            elif last_message and current_message.id != last_message.id:
                need_update = True
            elif len(current_message.components) == 0:
                need_update = True
            
            if not need_update:
                return
            
            # Создаем новое сообщение
            embed = discord.Embed(
                title=StartMessages.TITLE,
                description=StartMessages.DESCRIPTION.format(
                    cooldown=Config.REQUEST_COOLDOWN,
                    expiry_days=Config.REQUEST_EXPIRY_DAYS
                ),
                color=discord.Color.gold()
            )
            
            view = StartView()
            
            if current_message:
                await current_message.delete()
            
            new_message = await channel.send(embed=embed, view=view)
            self.message_id = new_message.id
            
            # Удаляем дубликаты
            async for msg in channel.history(limit=50):
                if (msg.author == self.bot.user and 
                    msg.id != self.message_id and 
                    msg.embeds and 
                    msg.embeds[0].title == StartMessages.TITLE):
                    await msg.delete()
            
            logger.info("🔄 Стартовое сообщение обновлено")
            
        except Exception as e:
            logger.error(f"Ошибка в ensure_position: {e}")
        finally:
            self.is_updating = False
    
    async def start_checking(self):
        """Запускает периодическую проверку"""
        await self.bot.wait_until_ready()
        
        # Первая проверка
        await self.ensure_position()
        
        # Дальше с интервалом
        while not self.bot.is_closed():
            await asyncio.sleep(self.check_interval)
            await self.ensure_position()