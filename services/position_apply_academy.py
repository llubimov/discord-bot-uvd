import discord
from config import Config
from views.academy_apply_view import AcademyApplyView
from .base_position import BasePositionManager

TITLE = "ЗАЯВКА ИЗ АКАДЕМИИ"
DESCRIPTION = (
    "**Выпускники академии:** выберите отдел для перевода.\n\n"
    "Нажмите кнопку нужного отдела и заполните заявку."
)


class AcademyApplyPositionManager(BasePositionManager):
    @property
    def channel_id(self) -> int:
        return Config.ACADEMY_CHANNEL_ID

    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title=TITLE, description=DESCRIPTION, color=discord.Color.gold())
        return embed

    async def get_view(self) -> discord.ui.View:
        return AcademyApplyView()

    async def should_keep_message(self, message: discord.Message) -> bool:
        return bool(message.embeds and message.embeds[0].title == TITLE)
