import re
import logging
import asyncio
import discord
from datetime import datetime
from config import Config
from state import active_firing_requests, active_promotion_requests, bot
from database import save_request
from views.firing_view import FiringView
from views.promotion_view import PromotionView
from models import FiringRequest, PromotionRequest
from constants import WebhookPatterns

logger = logging.getLogger(__name__)

class WebhookHandler:
    """Обработчик вебхуков (рапорты на увольнение/повышение)"""
    
    def __init__(self, bot):
        self.bot = bot
        # Компилируем регулярки для скорости
        self._compile_patterns()

    def _compile_patterns(self):
        """Компилирует все регулярные выражения"""
        self.firing_patterns = {
            key: re.compile(pattern, re.IGNORECASE) 
            for key, pattern in WebhookPatterns.FIRING.items()
        }
        self.promotion_patterns = {
            key: re.compile(pattern, re.IGNORECASE) 
            for key, pattern in WebhookPatterns.PROMOTION.items()
        }
        self.common_patterns = {
            key: re.compile(pattern, re.IGNORECASE) 
            for key, pattern in WebhookPatterns.COMMON.items()
        }

    async def process_webhook(self, message: discord.Message):
        """Основной обработчик вебхуков"""
        if not message.embeds:
            return
        
        embed = message.embeds[0]
        
        # Определяем тип по заголовку или содержимому
        if embed.title == "РАПОРТ ОБ УВОЛЬНЕНИИ":
            await self.process_firing(message, embed)
        else:
            # Проверяем на повышение (ищем 👤 в полях)
            for field in embed.fields:
                if field.name and "👤" in field.name and "|" in field.name:
                    await self.process_promotion(message, embed)
                    return

    async def process_firing(self, message, embed):
        """Обработка рапорта об увольнении"""
        data = self._parse_firing_embed(embed)
        if not data:
            logger.error("Не удалось распарсить рапорт об увольнении")
            return
        
        # Создаем embed и view
        new_embed = discord.Embed.from_dict(embed.to_dict())
        view = FiringView(user_id=data['discord_id'])
        
        # Отправляем в канал
        role_mention = f"<@&{Config.FIRING_STAFF_ROLE_ID}>"
        bot_msg = await message.channel.send(
            content=role_mention, 
            embed=new_embed, 
            view=view
        )
        
        # Сохраняем в state и БД
        firing_request = FiringRequest(
            discord_id=data['discord_id'],
            full_name=data['full_name'],
            rank="",
            reason=data['reason'],
            recovery_option=data['recovery_option']
        )
        firing_request.message_link = bot_msg.jump_url
        
        active_firing_requests[bot_msg.id] = firing_request.to_dict()
        await asyncio.to_thread(
            save_request, 
            'firing_requests', 
            bot_msg.id, 
            firing_request.to_dict()
        )
        
        # Удаляем оригинальное сообщение
        await message.delete()
        
        logger.info(f"✅ Создан рапорт на увольнение для {data['discord_id']}")

    async def process_promotion(self, message, embed):
        """Обработка рапорта на повышение"""
        data = self._parse_promotion_embed(embed)
        if not data:
            logger.error("Не удалось распарсить рапорт на повышение")
            return
        
        # Создаем embed и view
        new_embed = discord.Embed.from_dict(embed.to_dict())
        view = PromotionView(
            user_id=data['discord_id'],
            new_rank=data['new_rank'],
            full_name=data['full_name'],
            message_id=0  # временно
        )
        
        # Отправляем в канал
        bot_msg = await message.channel.send(embed=new_embed, view=view)
        
        # Сохраняем в state и БД
        promo_request = PromotionRequest(
            discord_id=data['discord_id'],
            full_name=data['full_name'],
            new_rank=data['new_rank'],
            message_link=bot_msg.jump_url
        )
        
        active_promotion_requests[bot_msg.id] = promo_request.to_dict()
        await asyncio.to_thread(
            save_request, 
            'promotion_requests', 
            bot_msg.id, 
            promo_request.to_dict()
        )
        
        # Обновляем ID сообщения в view
        view.message_id = bot_msg.id
        await bot_msg.edit(view=view)
        
        # Удаляем оригинальное сообщение
        await message.delete()
        
        logger.info(f"✅ Создан рапорт на повышение для {data['discord_id']}")

    def _parse_firing_embed(self, embed):
        """Парсит embed увольнения"""
        description = embed.description
        if not description:
            logger.error("Нет описания в embed увольнения")
            return None
        
        # 1. Ищем ID пользователя
        discord_id = None
        match = self.firing_patterns['user_id'].search(description)
        if match:
            discord_id = int(match.group(1))
        
        if not discord_id:
            logger.error("Не найден ID пользователя в рапорте")
            return None
        
        # 2. Ищем имя
        full_name = "Сотрудник"
        match = self.firing_patterns['full_name'].search(description)
        if match:
            full_name = match.group(1).strip()
            logger.info(f"✅ Найдено имя: {full_name}")
        else:
            # Пробуем запасной вариант
            match = self.firing_patterns['full_name_alt'].search(description)
            if match:
                full_name = match.group(1).strip()
                logger.info(f"✅ Найдено имя (альт): {full_name}")
            else:
                logger.warning("⚠️ Имя не найдено, используем 'Сотрудник'")
        
        # 3. Ищем причину
        reason = "псж"
        match = self.firing_patterns['reason'].search(description)
        if match:
            reason = match.group(1).strip()
        
        # 4. Ищем опцию восстановления
        recovery_option = "без возможности восстановления"
        match = self.firing_patterns['recovery'].search(description)
        if match:
            recovery_option = match.group(1).strip()
        
        logger.info(
            f"📝 Данные увольнения: "
            f"id={discord_id}, имя='{full_name}', причина='{reason}'"
        )
        
        return {
            'discord_id': discord_id,
            'full_name': full_name,
            'reason': reason,
            'recovery_option': recovery_option
        }

    def _parse_promotion_embed(self, embed):
        """Парсит embed повышения"""
        discord_id = None
        new_rank = None
        full_name = None
        
        # 1. Ищем ID в полях
        for field in embed.fields:
            match = self.promotion_patterns['user_id'].search(field.value)
            if match:
                discord_id = int(match.group(1))
                break
        
        # 2. Если не нашли, ищем в описании
        if not discord_id and embed.description:
            match = self.promotion_patterns['user_id_desc'].search(embed.description)
            if match:
                discord_id = int(match.group(1))
        
        if not discord_id:
            logger.error("Не найден ID пользователя в рапорте на повышение")
            return None
        
        # 3. Ищем звание и имя в полях с 👤
        for field in embed.fields:
            if field.name and "👤" in field.name:
                match = self.promotion_patterns['rank_and_name'].search(field.name)
                if match:
                    full_name = match.group(1).strip()
                    new_rank = match.group(2).strip()
                    break
        
        if not new_rank:
            logger.error("Не найдено звание в рапорте на повышение")
            return None
        
        logger.info(
            f"📝 Данные повышения: "
            f"id={discord_id}, имя='{full_name}', звание='{new_rank}'"
        )
        
        return {
            'discord_id': discord_id,
            'full_name': full_name or "сотрудник",
            'new_rank': new_rank
        }