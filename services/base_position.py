"""
=====================================================
БАЗОВЫЙ МЕНЕДЖЕР ПОЗИЦИИ СООБЩЕНИЙ
Следит чтобы важные сообщения всегда были внизу канала
=====================================================
"""

import logging
import asyncio
import discord
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BasePositionManager(ABC):
    """
    Базовый класс для менеджеров позиции сообщений.
    Следит чтобы сообщение всегда было последним в канале.
    
    Наследники должны определить:
    - channel_id - ID канала
    - get_embed() - создать embed для сообщения
    - get_view() - создать View для сообщения
    - should_keep_message() - проверка что сообщение принадлежит нам
    """
    
    def __init__(self, bot):
        self.bot = bot
        self.message_id = None
        self.is_updating = False
    
    @property
    @abstractmethod
    def channel_id(self) -> int:
        """ID канала для мониторинга"""
        pass
    
    @property
    def check_interval(self) -> int:
        """Интервал проверки в секундах (по умолчанию 60)"""
        return 60
    
    @abstractmethod
    async def get_embed(self) -> discord.Embed:
        """Создать embed для сообщения"""
        pass
    
    @abstractmethod
    async def get_view(self) -> discord.ui.View:
        """Создать View для сообщения"""
        pass
    
    @abstractmethod
    async def should_keep_message(self, message: discord.Message) -> bool:
        """
        Проверить что сообщение принадлежит нам и его нужно сохранять
        """
        pass
    
    async def find_our_message(self, channel):
        """Ищет наше сообщение в канале"""
        async for msg in channel.history(limit=50):
            if msg.author == self.bot.user and await self.should_keep_message(msg):
                return msg
        return None
    
    async def ensure_position(self):
        """Проверяет и перемещает сообщение если нужно"""
        if self.is_updating:
            return
        
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Канал {self.channel_id} не найден")
            return
        
        try:
            self.is_updating = True
            
            # Находим текущее сообщение
            current_message = None
            if self.message_id:
                try:
                    current_message = await channel.fetch_message(self.message_id)
                    # Проверяем что сообщение всё ещё наше
                    if not await self.should_keep_message(current_message):
                        current_message = None
                        self.message_id = None
                except:
                    self.message_id = None
            
            # Если не нашли по ID, ищем в истории
            if not current_message:
                current_message = await self.find_our_message(channel)
                if current_message:
                    self.message_id = current_message.id
            
            # Находим последнее сообщение в канале
            last_message = None
            async for msg in channel.history(limit=1):
                last_message = msg
                break
            
            # Проверяем нужно ли обновлять
            need_update = False
            
            if not current_message:
                need_update = True
                logger.info(f"Сообщение не найдено в канале {self.channel_id} - создаем")
            elif last_message and current_message.id != last_message.id:
                need_update = True
                logger.info(f"Сообщение не внизу канала {self.channel_id} - перемещаем")
            elif len(current_message.components) == 0:
                need_update = True
                logger.info(f"Кнопки пропали в канале {self.channel_id} - восстанавливаем")
            
            if need_update:
                # Удаляем старое сообщение если есть
                if current_message:
                    await current_message.delete()
                
                # Создаем новое внизу
                embed = await self.get_embed()
                view = await self.get_view()
                
                new_message = await channel.send(embed=embed, view=view)
                self.message_id = new_message.id
                
                # Удаляем дубликаты
                await self._remove_duplicates(channel)
                
                logger.info(f"🔄 Сообщение обновлено в канале {self.channel_id}")
            
        except Exception as e:
            logger.error(f"Ошибка в ensure_position для канала {self.channel_id}: {e}")
        finally:
            self.is_updating = False
    
    async def _remove_duplicates(self, channel):
        """Удаляет дубликаты наших сообщений"""
        try:
            async for msg in channel.history(limit=50):
                if (msg.author == self.bot.user and 
                    msg.id != self.message_id and 
                    await self.should_keep_message(msg)):
                    await msg.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении дубликатов: {e}")
    
    async def start_checking(self):
        """Запускает периодическую проверку"""
        await self.bot.wait_until_ready()
        
        # Первая проверка
        await self.ensure_position()
        
        # Дальше с интервалом
        while not self.bot.is_closed():
            await asyncio.sleep(self.check_interval)
            await self.ensure_position()