import logging
import discord
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

class WarehouseAudit:
    """Логирование выдач со склада"""
    
    def __init__(self, bot):
        self.bot = bot
        self.audit_channel_id = Config.WAREHOUSE_AUDIT_CHANNEL_ID
    
    async def log_issue(self, staff_member: discord.Member, requester_id: int, items: list, message_link: str):
        """
        Логирует выдачу в канал аудита
        staff_member - кто выдал
        requester_id - кому выдали
        items - список предметов
        message_link - ссылка на сообщение с запросом
        """
        try:
            channel = self.bot.get_channel(self.audit_channel_id)
            if not channel:
                logger.error(f"Канал аудита {self.audit_channel_id} не найден")
                return
            
            embed = discord.Embed(
                title="📦 ВЫДАЧА СО СКЛАДА",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="👮 Выдал",
                value=staff_member.mention,
                inline=True
            )
            
            # Кому выдал (только упоминание)
            embed.add_field(
                name="👤 Получатель",
                value=f"<@{requester_id}>",
                inline=True
            )
            
            # Состав выдачи
            items_text = ""
            for item in items:
                items_text += f"• {item['item']} — **{item['quantity']}** шт\n"
            
            embed.add_field(
                name="📋 Состав",
                value=items_text or "Пусто",
                inline=False
            )
            
            # Ссылка на запрос
            embed.add_field(
                name="🔗 Запрос",
                value=f"[Перейти к запросу]({message_link})",
                inline=False
            )
            
            embed.set_footer(text=f"ID выдачи: {staff_member.id} → {requester_id}")
            
            await channel.send(embed=embed)
            logger.info(f"Аудит: {staff_member.id} выдал {requester_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при логировании аудита: {e}")