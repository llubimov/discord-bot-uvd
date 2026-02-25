import discord
from config import Config
from views.apply_channel_view import ApplyChannelView
from .base_position import BasePositionManager

TITLE = "ПЕРЕВОД В ОСН \"ГРОМ\""
DESCRIPTION = (
    "Критерии для перевода:\n"
    "Возраст: от 15 лет\n"
    "Звание: старший сержант полиции\n\n"
    "**ПОДАТЬ ЗАЯВКУ ИЗ:**"
)


class ApplyGromPositionManager(BasePositionManager):
    @property
    def channel_id(self) -> int:
        return Config.CHANNEL_APPLY_GROM

    async def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title=TITLE, description=DESCRIPTION, color=discord.Color.blue())
        return embed

    async def get_view(self) -> discord.ui.View:
        return ApplyChannelView("grom", [("pps", "「ППС」"), ("orls", "「ОРЛС」"), ("osb", "「ОСБ」")])

    async def should_keep_message(self, message: discord.Message) -> bool:
        return bool(message.embeds and message.embeds[0].title == TITLE)
