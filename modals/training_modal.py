import discord
from discord.ui import Modal, TextInput
import logging
from views.training_buttons import ExamView
from constants import ExamMessages

logger = logging.getLogger(__name__)


def _exam_name_default(member):
    if not member:
        return ""
    from utils.member_display import get_member_full_name
    return get_member_full_name(member)


class ExamModal(Modal):
    def __init__(self, member=None):
        super().__init__(title="🎓 ЗАПИСЬ НА ЭКЗАМЕН")
        name_default = _exam_name_default(member)
        self.name = TextInput(
            label="Ваше имя и фамилия",
            placeholder="Иван Петров",
            required=True,
            max_length=50,
            default=name_default,
        )
        self.add_item(self.name)
    
    async def on_submit(self, interaction: discord.Interaction):
        from datetime import datetime
        import random

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