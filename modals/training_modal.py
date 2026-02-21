import discord
from discord.ui import Modal, TextInput
import logging
from views.training_buttons import ExamView
from constants import ExamMessages

logger = logging.getLogger(__name__)

class ExamModal(Modal):
    """Модалка для отправки на экзамен"""
    
    def __init__(self):
        super().__init__(title="🎓 ЗАПИСЬ НА ЭКЗАМЕН")
        
        self.name = TextInput(
            label="Ваше имя и фамилия",
            placeholder="Иван Петров",
            required=True,
            max_length=50
        )
        self.add_item(self.name)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Отправляет уведомление с кнопкой"""
        from datetime import datetime
        import random
        
        # Формируем текст
        text = ExamMessages.EXAM_NOTIFICATION.format(
            header=ExamMessages.HEADER,
            date=datetime.now().strftime("«%d» %B %Y года"),
            name=self.name.value,
            greeting=random.choice(ExamMessages.CONGRATS),
            report_id=f"УВД-{random.randint(1000, 9999)}"
        )
        
        embed = discord.Embed(
            title="⚡ ПОВЕСТКА В АКАДЕМИЮ ⚡",
            description=text,
            color=0xFFD700
        )
        
        # Отправляем в ЛС с кнопкой
        await interaction.user.send(
            embed=embed,
            view=ExamView()
        )
        
        await interaction.response.send_message(
            "✅ Проверьте личные сообщения!",
            ephemeral=True
        )