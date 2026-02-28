import discord
from discord.ui import Modal, TextInput
import logging
from config import Config
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

        now = datetime.now()
        month_name = ExamMessages.MONTHS.get(now.month, now.strftime("%B"))
        date_str = f"«{now.day}» {month_name} {now.year} года"

        congrats = Config.EXAM_CONGRATS
        greeting = random.choice(congrats) if congrats else "Добро пожаловать!"

        text = Config.EXAM_NOTIFICATION_TEMPLATE.format(
            header=Config.EXAM_HEADER,
            date=date_str,
            name=self.name.value,
            greeting=greeting,
        )
        
        embed = discord.Embed(
            title="⚡ ПОВЕСТКА В АКАДЕМИЮ ⚡",
            description=text,
            color=0xFFD700
        )
        

        await interaction.user.send(
            embed=embed,
            view=ExamView()
        )
        
        await interaction.response.send_message(
            "✅ Проверьте личные сообщения!",
            ephemeral=True
        )