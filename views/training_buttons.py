import discord
from discord.ui import View, Button
import logging
import asyncio
from config import Config

logger = logging.getLogger(__name__)

class ExamButton(Button):
    """Кнопка для ПРИНУДИТЕЛЬНОГО перемещения в голосовой канал"""
    
    def __init__(self):
        super().__init__(
            label="🔊 ПЕРЕЙТИ В КАНАЛ ЭКЗАМЕНА",
            style=discord.ButtonStyle.success,
            emoji="🎓",
            custom_id="exam_button"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Логика при нажатии - принудительное перемещение"""
        
        # 🔥 СРАЗУ УБИРАЕМ КНОПКУ (чтобы нельзя было нажать дважды)
        try:
            await interaction.message.edit(view=None)
            logger.info(f"Кнопка удалена для {interaction.user.id}")
        except Exception as e:
            logger.error(f"Ошибка при удалении кнопки: {e}")
        
        # Получаем сервер
        guild = interaction.client.get_guild(Config.GUILD_ID)
        if not guild:
            await interaction.response.send_message(
                "❌ Не удалось найти сервер.",
                ephemeral=True
            )
            return
        
        # Получаем целевой канал
        channel = guild.get_channel(Config.EXAM_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "❌ Канал экзамена не найден!",
                ephemeral=True
            )
            return
        
        # Получаем MEMBER
        member = guild.get_member(interaction.user.id)
        
        # Проверяем, что пользователь в голосовом канале
        if not member or not member.voice:
            await interaction.response.send_message(
                "❌ Вы должны находиться в голосовом канале!\n"
                "Зайдите в любой голосовой канал и нажмите кнопку снова.",
                ephemeral=True
            )
            return
        
        try:
            # Перемещаем пользователя
            await member.move_to(channel)
            
            # Отправляем подтверждение
            await interaction.response.send_message(
                f"✅ Вы перемещены в канал {channel.mention}!",
                ephemeral=True
            )
            
            logger.info(f"Пользователь {interaction.user.id} перемещен в канал {Config.EXAM_CHANNEL_ID}")
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ У бота нет прав для перемещения!\n"
                "Требуется право **Перемещать участников**",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка перемещения: {e}")
            await interaction.response.send_message(
                "❌ Ошибка при перемещении",
                ephemeral=True
            )


class ExamView(View):
    """View с кнопкой для принудительного перемещения"""
    
    def __init__(self, timeout_seconds: int = 3600):
        super().__init__(timeout=None)
        self.add_item(ExamButton())
        
        self.timeout_seconds = timeout_seconds
        self.message = None
        self.user_id = None
    
    async def start_timer(self, message: discord.Message, user_id: int):
        self.message = message
        self.user_id = user_id
        asyncio.create_task(self._auto_destroy())
    
    async def _auto_destroy(self):
        try:
            await asyncio.sleep(self.timeout_seconds)
            if self.message:
                try:
                    await self.message.delete()
                except:
                    pass
        except:
            pass