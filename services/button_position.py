"""
====
СЛЕЖЕНИЕ ЗА ПОЗИЦИЕЙ КНОПОК СКЛАДА
Кнопки всегда должны быть последним сообщением в чате
====
"""

import logging
import asyncio
import discord
from config import Config
from views.warehouse_start import WarehouseStartView
from views.message_texts import WarehouseMessages

logger = logging.getLogger(__name__)

class ButtonPositionManager:
    """Менеджер позиции кнопок склада"""
    
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = Config.WAREHOUSE_REQUEST_CHANNEL_ID
        self.message_id = None
        self.check_interval = 30  # 3 минуты
    
    async def find_warehouse_message(self, channel):
        """Ищет наше сообщение с кнопками в канале"""
        async for msg in channel.history(limit=50):
            if msg.author == self.bot.user and msg.embeds:
                embed = msg.embeds[0]
                if embed.title == WarehouseMessages.START_TITLE:
                    return msg
        return None
    
    async def ensure_position(self):
        """Проверяет и перемещает кнопки если надо"""
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            return
        
        try:
            # Находим наше сообщение
            our_message = await self.find_warehouse_message(channel)
            
            # Находим последнее сообщение в канале
            last_message = None
            async for msg in channel.history(limit=1):
                last_message = msg
                break
            
            # Проверяем нужно ли обновлять
            need_update = False
            
            if not our_message:
                need_update = True
                logger.info("Кнопки склада не найдены - создаем")
            elif last_message and our_message.id != last_message.id:
                need_update = True
                logger.info("Кнопки склада не внизу - перемещаем")
            elif len(our_message.components) == 0:
                need_update = True
                logger.info("Кнопки склада пропали - восстанавливаем")
            
            if need_update:
                # Удаляем старое сообщение если есть
                if our_message:
                    await our_message.delete()
                
                # Создаем новое внизу
                embed = discord.Embed(
                    title=WarehouseMessages.START_TITLE,
                    description=WarehouseMessages.START_DESCRIPTION,
                    color=discord.Color.blue()
                )
                
                view = WarehouseStartView()
                new_msg = await channel.send(embed=embed, view=view)
                self.message_id = new_msg.id
                logger.info("🔄 Кнопки склада перемещены вниз")
            
        except Exception as e:
            logger.error(f"Ошибка в button_position: {e}")
    
    async def start_checking(self):
        """Запускает периодическую проверку"""
        await self.bot.wait_until_ready()
        await self.ensure_position()
        
        while not self.bot.is_closed():
            await asyncio.sleep(self.check_interval)
            await self.ensure_position()