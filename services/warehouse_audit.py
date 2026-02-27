import logging
import discord
from datetime import datetime
from config import Config
from views.warehouse_theme import GREEN

logger = logging.getLogger(__name__)

class WarehouseAudit:
    def __init__(self, bot):
        self.bot = bot
        self.audit_channel_id = Config.WAREHOUSE_AUDIT_CHANNEL_ID
    
    async def log_issue(self, staff_member: discord.Member, requester_id: int, items: list, message_link: str):
        try:
            channel = self.bot.get_channel(self.audit_channel_id)
            if not channel:
                logger.error(f"Канал аудита {self.audit_channel_id} не найден")
                return
            
            embed = discord.Embed(
                title="📦 Выдача со склада",
                color=GREEN,
                timestamp=datetime.now()
            )
            embed.add_field(
                name="👮 Выдал",
                value=staff_member.mention,
                inline=True
            )
            
            embed.add_field(
                name="👤 Получатель",
                value=f"<@{requester_id}>",
                inline=True
            )
            
            items_text = ""
            for item in items:
                items_text += f"• {item['item']} — **{item['quantity']}** шт\n"
            
            embed.add_field(
                name="📋 Состав",
                value=items_text or "Пусто",
                inline=False
            )
            
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